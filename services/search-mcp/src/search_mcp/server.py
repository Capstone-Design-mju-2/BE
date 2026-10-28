import os
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8081")
# The LLM picks a name: given numeric codes, gpt-oss sent them as JSON numbers and the schema rejected them.
CATEGORY_CODES = {
    "스킨케어": "104001", "선케어": "104002", "클렌징/필링": "104003", "프레그런스": "104005", "헤어케어": "104006",
    "바디케어": "104007", "쉐이빙/제모": "104009", "뷰티 디바이스/소품": "104010", "미용소품": "104011",
    "헬스/푸드": "104012", "마스크팩": "104013", "베이스메이크업": "104014", "립메이크업": "104015",
    "아이메이크업": "104016", "네일": "104017",
}
# Everyday names the LLM may exclude, mapped to names on ingredient lists (ADR-97). "알코올" means volatile alcohols;
# fatty alcohols such as 세테아릴알코올 moisturise and are not excluded.
INGREDIENT_NAMES = {
    "향료": ["향료"],
    "알코올": ["에탄올", "변성알코올", "알코올", "아이소프로필알코올"],
    "미네랄오일": ["미네랄오일"],
}
Ingredient = Literal["향료", "알코올", "미네랄오일"]
Category = Literal["스킨케어", "선케어", "클렌징/필링", "프레그런스", "헤어케어", "바디케어", "쉐이빙/제모", "뷰티 디바이스/소품",
                   "미용소품", "헬스/푸드", "마스크팩", "베이스메이크업", "립메이크업", "아이메이크업", "네일"]

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
async def search_products(q: str, max_price: int | None = None, category: Category | None = None,
                          brand: str | None = None,
                          exclude_ingredients: list[Ingredient] | Ingredient | None = None,
                          limit: int = 5) -> dict[str, Any]:
    """Search products by keyword in product names and review texts.

    max_price keeps only products priced at or below it (KRW). limit is 1 to 20.
    category keeps products of one category, given by its name.
    brand keeps one brand, matched exactly by its Korean name.
    exclude_ingredients drops products containing any of them, and products whose ingredient list is unknown.
    """
    params: dict[str, Any] = {"q": q, "limit": limit}
    if max_price is not None:
        params["maxPrice"] = max_price
    if category is not None:
        params["category"] = CATEGORY_CODES[category]
    if brand is not None:
        params["brand"] = brand
    if exclude_ingredients:
        # gpt-oss often sends one ingredient as a bare string; rejecting it cost whole conversations.
        if isinstance(exclude_ingredients, str):
            exclude_ingredients = [exclude_ingredients]
        params["excludeIngredient"] = [name for i in exclude_ingredients for name in INGREDIENT_NAMES[i]]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{CATALOG_SERVICE_URL}/api/v1/products/search", params=params)
        response.raise_for_status()
        return response.json()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
