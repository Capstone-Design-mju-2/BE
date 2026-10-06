import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_service.config import settings


class ToolError(Exception):
    """A tool call failed or the MCP server could not be reached."""


class McpTools:
    """search-mcp and inventory-mcp as stdio child processes, opened once and reused (ADR-67, ADR-68)."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._search: ClientSession | None = None
        self._inventory: ClientSession | None = None

    async def __aenter__(self) -> "McpTools":
        self._search = await self._open("search-mcp", {"CATALOG_SERVICE_URL": settings.catalog_service_url})
        self._inventory = await self._open("inventory-mcp", {"ORDER_SERVICE_URL": settings.order_service_url})
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def _open(self, executable: str, env: dict[str, str]) -> ClientSession:
        command = str(Path(sys.executable).parent / executable)
        read, write = await self._stack.enter_async_context(
            stdio_client(StdioServerParameters(command=command, env=env)))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def search_products(self, q: str, max_price: int | None, limit: int) -> dict[str, Any]:
        arguments: dict[str, Any] = {"q": q, "limit": limit}
        if max_price is not None:
            arguments["max_price"] = max_price
        return await self._call(self._search, "search_products", arguments)

    async def check_inventory(self, product_ids: list[int]) -> dict[str, Any]:
        return await self._call(self._inventory, "check_inventory", {"product_ids": product_ids})

    @staticmethod
    async def _call(session: ClientSession | None, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await session.call_tool(name, arguments)
        except Exception as error:
            raise ToolError(f"{name} could not be called") from error
        if result.is_error or result.structured_content is None:
            raise ToolError(f"{name} answered with an error")
        return result.structured_content
