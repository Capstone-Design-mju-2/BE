"""Load initial option stock for catalog products through the order load API.

Catalog has no list API, so each JSONL line is posted to the idempotent catalog load API
to learn its productId. Each product gets one "default" option. The order load API is
idempotent and never changes stock of existing options, so reruns are no-ops.
To reset demo stock, use scripts/reset_demo_stock.sh.

    uv run python scripts/seed_inventory.py .local/musinsa/104001-2026-09-30.jsonl --sold-out 101,205
"""

import argparse
import json
import os
import sys
import urllib.request

DEFAULT_OPTION = "default"


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


def parse_ids(text: str) -> set[int]:
    """
    >>> sorted(parse_ids("101, 205,"))
    [101, 205]
    >>> parse_ids("")
    set()
    """
    return {int(part) for part in text.split(",") if part.strip()}


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
    parser.add_argument("--sold-out", default="", help="comma-separated productIds seeded with quantity 0")
    args = parser.parse_args()
    sold_out = parse_ids(args.sold_out)
    catalog, order = base_url("CATALOG", "8081"), base_url("ORDER", "8082")

    inserted = updated = 0
    for path in args.files:
        with open(path, encoding="utf-8") as file:
            for line in file:
                product = json.loads(line)
                product_id = post(f"{catalog}/internal/products/load", line)["productId"]
                if product.get("isSoldOut") or product_id in sold_out:
                    stock = 0
                else:
                    stock = quantity(product["reviewCount"])
                result = post(f"{order}/api/v1/internal/inventories/load", {
                    "productId": product_id,
                    "options": [{
                        "optionKey": DEFAULT_OPTION,
                        "name": product["name"],
                        "price": product["price"],
                        "quantity": stock,
                    }],
                })
                inserted += result["inserted"]
                updated += result["updated"]

    print(f"{inserted} options inserted, {updated} already present, sold out: {sorted(sold_out)}")