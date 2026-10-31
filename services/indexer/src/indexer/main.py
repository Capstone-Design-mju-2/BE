"""Outbox poller: applies catalog price changes to the OpenSearch review documents (ADR-121).

Each poll takes up to BATCH pending events in one transaction, applies them in order and marks them processed. An
OpenSearch failure rolls the batch back, so the events already applied in it are applied again on a later poll:
delivery is at least once, and applying the same price twice leaves the same document.
"""

import json
import logging
import os
import time
from pathlib import Path

import httpx
import psycopg

POLL_SECONDS = float(os.getenv("INDEXER_POLL_SECONDS", "1"))
BATCH = 100
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "reviews")
# Every application as one JSON line, so the sync measurement can count events applied more than once.
APPLY_LOG = os.getenv("INDEXER_APPLY_LOG")
CATALOG_DB = "host=127.0.0.1 port={} dbname={} user={} password={}".format(
    os.getenv("CATALOG_DB_PORT", "5433"), os.getenv("CATALOG_DB_NAME", "catalog"),
    os.getenv("CATALOG_DB_USER", "catalog"), os.getenv("CATALOG_DB_PASSWORD", "catalog-local"))

PENDING = "SELECT id, payload FROM outbox WHERE processed_at IS NULL ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED"
MARK = "UPDATE outbox SET processed_at = now() WHERE id = %s"

log = logging.getLogger("indexer")


def price_update(payload: dict) -> dict:
    """The _update_by_query body for one PriceChanged event, the same rewrite the dual write sends.

    >>> price_update({"productId": 7, "price": 30000})
    {'query': {'term': {'product_id': 7}}, 'script': {'source': 'ctx._source.price = params.price', 'params': {'price': 30000}}}
    """
    return {"query": {"term": {"product_id": payload["productId"]}},
            "script": {"source": "ctx._source.price = params.price", "params": {"price": payload["price"]}}}


def poll_once(conn: psycopg.Connection, client: httpx.Client) -> int:
    """Apply one batch of pending events and return how many were marked processed."""
    with conn.transaction():
        rows = conn.execute(PENDING, (BATCH,)).fetchall()
        for event_id, payload in rows:
            response = client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_update_by_query",
                                   params={"refresh": "true"}, json=price_update(payload))
            response.raise_for_status()
            _record(event_id, payload)
            conn.execute(MARK, (event_id,))
    return len(rows)


def _record(event_id: int, payload: dict) -> None:
    if APPLY_LOG:
        with Path(APPLY_LOG).open("a", encoding="utf-8") as file:
            file.write(json.dumps({"eventId": event_id, "productId": payload["productId"], "at": time.time()}) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Same limit as the dual write, so a paused OpenSearch costs both paths the same wait per call.
    with psycopg.connect(CATALOG_DB, autocommit=True) as conn, httpx.Client(timeout=2.0) as client:
        log.info("polling the outbox every %.1f s into %s/%s", POLL_SECONDS, OPENSEARCH_URL, OPENSEARCH_INDEX)
        while True:
            try:
                if poll_once(conn, client):
                    continue
            except (httpx.HTTPError, psycopg.Error) as error:
                log.warning("batch rolled back, retrying on the next poll: %r", error)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
