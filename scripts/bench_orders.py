"""Measure order throughput and latency per stock strategy against a running order-service.

Start order-service with the strategy under test, then run both scenarios:

    ./gradlew :services:order-service:bootRun --args='--order.stock-strategy=pessimistic'
    uv run python scripts/bench_orders.py --strategy pessimistic --stock 1000 --requests 1000
    uv run python scripts/bench_orders.py --strategy pessimistic --stock 50 --requests 200

Every request orders one unit of a single option, so all requests contend on one row.
Stock of the bench option is reset through the order-db container before each run.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

PRODUCT_ID = 900001
WARMUP_PRODUCT_ID = 900002
OPTION_KEY = "bench"


def percentile(values: list[float], p: int) -> float:
    """Nearest-rank percentile.

    >>> percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95)
    10
    >>> percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50)
    5
    """
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))
    return ordered[rank - 1]


def sql(statement: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "order-db", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -v ON_ERROR_STOP=1'],
        input=statement, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def post(url: str, body: dict) -> None:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def reset_stock(base: str, product_id: int, stock: int) -> None:
    post(f"{base}/api/v1/internal/inventories/load", {
        "productId": product_id,
        "options": [{"optionKey": OPTION_KEY, "name": "부하 테스트 상품", "price": 10000, "quantity": 0}],
    })
    sql(f"UPDATE inventory SET quantity = {stock}, version = 0 "
        f"WHERE product_id = {product_id} AND option_key = '{OPTION_KEY}';")


def order(base: str, product_id: int) -> tuple[str, float]:
    body = {"ordererKey": "bench", "items": [{"productId": product_id, "optionKey": OPTION_KEY, "quantity": 1}]}
    request = urllib.request.Request(f"{base}/api/v1/orders", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
        outcome = "SUCCESS"
    except urllib.error.HTTPError as error:
        try:
            outcome = json.load(error).get("code", f"HTTP_{error.code}")
        except ValueError:
            outcome = f"HTTP_{error.code}"
    except OSError:
        outcome = "CONNECTION_ERROR"
    return outcome, (time.perf_counter() - start) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, help="label only; must match the running order-service")
    parser.add_argument("--stock", type=int, required=True)
    parser.add_argument("--requests", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=200)
    args = parser.parse_args()
    base = "http://{}:{}".format(os.getenv("ORDER_SERVICE_HOST", "127.0.0.1"),
                                 os.getenv("ORDER_SERVICE_PORT", "8082"))

    reset_stock(base, WARMUP_PRODUCT_ID, args.warmup)
    with ThreadPoolExecutor(args.concurrency) as pool:
        list(pool.map(lambda _: order(base, WARMUP_PRODUCT_ID), range(args.warmup)))

    reset_stock(base, PRODUCT_ID, args.stock)
    count_orders = f"SELECT COUNT(*) FROM order_items WHERE product_id = {PRODUCT_ID};"
    before = int(sql(count_orders))

    start = time.perf_counter()
    with ThreadPoolExecutor(args.concurrency) as pool:
        results = list(pool.map(lambda _: order(base, PRODUCT_ID), range(args.requests)))
    elapsed = time.perf_counter() - start

    orders = int(sql(count_orders)) - before
    final_stock = int(sql(f"SELECT quantity FROM inventory "
                          f"WHERE product_id = {PRODUCT_ID} AND option_key = '{OPTION_KEY}';"))
    outcomes = Counter(outcome for outcome, _ in results)
    latencies = [ms for _, ms in results]
    success = outcomes["SUCCESS"]
    failures = ", ".join(f"{code} {n}" for code, n in sorted(outcomes.items()) if code != "SUCCESS") or "0"
    oversold = max(0, orders - args.stock)
    stock_drift = final_stock - max(0, args.stock - orders)

    if success != orders:
        print(f"warning: {success} success responses but {orders} order rows", file=sys.stderr)
    print(f"| `{args.strategy}` | {args.stock} | {args.requests} | {args.concurrency} | "
          f"{len(results) / elapsed:.0f} | {percentile(latencies, 50):.0f} | {percentile(latencies, 95):.0f} | "
          f"{success} | {failures} | {oversold} | {stock_drift} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())