"""Real search-mcp child processes, only the health tool (no catalog or order service needed).

uv run --package agent-service python -m unittest discover -s services/agent-service/tests
"""

import asyncio
import os
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_service.tools import ToolError, _Session

HEALTH = {"status": "UP", "service": "search-mcp"}
LOGGER = "agent_service.tools"


def children(name: str = "search-mcp") -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(os.getpid()), "-f", name], capture_output=True, text=True).stdout
    return [int(pid) for pid in out.split()]


def gone(pid: int) -> bool:
    return subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0


class SessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = _Session("search-mcp", {})
        await self.session.start()

    async def asyncTearDown(self):
        await self.session.stop()

    async def kill_child(self):
        (pid,) = children()
        os.kill(pid, signal.SIGKILL)
        await asyncio.sleep(0.3)

    async def test_정상일_때_도구를_부른다(self):
        self.assertEqual(await self.session.call("health", {}), HEALTH)

    async def test_서버가_죽어도_다음_호출이_성공한다(self):
        await self.kill_child()

        with self.assertLogs(LOGGER, level="WARNING"):
            self.assertEqual(await self.session.call("health", {}), HEALTH)
        self.assertEqual(await self.session.call("health", {}), HEALTH)
        self.assertEqual(len(children()), 1)

    async def test_죽은_직후_동시_호출은_모두_성공하고_재연결은_한_번이다(self):
        await self.kill_child()

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            results = await asyncio.gather(*(self.session.call("health", {}) for _ in range(20)),
                                           return_exceptions=True)

        self.assertEqual(results, [HEALTH] * 20)
        self.assertEqual(len(children()), 1)
        self.assertEqual(len(logs.records), 1)

    async def test_도구가_오류로_답하면_세션을_다시_열지_않는다(self):
        (pid,) = children()

        with self.assertRaises(ToolError):
            await self.session.call("no_such_tool", {})

        self.assertEqual(children(), [pid])

    async def test_종료하면_자식_프로세스가_남지_않는다(self):
        await self.session.stop()

        self.assertEqual(children(), [])


class HungServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = _Session("search-mcp", {}, call_timeout=1)
        await self.session.start()

    async def asyncTearDown(self):
        await self.session.stop()

    async def test_응답_없이_멈춘_서버는_제한_시간_뒤_새_프로세스로_복구한다(self):
        (stuck,) = children()
        os.kill(stuck, signal.SIGSTOP)

        with self.assertLogs(LOGGER, level="WARNING"):
            result = await self.session.call("health", {})

        self.assertEqual(result, HEALTH)
        (fresh,) = children()
        self.assertNotEqual(fresh, stuck)
        self.assertTrue(gone(stuck))
        self.assertEqual(await self.session.call("health", {}), HEALTH)


class ReopenHangTest(unittest.IsolatedAsyncioTestCase):
    """A server that starts but never answers initialize while the session is being reopened."""

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.marker = Path(self.directory.name) / "hang"
        wrapper = Path(self.directory.name) / "search-mcp-wrapper"
        real = Path(sys.executable).parent / "search-mcp"
        wrapper.write_text(f'#!/bin/sh\n[ -e "$MARKER" ] && exec sleep 3600\nexec {real}\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        self.session = _Session(str(wrapper), {"MARKER": str(self.marker)}, start_timeout=2, call_timeout=2)
        await self.session.start()

    async def asyncTearDown(self):
        await self.session.stop()
        self.directory.cleanup()

    async def test_재연결_중_초기화가_멈춰도_제한_시간_뒤_다시_시도해_복구한다(self):
        self.marker.touch()
        os.kill(children()[0], signal.SIGKILL)
        asyncio.get_running_loop().call_later(3, self.marker.unlink)

        with self.assertLogs(LOGGER, level="WARNING"):
            result = await self.session.call("health", {})

        self.assertEqual(result, HEALTH)
        await self.session.stop()
        self.assertEqual(children("sleep 3600"), [])


class StartTest(unittest.IsolatedAsyncioTestCase):
    async def test_서버가_뜨지_못하면_시작이_제한_시간_안에_실패하고_종료도_된다(self):
        session = _Session("no-such-mcp-server", {}, start_timeout=1)

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            with self.assertRaises(TimeoutError):
                await session.start()
            await session.stop()

        self.assertEqual(children("no-such-mcp-server"), [])
        first, *rest = logs.records
        self.assertIsNotNone(first.exc_info)
        self.assertTrue(rest)
        self.assertTrue(all(record.exc_info is None for record in rest))


if __name__ == "__main__":
    unittest.main()
