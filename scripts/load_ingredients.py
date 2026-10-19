"""Load ingredient lists into catalog-service, one product per request (ADR-75, ADR-97).

    uv run python scripts/load_ingredients.py .local/musinsa/essentials/essentials.jsonl \\
        .local/musinsa/essentials/essentials-food.jsonl .local/musinsa/essentials/essentials-food-retry.jsonl \\
        --glowpick .local/musinsa/essentials/glowpick.jsonl

Musinsa notices come from collect_essentials.py. When a notice only says "see the detail page", the Glowpick match
fills in. A product with neither is sent as empty, so it counts as unknown and any ingredient exclusion drops it.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

MIN_NAMES = 3
MAX_NAME = 100


def parse_ingredients(text: str | None) -> list[str] | None:
    """Split a notice into ingredient names, or None when it is not a usable list.

    >>> parse_ingredients("정제수, 글리세린, 1,2-헥산다이올, 하이알루로닉애씨드(1,000 ppm), 향료")
    ['정제수', '글리세린', '1,2-헥산다이올', '하이알루로닉애씨드', '향료']
    >>> parse_ingredients("[01호] 정제수,미네랄 오일<br />리날룰(향료), 에탄올(발효주정)")
    ['정제수', '미네랄오일', '리날룰', '향료', '에탄올']
    >>> parse_ingredients("상세페이지 참조"), parse_ingredients(None)
    (None, None)

    Lists separated by spaces come out as one long name; one of them makes the whole list unknown.

    >>> parse_ingredients("정제수, 글리세린, " + "가" * 101) is None
    True
    """
    if not text:
        return None
    return _names(_split(re.sub(r"<[^>]*>", "\n", text)))


def glowpick_ingredients(record: dict) -> list[str] | None:
    """Glowpick's list for a matched product. Only same-volume matches are used: in the 30-product check they all
    agreed at least 85% with the Musinsa notice, while a different volume turned out to be another version (ADR-75).

    >>> glowpick_ingredients({"found": True, "volumeMatch": True, "ingredientsKo": ["정제수", "글리세린", "향료(리모넨)"]})
    ['정제수', '글리세린', '향료']
    >>> glowpick_ingredients({"found": True, "volumeMatch": False, "ingredientsKo": ["정제수", "글리세린", "향료"]})
    """
    if not (record.get("found") and record.get("volumeMatch")):
        return None
    return _names(record.get("ingredientsKo") or [])


def _names(tokens: list[str]) -> list[str] | None:
    names: list[str] = []
    for token in tokens:
        token = re.sub(r"^\[[^\]]*\]", "", token)
        base, _, rest = token.partition("(")
        base = re.sub(r"\s+", "", base)
        if len(base) > MAX_NAME:
            return None
        # "리날룰(향료)" marks an ingredient used as fragrance.
        for name in (base, "향료" if "향료" in rest else ""):
            if name and name not in names:
                names.append(name)
    return names if len(names) >= MIN_NAMES else None


def _split(text: str) -> list[str]:
    """Split on commas and newlines outside brackets, keeping commas between digits as in "1,2-헥산다이올"."""
    tokens, current, depth = [], [], 0
    for i, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        between_digits = 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()
        if depth <= 0 and (char == "\n" or (char == "," and not between_digits)):
            tokens.append("".join(current).strip())
            current, depth = [], 0
        else:
            current.append(char)
    tokens.append("".join(current).strip())
    return [t for t in tokens if t]


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="Musinsa notices; the first usable list per product wins")
    parser.add_argument("--glowpick", help="Glowpick matches, used only for products without a usable notice")
    parser.add_argument("--base-url", default="http://{}:{}".format(
        os.getenv("CATALOG_SERVICE_HOST", "127.0.0.1"), os.getenv("CATALOG_SERVICE_PORT", "8081")))
    args = parser.parse_args()

    lists: dict[int, dict] = {}
    for path in args.files:
        for record in read_jsonl(path):
            names = parse_ingredients(record.get("ingredients"))
            if record["externalId"] not in lists or (names and not lists[record["externalId"]]["names"]):
                lists[record["externalId"]] = {"names": names or [], "source": "musinsa" if names else None}
    for record in read_jsonl(args.glowpick) if args.glowpick else []:
        names = glowpick_ingredients(record)
        if names and not lists.get(record["externalId"], {}).get("names"):
            lists[record["externalId"]] = {"names": names, "source": "glowpick",
                                           "sourceUrl": f"https://www.glowpick.com/products/{record['glowpickId']}"}

    counts = {"musinsa": 0, "glowpick": 0, None: 0, "missing": 0}
    for external_id, body in lists.items():
        request = urllib.request.Request(
            f"{args.base_url}/internal/products/{external_id}/ingredients", method="PUT",
            data=json.dumps(body, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=30).close()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                counts["missing"] += 1
                continue
            print(f"{external_id}: {error.code} {error.read().decode()[:300]}", file=sys.stderr)
            return 1
        counts[body["source"]] += 1

    print(f"loaded {counts['musinsa']} lists from Musinsa, {counts['glowpick']} from Glowpick, {counts[None]} unknown, "
          f"{counts['missing']} products not in the catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
