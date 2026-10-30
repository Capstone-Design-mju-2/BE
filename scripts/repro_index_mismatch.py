"""Reproduce the catalog DB and the OpenSearch index disagreeing after a price change (Stage 3, ADR-102).

    uv run --package search-mcp --extra embed python scripts/repro_index_mismatch.py

Needs catalog-db and OpenSearch with the review index. The product's price is raised in the catalog
DB and put back at the end. Nothing copies catalog changes into the index yet, so the vector search keeps filtering
on the indexed price; the dual write and Outbox of the next stage are meant to close this gap.
"""

import asyncio
import json
import os
import subprocess
import sys

os.environ.setdefault("SEARCH_BACKEND", "opensearch")
from search_mcp import server  # noqa: E402

QUESTION = "건성 피부에 끈적이지 않는 수분크림"
MAX_PRICE = 30000


def sql(query: str) -> str:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "catalog-db", "psql", "-U", "catalog", "-d", "catalog", "-tA", "-c", query],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def vector_search() -> list[dict]:
    return asyncio.run(server.search_products(QUESTION, max_price=MAX_PRICE))["products"]


def main() -> int:
    before = vector_search()
    product = before[0]
    product_id, indexed_price = product["productId"], product["price"]
    db_price = int(sql(f"select price from products where id = {product_id}"))
    print(f"before: vector search top {product_id} {product['name']!r}, index price {indexed_price}, DB price {db_price}")
    if db_price != indexed_price:
        print("index and DB already disagree; reindex before reproducing", file=sys.stderr)
        return 1

    raised = MAX_PRICE + 20000
    sql(f"update products set price = {raised} where id = {product_id}")
    try:
        print(f"catalog DB: price of {product_id} set to {raised} (over max_price {MAX_PRICE})")
        after = vector_search()
        stale = next((p for p in after if p["productId"] == product_id), None)
        print(f"after: vector search {'still returns' if stale else 'no longer returns'} {product_id}"
              + (f" with price {stale['price']} from the index" if stale else ""))
        print(json.dumps({"productId": product_id, "maxPrice": MAX_PRICE, "dbPrice": raised,
                          "indexPrice": stale["price"] if stale else None, "violatesMaxPrice": bool(stale)}))
    finally:
        sql(f"update products set price = {db_price} where id = {product_id}")
        print(f"restored price of {product_id} to {db_price}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
