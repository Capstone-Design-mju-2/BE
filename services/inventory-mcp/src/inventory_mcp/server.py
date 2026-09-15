from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="inventory-mcp",
    instructions="Inventory tools are added after the order service API is defined.",
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "inventory-mcp",
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
