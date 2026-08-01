# wadi

**Ground-truth architecture for microservice systems, extracted from code.**

Wadi statically analyzes an entire microservice system — one repo or many — and
materializes a queryable model of its architecture: every REST endpoint of every
service, each endpoint's full interprocedural control-flow graph down to the
database and outbound HTTP calls, served to humans (web UI), programs (REST API),
and coding agents (MCP server). Built on [Joern](https://joern.io) code property
graphs; deterministic and fully offline — no API keys, no LLM in the core pipeline.

```text
your repos ──▶ service discovery ──▶ per-endpoint flow graphs ──▶ REST API · MCP · UI
```

## Quickstart

**Requirements:** a container runtime (Docker Desktop, OrbStack, Podman, or Docker
Engine) and [uv](https://docs.astral.sh/uv/) (or pipx). Everything else — JVM,
Joern, MongoDB, Neo4j — ships inside version-pinned images.

```sh
# 1. Install the CLI
uv tool install wadi-sh        # or: pipx install wadi-sh

# 2. Start the stack (first run pulls ~3 GB of images, then it's cached)
wadi up

# 3. Analyze a system — a local checkout or git URLs
wadi analyze .                                   # the repo you're standing in
wadi analyze --repo https://github.com/cloudhubs/train-ticket-aitest.git --wait

# 4. Explore
wadi systems                   # registered systems
wadi snapshots <system-id>     # analysis runs (immutable, SHA-pinned)
wadi services <snapshot-id>    # discovered services + endpoint counts
wadi endpoints <snapshot-id> <service-id>
```

Every read command takes `--json` for scripting. Exit codes are stable:
`0` success · `1` analysis failed · `2` usage · `3` stack unreachable.

### For coding agents (MCP)

The MCP server answers architecture-level questions — endpoint inventories with
auth state, per-endpoint flow graphs at method granularity — so agents query
ground truth instead of grepping source:

```sh
wadi mcp install    # prints the config snippet for Claude Code etc.
# or directly:  claude mcp add wadi -- wadi mcp
```

Tools: `list_systems` · `list_snapshots` · `list_services` · `list_endpoints` ·
`endpoint_icfg` (method-level roll-up by default; statement-level drill-down on
request).

### Web UI

The explorer (services → endpoints → flow graphs) ships in the stack and serves
at `http://127.0.0.1:9235`. In v0.1.0 it starts via the compose profile from a
source checkout (`docker compose -p wadi -f infra/docker-compose.yml --profile
frontend up -d`); a `wadi ui` command is planned.

## What you get, concretely

- **Endpoint inventory** — method, route, params, response type, and a
  *tri-state* auth field (`required` / `open` / honestly `unknown`) per endpoint.
- **Per-endpoint ICFG** — an interprocedural control-flow graph from the handler
  through DI-resolved implementations down to `sink=db` / `sink=http-client`
  call sites, every node anchored to `file:line` in the exact analyzed commit.
- **Deterministic identity** — service and endpoint IDs are content-derived, so
  they're stable across runs and diffable across snapshots.
- **Honest unknowns** — what static analysis can't determine is marked as
  undetermined, never guessed or silently dropped.

Measured on the [TrainTicket](https://github.com/cloudhubs/train-ticket-aitest)
benchmark (22 services): **365/365 endpoints, exact against manually verified
ground truth**, ~3 minutes wall-clock on a laptop.

**Current scope (Phase 1):** Java/Spring, single-service flow graphs.
**Next (Phase 2):** cross-service stitching (remote call ↔ endpoint matching),
Spring Security auth extraction, the coverage report. Roadmap:
[`docs/architecture.md`](docs/architecture.md) §11.

## How it works

A pinned, stock Joern builds a code property graph per service; wadi's Scala
passes resolve Spring dependency injection and tag endpoints/sinks; a Python
pipeline assembles per-endpoint flow graphs and writes versioned JSON artifacts
to MongoDB — the single source of truth every surface (REST, MCP, UI) reads.
The full decision record lives in [`docs/architecture.md`](docs/architecture.md);
implementation notes and known gaps in
[`docs/phase1-implementation-notes.md`](docs/phase1-implementation-notes.md).

## Development

```sh
make sync        # install the uv workspace
make test-unit   # fast tests, no infrastructure
make test        # full suite (Docker required — spins up real MongoDB)
make lint typecheck
make schema      # regenerate JSON Schemas + frontend types after contract changes

cd joern-platform && sbt test    # Scala conformance suite (builds real CPGs)
make joern-image && make e2e     # whole-stack conformance e2e
```

Layout: `joern-platform/` (Scala — CPG passes, framework packs, conformance
fixtures) · `libs/` (contracts, storage, git intake, config, Joern client) ·
`services/` (orchestrator, extraction worker, stitcher, MCP server) · `cli/` ·
`frontend/` · `infra/` (compose). Services never import each other — all
coupling goes through versioned contracts in `libs/wadi-contracts`.

## License

[Apache-2.0](LICENSE)
