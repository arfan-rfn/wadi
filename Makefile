# Wadi developer entrypoints (architecture.md §9).
# Everything here must also be runnable as plain commands in CI.

.PHONY: sync lint fmt typecheck test test-unit test-integration schema up down help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

sync: ## Install / sync the uv workspace (all members + dev group)
	uv sync --all-packages

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and fix lint
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Pyright strict over the whole workspace
	uv run pyright

test-unit: ## Unit tests only (no external infrastructure)
	uv run pytest -m "not integration"

test-integration: ## Integration tests (requires Docker)
	uv run pytest -m integration

test: ## Full test suite
	uv run pytest

schema: ## Export JSON Schemas from wadi-contracts and regenerate frontend TS types
	uv run --package wadi-contracts python libs/wadi-contracts/scripts/export_schema.py --out schemas/
	@if [ -d frontend/node_modules ]; then \
		cd frontend && npm run generate-types; \
	else \
		echo "frontend/node_modules missing — run 'npm install' in frontend/ to regenerate TS types"; \
	fi

up: ## Start the local stack (docker compose, project name 'wadi')
	docker compose -p wadi -f infra/docker-compose.yml up -d

down: ## Stop the local stack
	docker compose -p wadi -f infra/docker-compose.yml down

sync-compose: ## Copy infra compose definitions into the CLI's embedded resources
	cp infra/docker-compose.yml cli/src/wadi_cli/resources/docker-compose.yml
	cp infra/docker-compose.expose-db.yml cli/src/wadi_cli/resources/docker-compose.expose-db.yml

joern-image: ## Build the wadi-joern image (pinned Joern + the wadi jar)
	docker build -t ghcr.io/wadi-sh/joern:0.1.0 joern-platform/

e2e: ## Whole-stack conformance e2e (needs Docker + the wadi-joern image)
	uv run pytest e2e -q
