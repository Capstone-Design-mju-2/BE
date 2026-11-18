"""Index every review's text into OpenSearch for keyword search, one document per review (ADR-174, ADR-175).

    docker compose exec opensearch bin/opensearch-plugin install --batch analysis-nori   # once per container
    docker compose restart opensearch
    python3 scripts/index_review_text.py [--index reviews-text]

The hybrid search (SEARCH_BACKEND=hybrid) merges this index's ranking with the vector index's. Each document has the
product fields the vector index has (scripts/index_reviews.py), so the same filters run on both, and no vector. The
text is analysed by nori into morphemes: with the built-in two-letter analyser the keyword search added nothing to the
vector search (ADR-175). An index of the same name is replaced; about 800,000 reviews take two minutes.
"""

import argparse
import json
import sys
import time
import urllib.error
from collections import defaultdict

from index_reviews import catalog, request

BULK = 2000
MAPPING = {
    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"}},
    "mappings": {"properties": {
        "review_id": {"type": "long"},
        "product_id": {"type": "long"},
        "content": {"type": "text", "analyzer": "nori"},
        "grade": {"type": "byte"},
        "skin_type": {"type": "keyword"},
        "name": {"type": "text", "index": False},
        "brand": {"type": "keyword"},
        "price": {"type": "integer"},
        "category": {"type": "keyword"},
        "ingredients": {"type": "keyword"},
    }},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default="reviews-text")
    args = parser.parse_args()

    products = {int(i): {"name": name, "brand": brand, "price": int(price), "category": category}
                for i, name, brand, price, category in
                catalog("SELECT id, name, brand_name, price, category_code FROM products")}
    ingredients: dict[int, list[str]] = defaultdict(list)
    for product_id, name in catalog("SELECT product_id, name FROM product_ingredients"):
        ingredients[int(product_id)].append(name)
    reviews = catalog("SELECT id, product_id, content, grade, skin_type FROM reviews")
    print(f"{len(products)} products, {len(reviews)} reviews", flush=True)

    try:
        request("DELETE", f"/{args.index}")
        print(f"replaced index {args.index}", flush=True)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    request("PUT", f"/{args.index}", MAPPING)

    started = time.perf_counter()
    for start in range(0, len(reviews), BULK):
        lines = []
        for review_id, product_id, content, grade, skin_type in reviews[start:start + BULK]:
            product_id = int(product_id)
            lines.append(json.dumps({"index": {"_index": args.index, "_id": int(review_id)}}))
            lines.append(json.dumps({"review_id": int(review_id), "product_id": product_id, "content": content,
                                     "grade": int(grade), "skin_type": skin_type or None, **products[product_id],
                                     "ingredients": ingredients[product_id]}, ensure_ascii=False))
        result = request("POST", "/_bulk", "\n".join(lines) + "\n")
        if result["errors"]:
            print(next(i for i in result["items"] if "error" in i["index"]), file=sys.stderr)
            return 1

    request("PUT", f"/{args.index}/_settings", {"index": {"refresh_interval": None}})
    request("POST", f"/{args.index}/_refresh")
    store = request("GET", f"/{args.index}/_stats/store")["_all"]["primaries"]["store"]["size_in_bytes"]
    print(json.dumps({"index": args.index, "documents": request("GET", f"/{args.index}/_count")["count"],
                      "minutes": round((time.perf_counter() - started) / 60, 1),
                      "storeGiB": round(store / 2**30, 3)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
