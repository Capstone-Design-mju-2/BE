"""Write the semantic search fixture the smoke test indexes, with vectors from the real model (ADR-101).

    uv run --package search-mcp --extra embed python scripts/make_search_fixture.py

CI has no model, so the vectors are computed here once and committed. The reviews are made up: collected reviews
stay out of the repository (ADR-45).
"""

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRODUCTS = {
    1001: {"name": "수분 크림 A", "brand": "브랜드A", "price": 25000, "category": "104001",
           "ingredients": ["정제수", "글리세린"],
           "reviews": ["건성인데 하루 종일 촉촉하고 끈적이지 않아요", "속당김 없이 보습이 오래가요"]},
    1002: {"name": "산뜻 선크림 B", "brand": "브랜드B", "price": 18000, "category": "104002",
           "ingredients": ["정제수", "향료"],
           "reviews": ["백탁 없이 산뜻하게 발리는 선크림이에요", "야외 활동할 때 땀에도 잘 안 지워져요"]},
    1003: {"name": "진정 토너 C", "brand": "브랜드C", "price": 45000, "category": "104001", "ingredients": [],
           "reviews": ["붉어진 피부가 금방 진정돼요", "순해서 예민한 피부에도 따갑지 않아요"]},
}
QUERIES = ["건성 피부에 촉촉한 수분크림", "예민한 피부를 진정시키는 토너"]


def main() -> None:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-m3", device="cpu")

    def vector(text: str) -> list[float]:
        return [round(x, 6) for x in model.encode(text, normalize_embeddings=True).tolist()]

    reviews = []
    for product_id, product in PRODUCTS.items():
        fields = {k: v for k, v in product.items() if k != "reviews"}
        for n, content in enumerate(product["reviews"]):
            reviews.append({"review_id": product_id * 10 + n, "product_id": product_id, "content": content, "grade": 5,
                            **fields, "embedding": vector(content)})
    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "search-reviews.json").write_text(json.dumps(reviews, ensure_ascii=False))
    (FIXTURES / "search-queries.json").write_text(json.dumps({q: vector(q) for q in QUERIES}, ensure_ascii=False))


if __name__ == "__main__":
    main()
