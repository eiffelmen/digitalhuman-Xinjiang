import asyncio
import os
from typing import TYPE_CHECKING

from asr.factory import create_asr_provider
from asr.base import BaseASRProvider
from audio_vad import AudioVAD
from loguru import logger

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse
    from app_v2 import AppState


def _get_llm_response():
    provider = os.environ.get("LLM_PROVIDER", "gongan")
    if provider == "gongan":
        from llm.providers.gongan import llm_response
    elif provider == "rag":
        from llm.providers.rag import llm_response
    elif provider == "chatgpt_oss":
        from llm.providers.chatgpt_oss import llm_response
    elif provider == "ratubrain":
        from llm.providers.ratubrain import llm_response
    elif provider == "iflytek":
        from llm.providers.iflytek import llm_response
    elif provider == "aliyun":
        from llm.providers.aliyun import llm_response
    else:
        from llm.providers.gongan import llm_response
    return llm_response


class ASRSessionHandler:
    def __init__(self, session_id: str, state: "AppState", ws: "WebSocketResponse | None" = None):
        self._session_id = session_id
        self._state = state
        self._ws = ws
        self._provider: BaseASRProvider | None = None
        self._vad = AudioVAD(
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end,
            on_audio=self._on_audio,
            threshold=0.7,
        )

    async def on_audio_chunk(self, pcm: bytes) -> None:
        # 数字人正在说话时，跳过 VAD 处理，防止麦克风拾取数字人自身声音导致反馈循环
        nerfreal = self._state.nerfreals.get(self._session_id)
        if nerfreal and getattr(nerfreal, 'speaking', False):
            return
        await self._vad.process_chunk(pcm)

    async def _on_speech_start(self, pre_buffer: list[bytes]) -> None:
        logger.info(f"[ASR] speech start, session={self._session_id}")
        try:
            self._provider = create_asr_provider()
            await self._provider.start_session()
            for chunk in pre_buffer:
                await self._provider.send_audio(chunk)
        except Exception as e:
            logger.warning(f"[ASR] failed to start provider: {e}")
            if self._provider:
                try:
                    await self._provider.close()
                except Exception:
                    pass
            self._provider = None

    async def _on_audio(self, frame: bytes) -> None:
        if self._provider:
            try:
                await self._provider.send_audio(frame)
            except Exception as e:
                logger.warning(f"[ASR] failed to send audio frame: {e}")

    async def _on_speech_end(self) -> None:
        if not self._provider:
            return
        logger.info(f"[ASR] speech end, session={self._session_id}")
        provider = self._provider
        self._provider = None
        try:
            text = await provider.end_session()
        except Exception as e:
            logger.warning(f"[ASR] provider end_session failed: {e}")
            text = ""
        finally:
            await provider.close()

        if not text:
            logger.debug("[ASR] empty result, skipping LLM dispatch")
            return

        logger.info(f"[ASR] recognized: {text!r}")

        # 将 ASR 结果推送给前端
        await self._send_asr_result(text)

        self._dispatch_to_llm(text)

    async def _send_asr_result(self, text: str) -> None:
        if not self._ws:
            return
        try:
            await self._ws.send_json({"type": "asr", "data": text})
        except Exception as e:
            logger.warning(f"[ASR] failed to send result to client: {e}")

    def _dispatch_to_llm(self, text: str) -> None:
        nerfreal = self._state.nerfreals.get(self._session_id)
        if not nerfreal:
            logger.warning(f"[ASR] no nerfreal for session={self._session_id}")
            return
        result_queue = asyncio.Queue()
        self._state.llm_response_queues[self._session_id] = result_queue
        llm_response = _get_llm_response()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            llm_response,
            text,
            nerfreal,
            self._session_id,
            result_queue,
        )

    async def close(self) -> None:
        if self._provider:
            await self._provider.close()
            self._provider = None
