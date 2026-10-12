"""Collect the option list (axes and sellable option items) of already collected products into JSONL.

Same rules as collect_musinsa.py: no login, >= 1s between requests, stop on the first failed request.
The response carries no stock or sold-out field, so only option names, codes and extra prices are kept.
Reruns skip products already written.

    uv run python scripts/collect_options.py .local/musinsa/full/*.jsonl --limit 50
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from collect_musinsa import Blocked, Client

OPTIONS_URL = "https://goods-detail.musinsa.com/api2/goods/{}/options"


def product_ids(paths: list[str]) -> list[int]:
    ids = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").split("\n"):
            if line:
                ids.setdefault(json.loads(line)["externalId"], None)
    return list(ids)


def done_ids(out: Path) -> set[int]:
    if not out.exists():
        return set()
    return {json.loads(line)["externalId"] for line in out.read_text(encoding="utf-8").split("\n") if line}


def slim(data: dict) -> dict:
    """Keep what an option picker and option-level stock need.

    >>> data = {"basic": [{"no": 1, "name": "색상", "displayType": "DROPDOWN", "isDeleted": False,
    ...     "optionValues": [{"no": 10, "name": "21호", "code": "21", "color": None, "isDeleted": False, "imageUrl": "x"}]}],
    ...     "extra": [], "optionItems": [{"no": 100, "optionValueNos": [10], "managedCode": "21", "price": 0,
    ...     "activated": True, "isDeleted": False, "optionValues": [], "colors": []}]}
    >>> slim(data)["axes"][0]["values"]
    [{'no': 10, 'name': '21호', 'code': '21', 'color': None, 'isDeleted': False}]
    >>> slim(data)["items"]
    [{'no': 100, 'valueNos': [10], 'managedCode': '21', 'price': 0, 'activated': True, 'isDeleted': False}]
    """
    axes = [{"no": a["no"], "name": a["name"], "isDeleted": a["isDeleted"],
             "values": [{k: v[k] for k in ("no", "name", "code", "color", "isDeleted")} for v in a["optionValues"]]}
            for a in data.get("basic") or []]
    items = [{"no": i["no"], "valueNos": i["optionValueNos"], "managedCode": i["managedCode"], "price": i["price"],
              "activated": i["activated"], "isDeleted": i["isDeleted"]}
             for i in data.get("optionItems") or []]
    return {"axes": axes, "extraCount": len(data.get("extra") or []), "items": items}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", default=".local/musinsa/options/options.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = done_ids(out)
    todo = [i for i in product_ids(args.files) if i not in done][:args.limit]
    collected_on = dt.date.today().isoformat()
    client = Client()
    print(f"{len(done)} already collected, {len(todo)} to go", flush=True)

    with out.open("a", encoding="utf-8") as file:
        for count, external_id in enumerate(todo, 1):
            try:
                body = client.get(OPTIONS_URL.format(external_id), {})
            except Blocked as error:
                print(f"stopped after {count - 1}: {error}", file=sys.stderr)
                return 1
            if (body.get("meta") or {}).get("result") != "SUCCESS":
                print(f"stopped after {count - 1}: {external_id} answered {body.get('meta')}", file=sys.stderr)
                return 1
            record = {"externalId": external_id, **slim(body.get("data") or {}), "collectedOn": collected_on}
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
            if count % 100 == 0:
                print(f"{count}/{len(todo)}", flush=True)

    print(f"done: {len(todo)} collected, {client.request_count} requests", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
