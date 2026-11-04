"""Applies catalog price changes to the OpenSearch review documents, from the outbox table or from Kafka.

Outbox mode (ADR-121): each poll takes up to BATCH pending events in one transaction, applies them in order and marks
them processed. An OpenSearch failure rolls the batch back, so the events already applied in it are applied again on a
later poll: delivery is at least once, and applying the same price twice leaves the same document.

Kafka mode (ADR-132, INDEXER_SOURCE=kafka): Debezium carries the same outbox rows to Kafka, keyed by product so one
product's changes arrive in order. The offset is committed only after the price is in the index, so a failure applies
the event again: at least once, as with the poller.
"""

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import httpx
import psycopg
from confluent_kafka import Consumer

SOURCE = os.getenv("INDEXER_SOURCE", "outbox")
POLL_SECONDS = float(os.getenv("INDEXER_POLL_SECONDS", "1"))
BATCH = 100
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:9092")
TOPIC = "outbox.event.product"
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


def apply(client: httpx.Client, payload: dict) -> None:
    response = client.post(f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_update_by_query", params={"refresh": "true"},
                           json=price_update(payload))
    response.raise_for_status()


def poll_once(conn: psycopg.Connection, client: httpx.Client) -> int:
    """Apply one batch of pending events and return how many were marked processed."""
    with conn.transaction():
        rows = conn.execute(PENDING, (BATCH,)).fetchall()
        for event_id, payload in rows:
            apply(client, payload)
            _record(event_id, payload)
            conn.execute(MARK, (event_id,))
    return len(rows)


def consume(client: httpx.Client) -> None:
    # A stop (SIGTERM) closes the consumer so it leaves its group at once; killed without closing, a restarted indexer
    # would wait out the dead member's session (45 s by default) before getting the partition back.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    consumer = Consumer({"bootstrap.servers": KAFKA_BOOTSTRAP, "group.id": "indexer", "enable.auto.commit": False,
                         "auto.offset.reset": "earliest"})
    consumer.subscribe([TOPIC])
    try:
        while True:
            message = consumer.poll(POLL_SECONDS)
            if message is None:
                continue
            if message.error():
                log.warning("kafka error: %s", message.error())
                continue
            payload = json.loads(message.value())
            # ponytail: retries in place without polling Kafka, so an outage longer than max.poll.interval.ms
            # (5 min) drops the consumer from its group; seek back and poll again if outages get that long.
            while True:
                try:
                    apply(client, payload)
                    break
                except httpx.HTTPError as error:
                    log.warning("event not applied, retrying: %r", error)
                    time.sleep(POLL_SECONDS)
            # Debezium's outbox router puts the outbox row id in the "id" header.
            _record(int(dict(message.headers())["id"]), payload)
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()


def _record(event_id: int, payload: dict) -> None:
    if APPLY_LOG:
        with Path(APPLY_LOG).open("a", encoding="utf-8") as file:
            file.write(json.dumps({"eventId": event_id, "productId": payload["productId"], "at": time.time()}) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Same limit as the dual write, so a paused OpenSearch costs every path the same wait per call.
    if SOURCE == "kafka":
        log.info("consuming %s from %s into %s/%s", TOPIC, KAFKA_BOOTSTRAP, OPENSEARCH_URL, OPENSEARCH_INDEX)
        with httpx.Client(timeout=2.0) as client:
            consume(client)
        return
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
