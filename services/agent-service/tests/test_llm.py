import asyncio
import time
import unittest
from unittest import mock

import httpx

from agent_service.llm import Llm, LlmError


class LlmTest(unittest.TestCase):
    def test_전체_호출이_시간_제한을_넘기면_LlmError다(self):
        async def never_finishes(*args, **kwargs):
            await asyncio.sleep(10)

        llm = Llm("http://llm.invalid/v1", "key", "model", timeout=0.2)
        started = time.monotonic()
        with mock.patch.object(httpx.AsyncClient, "post", never_finishes):
            with self.assertRaises(LlmError):
                asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))
        self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
