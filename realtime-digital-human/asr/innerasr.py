import asyncio
import json
import os
import ssl
from urllib.parse import urlsplit, urlunsplit

import websockets
from loguru import logger
from websockets.exceptions import ConnectionClosed

from asr.base import BaseASRProvider


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_ws_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    scheme = parsed.scheme.lower()
    if scheme == "http":
        scheme = "ws"
    elif scheme == "https":
        scheme = "wss"
    elif scheme not in {"ws", "wss"}:
        raise ValueError(
            "INNER_ASR_WS_URL must use ws://, wss://, http:// or https://"
        )
    return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _default_origin(ws_url: str) -> str:
    parsed = urlsplit(ws_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{scheme}://{parsed.netloc}"


class InnerASRProvider(BaseASRProvider):
    """内网 Qwen ASR WebSocket provider。

    协议：等待 ready，发送 PCM16LE/16kHz/mono 二进制帧，结束时发送
    {"event": "commit"}，最终文本读取 final.full_text。
    """

    def __init__(self) -> None:
        raw_url = os.environ.get("INNER_ASR_WS_URL", "").strip()
        if not raw_url:
            raise RuntimeError(
                "Missing INNER_ASR_WS_URL. Set it to the intranet ASR WebSocket URL."
            )

        self._ws_url = _normalize_ws_url(raw_url)
        self._origin = os.environ.get("INNER_ASR_ORIGIN", "").strip()
        if not self._origin:
            self._origin = _default_origin(self._ws_url)
        self._insecure = _env_bool("INNER_ASR_INSECURE", True)
        self._connect_timeout = _env_float("INNER_ASR_CONNECT_TIMEOUT", 10.0)
        self._ready_timeout = _env_float("INNER_ASR_READY_TIMEOUT", 10.0)
        self._final_timeout = _env_float("INNER_ASR_FINAL_TIMEOUT", 30.0)
        self._chunk_bytes = max(
            2,
            int(os.environ.get("INNER_ASR_CHUNK_BYTES", "12800") or 12800),
        )
        if self._chunk_bytes % 2:
            self._chunk_bytes += 1

        self._ws = None
        self._recv_task = None
        self._done = asyncio.Event()
        self._partial_callback = None
        self._pending_pcm = bytearray()
        self._partial_text = ""
        self._final_text = ""
        self._last_emitted_partial = ""
        self._terminal_error = ""
        self._audio_chunks_sent = 0
        self._audio_bytes_sent = 0

    def set_partial_callback(self, callback) -> None:
        self._partial_callback = callback

    async def start_session(self) -> None:
        self._done = asyncio.Event()
        self._pending_pcm.clear()
        self._partial_text = ""
        self._final_text = ""
        self._last_emitted_partial = ""
        self._terminal_error = ""
        self._audio_chunks_sent = 0
        self._audio_bytes_sent = 0

        connect_kwargs = {
            "open_timeout": self._connect_timeout,
            "ping_interval": None,
            "close_timeout": 2,
            "max_size": 2 * 1024 * 1024,
        }
        if self._origin:
            connect_kwargs["origin"] = self._origin
        if self._ws_url.startswith("wss://") and self._insecure:
            connect_kwargs["ssl"] = ssl._create_unverified_context()

        logger.info(
            "Inner ASR connecting: "
            f"url={self._ws_url}, origin={self._origin}, "
            f"insecure={self._insecure}, chunk_bytes={self._chunk_bytes}"
        )
        try:
            self._ws = await websockets.connect(self._ws_url, **connect_kwargs)
            raw = await asyncio.wait_for(
                self._ws.recv(),
                timeout=self._ready_timeout,
            )
            ready = self._decode_message(raw)
            if ready.get("event") != "ready":
                raise RuntimeError(f"expected ready event, got {ready!r}")
            sample_rate = ready.get("sample_rate")
            if sample_rate not in (None, 16000, "16000"):
                raise RuntimeError(
                    f"inner ASR requires an unexpected sample rate: {sample_rate!r}"
                )
            logger.info(
                "Inner ASR ready: "
                f"sample_rate={sample_rate}, model={ready.get('model')!r}, "
                f"device={ready.get('device')!r}"
            )
            self._recv_task = asyncio.create_task(self._recv_loop())
        except Exception:
            await self.close()
            raise

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        if not self._ws:
            raise RuntimeError("Inner ASR websocket is not connected")

        self._pending_pcm.extend(pcm)
        while len(self._pending_pcm) >= self._chunk_bytes:
            chunk = bytes(self._pending_pcm[: self._chunk_bytes])
            del self._pending_pcm[: self._chunk_bytes]
            await self._send_pcm(chunk)

    async def end_session(self) -> str:
        if not self._ws:
            return ""

        if self._pending_pcm:
            await self._send_pcm(bytes(self._pending_pcm))
            self._pending_pcm.clear()

        await self._ws.send(json.dumps({"event": "commit"}, ensure_ascii=False))
        logger.info(
            "Inner ASR commit sent: "
            f"chunks={self._audio_chunks_sent}, bytes={self._audio_bytes_sent}"
        )
        try:
            await asyncio.wait_for(self._done.wait(), timeout=self._final_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Inner ASR final timeout after {self._final_timeout}s; "
                "using the latest partial result when available"
            )

        text = (self._final_text or self._partial_text).strip()
        if self._terminal_error and not text:
            raise RuntimeError(f"Inner ASR service error: {self._terminal_error}")
        if not self._final_text and text:
            logger.warning("Inner ASR final missing; falling back to latest partial text")
        logger.info(f"Inner ASR result: {text!r}")
        return text

    async def _send_pcm(self, pcm: bytes) -> None:
        if not self._ws:
            raise RuntimeError("Inner ASR websocket is not connected")
        await self._ws.send(pcm)
        self._audio_chunks_sent += 1
        self._audio_bytes_sent += len(pcm)

    async def _recv_loop(self) -> None:
        try:
            while self._ws:
                raw = await self._ws.recv()
                data = self._decode_message(raw)
                event = data.get("event")
                logger.debug(f"Inner ASR message: {data}")

                if event == "partial":
                    self._partial_text = self._apply_partial(
                        self._partial_text,
                        data,
                    )
                    await self._emit_partial(self._partial_text)
                    continue

                if event == "final":
                    self._final_text = str(
                        data.get("full_text")
                        or data.get("text")
                        or data.get("result")
                        or self._partial_text
                        or ""
                    ).strip()
                    self._done.set()
                    return

                if event == "error":
                    self._terminal_error = str(
                        data.get("message")
                        or data.get("reason")
                        or data.get("error")
                        or data
                    )
                    logger.warning(f"Inner ASR service error: {self._terminal_error}")
                    self._done.set()
                    return
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            self._terminal_error = (
                f"websocket closed code={exc.code}, reason={exc.reason!r}"
            )
            logger.warning(f"Inner ASR {self._terminal_error}")
        except Exception as exc:
            self._terminal_error = str(exc)
            logger.warning(f"Inner ASR receive error: {exc}")
        finally:
            self._done.set()

    async def _emit_partial(self, text: str) -> None:
        text = (text or "").strip()
        if not text or text == self._last_emitted_partial:
            return
        self._last_emitted_partial = text
        callback = self._partial_callback
        if not callback:
            return
        try:
            result = callback(text, is_final=False)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning(f"Inner ASR partial callback failed: {exc}")

    @staticmethod
    def _decode_message(raw) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError(f"Inner ASR returned non-object JSON: {data!r}")
        return data

    @staticmethod
    def _apply_partial(current: str, data: dict) -> str:
        full_text = data.get("full_text")
        if full_text:
            return str(full_text)

        delta = str(data.get("delta") or data.get("text") or "")
        replace_from = data.get("replace_from")
        if replace_from is not None:
            try:
                position = max(0, min(len(current), int(replace_from)))
            except (TypeError, ValueError):
                position = len(current)
            return current[:position] + delta
        if data.get("reset"):
            return delta
        return current + delta

    async def close(self) -> None:
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
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._done.set()
