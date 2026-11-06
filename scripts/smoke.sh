#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi
# The smoke test checks the default catalog search; smoke_mcp.py checks the OpenSearch path on its own index.
export SEARCH_BACKEND=catalog

CATALOG_PID=""
ORDER_PID=""
AGENT_PID=""
GATEWAY_PID=""
LOG_DIR="$(mktemp -d)"

cleanup() {
    local exit_code=$?

    for pid in "$CATALOG_PID" "$ORDER_PID" "$AGENT_PID" "$GATEWAY_PID"; do
        if [[ -n "$pid" ]]; then
            kill "$pid" 2>/dev/null || true
        fi
    done

    for pid in "$CATALOG_PID" "$ORDER_PID" "$AGENT_PID" "$GATEWAY_PID"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done

    docker compose down >/dev/null 2>&1 || true

    if [[ $exit_code -ne 0 ]]; then
        echo "Smoke test failed. Service logs:" >&2
        for log in "$LOG_DIR"/*.log; do
            if [[ -f "$log" ]]; then
                echo "=== $log ===" >&2
                cat "$log" >&2
            fi
        done
    fi

    rm -rf "$LOG_DIR"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

wait_for_http() {
    local url=$1
    local label=$2
    local pid=$3

    for _ in {1..60}; do
        if curl -fsS "$url" >/dev/null 2>&1; then
            echo "$label is ready"
            return 0
        fi

        if ! kill -0 "$pid" 2>/dev/null; then
            echo "$label exited before becoming ready" >&2
            return 1
        fi

        sleep 2
    done

    echo "$label did not become ready within 120 seconds" >&2
    return 1
}

refuse_if_running() {
    local url=$1
    local label=$2

    if curl -fsS "$url" >/dev/null 2>&1; then
        echo "$label already answers at $url. Stop it first: the smoke test would otherwise pass against an old build." >&2
        exit 1
    fi
}

refuse_if_running "http://${CATALOG_SERVICE_HOST:-127.0.0.1}:${CATALOG_SERVICE_PORT:-8081}/actuator/health" "catalog-service"
refuse_if_running "http://${ORDER_SERVICE_HOST:-127.0.0.1}:${ORDER_SERVICE_PORT:-8082}/actuator/health" "order-service"
refuse_if_running "http://${AGENT_SERVICE_HOST:-127.0.0.1}:${AGENT_SERVICE_PORT:-8000}/health" "agent-service"
GATEWAY_URL="http://${GATEWAY_SERVICE_HOST:-127.0.0.1}:${GATEWAY_SERVICE_PORT:-8080}"
refuse_if_running "$GATEWAY_URL/actuator/health" "gateway-service"

# --inexact keeps the optional embedding packages (search-mcp[embed]) a developer installed for semantic search.
uv sync --locked --all-packages --inexact
make check
docker compose up -d --wait catalog-db order-db opensearch

java -jar services/catalog-service/build/libs/catalog-service-0.1.0-SNAPSHOT.jar >"$LOG_DIR/catalog.log" 2>&1 &
CATALOG_PID=$!
java -jar services/order-service/build/libs/order-service-0.1.0-SNAPSHOT.jar >"$LOG_DIR/order.log" 2>&1 &
ORDER_PID=$!
uv run --package agent-service agent-service >"$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
java -jar services/gateway-service/build/libs/gateway-service-0.1.0-SNAPSHOT.jar >"$LOG_DIR/gateway.log" 2>&1 &
GATEWAY_PID=$!

wait_for_http "http://${CATALOG_SERVICE_HOST:-127.0.0.1}:${CATALOG_SERVICE_PORT:-8081}/actuator/health" "catalog-service" "$CATALOG_PID"
wait_for_http "http://${ORDER_SERVICE_HOST:-127.0.0.1}:${ORDER_SERVICE_PORT:-8082}/actuator/health" "order-service" "$ORDER_PID"
wait_for_http "http://${AGENT_SERVICE_HOST:-127.0.0.1}:${AGENT_SERVICE_PORT:-8000}/health" "agent-service" "$AGENT_PID"
wait_for_http "$GATEWAY_URL/actuator/health" "gateway-service" "$GATEWAY_PID"

uv run python scripts/smoke_mcp.py

# Through the gateway (ADR-133): each route reaches its service, and /internal/* is not routed.
# Catalog is checked with search: the list answers 400 for a category with no products, and the smoke DB has none.
curl -fsS -H 'Content-Type: application/json' -d '{"message": "토너 추천해 줘"}' "$GATEWAY_URL/api/v1/chat" >/dev/null
curl -fsS "$GATEWAY_URL/api/v1/products/search?q=toner&limit=1" >/dev/null
curl -fsS -H 'Content-Type: application/json' -d '{"productIds": [1]}' \
    "$GATEWAY_URL/api/v1/inventories/check" >/dev/null
test "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$GATEWAY_URL/internal/products/load")" = 404
echo "Gateway routes passed"

echo "Baseline smoke test passed"
