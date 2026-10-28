"""Index every review with its BGE-M3 vector into OpenSearch, one document per review (ADR-101, ADR-102).

    uv run --package search-mcp --extra embed python scripts/index_reviews.py [--index reviews] [--compression 2x]

Run scripts/embed_reviews.py first. An index of the same name is replaced: it is a copy rebuilt from the catalog and
the stored vectors. Product fields are copied into every review so filters run inside the k-NN search, which also
means a product changed in the catalog afterwards stays stale here until the next run.
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200")
EMBEDDINGS = Path(".local/embeddings/bge-m3")
BULK = 500


def mapping(compression: str) -> dict:
    return {
        "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"}},
        "mappings": {
            # The vectors live in .local/embeddings; keeping them in _source too would double the disk.
            "_source": {"excludes": ["embedding"]},
            "properties": {
                "review_id": {"type": "long"},
                "product_id": {"type": "long"},
                "content": {"type": "text", "index": False},
                "grade": {"type": "byte"},
                "name": {"type": "text", "index": False},
                "brand": {"type": "keyword"},
                "price": {"type": "integer"},
                "category": {"type": "keyword"},
                "ingredients": {"type": "keyword"},
                "embedding": {"type": "knn_vector", "dimension": 1024, "space_type": "innerproduct",
                              "mode": "in_memory", "compression_level": compression},
            },
        },
    }


def document(review_id: int, review: tuple, product: dict, ingredients: list[str], vector: list[float]) -> dict:
    """
    >>> document(7, (3, "촉촉해요", 5), {"name": "크림", "brand": "A", "price": 9000, "category": "104001"}, [], [0.5])
    {'review_id': 7, 'product_id': 3, 'content': '촉촉해요', 'grade': 5, 'name': '크림', 'brand': 'A', 'price': 9000, 'category': '104001', 'ingredients': [], 'embedding': [0.5]}
    """
    product_id, content, grade = review
    return {"review_id": review_id, "product_id": product_id, "content": content, "grade": grade, **product,
            "ingredients": ingredients, "embedding": vector}


def request(method: str, path: str, body: dict | str | None = None) -> dict:
    ndjson = isinstance(body, str)
    data = None if body is None else (body if ndjson else json.dumps(body)).encode()
    req = urllib.request.Request(f"{OPENSEARCH_URL}{path}", data=data, method=method, headers={
        "Content-Type": "application/x-ndjson" if ndjson else "application/json"})
    with urllib.request.urlopen(req, timeout=600) as response:
        return json.loads(response.read() or b"{}")


def catalog(query: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "catalog-db", "psql", "-U", "catalog", "-d", "catalog", "-c",
         f"COPY ({query}) TO STDOUT WITH (FORMAT csv)"],
        capture_output=True, text=True, check=True,
    ).stdout
    return list(csv.reader(io.StringIO(out)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default="reviews")
    parser.add_argument("--compression", default="2x", choices=["1x", "2x"])
    args = parser.parse_args()

    import numpy as np

    products = {int(i): {"name": name, "brand": brand, "price": int(price), "category": category}
                for i, name, brand, price, category in
                catalog("SELECT id, name, brand_name, price, category_code FROM products")}
    ingredients: dict[int, list[str]] = defaultdict(list)
    for product_id, name in catalog("SELECT product_id, name FROM product_ingredients"):
        ingredients[int(product_id)].append(name)
    reviews = {int(i): (int(product_id), content, int(grade))
               for i, product_id, content, grade in catalog("SELECT id, product_id, content, grade FROM reviews")}
    chunks = sorted(EMBEDDINGS.glob("[0-9]*.npz"))
    print(f"{len(products)} products, {len(reviews)} reviews, {len(chunks)} vector chunks", flush=True)

    try:
        request("DELETE", f"/{args.index}")
        print(f"replaced index {args.index}", flush=True)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    request("PUT", f"/{args.index}", mapping(args.compression))

    started = time.perf_counter()
    indexed = 0
    for chunk in chunks:
        stored = np.load(chunk)
        for start in range(0, len(stored["ids"]), BULK):
            lines = []
            for review_id, vector in zip(stored["ids"][start:start + BULK], stored["vectors"][start:start + BULK]):
                review_id = int(review_id)
                review = reviews[review_id]
                lines.append(json.dumps({"index": {"_index": args.index, "_id": review_id}}))
                lines.append(json.dumps(document(review_id, review, products[review[0]], ingredients[review[0]],
                                                 vector.tolist()), ensure_ascii=False))
            result = request("POST", "/_bulk", "\n".join(lines) + "\n")
            if result["errors"]:
                print(next(i for i in result["items"] if "error" in i["index"]), file=sys.stderr)
                return 1
            indexed += len(lines) // 2
        print(f"{chunk.name}: {indexed} documents, {(time.perf_counter() - started) / 60:.1f} min", flush=True)

    request("PUT", f"/{args.index}/_settings", {"index": {"refresh_interval": None}})
    request("POST", f"/{args.index}/_refresh")
    elapsed = time.perf_counter() - started
    count = request("GET", f"/{args.index}/_count")["count"]
    store = request("GET", f"/{args.index}/_stats/store")["_all"]["primaries"]["store"]["size_in_bytes"]
    segments = len(request("GET", f"/_cat/segments/{args.index}?format=json"))
    request("GET", f"/_plugins/_knn/warmup/{args.index}")
    stats = request("GET", "/_plugins/_knn/stats")
    node = next(iter(stats["nodes"].values()))
    print(json.dumps({
        "index": args.index, "compression": args.compression, "documents": count, "missingVectors": len(reviews) - count,
        "minutes": round(elapsed / 60, 1), "storeGiB": round(store / 2**30, 3), "segments": segments,
        "graphMemoryGiB": round(node["graph_memory_usage"] / 2**20, 3),
        "graphMemoryPercentage": node["graph_memory_usage_percentage"],
        "circuitBreakerTriggered": stats["circuit_breaker_triggered"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
