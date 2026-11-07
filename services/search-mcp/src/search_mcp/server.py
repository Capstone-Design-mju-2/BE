import json
import os
from collections import Counter
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
# Reviews fetched per search before grouping them into products. At 100 each of the 21 quality questions still had
# five products of the asked type; at 50 a one-brand question had four products in all (ADR-115).
CANDIDATES = 100
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
SkinType = Literal["dry", "oily", "combination", "sensitive"]


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
        ("Search products by the meaning of their reviews. " if SEARCH_BACKEND == "opensearch"
         else "Search products by keyword in product names and review texts. ")
        + "Each product carries up to two review excerpts as evidence."
    ),
)


@server.tool()
def health() -> dict[str, str]:
    """Return the MCP server health status."""
    return {
        "status": "UP",
        "service": "search-mcp",
    }


async def search_products(q: str, max_price: int | None = None, category: Category | None = None,
                          brand: str | None = None,
                          exclude_ingredients: list[Ingredient] | Ingredient | None = None,
                          limit: int = 5, skin_type: SkinType | None = None) -> dict[str, Any]:
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
    excluded = excluded_names(exclude_ingredients)
    if excluded:
        params["excludeIngredient"] = excluded
    # Left out of the docstring the LLM reads: the agent fills it from the chat request (ADR-120).
    if skin_type is not None:
        params["skinType"] = skin_type
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{CATALOG_SERVICE_URL}/api/v1/products/search", params=params)
        response.raise_for_status()
        return response.json()


async def search_reviews(q: str, max_price: int | None = None, category: Category | None = None,
                         brand: str | None = None,
                         exclude_ingredients: list[Ingredient] | Ingredient | None = None,
                         product_types: list[str] | str | None = None, limit: int = 5,
                         skin_type: SkinType | None = None) -> dict[str, Any]:
    """Search products whose reviews match the meaning of q, one sentence of the product type and the conditions.

    product_types keeps products whose name contains one of them: the type as product names write it, without
    modifiers (크림 for 수분크림), along with its other names.
    max_price keeps only products priced at or below it (KRW). limit is 1 to 20.
    category keeps products of one category, given by its name.
    brand keeps one brand, matched exactly by its Korean name.
    exclude_ingredients drops products containing any of them, and products whose ingredient list is unknown.
    """
    filters: list[dict] = []
    if max_price is not None:
        filters.append({"range": {"price": {"lte": max_price}}})
    if category is not None:
        filters.append({"term": {"category": CATEGORY_CODES[category]}})
    # Like the catalog, surrounding spaces are dropped and a blank brand filters nothing.
    if brand and brand.strip():
        filters.append({"term": {"brand": brand.strip()}})
    must_not = []
    excluded = excluded_names(exclude_ingredients)
    if excluded:
        # Same rule as the catalog: a product with no known ingredient list cannot be shown to lack one.
        filters.append({"exists": {"field": "ingredients"}})
        must_not.append({"terms": {"ingredients": excluded}})
    vector = embed(q)
    knn: dict[str, Any] = {"vector": vector, "k": CANDIDATES}
    if filters or must_not:
        knn["filter"] = {"bool": {"filter": filters, "must_not": must_not}}
    body = {"size": CANDIDATES,
            "_source": ["review_id", "product_id", "content", "grade", "skin_type", "name", "brand", "price"],
            "query": {"knn": {"embedding": knn}}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_search", json=body)
        response.raise_for_status()
    reviews = [hit["_source"] for hit in response.json()["hits"]["hits"]]
    # A review can describe the asked conditions for a product of another type, a mist for a cream (ADR-115).
    if isinstance(product_types, str):
        product_types = [product_types]
    types = [t for t in product_types or [] if t.strip()]
    if types:
        reviews = [r for r in reviews if has_type(r["name"], types)]
    products = group_by_product(reviews, limit)
    # skin_type is left out of the docstring the LLM reads: the agent fills it from the chat request (ADR-120, ADR-134).
    if skin_type is not None and products:
        found = await closest_of_skin_type(vector, [p["productId"] for p in products], skin_type)
        products = [with_skin_type(product, closest) for product, closest in zip(products, found)]
    return {"products": products}


async def closest_of_skin_type(vector: list[float], product_ids: list[int], skin_type: str) -> list[list[dict]]:
    """Each product's two reviews closest to q among those by writers of skin_type, in one request."""
    lines = []
    for product_id in product_ids:
        knn = {"vector": vector, "k": 2, "filter": {"bool": {"filter": [
            {"term": {"product_id": product_id}}, {"term": {"skin_type": skin_type}}]}}}
        lines += [json.dumps({"index": OPENSEARCH_INDEX}),
                  json.dumps({"size": 2, "_source": ["review_id", "content", "grade", "skin_type"],
                              "query": {"knn": {"embedding": knn}}})]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/_msearch", content="\n".join(lines) + "\n",
                                     headers={"Content-Type": "application/x-ndjson"})
        response.raise_for_status()
    return [[hit["_source"] for hit in result["hits"]["hits"]] for result in response.json()["responses"]]


# Each backend exposes only the arguments it honours; product_types means nothing to the catalog search.
server.tool(name="search_products")(search_reviews if SEARCH_BACKEND == "opensearch" else search_products)


def excluded_names(exclude_ingredients: list[str] | str | None) -> list[str]:
    # gpt-oss often sends one ingredient as a bare string; rejecting it cost whole conversations.
    if isinstance(exclude_ingredients, str):
        exclude_ingredients = [exclude_ingredients]
    return [name for i in exclude_ingredients or [] for name in INGREDIENT_NAMES[i]]


def has_type(name: str, types: list[str]) -> bool:
    """Product names space their types freely, so spaces are ignored on both sides.

    >>> has_type("퓨어 소이빈 클렌징 폼 160ml", ["클렌징폼"])
    True
    >>> has_type("산뜻 선크림 B", ["토너", "스킨"])
    False
    """
    compact = name.replace(" ", "")
    return any(t.replace(" ", "") in compact for t in types)


def group_by_product(reviews: list[dict], limit: int) -> list[dict]:
    """Rank products by how many of the fetched reviews are theirs, the closest review breaking ties, as the catalog
    ranks by matching reviews (ADR-128). Each keeps its two closest reviews as evidence. Reviews come closest first.

    >>> reviews = [{"review_id": r, "product_id": p, "content": c, "grade": 5, "name": "N", "brand": "B", "price": 1}
    ...            for r, p, c in [(1, 10, "a"), (2, 20, "b"), (3, 20, "c"), (4, 30, "d"), (5, 20, "e"), (6, 30, "f")]]
    >>> [(p["productId"], [e["reviewId"] for e in p["evidence"]]) for p in group_by_product(reviews, 2)]
    [(20, [2, 3]), (30, [4, 6])]
    """
    products: dict[int, dict] = {}
    counts: Counter[int] = Counter()
    for review in reviews:
        counts[review["product_id"]] += 1
        product = products.get(review["product_id"])
        if product is None:
            product = products[review["product_id"]] = {
                "productId": review["product_id"], "name": review["name"], "brand": review["brand"],
                "price": review["price"], "evidence": []}
        if len(product["evidence"]) < 2:
            product["evidence"].append(evidence(review))
    # sorted is stable, so products with equal counts keep the order of their closest review.
    return sorted(products.values(), key=lambda p: -counts[p["productId"]])[:limit]


def with_skin_type(product: dict, found: list[dict]) -> dict:
    """Put the product's reviews closest to q among those by writers of the asked skin type ahead of its evidence, as
    the catalog does (ADR-120). The fetched reviews alone held one for only half the products (ADR-134).

    >>> product = {"productId": 1, "evidence": [{"reviewId": 1, "skinType": None}, {"reviewId": 2, "skinType": "dry"}]}
    >>> found = [{"review_id": 2, "content": "b", "grade": 5, "skin_type": "dry"}]
    >>> [(e["reviewId"], e["skinType"]) for e in with_skin_type(product, found)["evidence"]]
    [(2, 'dry'), (1, None)]
    """
    picked = [evidence(review) for review in found]
    ids = {e["reviewId"] for e in picked}
    return {**product, "evidence": (picked + [e for e in product["evidence"] if e["reviewId"] not in ids])[:2]}


def evidence(review: dict) -> dict:
    return {"reviewId": review["review_id"], "rating": review["grade"], "excerpt": excerpt(review["content"]),
            "skinType": review.get("skin_type")}


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
