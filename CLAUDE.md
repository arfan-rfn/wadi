# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

**Phase 1 (backbone + vertical slice) is implemented.** Wadi is a polyglot microservice static-analysis platform built on Joern: it analyzes an entire microservice system (one repo or many), extracts per-endpoint interprocedural control-flow graphs, detects cross-service communication, stitches flows across services, and exposes the result via a REST API, MCP server, and web frontend. Implementation decisions made during Phase 1 (and known gaps) are recorded in `docs/phase1-implementation-notes.md` — read it alongside the architecture doc.

## Commands

- `make sync` — install the uv workspace. `make test` — full Python suite (Mongo integration tests spin up a Docker container; they skip without Docker). `make test-unit` — no infrastructure.
- `make lint` / `make fmt` / `make typecheck` — ruff + pyright strict, workspace-wide, zero-tolerance in CI.
- `make schema` — regenerate `schemas/` + frontend TS types after ANY `wadi-contracts` change; CI fails on staleness. Same for `make sync-compose` after editing `infra/docker-compose.yml` (the CLI embeds a copy).
- `cd joern-platform && sbt test` — Scala conformance tests (build real CPGs from `fixtures/`); also writes `target/petstore-export/export.json`, which the Python cross-language golden test consumes (`pytest services/extraction-worker/tests/test_real_export.py`).
- `make joern-image` then `make e2e` — the whole-stack conformance e2e (real Joern container).
- Run a single Python test: `uv run pytest path/to/test_file.py::TestClass::test_name`.

## The Documents

| Doc | Role |
|---|---|
| `docs/architecture.md` | **The normative decision record.** ADR-style: every structural decision with rationale and rejected alternatives. Principles P1–P10 (§2), stack (§3), layer design (§5), storage tiers (§6), data contracts (§7), repo layout (§9), extensibility playbook (§10), 10-phase roadmap (§11), CLI design (§15). Read this first for any design or implementation work. |
| `docs/architecture-views.md` | Visual companion: system context, full service-connectivity map (protocols + directions), lifecycle state machines, stitched-graph schema, deployment topologies, use-case traces UC1–UC8. |
| `docs/joern-migration-architecture.md` | Historical reference: the study that selected Joern and defined the analysis approach. Wadi adopts its analysis design but is clean-slate — no legacy contracts or consumers. |

## Rules That Govern All Future Work

These come from `architecture.md` and are binding, not aspirational:

- **Decisions are recorded before they're implemented.** Any structural change updates `architecture.md` first, in its format: decision + rationale + rejected alternatives. Docs move with code in the same PR.
- **P1 — Coupling only through contracts.** Services never import each other; all inter-service communication is versioned JSON artifacts in MongoDB + the job collection. Shared code lives in `libs/*` only.
- **P4 — Single writer per data domain.** Each Mongo collection / data domain has exactly one writing service. To cause a write in another domain, call that domain's owner (usually the orchestrator's REST API).
- **P5 — Joern is stock and pinned, never forked.** All customization via CpgPass / CPGQL query packs / tags compiled into a jar in the `wadi-joern` image. CPGs are evictable cache, never a store.
- **P6 — Extension decision rule.** Needs to see inside one service's code graph → Scala (pass or query pack in `joern-platform`). Spans services, configs, or extracted artifacts → Python (service or library).
- **P7 — Symbolic truth, LLM judgment.** The core pipeline is deterministic and runs with no API keys. LLM output is always provenance-marked (`llm-guessed`), never blended into ground truth.
- **P8 — Every framework pack ships a conformance fixture** (tiny sample repo + expected JSON, diffed in CI).
- **P10 — Honest unknowns.** What analysis cannot determine is materialized explicitly (placeholder nodes, "target undetermined" facts), never omitted or falsely resolved.
- **Identity stability:** service/endpoint IDs are deterministic and content-derived (hash of service + method + normalized URI), never random per run.
- **Contracts are the spine:** Pydantic v2 models in `libs/wadi-contracts` are the single source of truth; frontend TS types are generated from their JSON Schema, never hand-written. Every artifact carries `schema_version`, snapshot key, and tz-aware UTC timestamps. The tag vocabulary (`endpoint=…`, `sink=…`, `model=…`) is a versioned registry in `wadi-contracts`, not a pack convention.

## Planned Structure & Toolchain

Monorepo (see `architecture.md` §9 for the full tree): `joern-platform/` (Scala/sbt — the only JVM code), `libs/` (shared Python packages: wadi-contracts, wadi-storage, wadi-config, wadi-repo, wadi-joern-client), `services/` (orchestrator, extraction-worker, stitcher, mcp-server — FastAPI/worker apps), `cli/` (Typer + httpx; compose-wrapper + REST client only, no DB access), `frontend/` (Next.js App Router + generated types), `infra/` (docker-compose).

- **Python 3.12+, uv workspace, FastAPI, Pydantic v2; pyright strict + ruff + pytest** (CI-enforced).
- **Scala:** scalafmt + warnings-as-errors; packs stay declarative (a pack needing hundreds of lines is a design smell).
- **Storage:** MongoDB (Tier 1, source of truth) → Neo4j (Tier 2, derived/rebuildable); CPG files are Tier 0 cache. Only `wadi-storage` imports DB drivers; only `wadi-config` reads env vars (`WADI_*` prefix).
- Planned Makefile targets: `make up / test / schema / slice`. `make schema` regenerates frontend types; CI fails if they're stale.
- Default ports: orchestrator API 9234, frontend 9235 (the "WADI keypad block"); DB ports never published to the host.

## Phase 1 Scope (first build)

The vertical slice proving the architecture: `spring-petstore-mini` fixture → wadi-joern image (pinned Joern + spring packs + SpringDIPass) → extraction worker pipeline → orchestrator REST API under `/api/v1` → MCP listing tools + `endpoint_icfg` → one frontend page → stitcher skeleton → conformance e2e in CI → thin `wadi` CLI. Week-one validations: the bulk-export transport (§5.1) and the `lombok-mini` fixture (delombok anchor correctness). See `architecture.md` §11 for the full phase list.
