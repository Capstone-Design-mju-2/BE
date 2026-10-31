"""Index sync experiment (ADR-121): price changes through the catalog API, then loss, repeated applications and the
delay from the change request to search.

catalog-service must run in the mode under test, for example CATALOG_INDEX_SYNC=outbox make run-catalog. In outbox
mode this script starts the indexer itself, so it can also stop it for a while.

    uv run --package indexer python scripts/bench_index_sync.py dual-write --pause-opensearch 5 10
    uv run --package indexer python scripts/bench_index_sync.py outbox --stop-indexer 5 10

Every changed price is put back through the same API at the end; a product the index still disagrees on afterwards
is rewritten from the DB, and the result says how many.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
CATALOG_URL = "http://{}:{}".format(os.getenv("CATALOG_SERVICE_HOST", "127.0.0.1"),
                                    os.getenv("CATALOG_SERVICE_PORT", "8081"))
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200")
INDEX = os.getenv("OPENSEARCH_INDEX", "reviews")
CATALOG_DB = "host=127.0.0.1 port={} dbname={} user={} password={}".format(
    os.getenv("CATALOG_DB_PORT", "5433"), os.getenv("CATALOG_DB_NAME", "catalog"),
    os.getenv("CATALOG_DB_USER", "catalog"), os.getenv("CATALOG_DB_PASSWORD", "catalog-local"))
SWEEP_SECONDS = 0.2
PRICE_STEP = 10


def sample(conn: psycopg.Connection, count: int, seed: str) -> list[tuple[int, int]]:
    """Products with reviews in a fixed pseudo-random order, so a rerun changes the same products."""
    return conn.execute("""
        SELECT id, price FROM products WHERE review_count > 0 ORDER BY md5(id::text || %s) LIMIT %s
        """, (seed, count)).fetchall()


def doc_counts(client: httpx.Client, ids: list[int], prices: dict[int, int] | None = None) -> dict[int, int]:
    """Review documents per product; with prices, only those already carrying that product's price."""
    if prices is None:
        query = {"terms": {"product_id": ids}}
    else:
        query = {"bool": {"should": [{"bool": {"filter": [{"term": {"product_id": i}}, {"term": {"price": prices[i]}}]}}
                                     for i in ids], "minimum_should_match": 1}}
    body = {"size": 0, "query": query, "aggs": {"p": {"terms": {"field": "product_id", "size": len(ids)}}}}
    response = client.post(f"{OPENSEARCH_URL}/{INDEX}/_search", json=body)
    response.raise_for_status()
    return {b["key"]: b["doc_count"] for b in response.json()["aggregations"]["p"]["buckets"]}


def change_prices(changes: list[tuple[int, int]], interval: float) -> list[dict]:
    """Send the changes one by one, interval apart, and note when each one was committed."""
    sent = []
    with httpx.Client(timeout=30.0) as client:
        start = time.monotonic()
        for n, (product_id, price) in enumerate(changes):
            time.sleep(max(0.0, start + n * interval - time.monotonic()))
            asked = time.monotonic()
            response = client.put(f"{CATALOG_URL}/internal/products/{product_id}/price", json={"price": price})
            sent.append({"productId": product_id, "price": price, "status": response.status_code,
                         "asked": asked, "committed": time.monotonic()})
    return sent


def watch(targets: dict[int, int], totals: dict[int, int], deadline: float, seen: dict[int, float],
          stop: threading.Event) -> None:
    """Note when search first shows all of a product's documents with its target price."""
    with httpx.Client(timeout=2.0) as client:
        while not stop.is_set() and time.monotonic() < deadline:
            pending = [i for i in targets if i not in seen]
            if not pending:
                return
            try:
                counts = doc_counts(client, pending, targets)
            except httpx.HTTPError:
                counts = {}
            now = time.monotonic()
            for i in pending:
                if counts.get(i) == totals[i]:
                    seen[i] = now
            time.sleep(SWEEP_SECONDS)


def at(delay: float, action) -> threading.Thread:
    thread = threading.Thread(target=lambda: (time.sleep(delay), action()), daemon=True)
    thread.start()
    return thread


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


def block_writes(on: bool) -> None:
    """The write block OpenSearch also sets by itself when a disk fills up: every write fails until it is lifted."""
    with httpx.Client(timeout=10.0) as client:
        client.put(f"{OPENSEARCH_URL}/{INDEX}/_settings", json={"index.blocks.write": on}).raise_for_status()


def one_document_per_product(client: httpx.Client, ids: list[int]) -> dict[int, str]:
    body = {"size": len(ids), "query": {"terms": {"product_id": ids}}, "collapse": {"field": "product_id"},
            "_source": ["product_id"]}
    response = client.post(f"{OPENSEARCH_URL}/{INDEX}/_search", json=body)
    response.raise_for_status()
    return {hit["_source"]["product_id"]: hit["_id"] for hit in response.json()["hits"]["hits"]}


def versions(client: httpx.Client, docs: dict[int, str]) -> dict[int, int]:
    """Every rewrite raises a document's _version, so its growth counts the applications the server really made,
    including ones whose response the writer never got."""
    response = client.post(f"{OPENSEARCH_URL}/{INDEX}/_mget", params={"_source": "false"},
                           json={"ids": list(docs.values())})
    response.raise_for_status()
    by_id = {doc["_id"]: doc["_version"] for doc in response.json()["docs"]}
    return {product: by_id[doc] for product, doc in docs.items()}


def applications(before: dict[int, int], after: dict[int, int]) -> dict:
    counts: dict[int, list[int]] = {}
    for product, version in after.items():
        counts.setdefault(version - before[product], []).append(product)
    return {"products": {str(n): len(p) for n, p in sorted(counts.items())},
            "notApplied": sorted(counts.get(0, [])),
            "appliedMoreThanOnce": sorted(p for n, ps in counts.items() if n > 1 for p in ps)}


class Indexer:
    """The outbox poller as a child process the experiment can stop and start again."""

    def __init__(self, apply_log: Path) -> None:
        self.env = {**os.environ, "INDEXER_APPLY_LOG": str(apply_log)}
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        # The interpreter itself rather than `uv run`, so stopping it really stops the poller.
        self.process = subprocess.Popen([sys.executable, "-m", "indexer.main"], cwd=ROOT, env=self.env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=30)
            self.process = None


def run_once(conn, mode, changes, totals, args, indexer, label) -> dict:
    targets = dict(changes)
    seen: dict[int, float] = {}
    stop = threading.Event()
    window = args.products * args.interval + args.settle
    watcher = threading.Thread(target=watch, args=(targets, totals, time.monotonic() + window, seen, stop), daemon=True)
    first_event = conn.execute("SELECT coalesce(max(id), 0) FROM outbox").fetchone()[0]
    faults = []
    if args.pause_opensearch:
        when, length = args.pause_opensearch
        faults.append(at(when, lambda: compose("pause", "opensearch")))
        faults.append(at(when + length, lambda: compose("unpause", "opensearch")))
    if args.stop_indexer and indexer is not None:
        when, length = args.stop_indexer
        faults.append(at(when, indexer.stop))
        faults.append(at(when + length, indexer.start))
    if args.block_writes:
        when, length = args.block_writes
        faults.append(at(when, lambda: block_writes(True)))
        faults.append(at(when + length, lambda: block_writes(False)))
    watcher.start()
    sent = change_prices(changes, args.interval)
    for fault in faults:
        fault.join()
    watcher.join()
    stop.set()
    with httpx.Client(timeout=10.0) as client:
        landed = doc_counts(client, list(targets), targets)
    db = dict(conn.execute("SELECT id, price FROM products WHERE id = ANY(%s)", (list(targets),)).fetchall())
    # Measured from the request, not the response: the dual write answers only after the index has the price.
    delays = [seen[s["productId"]] - s["asked"] for s in sent
              if s["productId"] in seen and seen[s["productId"]] >= s["asked"]]
    api = [s["committed"] - s["asked"] for s in sent]
    events = conn.execute("SELECT count(*), count(processed_at) FROM outbox WHERE id > %s", (first_event,)).fetchone()
    return {
        "run": label, "mode": mode, "changes": len(sent),
        "httpStatus": {str(code): sum(1 for s in sent if s["status"] == code) for code in {s["status"] for s in sent}},
        "lost": sorted(i for i in targets if db[i] == targets[i] and landed.get(i) != totals[i]),
        "notVisibleInWindow": sorted(i for i in targets if i not in seen),
        "delaySeconds": summary(delays), "apiSeconds": summary(api),
        "outboxEvents": events[0], "outboxProcessed": events[1], "firstEventId": first_event + 1,
    }


def summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {"count": len(values), "p50": round(statistics.median(ordered), 3),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3), "max": round(ordered[-1], 3)}


def repeated(apply_log: Path, first_event: int) -> dict:
    """Events of this run the indexer applied more than once, read from its apply log."""
    if not apply_log.exists():
        return {}
    counts: dict[int, int] = {}
    for line in apply_log.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)["eventId"]
        if event >= first_event:
            counts[event] = counts.get(event, 0) + 1
    return {str(e): n for e, n in counts.items() if n > 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["dual-write", "outbox"])
    parser.add_argument("--products", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.2, help="seconds between price changes")
    parser.add_argument("--settle", type=float, default=30.0, help="seconds to keep watching after the last change")
    parser.add_argument("--pause-opensearch", type=float, nargs=2, metavar=("AT", "FOR"))
    parser.add_argument("--stop-indexer", type=float, nargs=2, metavar=("AT", "FOR"))
    parser.add_argument("--block-writes", type=float, nargs=2, metavar=("AT", "FOR"))
    parser.add_argument("--seed", default="1031")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    apply_log = args.out.with_suffix(".apply.jsonl")
    indexer = Indexer(apply_log) if args.mode == "outbox" else None
    with psycopg.connect(CATALOG_DB, autocommit=True) as conn:
        original = dict(sample(conn, args.products, args.seed))
        with httpx.Client(timeout=10.0) as client:
            totals = doc_counts(client, list(original))
            original = {i: p for i, p in original.items() if totals.get(i)}
            docs = one_document_per_product(client, list(original))
            before = versions(client, docs)
        if indexer is not None:
            indexer.start()
            # Changes sent while it is still starting would count its start-up as sync delay.
            time.sleep(5)
        try:
            changed = run_once(conn, args.mode, [(i, p + PRICE_STEP) for i, p in original.items()], totals, args,
                               indexer, "change")
            changed["repeatedApplications"] = repeated(apply_log, changed["firstEventId"])
            with httpx.Client(timeout=10.0) as client:
                middle = versions(client, docs)
            changed["serverApplications"] = applications(before, middle)
            restore_args = argparse.Namespace(**{**vars(args), "pause_opensearch": None, "stop_indexer": None,
                                                 "block_writes": None})
            restored = run_once(conn, args.mode, list(original.items()), totals, restore_args, indexer, "restore")
            with httpx.Client(timeout=10.0) as client:
                restored["serverApplications"] = applications(middle, versions(client, docs))
        finally:
            if indexer is not None:
                indexer.stop()
            if args.block_writes:
                block_writes(False)
            if args.pause_opensearch:
                # Not checked: it fails on a running container, which is the case unless the run broke mid-pause.
                subprocess.run(["docker", "compose", "unpause", "opensearch"], cwd=ROOT, capture_output=True)
        db = dict(conn.execute("SELECT id, price FROM products WHERE id = ANY(%s)", (list(original),)).fetchall())
        with httpx.Client(timeout=30.0) as client:
            landed = doc_counts(client, list(original), db)
            repaired = [i for i in original if landed.get(i) != totals[i]]
            for i in repaired:
                client.post(f"{OPENSEARCH_URL}/{INDEX}/_update_by_query", params={"refresh": "true"},
                            json={"query": {"term": {"product_id": i}},
                                  "script": {"source": "ctx._source.price = params.price", "params": {"price": db[i]}}}
                            ).raise_for_status()
    result = {"mode": args.mode, "products": len(original), "reviewDocuments": sum(totals[i] for i in original),
              "interval": args.interval, "pauseOpenSearch": args.pause_opensearch, "stopIndexer": args.stop_indexer,
              "blockWrites": args.block_writes,
              "dbPricesRestored": all(db[i] == p for i, p in original.items()), "indexRepairedAfterRestore": repaired,
              "change": changed, "restore": restored}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("change", "restore")}, ensure_ascii=False))
    for part in ("change", "restore"):
        print(part, json.dumps({k: v for k, v in result[part].items() if k != "run"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
