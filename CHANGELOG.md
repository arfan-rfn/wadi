# Changelog

All notable changes to wadi. One version spans the whole release set
(CLI, images, contracts — architecture.md §13).

## 0.1.0 — unreleased (Phase 1: backbone + vertical slice)

### Added
- `wadi-contracts`: the Pydantic data contracts (System, Snapshot, ServiceBoundary,
  Endpoint with structured auth, ICFG with explicit root + source anchors,
  RemoteCall, MqInteraction, DataModel, ExtractionJob), deterministic
  content-derived IDs, the versioned tag registry, JSON Schema export.
- `wadi-storage`: Mongo repositories, lease-based job queue with crash recovery,
  transparent >16MB ICFG chunking, Neo4j connection seam, shared JobRunner.
- `wadi-repo`: bare-mirror cache, SHA pinning, disposable checkouts, path deltas,
  pinned-SHA file reads (source-on-demand primitive).
- `wadi-config`: WADI_* settings (12-factor, §13).
- `joern-platform`: SpringDIPass (interface→impl call edges), spring packs
  (endpoints / http-client / spring-data sinks / models), statement-coarsened
  bulk export, spring-petstore-mini + lombok-mini conformance fixtures,
  wadi-joern image (pinned Joern 4.0.593, delombok types-only for anchor fidelity).
- `extraction-worker`: boundary discovery (Maven + compose identities), CPGQL
  control flow, interprocedural ICFG assembly, artifact materialization.
- `orchestrator`: /api/v1 (systems, analyze, snapshots, jobs, read API,
  source-on-demand), snapshot lifecycle monitor, optional bearer auth.
- `stitcher`: skeleton pipeline (Phase 2 fills matching + Neo4j).
- `mcp-server`: list_systems/list_snapshots/list_services/list_endpoints/
  endpoint_icfg with method-level roll-up (stdio + streamable HTTP).
- `wadi` CLI: up/down/status/analyze(--wait)/systems/snapshots/services/
  endpoints/mcp, embedded compose, stable exit codes 0/1/2/3.
- Frontend: Next.js explorer (systems → snapshots → services → endpoints → ICFG)
  over generated contract types.
- Infra: compose stack (loopback-only 9234/9235, no DB ports), CI
  (lint/type/test/staleness/license gates, Scala conformance, cross-language
  golden test, whole-stack e2e).
