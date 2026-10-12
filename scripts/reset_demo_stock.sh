#!/usr/bin/env bash
set -euo pipefail

docker compose exec -T order-db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "TRUNCATE order_items, orders, inventory RESTART IDENTITY;"'

uv run python scripts/seed_inventory.py "$@"