"""Register the Debezium connector that carries catalog's outbox rows into Kafka, or update it (ADR-132).

    docker compose up -d kafka connect
    uv run python scripts/register_outbox_connector.py

Each new outbox row becomes one message on outbox.event.product, keyed by the product id, so the changes of one product
stay in order on one partition. The value is the row's payload, the event id is in the header "id".
"""

import json
import os
import time
import urllib.error
import urllib.request

CONNECT_URL = os.getenv("CONNECT_URL", "http://127.0.0.1:8083")
NAME = "catalog-outbox"
CONFIG = {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "plugin.name": "pgoutput",
    "database.hostname": "catalog-db",
    "database.port": "5432",
    "database.user": os.getenv("CATALOG_DB_USER", "catalog"),
    # Resolved inside Kafka Connect from its environment (compose.yaml), so the password is in no request or config.
    "database.password": "${env:CATALOG_DB_PASSWORD}",
    "database.dbname": os.getenv("CATALOG_DB_NAME", "catalog"),
    "topic.prefix": "catalog",
    "table.include.list": "public.outbox",
    "publication.autocreate.mode": "filtered",
    "slot.name": "catalog_outbox",
    # Rows written before the connector existed were applied by the outbox poller (ADR-121).
    "snapshot.mode": "no_data",
    "transforms": "outbox",
    "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
    "transforms.outbox.table.field.event.id": "id",
    "transforms.outbox.table.field.event.key": "aggregate_id",
    "transforms.outbox.table.field.event.payload": "payload",
    "transforms.outbox.route.by.field": "aggregate_type",
    "transforms.outbox.route.topic.replacement": "outbox.event.${routedByValue}",
    "transforms.outbox.table.expand.json.payload": "true",
    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
}


def request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CONNECT_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read() or b"{}")


def main() -> None:
    # Kafka Connect takes a while to start; its REST API answers once the worker has joined.
    for _ in range(60):
        try:
            request("GET", "/connectors")
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    else:
        raise SystemExit(f"Kafka Connect did not answer at {CONNECT_URL}")
    request("PUT", f"/connectors/{NAME}/config", CONFIG)
    states = []
    for _ in range(30):
        try:
            status = request("GET", f"/connectors/{NAME}/status")
        except urllib.error.HTTPError as error:
            # Right after the PUT the status is not there yet.
            if error.code != 404:
                raise
            time.sleep(2)
            continue
        states = [status["connector"]["state"]] + [task["state"] for task in status.get("tasks", [])]
        if states[1:] and all(state == "RUNNING" for state in states):
            print(f"{NAME}: RUNNING")
            return
        if "FAILED" in states:
            raise SystemExit(json.dumps(status, indent=1))
        time.sleep(2)
    raise SystemExit(f"{NAME} did not start: {states}")


if __name__ == "__main__":
    main()
