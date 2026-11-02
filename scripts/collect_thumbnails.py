"""Collect each listed product's thumbnail address from the Musinsa product lists (ADR-127).

Same request rules as collect_musinsa.py. Only the address is kept: browsers load the image from Musinsa's CDN.
A product no longer listed gets no address.

    uv run python scripts/collect_thumbnails.py 104001 104002 104003 104005 104006 104007 104009 104010 104011 \\
        104012 104013 104014 104015 104016 104017
"""

import argparse
import json
import sys
from pathlib import Path

from collect_musinsa import Blocked, Client, list_products


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("categories", nargs="+", help="category codes, as in products.category_code")
    parser.add_argument("--out", default=".local/musinsa/thumbnails.jsonl")
    args = parser.parse_args()

    client = Client()
    written = 0
    with Path(args.out).open("w", encoding="utf-8") as file:
        try:
            for category in args.categories:
                for item in list_products(client, category, sys.maxsize):
                    if item.get("thumbnail"):
                        file.write(json.dumps({"externalId": item["goodsNo"], "imageUrl": item["thumbnail"]}) + "\n")
                        written += 1
        except Blocked as error:
            print(f"stopped after {client.request_count} requests, {written} thumbnails in {args.out}: {error}",
                  file=sys.stderr)
            return 1
    print(f"{written} thumbnails, {client.request_count} requests -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
