"""Load collected JSONL into catalog-service, one product per request.

    uv run python scripts/load_catalog.py .local/musinsa/104001-2026-09-30.jsonl
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def drop_unrated(product: dict) -> tuple[dict, int]:
    """reviews.grade is CHECK 1..5, but Musinsa sends 0 for reviews without a star rating (ADR-65).

    >>> drop_unrated({"reviews": [{"grade": 0}, {"grade": 4}]})
    ({'reviews': [{'grade': 4}]}, 1)
    """
    rated = [r for r in product["reviews"] if r["grade"] >= 1]
    return {**product, "reviews": rated}, len(product["reviews"]) - len(rated)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--base-url", default="http://{}:{}".format(
        os.getenv("CATALOG_SERVICE_HOST", "127.0.0.1"), os.getenv("CATALOG_SERVICE_PORT", "8081")))
    args = parser.parse_args()

    products = reviews = skipped = 0
    for path in args.files:
        with open(path, encoding="utf-8") as file:
            for line in file:
                product, dropped = drop_unrated(json.loads(line))
                skipped += dropped
                request = urllib.request.Request(f"{args.base_url}/internal/products/load",
                                                 data=json.dumps(product, ensure_ascii=False).encode(),
                                                 headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        reviews += json.load(response)["reviewCount"]
                except urllib.error.HTTPError as error:
                    print(f"{path}: {error.code} {error.read().decode()[:300]}", file=sys.stderr)
                    return 1
                products += 1

    print(f"loaded {products} products, {reviews} reviews, skipped {skipped} unrated reviews")
    return 0


if __name__ == "__main__":
    sys.exit(main())
