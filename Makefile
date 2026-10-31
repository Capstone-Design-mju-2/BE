SHELL := /bin/bash

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: bootstrap dependencies-update build check smoke infra-up infra-down infra-reset reset-inventory run-catalog run-order run-agent run-search-mcp run-inventory-mcp

bootstrap:
	./gradlew --version
	uv sync --locked --all-packages

dependencies-update:
	uv lock --upgrade
	uv sync --locked --all-packages

build:
	./gradlew clean build
	uv run python -m compileall services/agent-service/src services/search-mcp/src services/inventory-mcp/src

check:
	docker compose config --quiet
	./gradlew clean build
	uv lock --check
	uv run python -m compileall -q services/agent-service/src services/search-mcp/src services/inventory-mcp/src
	uv run --package agent-service python -m unittest discover -s services/agent-service/tests
	uv run --package agent-service python -m doctest services/agent-service/src/agent_service/agent.py
	SEARCH_BACKEND=catalog uv run --package search-mcp python -m doctest services/search-mcp/src/search_mcp/server.py
	uv run python -m doctest services/agent-service/src/agent_service/extract.py scripts/seed_inventory.py scripts/collect_musinsa.py scripts/collect_options.py scripts/load_catalog.py scripts/load_ingredients.py scripts/collect_essentials.py scripts/embed_reviews.py scripts/index_reviews.py scripts/bench_orders.py

smoke:
	./scripts/smoke.sh

infra-up:
	docker compose up -d --wait catalog-db order-db

infra-down:
	docker compose down

infra-reset:
	@test "$(CONFIRM)" = "1" || (echo "This deletes local database volumes. Re-run with CONFIRM=1." && exit 1)
	docker compose down --volumes

reset-inventory:
	@test "$(CONFIRM)" = "1" || (echo "This empties the order inventory table, including quantities changed by orders. Re-run with CONFIRM=1." && exit 1)
	docker compose exec -T order-db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "TRUNCATE inventory"'

run-catalog:
	./gradlew :services:catalog-service:bootRun

run-order:
	./gradlew :services:order-service:bootRun

run-agent:
	uv run --package agent-service agent-service

run-search-mcp:
	uv run --package search-mcp search-mcp

run-inventory-mcp:
	uv run --package inventory-mcp inventory-mcp
