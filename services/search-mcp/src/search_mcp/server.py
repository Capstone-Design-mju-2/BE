import json
import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8081")
# "catalog" searches review text in the catalog DB; "opensearch" searches review vectors (ADR-102); "hybrid" searches
# the vectors and the review text in OpenSearch and merges the two rankings (ADR-174).
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "catalog")
VECTORS = SEARCH_BACKEND in ("opensearch", "hybrid")
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "reviews")
# The keyword index holds the same reviews without vectors, their text analysed by nori (ADR-175). It is built by
# scripts/index_review_text.py.
OPENSEARCH_TEXT_INDEX = os.getenv("OPENSEARCH_TEXT_INDEX", "reviews-text")
# The constant of reciprocal rank fusion, as its authors set it (Cormack, Clarke and Büttcher, 2009).
RRF_K = 60
# CI has no model: it searches with question vectors the real model computed once, keyed by question.
QUERY_VECTORS = os.getenv("QUERY_VECTORS")
# Reviews fetched per search before grouping them into products. At 100 each of the 21 quality questions still had
# five products of the asked type; at 50 a one-brand question had four products in all (ADR-115).
CANDIDATES = 100
EXCERPT_LENGTH = 80
EXCERPT_LEAD = 20
PRODUCT_CANDIDATES = 10
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
# Items of Musinsa's review survey that found products can be ranked by, and the review count (ADR-177).
RankBy = Literal["자극여부", "보습력", "지속력", "흡수력", "발림성", "향 만족도", "발색력", "밀착력", "세정력", "끈적임 여부",
                 "커버력", "모발상태", "편의성", "트러블 유발 여부", "진정효과", "사용 후 촉감", "잔향 만족도", "다크닝 여부",
                 "워터프루프 기능", "손상정도", "각질 부각 여부", "리뷰 수"]
# Products the survey ranks before the best `limit` are kept: the right ones are among the first 20 found far more
# often than among the first 5 (ADR-177).
RANK_POOL = 20
# 331 of 356 cited reviews were rated 5 and none below 3, so each card also gets one of its product's reviews rated
# 1 to 3, where the complaints are (ADR-179).
LOW_RATED = {"range": {"grade": {"lte": 3}}}
CRITICAL_POOL = 5
# Of the low-rated reviews closest to a question 45% stated a downside, of those using one of these words 87%.
COMPLAINT_WORDS = ["아쉬", "별로", "단점", "다만", "실망", "불편", "안 맞", "안맞", "글쎄", "모르겠", "그닥", "그다지"]
# Survey answers that do not rate an item well, spaces removed. Every other answer of the items above does.
SURVEY_NOT_GOOD = {"보통", "낮음", "매우낮음", "나쁨", "매우나쁨", "약간있음", "매우있음", "조금있음", "눈에띄게있음",
                   "심하게있음", "아쉬움", "매우아쉬움", "불편함", "어려움", "매우어려움", "번거로움", "번거러움", "부각됨",
                   "많이부각됨", "조금다름", "매우다름"}
# What a product name says comes as a gift: a bracket naming a gift or opening with a plus, or the rest of the name
# after a plus and the word for gift.
GIFT_TAIL = re.compile(r"\+\s*[\(\[]?\s*증정.*$")
GIFT_GROUP = re.compile(r"[\(\[][^\)\]]*(증정|사은품)[^\)\]]*[\)\]]|[\(\[]\s*\+[^\)\]]*[\)\]]")
# Words a product name ends its type with, and marks of a set of several products. A list made by reading product
# names: a type missing from it only means the old rule (the asked word anywhere in the name) applies to that name.
TYPE_WORDS = ["크림", "세럼", "앰플", "에센스", "토너", "스킨", "로션", "에멀전", "에멀젼", "패드", "폼", "오일", "워터", "밤",
              "미스트", "마스크", "팩", "클렌저", "젤", "샴푸", "트리트먼트", "린스", "컨디셔너", "워시", "스크럽", "스틱",
              "쿠션", "파운데이션", "틴트", "립스틱", "마스카라", "섀도우", "팔레트", "퍼퓸", "향수", "부스터", "소프너",
              "필링", "패치", "스프레이", "파우더", "프라이머", "컨실러", "라이너", "글로스", "토닉"]
SET_MARKS = ["세트", "SET", "Set", "2종", "3종", "+"]
# A product with few answers is pulled toward the share an average product has, by this many answers' weight.
SURVEY_PRIOR, SURVEY_PRIOR_WEIGHT = 0.8, 10


tracer = trace.get_tracer("search-mcp")


def _embedder() -> Callable[[str], list[float]]:
    if QUERY_VECTORS:
        vectors = json.loads(Path(QUERY_VECTORS).read_text(encoding="utf-8"))
        return lambda q: vectors[q]
    import torch
    from sentence_transformers import SentenceTransformer

    # Loaded at start, about 10 s on an M2 (ADR-102), so the first search does not pay for it.
    model = SentenceTransformer("BAAI/bge-m3", device="mps" if torch.backends.mps.is_available() else "cpu")

    def encode(q: str) -> list[float]:
        with tracer.start_as_current_span("embed"):
            return model.encode(q, normalize_embeddings=True).tolist()

    return encode


embed = _embedder() if VECTORS else None

server = MCPServer(
    name="search-mcp",
    instructions=(
        ("Search products by the meaning of their reviews. " if VECTORS
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
                         skin_type: SkinType | None = None, rank_by: RankBy | None = None) -> dict[str, Any]:
    """Search products whose reviews match the meaning of q, one sentence of the product type and the conditions.

    rank_by orders the found products by what buyers answered about one item of the review survey, or by 리뷰 수
    when the question asks for popular products. Give the item the question asks about: 자극여부 (자극 없는, 순한),
    보습력 (촉촉한), 끈적임 여부 (끈적이지 않는, 산뜻한), 지속력 (오래 가는), 잔향 만족도 (향이 오래 가는),
    향 만족도 (향 좋은), 트러블 유발 여부 (트러블 안 나는), 진정효과, 흡수력, 발림성, 세정력, 발색력, 밀착력,
    커버력, 모발상태 (머릿결), 손상정도, 사용 후 촉감, 편의성, 다크닝 여부, 워터프루프 기능, 각질 부각 여부.
    Leave it out when no item fits.

    product_types keeps products whose name contains one of them: the type as product names write it, without
    modifiers (크림 for 수분크림), along with its other names.
    max_price keeps only products priced at or below it (KRW). limit is 1 to 20.
    category keeps products of one category, given by its name.
    brand keeps one brand, matched exactly by its Korean name.
    exclude_ingredients drops products containing any of them, and products whose ingredient list is unknown.
    Each product's similarity, from 0 to 1, is how close its closest review is to q.
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
    source = ["review_id", "product_id", "content", "grade", "skin_type", "name", "brand", "price"]
    body = {"size": CANDIDATES, "_source": source, "query": {"knn": {"embedding": knn}}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_search", json=body)
        response.raise_for_status()
        reviews = [{**hit["_source"], "similarity": similarity(hit["_score"])}
                   for hit in response.json()["hits"]["hits"]]
        if SEARCH_BACKEND == "hybrid":
            worded = {"size": CANDIDATES, "_source": source, "query": {"bool": {
                "must": [{"match": {"content": q}}], "filter": filters, "must_not": must_not}}}
            response = await client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_TEXT_INDEX}/_search", json=worded)
            response.raise_for_status()
            reviews = fuse(reviews, [hit["_source"] for hit in response.json()["hits"]["hits"]])
    # A review can describe the asked conditions for a product of another type, a mist for a cream (ADR-115).
    if isinstance(product_types, str):
        product_types = [product_types]
    types = [t for t in product_types or [] if t.strip()]
    if types:
        reviews = [r for r in reviews if has_type(r["name"], types)]
    if rank_by is None:
        products = group_by_product(reviews, limit)
    else:
        products = (await by_survey(group_by_product(reviews, max(limit, RANK_POOL)), rank_by))[:limit]
    # skin_type is left out of the docstring the LLM reads: the agent fills it from the chat request (ADR-120, ADR-134).
    ids = [p["productId"] for p in products]
    if skin_type is not None and products:
        found = await closest_per_product(vector, ids, {"term": {"skin_type": skin_type}}, 2)
        products = [with_skin_type(product, closest) for product, closest in zip(products, found)]
    if products:
        low = await closest_per_product(vector, ids, LOW_RATED, CRITICAL_POOL)
        products = [{**p, "criticalReview": critical(pool)} for p, pool in zip(products, low)]
    return {"products": await with_catalog_fields(products)}


async def by_survey(products: list[dict], rank_by: str) -> list[dict]:
    """Order found products by buyers' survey answers on one item, or by review count (ADR-177). A review that states
    the asked quality puts a product among the found ones; whether buyers mostly agree is what the survey knows. If
    the catalog cannot answer, the order stays as found."""
    if not products:
        return products
    params: dict[str, Any] = {"ids": [p["productId"] for p in products]}
    if rank_by != "리뷰 수":
        params["attribute"] = rank_by
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{CATALOG_SERVICE_URL}/internal/products/survey", params=params)
            response.raise_for_status()
    except httpx.HTTPError:
        return products
    return ranked(products, {survey["productId"]: survey for survey in response.json()["surveys"]}, rank_by)


def ranked(products: list[dict], surveys: dict[int, dict], rank_by: str) -> list[dict]:
    """Found products ordered by the survey item, unless most of them were never asked about it. Musinsa asks each
    kind of product its own items: face creams are not asked about stickiness while hand creams and sunscreens
    are, so ranking a mixed list by it put those above every face cream (ADR-177).

    >>> found = [{"productId": 1}, {"productId": 2}, {"productId": 3}]
    >>> answers = {2: {"productId": 2, "reviewCount": 5, "answers": {"전혀없음": 9}}}
    >>> [p["productId"] for p in ranked(found, answers, "끈적임 여부")]
    [1, 2, 3]
    >>> answers[3] = {"productId": 3, "reviewCount": 9, "answers": {"보통": 9}}
    >>> [p["productId"] for p in ranked(found, answers, "끈적임 여부")]
    [2, 1, 3]
    >>> [p["productId"] for p in ranked(found, answers, "리뷰 수")]
    [3, 2, 1]
    """
    asked = sum(bool(surveys.get(p["productId"], {}).get("answers")) for p in products)
    if rank_by != "리뷰 수" and 2 * asked < len(products):
        return products
    # sorted is stable, so products with equal scores keep the order they were found in.
    return sorted(products, key=lambda p: -survey_score(surveys.get(p["productId"]), rank_by))


def survey_score(survey: dict | None, rank_by: str) -> float:
    """The share of buyers who rated the item well, or the review count. A product nobody answered about comes just
    below an average one.

    >>> survey_score({"reviewCount": 7, "answers": {"전혀없음": 30, "보통": 10}}, "끈적임 여부")
    0.76
    >>> survey_score({"reviewCount": 7, "answers": {}}, "끈적임 여부"), survey_score(None, "리뷰 수")
    (0.79, 0)
    >>> survey_score({"reviewCount": 7, "answers": {}}, "리뷰 수")
    7
    """
    if rank_by == "리뷰 수":
        return survey["reviewCount"] if survey else 0
    answers = survey["answers"] if survey else {}
    total = sum(answers.values())
    if not total:
        return SURVEY_PRIOR - 0.01
    rated_well = sum(n for answer, n in answers.items() if answer not in SURVEY_NOT_GOOD)
    return round((rated_well + SURVEY_PRIOR * SURVEY_PRIOR_WEIGHT) / (total + SURVEY_PRIOR_WEIGHT), 4)


async def with_catalog_fields(products: list[dict]) -> list[dict]:
    """Add the catalog's image addresses (ADR-151) and same-product marks (ADR-172), which the review index lacks. If
    the catalog cannot answer, the cards go out without them rather than failing the search."""
    images: dict[int, dict] = {}
    if products:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{CATALOG_SERVICE_URL}/internal/products/images",
                                            params={"ids": [p["productId"] for p in products]})
                response.raise_for_status()
            images = {image["productId"]: image for image in response.json()["images"]}
        except httpx.HTTPError:
            pass
    return [{**p, "imageUrl": images.get(p["productId"], {}).get("imageUrl"),
             "thumbnailUrl": images.get(p["productId"], {}).get("thumbnailUrl"),
             "sameProductId": images.get(p["productId"], {}).get("sameProductId")} for p in products]


async def closest_per_product(vector: list[float], product_ids: list[int], condition: dict,
                              size: int) -> list[list[dict]]:
    """Each product's reviews closest to q among those meeting condition, in one request."""
    lines = []
    for product_id in product_ids:
        knn = {"vector": vector, "k": size, "filter": {"bool": {"filter": [
            {"term": {"product_id": product_id}}, condition]}}}
        lines += [json.dumps({"index": OPENSEARCH_INDEX}),
                  json.dumps({"size": size, "_source": ["review_id", "content", "grade", "skin_type"],
                              "query": {"knn": {"embedding": knn}}})]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/_msearch", content="\n".join(lines) + "\n",
                                     headers={"Content-Type": "application/x-ndjson"})
        response.raise_for_status()
    return [[hit["_source"] for hit in result["hits"]["hits"]] for result in response.json()["responses"]]


async def search_product_reviews(product_id: int, q: str) -> dict[str, Any]:
    """Find up to two reviews of one searched product that state q, a condition its evidence does not state.

    q is that condition in a few words as a review would write it, such as 진정 or 끈적이지 않음.
    """
    knn = {"vector": embed(q), "k": PRODUCT_CANDIDATES,
           "filter": {"bool": {"filter": [{"term": {"product_id": product_id}}]}}}
    body = {"size": PRODUCT_CANDIDATES, "_source": ["review_id", "content", "grade", "skin_type"],
            "query": {"knn": {"embedding": knn}}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_search", json=body)
        response.raise_for_status()
    reviews = [hit["_source"] for hit in response.json()["hits"]["hits"]]
    # Vectors miss negation: the review closest to 끈적이지 않음 can be one about dryness, so a review using the
    # condition's words comes first (ADR-136).
    worded = [r for r in reviews if anchor(" ".join(r["content"].split()), q.split()) >= 0]
    return {"productId": product_id, "reviews": [evidence(r, q) for r in (worded[:2] or reviews[:1])]}


# Each backend exposes only the arguments it honours; product_types means nothing to the catalog search.
server.tool(name="search_products")(search_reviews if VECTORS else search_products)
if VECTORS:
    server.tool()(search_product_reviews)


def excluded_names(exclude_ingredients: list[str] | str | None) -> list[str]:
    # gpt-oss often sends one ingredient as a bare string; rejecting it cost whole conversations.
    if isinstance(exclude_ingredients, str):
        exclude_ingredients = [exclude_ingredients]
    return [name for i in exclude_ingredients or [] for name in INGREDIENT_NAMES[i]]


def similarity(score: float) -> float:
    """The cosine of q and a review: OpenSearch scores an inner product p as 1 + p, or 1 / (1 - p) below zero, and
    the vectors are normalized.

    >>> similarity(1.7082), similarity(0.8)
    (0.708, -0.25)
    """
    return round(score - 1 if score >= 1 else 1 - 1 / score, 3)


def fuse(by_meaning: list[dict], by_words: list[dict]) -> list[dict]:
    """Merge the two review rankings by reciprocal rank fusion: a review scores 1 / (RRF_K + rank) in each ranking it
    is in, so one both searches found comes ahead of one only one of them found (ADR-174). A review only the keyword
    search found has no similarity.

    >>> [r["review_id"] for r in fuse([{"review_id": 1}, {"review_id": 2}], [{"review_id": 2}, {"review_id": 3}])]
    [2, 1, 3]
    """
    reviews: dict[int, dict] = {}
    scores: dict[int, float] = {}
    for ranking in (by_meaning, by_words):
        for rank, review in enumerate(ranking, start=1):
            reviews.setdefault(review["review_id"], review)
            scores[review["review_id"]] = scores.get(review["review_id"], 0) + 1 / (RRF_K + rank)
    # sorted is stable, so equal scores keep the vector search's reviews first.
    return sorted(reviews.values(), key=lambda r: -scores[r["review_id"]])[:CANDIDATES]


def main_name(name: str) -> str:
    """A product name without what comes as a gift, which names another type of product.

    >>> main_name("[어성초 세럼 5ml 증정] 어성초 카밍 토너 스킨 부스터 200ml")
    '어성초 카밍 토너 스킨 부스터 200ml'
    >>> main_name("[SET] 수딩크림 80ml X 2개 [총 160ml] (+다이브인 세럼 20ml)")
    '[SET] 수딩크림 80ml X 2개 [총 160ml]'
    >>> main_name("헤어 에센스 80ml 플로럴 향+(증정) 리커버리밤 20ML")
    '헤어 에센스 80ml 플로럴 향'
    """
    return GIFT_GROUP.sub("", GIFT_TAIL.sub("", name)).strip()


def has_type(name: str, types: list[str]) -> bool:
    """Whether the product is of one of the asked types. Product names space their types freely, so spaces are
    ignored on both sides. A name ends its type with the last type word in it, so "앰플 폼" is a foam and not an
    ampoule; a set holds several products, so any of them counts. Gifts do not count (ADR-177).

    >>> has_type("퓨어 소이빈 클렌징 폼 160ml", ["클렌징폼"])
    True
    >>> has_type("산뜻 선크림 B", ["토너", "스킨"])
    False
    >>> has_type("마다가스카르 센텔라 앰플 폼 125ml", ["세럼", "앰플"])
    False
    >>> has_type("[SET] 수딩크림 80ml X 2개 (+다이브인 세럼 20ml)", ["세럼"])
    False
    >>> has_type("밀크씨슬 리페어 2종 세트(토너+세럼)", ["토너"]), has_type("히알루론 수분크림 50ml", ["크림"])
    (True, True)
    """
    compact = main_name(name).replace(" ", "")
    ends = [compact.rfind(t.replace(" ", "")) + len(t.replace(" ", "")) for t in types
            if t.replace(" ", "") in compact]
    if not ends:
        return False
    if any(mark in compact for mark in SET_MARKS):
        return True
    # Where the name's last type word starts: an asked type that ends at or before it names something else.
    last = max((compact.rfind(word) for word in TYPE_WORDS), default=-1)
    return max(ends) > last


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
                "price": review["price"], "similarity": review.get("similarity"), "evidence": []}
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


def critical(reviews: list[dict]) -> dict | None:
    """The closest review that words a complaint, its excerpt opening near that word. None when no review does: a low
    rating alone seldom comes with a stated downside (ADR-179).

    >>> reviews = [{"review_id": 1, "content": "촉촉하고 좋아요", "grade": 3},
    ...            {"review_id": 2, "content": "향이 별로예요", "grade": 2}]
    >>> critical(reviews)["reviewId"], critical(reviews[:1])
    (2, None)
    """
    for review in reviews:
        words = [word for word in COMPLAINT_WORDS if word in review["content"]]
        if words:
            return evidence(review, " ".join(words))
    return None


def evidence(review: dict, q: str | None = None) -> dict:
    return {"reviewId": review["review_id"], "rating": review["grade"], "excerpt": excerpt(review["content"], q),
            "skinType": review.get("skin_type")}


def excerpt(content: str, q: str | None = None) -> str:
    """The catalog centres its excerpt on the matched word; a vector match has none, so the review opens it. Given the
    condition a product's reviews were searched for, the excerpt starts a little before it: 82 of 518 reviews stating a
    condition the evidence missed stated it past the opening 80 characters (ADR-136).

    >>> excerpt("  건성인데\\n  촉촉해요  ")
    '건성인데 촉촉해요'
    >>> len(excerpt("가" * 100))
    80
    >>> excerpt("가" * 100 + " 끈적임 없이 좋아요", "끈적이지 않음")[-12:]
    '가 끈적임 없이 좋아요'
    """
    text = " ".join(content.split())
    at = anchor(text, q.split()) if q else -1
    if at < EXCERPT_LENGTH - EXCERPT_LEAD:
        return text[:EXCERPT_LENGTH]
    return "…" + text[at - EXCERPT_LEAD:at - EXCERPT_LEAD + EXCERPT_LENGTH - 1]


def anchor(text: str, words: list[str]) -> int:
    """Where the first word found starts, each word cut down to two letters until found, as reviews conjugate it.

    >>> anchor("촉촉하고 안끈적여요", ["끈적이지", "않음"]), anchor("촉촉해요", ["진정"])
    (6, -1)
    """
    for word in words:
        for end in range(len(word), 1, -1):
            at = text.find(word[:end])
            if at >= 0:
                return at
    return -1


def export_traces() -> None:
    """Send spans to OTEL_EXPORTER_OTLP_ENDPOINT under OTEL_SERVICE_NAME; left unset, tracing does nothing (ADR-182)."""
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()


def main() -> None:
    export_traces()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
