import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8082")

server = MCPServer(
    name="inventory-mcp",
    instructions=(
        "Check real-time stock and delivery date for product ids. "
        "Every requested id is answered with IN_STOCK, OUT_OF_STOCK or NOT_FOUND."
    ),
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "inventory-mcp",
    }


@server.tool()
async def check_inventory(product_ids: list[int]) -> dict[str, Any]:
    """Check stock for up to 20 product ids and return one entry per requested id."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(f"{ORDER_SERVICE_URL}/api/v1/inventories/check",
                                     json={"productIds": product_ids})
        response.raise_for_status()
        return response.json()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
