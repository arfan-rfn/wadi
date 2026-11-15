# Wadi developer entrypoints (architecture.md §9).
# Everything here must also be runnable as plain commands in CI.

.PHONY: sync lint fmt typecheck test test-unit test-integration schema up down help bump sync-compose joern-image e2e measure-repository-sites reconcile-repository-sites blind-sample blind-score

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

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

verify-frontend: ## Everything CI's frontend job checks, in CI's order
	# The single source of truth for "is the frontend green". `.github/workflows/ci.yml`
	# invokes THIS target, so the list cannot drift from what CI enforces.
	#
	# It exists because it drifted twice. Running typecheck + lint + tests +
	# build locally reads like a complete gate and is not: CI also enforces
	# Prettier and generated-type freshness, and both have broken master —
	# 0.7.0 shipped a "Prettier, which /ship never ran" fix, and the 0.7.4
	# release repeated it exactly. Remembering was never the missing piece;
	# one command was.
	cd frontend && npm run lint
	cd frontend && npm run format:check
	cd frontend && npx tsc --noEmit
	cd frontend && npm run build
	cd frontend && npm test

verify-types-fresh: ## Generated TS types match the contracts (§7)
	$(MAKE) schema
	git diff --exit-code frontend/lib/generated/

up: ## Start the local stack (docker compose, project name 'wadi')
	docker compose -p wadi -f infra/docker-compose.yml up -d

down: ## Stop the local stack
	docker compose -p wadi -f infra/docker-compose.yml down

sync-compose: ## Copy infra compose definitions into the CLI's embedded resources
	cp infra/docker-compose.yml cli/src/wadi_cli/resources/docker-compose.yml
	cp infra/docker-compose.expose-db.yml cli/src/wadi_cli/resources/docker-compose.expose-db.yml

bump: ## Set the release version everywhere the guard checks (make bump V=x.y.z)
	@test -n "$(V)" || { echo "usage: make bump V=x.y.z"; exit 1; }
	@printf '%s\n' "$(V)" > VERSION
	perl -pi -e 's/^version = ".*"/version = "$(V)"/' cli/pyproject.toml libs/*/pyproject.toml services/*/pyproject.toml
	perl -pi -e 's/^version := ".*"/version := "$(V)"/' joern-platform/build.sbt
	perl -pi -e 's/wadi-contracts==\S+"/wadi-contracts==$(V)"/' cli/pyproject.toml
	perl -pi -e 's|(ghcr\.io/wadi-sh/[a-z-]+):\S+|$$1:$(V)|g' infra/docker-compose.yml
	$(MAKE) sync-compose
	uv lock

joern-image: ## Build the wadi-joern image (pinned Joern + the wadi jar)
	docker build -t ghcr.io/wadi-sh/joern:$$(cat VERSION) joern-platform/

e2e: ## Whole-stack conformance e2e (needs Docker + the wadi-joern image)
	uv run pytest e2e -q

# The §5.2.17 repository call-site oracle: reads source only, never an export (C4).
measure-repository-sites: ## Repository call sites from Java source (SRC=<root> [OUT=sites.json])
	@test -n "$(SRC)" || { echo "usage: make measure-repository-sites SRC=<source-root> [OUT=sites.json]"; exit 1; }
	uv run python -m wadi_testing.measure.repository_oracle "$(SRC)" $(if $(OUT),--json "$(OUT)")

# EXPORTS: export JSON files, or a directory of them (WADI_BASELINE_EXPORT_DIR).
reconcile-repository-sites: ## Oracle vs wadi db sinks, site by site (ORACLE=sites.json EXPORTS=<dir|files> [OUT=])
	@test -n "$(ORACLE)" -a -n "$(EXPORTS)" || { echo "usage: make reconcile-repository-sites ORACLE=sites.json EXPORTS=<dir-or-files> [OUT=reconciled.json]"; exit 1; }
	uv run python -m wadi_testing.measure.reconcile_repository_sites --oracle "$(ORACLE)" --exports $(EXPORTS) $(if $(OUT),--json "$(OUT)")

# The §5.2.17 blind hand check (reviews D3-D5): a seeded draw from a running
# orchestrator. Give the reader OUT/blind.json only; key.json holds wadi's answers.
blind-sample: ## Seeded blind draw for a hand check (SNAPSHOT= SEED= N= CORPUS=<root> [API=] [OUT=dir])
	@test -n "$(SNAPSHOT)" -a -n "$(SEED)" -a -n "$(N)" -a -n "$(CORPUS)" || { echo "usage: make blind-sample SNAPSHOT=<snap_id> SEED=<int> N=<size> CORPUS=<source-root> [API=http://127.0.0.1:9234/api/v1] [OUT=dir]"; exit 1; }
	uv run python -m wadi_testing.measure.blind_sample draw --snapshot "$(SNAPSHOT)" --seed "$(SEED)" --size "$(N)" --corpus "$(CORPUS)" $(if $(API),--api "$(API)") $(if $(OUT),--out-dir "$(OUT)")

blind-score: ## Score a reader's labels against the draw's key (KEY=key.json LABELS=labels.json [OUT=score.json])
	@test -n "$(KEY)" -a -n "$(LABELS)" || { echo "usage: make blind-score KEY=key.json LABELS=labels.json [OUT=score.json]"; exit 1; }
	uv run python -m wadi_testing.measure.blind_sample score --key "$(KEY)" --labels "$(LABELS)" $(if $(OUT),--json "$(OUT)")
