import asyncio
import time
import unittest
from unittest import mock

import httpx

from agent_service.llm import Llm, LlmError


class LlmTest(unittest.TestCase):
    def test_도구_없는_분석_호출에는_빈_tools_필드를_보내지_않는다(self):
        captured = {}

        async def reply(*args, **kwargs):
            captured.update(kwargs["json"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
                                             "usage": {}}, request=httpx.Request("POST", "http://llm.invalid/v1/chat/completions"))

        llm = Llm("http://llm.invalid/v1", "key", "model", timeout=1)
        with mock.patch.object(httpx.AsyncClient, "post", reply):
            asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))
        self.assertNotIn("tools", captured)

    def test_전체_호출이_시간_제한을_넘기면_LlmError다(self):
        async def never_finishes(*args, **kwargs):
            await asyncio.sleep(10)

        llm = Llm("http://llm.invalid/v1", "key", "model", timeout=0.2)
        started = time.monotonic()
        with mock.patch.object(httpx.AsyncClient, "post", never_finishes):
            with self.assertRaises(LlmError):
                asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))
        self.assertLess(time.monotonic() - started, 2)

    def test_호출_하나의_상한이_있으면_남은_시간보다_먼저_끊고_제공자_쪽_실패로_본다(self):
        async def never_finishes(*args, **kwargs):
            await asyncio.sleep(10)

        llm = Llm("http://llm.invalid/v1", "key", "model", timeout=60, call_timeout=0.2)
        started = time.monotonic()
        with mock.patch.object(httpx.AsyncClient, "post", never_finishes):
            with self.assertRaises(LlmError) as raised:
                asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(raised.exception.provider_down)

    def test_429와_5xx만_제공자_쪽_실패로_본다(self):
        for status, provider_down in ((429, True), (503, True), (400, False), (401, False)):
            async def answer(self, url, **kwargs):
                return httpx.Response(status, json={}, request=httpx.Request("POST", url))

            with self.subTest(status), mock.patch.object(httpx.AsyncClient, "post", answer):
                with self.assertRaises(LlmError) as raised:
                    asyncio.run(Llm("http://llm.invalid/v1", "key", "model", timeout=5).complete([], []))
                self.assertEqual(raised.exception.provider_down, provider_down)


if __name__ == "__main__":
    unittest.main()
