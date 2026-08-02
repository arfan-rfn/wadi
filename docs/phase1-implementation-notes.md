# Phase 1 Implementation Notes

**Status:** Living record of decisions made while building Phase 1 (§11.1),
in the same decision + rationale + rejected-alternatives format as
[`architecture.md`](./architecture.md). Everything here refines that document;
nothing contradicts it without saying so.

## Decisions made during implementation

**ICFG root is explicit (`entry_node_id`), not inferred.** The original model
implied the root entry is "the entry node with no incoming edges" — recursion
back into the handler falsifies that (the root gains an incoming CALL edge).
The `Icfg` contract now carries `entry_node_id`; validation requires it to
reference an entry node. *Rejected: topological inference — unsound; found by
the mutual-recursion unit test.*

**ICFG assembly is hand-rolled in Phase 1; NetworkX is retained for later
phases.** architecture.md (§3, §4, §11.1) names NetworkX as the assembly
mechanism, but the Phase 1 assembler builds the graph with plain
dicts/dataclasses (`services/extraction-worker/.../assembler.py`): the walk is
a single pass over the export with no graph algorithms on the critical path,
and going through a digraph API added indirection without earning it. The
`networkx` dependency stays declared in the worker on purpose — stitching,
pattern matching, and reachability queries (Phase 2+) are where the algorithm
library pays off, and that work should build on it rather than re-adding it.

**One extract job per snapshot in Phase 1.** The orchestrator enqueues a single
EXTRACT job covering fetch → boundary scan → per-service extraction, matching
the §4 sequence diagram (the per-service loop runs inside the worker's claimed
job). Per-service job fan-out arrives with incremental rebuilds (Phase 3);
`ExtractionJob.service_id` already supports it. P4 intact: only the
orchestrator creates jobs — including the stitch job, via its snapshot monitor.

**Delombok runs in `types-only` mode, not `run-delombok`.** javasrc2cpg bundles
delombok; in its default mode it analyzes the *rewritten* source, so anchors
land in delombok'ed coordinates while source-on-demand (Phase 1: git-backed)
serves the original — every line misaligned. `types-only` takes type
information from delombok but analyzes the ORIGINAL text: anchors align with
the pinned-SHA source by construction, and every anchor is
`variant: "original"`. Cost: the *interiors* of Lombok-generated methods are
not analyzed — acceptable because they are accessor/constructor plumbing, and
DI resolution (validated by `lombok-mini`) matches on interface types, not on
generated constructor bodies. *Rejected: run-delombok + persisting rewritten
files + `variant: "generated"` serving — the §5.3 mechanism remains the design
for when generated-code interiors matter; revisit if dataflow through Lombok
accessors becomes load-bearing (URL slicing, Phase 2+).*

**Joern pinning is by release zip, not container tag.** Upstream publishes only
rolling image tags (`nightly`, `master`) — unusable for the §13 exact-pin
requirement. The wadi-joern image installs the versioned release zip
(`v4.0.593`, matching `joernVersion` in build.sbt) onto a Temurin 21 base.

**Worker↔Joern protocol (verified against the live server).** Three control
queries per service — console `importCode.java(..., args=List("--delombok-mode",
"types-only"))` (frontend runs as a subprocess; default overlays applied),
`wadi.WadiPipeline.run(cpg, exportDir)`, `delete(project)` — plus the bulk
export on the shared volume. REPL semantics: the server reports `success` for
any *evaluated* query, including ones that raised; the client therefore
validates content (the `wadi export:` summary marker / `Cpg[` echo), and
treats `{"success": false, "err": "No result (yet?)..."}` as still-running.
*Rejected: a self-contained `runFromSource` inside our jar — javasrc2cpg is
not on the console classpath (frontends ship as separate subprocess
distributions).*

**The Scala↔Python bulk-export contract** lives in
`wadi_joern_client/export.py` (Pydantic, `EXPORT_SCHEMA_VERSION`) and
`WadiExport.scala` (writer). Major versions must match; the worker refuses
mismatches. The cross-language golden test
(`services/extraction-worker/tests/test_real_export.py`) feeds the *real*
sbt-produced export through the Python assembler in CI.

**Statement coarsening** (Scala side): statements = AST children of blocks
(calls, control structures, returns), minus lowering artifacts nested inside
leaf statements (e.g. `throw new X()` desugaring); the expression-level CFG is
projected onto them; IF edges are relabeled true/false from the AST
(`whenTrue`/`whenFalse`); each node maps to its *nearest* enclosing statement
(first-claimant mapping mislabels branch targets as self-loops).

**Timestamps are millisecond precision** (`wadi-contracts` time policy):
BSON datetimes are ms-precision; without truncation at the contract layer,
artifacts would not round-trip storage with exact equality.

**Method anchors include annotations.** Joern anchors a method declaration at
its first annotation line (e.g. `@GetMapping`), not the signature line. UI and
consumers should treat the anchor window as declaration-inclusive.

## First accuracy validation (TrainTicket, 2026-08-01)

Against `train-ticket-aitest@a84716f1` (22 services), manually verified ground
truth is **365 endpoints**. Wadi initially reported 366 — the one false
positive was a `@GetMapping` on a `@FeignClient` *interface* (an outbound-call
declaration, not a served endpoint). Fixed: `SpringEndpointPass` now requires
the owning type to be `@RestController`/`@Controller`; the petstore fixture
gained a Feign-trap file and a conformance assertion. Re-run: **365/365 exact**.
Commented-out controllers and Feign interfaces are correctly excluded.

Reference point: CIMET (the JavaParser predecessor) reports 262 on the same
commit — it deduplicates endpoints globally by API contract (method + URI),
so when this fork's inconsistency-injected duplicate controllers define the
same route in two services, only one service keeps it (103 of its 104 missing
endpoints are exactly such cross-service duplicates; two services lose their
entire inventory). Per-service endpoint inventory is wrong there by design of
its contract-keyed index.

## TTFV (§11.1 item 10 — tracked number)

TrainTicket-aitest (22 services, 365 endpoints), Apple-silicon laptop,
containerized stack: **~3 minutes** wall-clock per analysis run (cold mirror
173s, warm mirror 178s) — well inside the "10-service system ≤15 min cold"
target. Warm ≈ cold because per-service CPG construction dominates and Phase 1
deletes each CPG after export (P5) rather than caching by content hash; the
Tier-0 cache + path-delta rebuilds (§4) are the Phase 3 lever if this ever
regresses.

Local-path analysis (`wadi analyze .`) works against the containerized stack:
compose mounts `${WADI_ANALYZE_MOUNT:-$HOME}` read-only into the orchestrator
and worker so local repos can be mirrored (§13 "build in now" item — done).

## Phase 1 gaps (known, deliberate — status updated 2026-08-02 after 0.2.0)

- ~~Endpoint `params[]` are not yet populated~~ **Closed:** params are
  extracted from `@PathVariable`/`@RequestParam`/`@RequestBody`/`@RequestHeader`
  annotations (name, location, type, required) via `WadiExport.endpointParamObjs`
  → assembler.
- ~~URL recovery is literal/concatenation-based~~ **Closed:** the §5.2.4/§5.2.5
  backward slicer shipped in Phase 2 and was budget-corrected in Tranche 1
  (0.2.0). Remaining idioms are tracked in the §5.4.2 matrix (T2, issue #1).
- ~~The stitcher is the §5.4 skeleton~~ **Closed:** matching with confidence
  tiers, Neo4j population, and the coverage report all shipped in Phase 2
  (0.2.0), benchmark-validated.
- MQ interactions are modeled and assembled but no Kafka/Rabbit packs exist
  yet (Phase 3 — still accurate).
- Release engineering: PyPI publishing shipped in 0.1.1 (`wadi-sh` +
  `wadi-contracts` as a pinned pair). The remaining shared-deployment
  deliverables (remote contexts, GitHub Action, bearer-as-norm) now live in
  **Phase 6 — CI/CD & shared deployment** per the 2026-08-02 reprioritization
  (§11); the roadmap between here and there (Phase 2.5 accuracy/visibility,
  Phase 3 async/security) is deliberately local-first. Homebrew tap + curl
  installer are wrappers that may trail. Namespace claims (`wadi-sh` GitHub
  org, PyPI `wadi-sh` + `wadi-cli` stub, `trywadi.com`) should not wait — they
  are the only part someone else can take.
