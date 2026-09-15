import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT_DIR = Path(__file__).resolve().parents[1]


async def check_server(package: str, executable: str, expected_service: str) -> None:
    parameters = StdioServerParameters(
        command="uv",
        args=["run", "--package", package, executable],
        cwd=ROOT_DIR,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if "health" not in tool_names:
                raise RuntimeError(f"{package} does not expose the health tool: {tool_names}")

            result = await session.call_tool("health", {})
            expected = {"status": "UP", "service": expected_service}
            if result.structured_content != expected:
                raise RuntimeError(
                    f"{package} returned unexpected health content: "
                    f"{result.structured_content!r}"
                )

            print(f"{package} MCP health is UP")


async def main() -> None:
    await check_server("search-mcp", "search-mcp", "search-mcp")
    await check_server("inventory-mcp", "inventory-mcp", "inventory-mcp")


if __name__ == "__main__":
    asyncio.run(main())
