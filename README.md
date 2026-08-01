# Wadi

Wadi statically analyzes an entire microservice system — polyglot, one repo or many — and
materializes a queryable, ground-truth model of its architecture: every endpoint, its full
interprocedural control-flow graph down to the data layer, every cross-service call, stitched
into one system graph and served to humans (web UI), programs (REST API), and coding agents
(MCP server).

Built on [Joern](https://joern.io) for per-service code property graphs; everything *between*
services — boundary discovery, config resolution, stitching, storage, consumption surfaces —
is wadi.

**Status: Phase 1 (backbone + vertical slice) under active development.**
The normative design lives in [`docs/architecture.md`](docs/architecture.md); the visual
companion in [`docs/architecture-views.md`](docs/architecture-views.md).

## Development

Requirements: [uv](https://docs.astral.sh/uv/), a compose-compatible container runtime
(Docker Desktop / Podman / OrbStack), Node 20+ (frontend only).

```sh
make sync        # install the uv workspace
make test-unit   # fast tests, no infrastructure
make test        # full suite (needs Docker for Mongo integration tests)
make lint typecheck
make schema      # regenerate JSON Schemas + frontend types after contract changes
```

Repository layout (see architecture.md §9):

- `joern-platform/` — all Scala/JVM code: CpgPasses, framework query packs, conformance fixtures
- `libs/` — shared Python packages (`wadi-contracts`, `wadi-storage`, `wadi-config`, `wadi-repo`, `wadi-joern-client`)
- `services/` — orchestrator, extraction-worker, stitcher, mcp-server
- `cli/` — the `wadi` command
- `frontend/` — Next.js UI (generated contract types)
- `infra/` — docker-compose definition
