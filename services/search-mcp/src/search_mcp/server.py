from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="search-mcp",
    instructions="Product search tools are added after the catalog search API is defined.",
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "search-mcp",
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
