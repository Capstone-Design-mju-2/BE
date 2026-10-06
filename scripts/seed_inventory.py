"""Create initial order inventory for loaded catalog products.

Catalog has no list API, so each JSONL line is posted to the idempotent load API again
to learn its productId. The collected data has no options yet, so every product gets one
default option (optionKey ""). The order load API leaves the quantity of an existing option
alone, which makes reruns no-ops. Replace with real options once the collector sends them.

    uv run python scripts/seed_inventory.py .local/musinsa/104001-2026-09-30.jsonl
"""

import argparse
import json
import os
import sys
import urllib.request

from load_catalog import drop_unrated


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

    products = created = present = 0
    for path in args.files:
        with open(path, encoding="utf-8") as file:
            for line in file:
                product, _ = drop_unrated(json.loads(line))
                product_id = post(f"{catalog}/internal/products/load", product)["productId"]
                option = {"optionKey": "", "name": product["name"], "price": product["price"],
                          "quantity": quantity(product["reviewCount"])}
                result = post(f"{order}/api/v1/internal/inventories/load",
                              {"productId": product_id, "options": [option]})
                products += 1
                created += result["inserted"]
                present += result["updated"]

    print(f"{products} products, {created} inventories created, {present} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
