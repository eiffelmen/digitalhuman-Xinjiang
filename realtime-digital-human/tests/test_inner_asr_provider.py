import asyncio
import json
import os
import unittest
from unittest.mock import patch

from asr.innerasr import InnerASRProvider


class FakeWebSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.partial_sent = False

    async def recv(self):
        return await self.incoming.get()

    async def send(self, payload):
        self.sent.append(payload)
        if isinstance(payload, bytes) and not self.partial_sent:
            self.partial_sent = True
            await self.incoming.put(
                json.dumps(
                    {
                        "event": "partial",
                        "delta": "这是一次测试。这是一次。",
                        "replace_from": 0,
                        "reset": False,
                    },
                    ensure_ascii=False,
                )
            )
            await self.incoming.put(
                json.dumps(
                    {
                        "event": "partial",
                        "delta": "测试。这是一次测试。",
                        "replace_from": 11,
                        "reset": True,
                    },
                    ensure_ascii=False,
                )
            )
        if isinstance(payload, str) and json.loads(payload).get("event") == "commit":
            await self.incoming.put(
                json.dumps(
                    {
                        "event": "final",
                        "full_text": "这是一次测试。这是一次测试。这是一次测试。",
                    },
                    ensure_ascii=False,
                )
            )

    async def close(self):
        self.closed = True


class InnerASRPartialTest(unittest.TestCase):
    def test_partial_replace_from_assembles_full_text(self):
        text = InnerASRProvider._apply_partial(
            "",
            {
                "event": "partial",
                "delta": "这是一次测试。这是一次。",
                "replace_from": 0,
                "reset": False,
            },
        )
        text = InnerASRProvider._apply_partial(
            text,
            {
                "event": "partial",
                "delta": "测试。这是一次测试。",
                "replace_from": 11,
                "reset": True,
            },
        )
        self.assertEqual(text, "这是一次测试。这是一次测试。这是一次测试。")


class InnerASRProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_ready_pcm_commit_final_flow(self):
        fake_ws = FakeWebSocket()
        await fake_ws.incoming.put(
            json.dumps(
                {
                    "event": "ready",
                    "sample_rate": 16000,
                    "model": "./models/qwen-asr-1.7b",
                    "device": "cuda:1",
                }
            )
        )

        async def fake_connect(url, **kwargs):
            self.assertEqual(url, "wss://asr.internal.example:14432/api/ws/asr")
            self.assertEqual(
                kwargs["origin"],
                "https://asr.internal.example:14432",
            )
            return fake_ws

        environment = {
            "INNER_ASR_WS_URL": "https://asr.internal.example:14432/api/ws/asr",
            "INNER_ASR_ORIGIN": "https://asr.internal.example:14432",
            "INNER_ASR_INSECURE": "1",
            "INNER_ASR_CHUNK_BYTES": "8",
        }
        partials = []

        async def on_partial(text, *, is_final=False):
            partials.append((text, is_final))

        with patch.dict(os.environ, environment), patch(
            "asr.innerasr.websockets.connect",
            new=fake_connect,
        ):
            provider = InnerASRProvider()
            provider.set_partial_callback(on_partial)
            await provider.start_session()
            await provider.send_audio(b"\x01\x00" * 8)
            result = await provider.end_session()
            await provider.close()

        binary_payload = b"".join(
            item for item in fake_ws.sent if isinstance(item, bytes)
        )
        self.assertEqual(binary_payload, b"\x01\x00" * 8)
        self.assertEqual(json.loads(fake_ws.sent[-1]), {"event": "commit"})
        self.assertEqual(
            partials[-1],
            ("这是一次测试。这是一次测试。这是一次测试。", False),
        )
        self.assertEqual(result, "这是一次测试。这是一次测试。这是一次测试。")
        self.assertTrue(fake_ws.closed)
