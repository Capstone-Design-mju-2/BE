import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8081")

server = MCPServer(
    name="search-mcp",
    instructions=(
        "Search products by keyword in product names and review texts. "
        "Each product carries up to two review excerpts as evidence."
    ),
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "search-mcp",
    }


@server.tool()
async def search_products(q: str, max_price: int | None = None, limit: int = 5) -> dict[str, Any]:
    """Search products by keyword in product names and review texts.

    max_price keeps only products priced at or below it (KRW). limit is 1 to 20.
    """
    params = {"q": q, "limit": limit}
    if max_price is not None:
        params["maxPrice"] = max_price
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(f"{CATALOG_SERVICE_URL}/api/v1/products/search", params=params)
        response.raise_for_status()
        return response.json()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
