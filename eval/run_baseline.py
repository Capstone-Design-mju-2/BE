"""Baseline for the quality question set: rule extraction + keyword search, no LLM (ADR-93).

uv run --package agent-service python eval/run_baseline.py <label> > .local/eval/baseline-<label>.txt

Quality is scored against eval/quality-judgments.json. Latency is measured client side, one HTTP search call
from send to full body, after one warmup round.
"""

import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_service.extract import extract

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pool import ROOT, hard_violation, sql  # noqa: E402

CATALOG_URL = "http://127.0.0.1:8081"
ORDER_URL = "http://127.0.0.1:8082"
TOP = 5
ROUNDS = 20
CONCURRENCY = (1, 10)


def search_params(text: str) -> dict | None:
    term, max_price = extract(text)
    if term is None:
        return None
    params = {"q": term, "limit": TOP}
    if max_price is not None:
        params["maxPrice"] = max_price
    return params


def search(params: dict) -> list[dict]:
    with urllib.request.urlopen(f"{CATALOG_URL}/api/v1/products/search?{urllib.parse.urlencode(params)}") as r:
        return json.load(r)["products"]


def out_of_stock(ids: list[int]) -> list[int]:
    if not ids:
        return []
    request = urllib.request.Request(f"{ORDER_URL}/api/v1/inventories/check", json.dumps({"productIds": ids}).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as r:
        return [i["productId"] for i in json.load(r)["inventories"] if i["status"] != "IN_STOCK"]


def quality(questions: list[dict], judgments: dict) -> dict:
    rows = []
    for q in questions:
        params = search_params(q["text"])
        products = search(params) if params else []
        ids = [p["productId"] for p in products]
        relevant = judgments[q["id"]]["relevant"]
        judged = relevant.keys() | judgments[q["id"]]["notRelevant"].keys()
        violations = {}
        for p in products:
            info = {"id": p["productId"], "category": sql(f"select category_code from products where id = {p['productId']}"),
                    "price": p["price"], "brand": p["brand"]}
            v = hard_violation(q, info)
            if v:
                violations[p["productId"]] = v
        rows.append({"id": q["id"], "params": params, "ids": ids,
                     "relevant": [i for i in ids if str(i) in relevant],
                     "unjudged": [i for i in ids if str(i) not in judged],
                     "violations": violations, "outOfStock": out_of_stock(ids),
                     "answerKeySize": len(relevant)})
    shown = sum(len(r["ids"]) for r in rows)
    return {
        "rows": rows,
        "hitAt5": sum(1 for r in rows if r["relevant"]) / len(rows),
        "relevantInTop5Mean": statistics.mean(len(r["relevant"]) for r in rows),
        "precisionAt5": sum(len(r["relevant"]) for r in rows) / (TOP * len(rows)),
        "shown": shown,
        "violationRate": sum(len(r["violations"]) for r in rows) / shown if shown else 0,
        "questionsWithViolation": sum(1 for r in rows if r["violations"]),
        "outOfStock": sum(len(r["outOfStock"]) for r in rows),
        "emptyResults": sum(1 for r in rows if not r["ids"]),
        "unjudged": sum(len(r["unjudged"]) for r in rows),
    }


def timed(params: dict) -> float:
    start = time.perf_counter()
    search(params)
    return (time.perf_counter() - start) * 1000


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(p / 100 * len(ordered)) - 1]


def latency(questions: list[dict]) -> dict:
    params = [p for p in (search_params(q["text"]) for q in questions) if p]
    for p in params:
        timed(p)
    result = {"requestsPerRun": len(params) * ROUNDS}
    for workers in CONCURRENCY:
        with ThreadPoolExecutor(workers) as pool:
            started = time.perf_counter()
            ms = list(pool.map(timed, params * ROUNDS))
            wall = time.perf_counter() - started
        result[f"concurrency{workers}"] = {
            "p50": round(percentile(ms, 50), 1), "p95": round(percentile(ms, 95), 1),
            "p99": round(percentile(ms, 99), 1), "max": round(max(ms), 1), "throughputPerSec": round(len(ms) / wall, 2),
        }
    return result


def main() -> None:
    label = sys.argv[1]
    questions = json.loads((ROOT / "eval/quality-questions.json").read_text())["questions"]
    judgments = json.loads((ROOT / "eval/quality-judgments.json").read_text())["judgments"]
    q = quality(questions, judgments)
    for r in q["rows"]:
        print(f"{r['id']} params={r['params']} top={r['ids']} 정답={r['relevant']} "
              f"위반={r['violations']} 재고없음={r['outOfStock']} 미판정={r['unjudged']} 정답총수={r['answerKeySize']}")
    summary = {k: v for k, v in q.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False))
    lat = latency(questions)
    print(json.dumps(lat))
    out = ROOT / f".local/eval/baseline-{label}.json"
    out.write_text(json.dumps({"label": label, "quality": q, "latency": lat}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
