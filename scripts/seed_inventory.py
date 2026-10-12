"""Create initial order inventory for loaded catalog products, one row per Musinsa option item (SKU).

Catalog has no list API, so each JSONL line is posted to the idempotent load API again
to learn its productId. Options come from collect_options.py. The order load API leaves the
quantity of an existing option alone, which makes reruns no-ops; empty the table first
(make reset-inventory CONFIRM=1) to apply new quantities.

    uv run python scripts/seed_inventory.py .local/musinsa/104001-2026-09-30.jsonl
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import Counter

from load_catalog import drop_unrated

LOAD_BATCH = 50


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


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def sku_options(product: dict, record: dict) -> list[dict]:
    """One inventory row per option item. An option no rated review names starts sold out (ADR-78).

    One axis: reviews whose option text is the value. Two axes (2-pick sets): reviews are split on
    '·' and counted per value, and an item takes the smaller of its two values (ADR-80). Products
    without options keep the product-level rule.

    >>> product = {"name": "쿠션", "price": 30000, "reviewCount": 548,
    ...            "reviews": [{"optionText": "21호 본품"}, {"optionText": "21 호 본품"}, {"optionText": None}]}
    >>> one_axis = {"axes": [{"name": "컬러", "values": [{"no": 1, "name": "21호 본품"}, {"no": 2, "name": "23호 리필"}]}],
    ...             "items": [{"no": 11, "valueNos": [1], "price": 9700}, {"no": 12, "valueNos": [2], "price": 0}]}
    >>> sku_options(product, one_axis)
    [{'optionKey': '11', 'name': '21호 본품', 'price': 39700, 'quantity': 3}, {'optionKey': '12', 'name': '23호 리필', 'price': 30000, 'quantity': 0}]
    >>> values = [{"no": 1, "name": "A"}, {"no": 2, "name": "B"}, {"no": 3, "name": "C"}]
    >>> sets = {"axes": [{"name": "선택", "values": values}] * 2,
    ...         "items": [{"no": 21, "valueNos": [1, 2], "price": 0}, {"no": 22, "valueNos": [1, 3], "price": 0}]}
    >>> [(o["name"], o["quantity"]) for o in sku_options({**product, "reviews": [{"optionText": "A · B"}]}, sets)]
    [('A + B', 3), ('A + C', 0)]
    >>> none = {"axes": [{"name": "NONE", "values": [{"no": 9, "name": "NONE"}]}], "items": [{"no": 31, "valueNos": [9], "price": 0}]}
    >>> sku_options(product, none)
    [{'optionKey': '31', 'name': '쿠션', 'price': 30000, 'quantity': 10}]
    """
    names = {value["no"]: value["name"] for axis in record["axes"] for value in axis["values"]}
    texts = [review["optionText"] for review in product["reviews"] if review.get("optionText")]
    without_options = [axis["name"] for axis in record["axes"]] == ["NONE"]
    if len(record["axes"]) == 1:
        # Three one-axis value names contain '·', so only sets are split.
        mentions = Counter(norm(text) for text in texts)
    else:
        mentions = Counter(norm(part) for text in texts for part in text.split("·"))

    rows = []
    for item in record["items"]:
        values = [names[no] for no in item["valueNos"]]
        if without_options:
            name, stock = product["name"], quantity(product["reviewCount"])
        else:
            count = min(mentions[norm(value)] for value in values)
            name, stock = " + ".join(values), quantity(count) if count else 0
        rows.append({"optionKey": str(item["no"]), "name": name, "price": product["price"] + item["price"],
                     "quantity": stock})
    return rows


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
    parser.add_argument("--options", default=".local/musinsa/options/options.jsonl")
    args = parser.parse_args()
    catalog, order = base_url("CATALOG", "8081"), base_url("ORDER", "8082")
    with open(args.options, encoding="utf-8") as file:
        options = {record["externalId"]: record for record in map(json.loads, file)}

    products = created = present = sold_out = 0
    for path in args.files:
        with open(path, encoding="utf-8") as file:
            for line in file:
                product, _ = drop_unrated(json.loads(line))
                if product["externalId"] not in options:
                    print(f"no options for {product['externalId']}; run collect_options.py first", file=sys.stderr)
                    return 1
                product_id = post(f"{catalog}/internal/products/load", product)["productId"]
                rows = sku_options(product, options[product["externalId"]])
                # The load API accepts at most 50 options per request.
                for start in range(0, len(rows), LOAD_BATCH):
                    result = post(f"{order}/api/v1/internal/inventories/load",
                                  {"productId": product_id, "options": rows[start:start + LOAD_BATCH]})
                    created += result["inserted"]
                    present += result["updated"]
                products += 1
                sold_out += sum(1 for row in rows if row["quantity"] == 0)

    print(f"{products} products, {created} inventories created, {present} already present, "
          f"{sold_out} sold out as sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
