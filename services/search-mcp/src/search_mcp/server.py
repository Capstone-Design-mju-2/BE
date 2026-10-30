import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8081")
# "catalog" searches review text in the catalog DB; "opensearch" searches review vectors (ADR-102).
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "catalog")
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "reviews")
# CI has no model: it searches with question vectors the real model computed once, keyed by question.
QUERY_VECTORS = os.getenv("QUERY_VECTORS")
# Reviews fetched per search before grouping them into products.
CANDIDATES = 50
EXCERPT_LENGTH = 80
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


def _embedder() -> Callable[[str], list[float]]:
    if QUERY_VECTORS:
        vectors = json.loads(Path(QUERY_VECTORS).read_text(encoding="utf-8"))
        return lambda q: vectors[q]
    import torch
    from sentence_transformers import SentenceTransformer

    # Loaded at start, about 10 s on an M2 (ADR-102), so the first search does not pay for it.
    model = SentenceTransformer("BAAI/bge-m3", device="mps" if torch.backends.mps.is_available() else "cpu")
    return lambda q: model.encode(q, normalize_embeddings=True).tolist()


embed = _embedder() if SEARCH_BACKEND == "opensearch" else None

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
    category_code = CATEGORY_CODES[category] if category is not None else None
    excluded = []
    if exclude_ingredients:
        # gpt-oss often sends one ingredient as a bare string; rejecting it cost whole conversations.
        if isinstance(exclude_ingredients, str):
            exclude_ingredients = [exclude_ingredients]
        excluded = [name for i in exclude_ingredients for name in INGREDIENT_NAMES[i]]
    if SEARCH_BACKEND == "opensearch":
        return await _search_reviews(q, max_price, category_code, brand, excluded, limit)

    params: dict[str, Any] = {"q": q, "limit": limit}
    if max_price is not None:
        params["maxPrice"] = max_price
    if category_code is not None:
        params["category"] = category_code
    if brand is not None:
        params["brand"] = brand
    if excluded:
        params["excludeIngredient"] = excluded
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{CATALOG_SERVICE_URL}/api/v1/products/search", params=params)
        response.raise_for_status()
        return response.json()


async def _search_reviews(q: str, max_price: int | None, category: str | None, brand: str | None,
                          excluded: list[str], limit: int) -> dict[str, Any]:
    filters: list[dict] = []
    if max_price is not None:
        filters.append({"range": {"price": {"lte": max_price}}})
    if category is not None:
        filters.append({"term": {"category": category}})
    # Like the catalog, surrounding spaces are dropped and a blank brand filters nothing.
    if brand and brand.strip():
        filters.append({"term": {"brand": brand.strip()}})
    must_not = []
    if excluded:
        # Same rule as the catalog: a product with no known ingredient list cannot be shown to lack one.
        filters.append({"exists": {"field": "ingredients"}})
        must_not.append({"terms": {"ingredients": excluded}})
    knn: dict[str, Any] = {"vector": embed(q), "k": CANDIDATES}
    if filters or must_not:
        knn["filter"] = {"bool": {"filter": filters, "must_not": must_not}}
    body = {"size": CANDIDATES, "_source": ["review_id", "product_id", "content", "grade", "name", "brand", "price"],
            "query": {"knn": {"embedding": knn}}}
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_search", json=body)
        response.raise_for_status()
    return {"products": group_by_product([hit["_source"] for hit in response.json()["hits"]["hits"]], limit)}


def group_by_product(reviews: list[dict], limit: int) -> list[dict]:
    """Rank products by their closest review; each keeps its two closest reviews as evidence. Reviews come closest first.

    >>> reviews = [{"review_id": r, "product_id": p, "content": c, "grade": 5, "name": "N", "brand": "B", "price": 1}
    ...            for r, p, c in [(1, 10, "a"), (2, 20, "b"), (3, 10, "c"), (4, 10, "d"), (5, 30, "e"), (6, 20, "f")]]
    >>> [(p["productId"], [e["reviewId"] for e in p["evidence"]]) for p in group_by_product(reviews, 2)]
    [(10, [1, 3]), (20, [2, 6])]
    """
    products: dict[int, dict] = {}
    for review in reviews:
        product = products.get(review["product_id"])
        if product is None:
            if len(products) == limit:
                continue
            product = products[review["product_id"]] = {
                "productId": review["product_id"], "name": review["name"], "brand": review["brand"],
                "price": review["price"], "evidence": []}
        if len(product["evidence"]) < 2:
            product["evidence"].append({"reviewId": review["review_id"], "rating": review["grade"],
                                        "excerpt": excerpt(review["content"])})
    return list(products.values())


def excerpt(content: str) -> str:
    """The catalog centres its excerpt on the matched word; a vector match has none, so the review opens it.

    >>> excerpt("  건성인데\\n  촉촉해요  ")
    '건성인데 촉촉해요'
    >>> len(excerpt("가" * 100))
    80
    """
    return " ".join(content.split())[:EXCERPT_LENGTH]


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
