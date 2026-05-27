import asyncio
import time
from collections import deque
from enum import Enum
from typing import Callable, Awaitable

import torch
from silero_vad import load_silero_vad
from loguru import logger

SAMPLE_RATE = 16000
SILERO_CHUNK = 512          # silero 在 16kHz 时要求 512 样本/帧
PRE_BUFFER_MS = 300
TRAILING_MS_DEFAULT = 800
MAX_SESSION_S = 50


class VadState(Enum):
    SILENCE = "silence"
    SPEECH = "speech"
    TRAILING = "trailing"


class AudioVAD:
    def __init__(
        self,
        on_speech_start: Callable[[list], Awaitable[None]],
        on_speech_end: Callable[[], Awaitable[None]],
        on_audio: Callable[[bytes], Awaitable[None]] | None = None,
        threshold: float = 0.5,
        trailing_ms: int = TRAILING_MS_DEFAULT,
    ):
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end
        self._on_audio = on_audio
        self.threshold = threshold
        self._trailing_ms = trailing_ms
        self.state = VadState.SILENCE

        self._model = load_silero_vad()
        self._model.eval()
        self._model.reset_states()

        pre_buf_chunks = max(1, (PRE_BUFFER_MS * SAMPLE_RATE) // (SILERO_CHUNK * 1000))
        self._pre_buffer: deque[bytes] = deque(maxlen=pre_buf_chunks)
        self._chunk_buf = bytearray()

        self._trailing_start: float = 0.0
        self._speech_start: float = 0.0

    def _get_speech_prob(self, pcm_bytes: bytes) -> float:
        import numpy as np
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        arr = torch.from_numpy(samples)
        with torch.no_grad():
            return self._model(arr, SAMPLE_RATE).item()

    async def process_chunk(self, pcm: bytes) -> None:
        self._chunk_buf.extend(pcm)
        chunk_bytes = SILERO_CHUNK * 2
        while len(self._chunk_buf) >= chunk_bytes:
            frame = bytes(self._chunk_buf[:chunk_bytes])
            self._chunk_buf = self._chunk_buf[chunk_bytes:]
            await self._process_frame(frame)

    async def _process_frame(self, frame: bytes) -> None:
        # 把同步 PyTorch 推理移到默认线程池，避免阻塞 main event loop。
        # 否则每个前端 PCM 包会让 main loop 卡 ~10-30ms，进而让 aiortc 的
        # RTP 发包和 PlayerStreamTrack.recv 节奏不稳，前端听感卡顿。
        loop = asyncio.get_running_loop()
        prob = await loop.run_in_executor(None, self._get_speech_prob, frame)

        if self.state == VadState.SILENCE:
            self._pre_buffer.append(frame)
            if prob >= self.threshold:
                self.state = VadState.SPEECH
                self._speech_start = time.monotonic()
                logger.debug(f"VAD: SILENCE → SPEECH (prob={prob:.2f})")
                await self._on_speech_start(list(self._pre_buffer))

        elif self.state == VadState.SPEECH:
            logger.debug(f"VAD: SPEECH prob={prob:.2f} (threshold={self.threshold})")
            if self._on_audio:
                await self._on_audio(frame)
            if prob < self.threshold:
                self.state = VadState.TRAILING
                self._trailing_start = time.monotonic()
                logger.debug(f"VAD: SPEECH → TRAILING (prob={prob:.2f})")
            else:
                elapsed = time.monotonic() - self._speech_start
                if elapsed > MAX_SESSION_S:
                    logger.warning("VAD: max session duration reached, forcing end")
                    await self._on_speech_end()
                    self.state = VadState.SILENCE
                    self._pre_buffer.clear()
                    self._model.reset_states()

        elif self.state == VadState.TRAILING:
            if prob >= self.threshold:
                self.state = VadState.SPEECH
                logger.debug(f"VAD: TRAILING → SPEECH (prob={prob:.2f})")
                if self._on_audio:
                    await self._on_audio(frame)
            else:
                elapsed_ms = (time.monotonic() - self._trailing_start) * 1000
                if elapsed_ms >= self._trailing_ms:
                    logger.debug("VAD: TRAILING → SILENCE (speech end)")
                    await self._on_speech_end()
                    self.state = VadState.SILENCE
                    self._pre_buffer.clear()
                    self._model.reset_states()
