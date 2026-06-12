import asyncio
import json
import os
import time

import numpy as np
import websocket
import websockets
from websockets.exceptions import ConnectionClosed
from loguru import logger

from asr.base import BaseASRProvider
from gongan_api import env_bool, env_float, get_gongan_client


class GonganASRProvider(BaseASRProvider):
    def __init__(self) -> None:
        self._client = get_gongan_client()
        self._ws = None
        self._latest_text = ""
        self._recv_timeout = env_float("GONGAN_ASR_RECV_TIMEOUT", 3.0)
        self._ready_timeout = env_float("GONGAN_ASR_READY_TIMEOUT", 3.0)
        self._send_interval = env_float("GONGAN_ASR_SEND_INTERVAL", 0.01)
        self._use_punctuation = env_bool("GONGAN_ASR_PUNCTUATION", True)
        self._streaming = env_bool("GONGAN_ASR_STREAMING", False)
        self._buffered_partials = env_bool("GONGAN_ASR_BUFFERED_PARTIALS", True)
        self._partial_interval = env_float("GONGAN_ASR_PARTIAL_INTERVAL", 1.0)
        self._partial_min_bytes = int(os.environ.get("GONGAN_ASR_PARTIAL_MIN_BYTES", "24000"))
        self._pcm_buf = bytearray()
        self._recv_task = None
        self._partial_task = None
        self._ready = asyncio.Event()
        self._done = asyncio.Event()
        self._closed = False
        self._partial_callback = None
        self._last_partial_text = ""
        self._last_partial_mono = 0.0
        self._closed_send_drop_count = 0
        self._last_closed_send_log_mono = 0.0
        self._loop = None

    def set_partial_callback(self, callback) -> None:
        """Register an async callback for streaming ASR partial text."""
        self._partial_callback = callback

    async def _emit_partial(self, text: str, *, is_final: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not is_final and text == self._last_partial_text:
            return
        self._last_partial_text = text
        callback = self._partial_callback
        if not callback:
            return
        try:
            result = callback(text, is_final=is_final)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning(f"Gongan ASR partial callback failed: {exc}")

    async def start_session(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._pcm_buf.clear()
        self._latest_text = ""
        self._last_partial_text = ""
        self._ready = asyncio.Event()
        self._done = asyncio.Event()
        self._closed = False
        self._last_partial_mono = 0.0
        self._closed_send_drop_count = 0
        self._last_closed_send_log_mono = 0.0
        if not self._streaming:
            await asyncio.to_thread(self._client.ensure_login)
            logger.info("Gongan ASR buffered session started")
            return

        await asyncio.to_thread(self._client.ensure_login)
        url = self._client.tokenized_url(self._client.asr_ws_url)
        headers = self._client.websocket_headers()
        try:
            self._ws = await websockets.connect(
                url,
                origin=self._client.origin,
                additional_headers=headers,
                open_timeout=5,
            )
        except TypeError:
            self._ws = await websockets.connect(
                url,
                origin=self._client.origin,
                extra_headers=headers,
                open_timeout=5,
            )
        await self._ws.send(json.dumps({"signal": "start"}, ensure_ascii=False))
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info(f"Gongan ASR session started -> {self._client.asr_ws_url}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self._ready_timeout)
            logger.info("Gongan ASR server_ready received; audio streaming enabled")
        except asyncio.TimeoutError:
            logger.warning(
                f"Gongan ASR server_ready timeout after {self._ready_timeout}s; "
                "continuing with guarded audio send"
            )

    async def send_audio(self, pcm: bytes) -> None:
        if not self._streaming:
            self._pcm_buf.extend(pcm)
            return

        self._pcm_buf.extend(pcm)
        if not self._ws or self._closed:
            self._schedule_buffered_partial()
            self._closed_send_drop_count += 1
            current = time.monotonic()
            if (
                self._closed_send_drop_count <= 3
                or current - self._last_closed_send_log_mono >= 5.0
            ):
                self._last_closed_send_log_mono = current
                logger.debug(
                    "Gongan ASR send_audio: ws closed, keeping audio for "
                    f"buffered partial/final recognition, dropped_live_frames={self._closed_send_drop_count}"
                )
            return
        try:
            if not self._ready.is_set():
                await asyncio.wait_for(self._ready.wait(), timeout=self._ready_timeout)
            await self._ws.send(pcm)
            if self._send_interval > 0:
                await asyncio.sleep(self._send_interval)
        except asyncio.TimeoutError:
            logger.warning(
                f"Gongan ASR send_audio waiting server_ready timed out after "
                f"{self._ready_timeout}s; dropping this frame"
            )
        except ConnectionClosed as exc:
            self._closed = True
            self._done.set()
            logger.warning(
                f"Gongan ASR websocket closed while sending audio: code={exc.code}, reason={exc.reason!r}"
            )
        except Exception as exc:
            self._closed = True
            self._done.set()
            logger.warning(f"Gongan ASR send_audio error: {exc}")

    async def end_session(self) -> str:
        if not self._streaming:
            pcm_bytes = bytes(self._pcm_buf)
            self._pcm_buf.clear()
            text = await asyncio.to_thread(self._recognize_buffered, pcm_bytes)
            if text and self._use_punctuation:
                text = await asyncio.to_thread(self._client.restore_punctuation, text)
            logger.info(f"Gongan ASR result: {text!r}")
            return text

        if not self._ws:
            return ""

        if not self._closed:
            try:
                await self._ws.send(json.dumps({"signal": "end"}, ensure_ascii=False))
            except ConnectionClosed as exc:
                self._closed = True
                logger.warning(
                    f"Gongan ASR websocket closed before end signal: code={exc.code}, reason={exc.reason!r}"
                )
        logger.info("Gongan ASR end signal sent, waiting for result")

        try:
            await asyncio.wait_for(self._done.wait(), timeout=self._recv_timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Gongan ASR result wait timeout after {self._recv_timeout}s")

        text = self._latest_text.strip()
        if not text:
            pcm_bytes = bytes(self._pcm_buf)
            if pcm_bytes:
                logger.warning(
                    "Gongan ASR streaming returned empty result; "
                    f"falling back to buffered recognition with {len(pcm_bytes)} bytes"
                )
                text = await asyncio.to_thread(
                    self._recognize_buffered,
                    pcm_bytes,
                    True,
                )
        self._pcm_buf.clear()
        if text and self._use_punctuation:
            text = await asyncio.to_thread(self._client.restore_punctuation, text)

        logger.info(f"Gongan ASR result: {text!r}")
        return text

    def _schedule_buffered_partial(self) -> None:
        if not self._buffered_partials or not self._partial_callback:
            return
        if len(self._pcm_buf) < self._partial_min_bytes:
            return
        if self._partial_task and not self._partial_task.done():
            return
        current = time.monotonic()
        if current - self._last_partial_mono < self._partial_interval:
            return
        self._last_partial_mono = current
        pcm_snapshot = bytes(self._pcm_buf)
        self._partial_task = asyncio.create_task(
            self._run_buffered_partial_preview(pcm_snapshot)
        )

    async def _run_buffered_partial_preview(self, pcm_bytes: bytes) -> None:
        try:
            text = await asyncio.to_thread(self._recognize_buffered, pcm_bytes, False)
            if text:
                await self._emit_partial(text, is_final=False)
        except Exception as exc:
            logger.warning(f"Gongan ASR buffered partial preview failed: {exc}")

    def _recognize_buffered(self, pcm_bytes: bytes, emit_partials: bool = False) -> str:
        if not pcm_bytes:
            logger.warning("Gongan ASR buffered: no audio to send")
            return ""

        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        energy = int(np.abs(samples).mean()) if samples.size else 0
        logger.info(
            f"Gongan ASR buffered sending PCM: {len(samples)} samples "
            f"({len(samples) / 16000:.1f}s), energy={energy}"
        )

        ws = None
        latest_text = ""
        try:
            ws = websocket.create_connection(
                self._client.tokenized_url(self._client.asr_ws_url),
                header=self._client.websocket_header_list(),
                cookie=self._client.cookie_header(),
                origin=self._client.origin,
                timeout=5,
            )
            ws.send(json.dumps({"signal": "start"}, ensure_ascii=False))

            chunk_bytes = int(os.environ.get("GONGAN_ASR_CHUNK_BYTES", "2048"))
            sleep_s = env_float("GONGAN_ASR_SEND_INTERVAL", 0.01)
            for offset in range(0, len(pcm_bytes), chunk_bytes):
                ws.send_binary(pcm_bytes[offset: offset + chunk_bytes])
                if sleep_s > 0:
                    time.sleep(sleep_s)
            ws.send(json.dumps({"signal": "end"}, ensure_ascii=False))

            ws.settimeout(self._recv_timeout)
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    break
                except websocket.WebSocketConnectionClosedException as exc:
                    logger.warning(f"Gongan ASR buffered ws closed: {exc}")
                    break

                try:
                    data = json.loads(raw)
                except Exception:
                    logger.debug(f"Gongan ASR buffered non-JSON message: {raw!r}")
                    continue

                logger.debug(f"Gongan ASR buffered message: {data}")
                text = data.get("result") or data.get("text") or ""
                if text:
                    latest_text = text
                    if emit_partials:
                        loop = self._loop
                        if loop and not loop.is_closed():
                            asyncio.run_coroutine_threadsafe(
                                self._emit_partial(text, is_final=False),
                                loop,
                            )

                status = data.get("status")
                signal = data.get("signal")
                if status in (2, "2") or signal in {"end", "finished"}:
                    break
        except Exception as exc:
            logger.warning(f"Gongan ASR buffered error: {exc}")
        finally:
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass

        return latest_text.strip()

    async def _recv_loop(self) -> None:
        while self._ws and not self._closed:
            try:
                raw = await self._ws.recv()
            except ConnectionClosed as exc:
                self._closed = True
                logger.warning(
                    f"Gongan ASR websocket closed while receiving: code={exc.code}, reason={exc.reason!r}"
                )
                break
            except Exception as exc:
                self._closed = True
                logger.warning(f"Gongan ASR recv error: {exc}")
                break

            try:
                data = json.loads(raw)
            except Exception:
                logger.debug(f"Gongan ASR non-JSON message: {raw!r}")
                continue

            logger.debug(f"Gongan ASR message: {data}")
            text = data.get("result") or data.get("text") or ""
            status = data.get("status")
            signal = data.get("signal")
            if signal == "server_ready":
                self._ready.set()
                continue
            is_final = status in (2, "2") or signal in {"end", "finished"}
            if text:
                self._ready.set()
                self._latest_text = text
                await self._emit_partial(text, is_final=is_final)

            if is_final:
                self._done.set()
                return

        self._done.set()

    async def close(self) -> None:
        if self._partial_task and not self._partial_task.done():
            self._partial_task.cancel()
            try:
                await self._partial_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._partial_task = None
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._recv_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
