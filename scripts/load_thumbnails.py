"""Load thumbnail addresses from collect_thumbnails.py into catalog-service, one product per request (ADR-127).

    uv run python scripts/load_thumbnails.py .local/musinsa/thumbnails.jsonl

A listed product that is not in the catalog (listed after collection) is counted and skipped.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--base-url", default="http://{}:{}".format(
        os.getenv("CATALOG_SERVICE_HOST", "127.0.0.1"), os.getenv("CATALOG_SERVICE_PORT", "8081")))
    args = parser.parse_args()

    loaded = missing = 0
    with open(args.file, encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            request = urllib.request.Request(
                f"{args.base_url}/internal/products/{record['externalId']}/image", method="PUT",
                data=json.dumps({"imageUrl": record["imageUrl"]}).encode(), headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(request, timeout=30).close()
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    missing += 1
                    continue
                print(f"{record['externalId']}: {error.code} {error.read().decode()[:300]}", file=sys.stderr)
                return 1
            loaded += 1

    print(f"loaded {loaded} thumbnails, {missing} listed products not in the catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
