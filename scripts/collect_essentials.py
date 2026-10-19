"""Collect the product notice (cosmetics ingredients or food raw materials, functional claims) of already collected products into JSONL.

Same rules as collect_musinsa.py: no login, >= 1s between requests, stop on the first failed request.
Only the ingredient and functional-cosmetics fields are kept. Reruns skip products already written.

    uv run python scripts/collect_essentials.py .local/musinsa/full/*.jsonl --limit 50
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from collect_musinsa import Blocked, Client

ESSENTIAL_URL = "https://goods-detail.musinsa.com/api2/goods/{}/essential"


def pick(essentials: list[dict], keyword: str) -> str | None:
    """Notice field names vary by seller, so match on a keyword.

    >>> notice = [{"name": "제조국", "value": "대한민국"}, {"name": "화장품법에 따라 기재, 표시하여야 하는 모든 성분", "value": "정제수, 글리세린"}]
    >>> pick(notice, "모든 성분"), pick(notice, "기능성")
    ('정제수, 글리세린', None)
    >>> pick([{"name": "원료명 및 함량", "value": "유청단백분말, 코코아분말"}], "원료명")
    '유청단백분말, 코코아분말'
    >>> pick([{"name": "원재료명", "value": "현미, 귀리"}], "원재료")
    '현미, 귀리'
    """
    return next((e["value"] for e in essentials if keyword in e["name"]), None)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", default=".local/musinsa/essentials/essentials.jsonl")
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
                body = client.get(ESSENTIAL_URL.format(external_id), {})
            except Blocked as error:
                print(f"stopped after {count - 1}: {error}", file=sys.stderr)
                return 1
            if (body.get("meta") or {}).get("result") != "SUCCESS":
                print(f"stopped after {count - 1}: {external_id} answered {body.get('meta')}", file=sys.stderr)
                return 1
            essentials = (body.get("data") or {}).get("essentials") or []
            # Cosmetics list ingredients under "...모든 성분"; health food under "원료명 및 함량", other food "원재료명".
            ingredients = pick(essentials, "모든 성분") or pick(essentials, "원료명") or pick(essentials, "원재료")
            record = {"externalId": external_id, "ingredients": ingredients,
                      "functional": pick(essentials, "기능성"), "collectedOn": collected_on}
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
            if count % 100 == 0:
                print(f"{count}/{len(todo)}", flush=True)

    print(f"done: {len(todo)} collected, {client.request_count} requests", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
