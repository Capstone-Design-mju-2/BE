SHELL := /bin/bash

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: bootstrap dependencies-update build check smoke infra-up infra-down infra-reset run-catalog run-order run-agent run-search-mcp run-inventory-mcp

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

smoke:
	./scripts/smoke.sh

infra-up:
	docker compose up -d --wait catalog-db order-db

infra-down:
	docker compose down

infra-reset:
	@test "$(CONFIRM)" = "1" || (echo "This deletes local database volumes. Re-run with CONFIRM=1." && exit 1)
	docker compose down --volumes

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
