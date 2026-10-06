import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_service.config import settings

logger = logging.getLogger(__name__)

START_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 10
RECONNECT_WAIT_SECONDS = 10
CALL_TIMEOUT_SECONDS = 8  # the tools' own HTTP timeout is 3 s, so a healthy call never gets near this
BACKOFF_START_SECONDS = 0.2
BACKOFF_MAX_SECONDS = 5.0


class ToolError(Exception):
    """A tool call failed or the MCP server could not be reached."""


class _Session:
    """One MCP server over stdio (ADR-67), opened once and reused (ADR-68).

    A single task opens, owns and closes the session because the SDK must exit its cancel scopes in the task that
    entered them. When a call fails or gets no answer in time, that task reopens the session and the failed call is
    retried once (ADR-69).
    """

    def __init__(self, executable: str, env: dict[str, str], start_timeout: float = START_TIMEOUT_SECONDS,
                 call_timeout: float = CALL_TIMEOUT_SECONDS) -> None:
        self._executable = executable
        self._parameters = StdioServerParameters(command=str(Path(sys.executable).parent / executable), env=env)
        self._start_timeout = start_timeout
        self._call_timeout = call_timeout
        self._session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), self._start_timeout)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, STOP_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("%s session did not stop in time and was cancelled", self._executable)

    async def _run(self) -> None:
        delay = BACKOFF_START_SECONDS
        failures = 0
        while not self._stopping:
            self._wake.clear()
            opened = False
            try:
                async with stdio_client(self._parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._session = session
                        self._ready.set()
                        opened = True
                        delay = BACKOFF_START_SECONDS
                        failures = 0
                        await self._wake.wait()
            except Exception as error:
                if failures == 0:
                    logger.exception("%s session ended", self._executable)
                else:  # a server that keeps failing to start would otherwise log a full traceback every retry
                    logger.warning("%s session ended again (%d in a row): %r", self._executable, failures + 1, error)
            finally:
                self._session = None
                self._ready.clear()
            if not opened and not self._stopping:
                failures += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_SECONDS)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        for attempt in (1, 2):
            try:
                await asyncio.wait_for(self._ready.wait(), RECONNECT_WAIT_SECONDS)
            except TimeoutError as error:
                raise ToolError(f"{name} has no session") from error
            session = self._session
            try:
                result = await asyncio.wait_for(session.call_tool(name, arguments), self._call_timeout)
            except Exception as error:
                if self._session is session and self._ready.is_set():
                    logger.warning("%s call failed, reopening the session: %r", name, error)
                    self._ready.clear()
                    self._wake.set()
                if attempt == 2:
                    raise ToolError(f"{name} could not be called") from error
                continue
            if result.is_error or result.structured_content is None:
                raise ToolError(f"{name} answered with an error")
            return result.structured_content


class McpTools:
    def __init__(self) -> None:
        self._search = _Session("search-mcp", {"CATALOG_SERVICE_URL": settings.catalog_service_url})
        self._inventory = _Session("inventory-mcp", {"ORDER_SERVICE_URL": settings.order_service_url})

    async def __aenter__(self) -> "McpTools":
        try:
            await asyncio.gather(self._search.start(), self._inventory.start())
        except BaseException:
            await self._stop()
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stop()

    async def _stop(self) -> None:
        await asyncio.gather(self._search.stop(), self._inventory.stop())

    async def search_products(self, q: str, max_price: int | None, limit: int) -> dict[str, Any]:
        arguments: dict[str, Any] = {"q": q, "limit": limit}
        if max_price is not None:
            arguments["max_price"] = max_price
        return await self._search.call("search_products", arguments)

    async def check_inventory(self, product_ids: list[int]) -> dict[str, Any]:
        return await self._inventory.call("check_inventory", {"product_ids": product_ids})
