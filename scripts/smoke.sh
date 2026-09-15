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

CATALOG_PID=""
ORDER_PID=""
AGENT_PID=""
LOG_DIR="$(mktemp -d)"

cleanup() {
    local exit_code=$?

    for pid in "$CATALOG_PID" "$ORDER_PID" "$AGENT_PID"; do
        if [[ -n "$pid" ]]; then
            kill "$pid" 2>/dev/null || true
        fi
    done

    for pid in "$CATALOG_PID" "$ORDER_PID" "$AGENT_PID"; do
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

uv sync --locked --all-packages
make check
docker compose up -d --wait catalog-db order-db

java -jar services/catalog-service/build/libs/catalog-service-0.1.0-SNAPSHOT.jar >"$LOG_DIR/catalog.log" 2>&1 &
CATALOG_PID=$!
java -jar services/order-service/build/libs/order-service-0.1.0-SNAPSHOT.jar >"$LOG_DIR/order.log" 2>&1 &
ORDER_PID=$!
uv run --package agent-service agent-service >"$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!

wait_for_http "http://${CATALOG_SERVICE_HOST:-127.0.0.1}:${CATALOG_SERVICE_PORT:-8081}/actuator/health" "catalog-service" "$CATALOG_PID"
wait_for_http "http://${ORDER_SERVICE_HOST:-127.0.0.1}:${ORDER_SERVICE_PORT:-8082}/actuator/health" "order-service" "$ORDER_PID"
wait_for_http "http://${AGENT_SERVICE_HOST:-127.0.0.1}:${AGENT_SERVICE_PORT:-8000}/health" "agent-service" "$AGENT_PID"

uv run python scripts/smoke_mcp.py

echo "Baseline smoke test passed"
