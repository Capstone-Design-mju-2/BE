"""Pool judging candidates for the quality question set (ADR-93).

uv run --package agent-service python eval/build_pool.py > .local/eval/pool.txt

Three independent ways per question, so the answer key does not only contain what keyword search already finds:
  keyword  - the system under test: rule extraction + catalog search API (limit 10)
  popular  - category / price / brand / product-type filters, most reviewed first
  writers  - same filters, most reviews from the asked skin type (or the best survey answer) first
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from agent_service.extract import extract

ROOT = Path(__file__).resolve().parent.parent
CATALOG_URL = "http://127.0.0.1:8081"
POOL_JSON = ROOT / ".local/eval/pool.json"
PER_METHOD = 10
TOP_SURVEY_ANSWERS = ("매우 높음", "매우 좋음", "전혀없음", "전혀 없음", "거의없음", "거의 없음", "매우 만족")


def sql(query: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "catalog-db", "psql", "-U", "catalog", "-d", "catalog", "-tA", "-c", query],
        cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def filters(q: dict) -> str:
    parts = [f"p.category_code in ({', '.join(literal(c) for c in q['categories'])})"]
    if q.get("maxPrice"):
        parts.append(f"p.price <= {int(q['maxPrice'])}")
    if q.get("brand"):
        parts.append(f"p.brand_name = {literal(q['brand'])}")
    parts.append("(" + " or ".join(f"p.name ilike {literal('%' + t + '%')}" for t in q["typeNames"]) + ")")
    parts += [f"p.name not ilike {literal('%' + t + '%')}" for t in q.get("excludeNames", [])]
    return " and ".join(parts)


def keyword(q: dict) -> list[int]:
    term, max_price = extract(q["text"])
    if term is None:
        return []
    params = {"q": term, "limit": PER_METHOD}
    if max_price is not None:
        params["maxPrice"] = max_price
    with urllib.request.urlopen(f"{CATALOG_URL}/api/v1/products/search?{urllib.parse.urlencode(params)}") as r:
        return [p["productId"] for p in json.load(r)["products"]]


def popular(q: dict) -> list[int]:
    rows = sql(f"select p.id from products p where {filters(q)} order by p.review_count desc, p.id limit {PER_METHOD}")
    return [int(x) for x in rows.splitlines() if x]


def writers(q: dict) -> list[int]:
    conds = []
    if q.get("skinType"):
        conds.append(f"r.skin_type = {literal(q['skinType'])}")
    if q.get("surveyAttr"):
        answers = ", ".join(literal(a) for a in TOP_SURVEY_ANSWERS)
        conds.append(f"exists (select 1 from review_survey_answers s where s.review_id = r.id "
                     f"and s.attribute = {literal(q['surveyAttr'])} and s.answer in ({answers}))")
    if not conds:  # no skin type or survey to lean on: best rated among well-reviewed products
        rows = sql(f"select p.id from products p where {filters(q)} and p.review_count >= 30 "
                   f"order by p.review_score desc, p.review_count desc, p.id limit {PER_METHOD}")
    else:
        rows = sql(f"select p.id from products p join reviews r on r.product_id = p.id where {filters(q)} "
                   f"and {' and '.join(conds)} group by p.id order by count(*) desc, p.id limit {PER_METHOD}")
    return [int(x) for x in rows.splitlines() if x]


def hard_violation(q: dict, info: dict) -> str | None:
    """Conditions a shopper states outright are checked by code, not judged.

    Product type is left to the judge: name matching missed "선 세럼" for "선세럼" and rejected toner sets with pads.
    """
    if info["category"] not in q["categories"]:
        return f"카테고리 {info['category']}"
    if q.get("maxPrice") and info["price"] > q["maxPrice"]:
        return f"가격 {info['price']}원"
    if q.get("brand") and info["brand"] != q["brand"]:
        return f"브랜드 {info['brand']}"
    return None


def digest(q: dict, product_id: int) -> tuple[str, str | None]:
    info = json.loads(sql(
        f"select json_build_object('name', name, 'brand', brand_name, 'price', price, 'category', category_code, "
        f"'reviews', review_count, 'score', review_score) from products where id = {product_id}"))
    head = (f"  [{product_id}] {info['brand']} | {info['name'][:60]} | {info['price']}원 | cat {info['category']} "
            f"| 리뷰 {info['reviews']} | 점수 {info['score']}")
    violation = hard_violation(q, info)
    if violation:
        return f"{head}\n    자동 아님: {violation}", violation
    lines = [head]
    if q.get("surveyAttr"):
        dist = sql(f"select string_agg(answer || ' ' || n, ', ' order by n desc) from (select s.answer, count(*) n "
                   f"from review_survey_answers s join reviews r on r.id = s.review_id where r.product_id = {product_id} "
                   f"and s.attribute = {literal(q['surveyAttr'])} group by 1) t")
        lines.append(f"    설문 {q['surveyAttr']}: {dist or '없음'}")
    if q.get("skinType"):
        n = sql(f"select count(*) from reviews where product_id = {product_id} and skin_type = {literal(q['skinType'])}")
        lines.append(f"    {q['skinType']} 작성자 리뷰 {n}개")
    seed = q["id"]
    target = f"and skin_type = {literal(q['skinType'])}" if q.get("skinType") else ""
    sample = sql(f"select grade || '★ ' || coalesce(skin_type, '-') || ' | ' || left(replace(content, E'\\n', ' '), 70) "
                 f"from reviews where product_id = {product_id} {target} "
                 f"order by md5(id::text || {literal(seed)}) limit 2")
    # The judge searches reviews for the asked aspect the way a shopper would (Ctrl+F); quoted with both polarities.
    aspect = sql(f"select grade || '★ ' || coalesce(skin_type, '-') || ' | ' || "
                 f"substr(replace(content, E'\\n', ' '), greatest(1, {aspect_position(q)} - 25), 75) "
                 f"from reviews where product_id = {product_id} and ({aspect_match(q)}) "
                 f"order by md5(id::text || {literal(seed + 'a')}) limit 3")
    lines += [f"    무작위: {s}" for s in sample.splitlines()]
    lines += [f"    조건언급: {s}" for s in aspect.splitlines()]
    return "\n".join(lines), None


def aspect_match(q: dict) -> str:
    return " or ".join(f"content like {literal('%' + t + '%')}" for t in q["aspectTerms"])


def aspect_position(q: dict) -> str:
    """Where the first asked aspect appears, so the excerpt shows the sentence about it rather than the opening."""
    positions = ", ".join(f"nullif(strpos(content, {literal(t)}), 0)" for t in q["aspectTerms"])
    return f"coalesce(least({positions}), 1)"


def main() -> None:
    questions = json.loads((ROOT / "eval/quality-questions.json").read_text())["questions"]
    only = set(sys.argv[1:])
    pool = {}
    for q in questions:
        if only and q["id"] not in only:
            continue
        methods = {"keyword": keyword(q), "popular": popular(q), "writers": writers(q)}
        ids = list(dict.fromkeys(i for m in methods.values() for i in m))
        print(f"=== {q['id']} {q['text']}")
        print(f"  기준: {q['criteria']}")
        print(f"  방법별: {json.dumps(methods)}")
        auto_no = {}
        for product_id in ids:
            text, violation = digest(q, product_id)
            if violation:
                auto_no[product_id] = violation
            print(text)
        pool[q["id"]] = {"methods": methods, "candidates": ids, "autoNo": auto_no}
        sys.stdout.flush()
    POOL_JSON.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(POOL_JSON.read_text()) if POOL_JSON.exists() else {}
    existing.update(pool)
    POOL_JSON.write_text(json.dumps(existing, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
