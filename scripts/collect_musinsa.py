"""Collect a small Musinsa beauty sample into JSONL.

No login, >= 1s between requests, and stop on the first failed request without
retrying around it. Raw responses are never written: reviewer identifiers and
raw height/weight must not leave this process.

    uv run python scripts/collect_musinsa.py --category 104001 --products 25 --review-pages 3
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LIST_URL = "https://api.musinsa.com/api2/dp/v2/plp/goods"
REVIEW_URL = "https://goods.musinsa.com/api2/review/v1/view/list"
REQUEST_INTERVAL_SECONDS = 1.3
REVIEW_PAGE_SIZE = 20

PHONE = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class Blocked(Exception):
    pass


class Client:
    def __init__(self) -> None:
        self.last_request_at = 0.0
        self.request_count = 0

    def get(self, url: str, params: dict) -> dict:
        wait = REQUEST_INTERVAL_SECONDS - (time.monotonic() - self.last_request_at)
        if wait > 0:
            time.sleep(wait)
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        self.last_request_at = time.monotonic()
        self.request_count += 1
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise Blocked(f"{full_url}: {error}") from error


def mask(text: str) -> str:
    return EMAIL.sub("[이메일]", PHONE.sub("[전화번호]", text))


def bucket(value: int, step: int, low: int, high: int) -> tuple[int | None, int | None]:
    """Values outside [low, high) become open-ended. 0 means not provided.

    >>> bucket(163, 5, 140, 200), bucket(0, 5, 140, 200)
    ((160, 165), (None, None))
    >>> bucket(130, 5, 140, 200), bucket(205, 5, 140, 200)
    ((None, 140), (200, None))
    >>> mask("010-1234-5678 a.b@x.com 좋아요")
    '[전화번호] [이메일] 좋아요'
    """
    if value <= 0:
        return None, None
    if value < low:
        return None, low
    if value >= high:
        return high, None
    start = value - value % step
    return start, start + step


def to_review(raw: dict, collected_on: str) -> dict:
    profile = raw.get("userProfileInfo") or {}
    height = bucket(profile.get("userHeight") or 0, 5, 140, 200)
    weight = bucket(profile.get("userWeight") or 0, 5, 35, 120)
    return {
        "externalId": raw["no"],
        "content": mask(raw.get("content") or ""),
        "grade": int(raw["grade"]),
        "likeCount": raw.get("likeCount") or 0,
        "optionText": None if raw.get("goodsOption") in (None, "", "NONE") else raw["goodsOption"],
        "skinType": profile.get("skinType") or None,
        "skinTone": profile.get("skinTone") or None,
        "gender": profile.get("reviewSex") or None,
        "heightMinCm": height[0],
        "heightMaxCm": height[1],
        "weightMinKg": weight[0],
        "weightMaxKg": weight[1],
        "writtenAt": raw["createDate"],
        "survey": raw.get("reviewSurveySatisfaction"),
        "collectedOn": collected_on,
    }


def to_product(raw: dict, category: str, collected_on: str) -> dict:
    return {
        "externalId": raw["goodsNo"],
        "name": raw["goodsName"],
        "brandName": raw["brandName"],
        "categoryCode": category,
        "normalPrice": raw["normalPrice"],
        "price": raw["price"],
        "reviewCount": raw["reviewCount"],
        "reviewScore": raw["reviewScore"],
        "isSoldOut": raw["isSoldOut"],
        "collectedOn": collected_on,
    }


def list_products(client: Client, category: str, count: int) -> list[dict]:
    products, seen, page = [], set(), 1
    while len(products) < count:
        body = client.get(LIST_URL, {"category": category, "sortCode": "POPULAR", "page": page,
                                     "size": 60, "caller": "CATEGORY", "gf": "A"})
        items = body["data"]["list"]
        for item in items:
            if item["goodsNo"] not in seen and item["reviewCount"] > 0:
                seen.add(item["goodsNo"])
                products.append(item)
        if not body["data"]["pagination"]["hasNext"] or not items:
            break
        page += 1
    return products[:count]


def list_reviews(client: Client, goods_no: int, pages: int) -> list[dict]:
    reviews = []
    for page in range(pages):
        body = client.get(REVIEW_URL, {"page": page, "pageSize": REVIEW_PAGE_SIZE, "goodsNo": goods_no,
                                       "sort": "up_cnt_desc", "selectedSimilarNo": goods_no,
                                       "myFilter": "false", "hasPhoto": "false", "isExperience": "false"})
        items, page_info = body["data"]["list"], body["data"].get("page")
        reviews.extend(items)
        # Some goods answer 200 with page: null.
        if not items or not page_info or page + 1 >= page_info["totalPages"]:
            break
    return reviews


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="104001")
    parser.add_argument("--products", type=int, default=25)
    parser.add_argument("--review-pages", type=int, default=3)
    parser.add_argument("--out-dir", default=".local/musinsa")
    args = parser.parse_args()

    collected_on = dt.date.today().isoformat()
    out = Path(args.out_dir) / f"{args.category}-{collected_on}.jsonl"
    part = out.with_name(out.name + ".part")
    out.parent.mkdir(parents=True, exist_ok=True)
    client = Client()

    written = 0
    try:
        products = list_products(client, args.category, args.products)
        with part.open("w", encoding="utf-8") as file:
            for raw in products:
                product = to_product(raw, args.category, collected_on)
                product["reviews"] = [to_review(r, collected_on)
                                      for r in list_reviews(client, raw["goodsNo"], args.review_pages)]
                file.write(json.dumps(product, ensure_ascii=False) + "\n")
                file.flush()
                written += 1
    except Blocked as error:
        print(f"stopped after {client.request_count} requests, {written} products in {part}: {error}",
              file=sys.stderr)
        return 1

    part.replace(out)
    print(f"{written} products, {client.request_count} requests -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
