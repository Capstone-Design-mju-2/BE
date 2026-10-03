"""Create initial order inventory for loaded catalog products.

Catalog has no list API, so each JSONL line is posted to the idempotent load API again
to learn its productId. Only products the order service reports as NOT_FOUND are created,
which makes reruns no-ops. Replace with the option/stock load API in week 6.

    uv run python scripts/seed_inventory.py .local/musinsa/104001-2026-09-30.jsonl
"""

import argparse
import json
import os
import sys
import urllib.request

CHECK_BATCH = 20


def quantity(review_count: int) -> int:
    """
    >>> [quantity(n) for n in (0, 49, 50, 999, 1000)]
    [3, 3, 10, 10, 30]
    """
    if review_count < 50:
        return 3
    if review_count < 1000:
        return 10
    return 30


def post(url: str, body: dict | str) -> dict:
    data = body if isinstance(body, str) else json.dumps(body)
    request = urllib.request.Request(url, data=data.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def base_url(service: str, default_port: str) -> str:
    return "http://{}:{}".format(os.getenv(f"{service}_SERVICE_HOST", "127.0.0.1"),
                                 os.getenv(f"{service}_SERVICE_PORT", default_port))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    catalog, order = base_url("CATALOG", "8081"), base_url("ORDER", "8082")

    review_counts = {}
    for path in args.files:
        with open(path, encoding="utf-8") as file:
            for line in file:
                product_id = post(f"{catalog}/internal/products/load", line)["productId"]
                review_counts[product_id] = json.loads(line)["reviewCount"]

    ids = list(review_counts)
    missing = []
    for start in range(0, len(ids), CHECK_BATCH):
        result = post(f"{order}/api/v1/inventories/check", {"productIds": ids[start:start + CHECK_BATCH]})
        missing += [i["productId"] for i in result["inventories"] if i["status"] == "NOT_FOUND"]

    for product_id in missing:
        post(f"{order}/inventory", {"productId": product_id, "quantity": quantity(review_counts[product_id])})

    print(f"{len(ids)} products, {len(missing)} inventories created, {len(ids) - len(missing)} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
