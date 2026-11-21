import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from agent_service.config import settings

logger = logging.getLogger(__name__)

# The search server loads its model and encodes once before it is ready (ADR-183): 16 s on the demo server before the
# encoding was added, which takes about 8 s more. The reranker is loaded and scores once as well (ADR-187).
START_TIMEOUT_SECONDS = 120
STOP_TIMEOUT_SECONDS = 10
RECONNECT_WAIT_SECONDS = 10
# Must stay above the tools' own 30 s HTTP timeout and the reranking, 29 to 47 s a search on the demo server
# (ADR-187), or a slow but healthy server is restarted.
CALL_TIMEOUT_SECONDS = 90
BACKOFF_START_SECONDS = 0.2
BACKOFF_MAX_SECONDS = 5.0
# Tool arguments the agent fills from the chat request, so the LLM is never shown them (ADR-120).
REQUEST_ARGUMENTS = {"skin_type"}
# Tools the agent calls itself for the cards it shows; the LLM is not given them (ADR-187).
AGENT_ONLY_TOOLS = {"rank_evidence"}


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
        self.tools: list[types.Tool] = []
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
                        await asyncio.wait_for(session.initialize(), self._start_timeout)
                        self.tools = (await asyncio.wait_for(session.list_tools(), self._start_timeout)).tools
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


def _tracing(service: str) -> dict[str, str]:
    """Where a child sends its spans and the name it sends them under, when this process exports any (ADR-182).

    The MCP SDK carries the trace context in each call, so a child's spans join the chat that made the call.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    return {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint, "OTEL_SERVICE_NAME": service} if endpoint else {}


class McpTools:
    def __init__(self) -> None:
        # A child gets only the environment given here, so the model cache settings (HF_HOME, HF_HUB_OFFLINE in the
        # server image) are passed on explicitly.
        self._search = _Session("search-mcp", {"CATALOG_SERVICE_URL": settings.catalog_service_url,
                                               "SEARCH_BACKEND": settings.search_backend,
                                               "OPENSEARCH_URL": settings.opensearch_url,
                                               "EVIDENCE_RERANK": os.getenv("EVIDENCE_RERANK", ""),
                                               **{k: v for k, v in os.environ.items() if k.startswith("HF_")},
                                               **_tracing("search-mcp")})
        self._inventory = _Session("inventory-mcp", {"ORDER_SERVICE_URL": settings.order_service_url,
                                                     **_tracing("inventory-mcp")})

    async def __aenter__(self) -> "McpTools":
        try:
            await asyncio.gather(self._search.start(), self._inventory.start())
        except BaseException:
            await self._stop()
            raise
        # Every server exposes its own health tool; the LLM only needs the domain tools.
        tools = [(session, tool) for session in (self._search, self._inventory)
                 for tool in session.tools if tool.name != "health"]
        self._by_name = {tool.name: session for session, tool in tools}
        self.definitions = [
            {"type": "function",
             "function": {"name": tool.name, "description": tool.description or "",
                          "parameters": _without_request_arguments(tool.input_schema)}}
            for _, tool in tools if tool.name not in AGENT_ONLY_TOOLS
        ]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stop()

    async def _stop(self) -> None:
        await asyncio.gather(self._search.stop(), self._inventory.stop())

    async def check_inventory(self, product_ids: list[int]) -> dict[str, Any]:
        return await self._inventory.call("check_inventory", {"product_ids": product_ids})

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self._by_name.get(name)
        if session is None:
            raise ToolError(f"{name} is not a tool")
        return await session.call(name, arguments)


def _without_request_arguments(schema: dict[str, Any]) -> dict[str, Any]:
    properties = {name: spec for name, spec in schema.get("properties", {}).items() if name not in REQUEST_ARGUMENTS}
    return {**schema, "properties": properties}
