# Changelog

All notable changes to wadi. One version spans the whole release set
(CLI, images, contracts — architecture.md §13).

## Unreleased

### Added
- **Analysis-coverage metric (§5.4.3, Phase 2.5 M1):** the coverage report
  now answers "of the source code, how much did analysis actually walk" —
  per service and per snapshot, production methods (internal, non-synthetic,
  concrete, service-own sources) vs. methods in ≥1 endpoint's reachable
  closure, as counts + percentage. Computed in-CPG (export schema 2.2.0),
  carried on `ServiceBoundary.analysis_coverage` (contracts 1.5.0, additive),
  aggregated by the stitcher, surfaced via the coverage API/MCP tool and
  `wadi coverage`. Unknown is structurally distinct from zero everywhere
  (P10): a service without the fact reports null counts, and 0/0 has no
  percentage. Landed before T4 by design — the reachability-roots tranche
  will be measured as a before/after on this number.
- `wadi coverage` human output also lists unmodelled client libraries
  (the §5.4.2 census was previously JSON-only).
- **Provider-side endpoint contracts (§5.2.7, Phase 2.5 M5):** every
  endpoint now carries a field-level request/response wire shape.
  `response_type: Pet` becomes `{id, display_name, stock: {…}, …}` — walked
  from in-CPG type structure with generics recovered from the declared
  source text (javasrc2cpg erases them in type names), wrappers unwrapped
  (ResponseEntity/Optional/Mono/Flux/…), Jackson field semantics applied
  (@JsonProperty renames the wire name, @JsonIgnore omits — the shape is the
  wire contract, not the class layout), and honest terminals everywhere:
  `unresolved` (off-CPG type — name only, never fabricated fields),
  `cycle` (self-referencing DTOs terminate explicitly), `truncated` (depth
  cap). Staged-library DTOs (§5.2.6 union) resolve as first-class shapes.
  Export 2.3.0, contracts 1.6.0 (`TypeShape` on `Endpoint`), both additive.
  The baseline harness prints a per-run schema spot-check; TrainTicket's
  `Response{status, msg, data}` and yas's `AuthenticatedUser{username}`
  hand-verified against source. Consumer-side `sends[]`/`reads[]` stays in
  Phase 5 by design.
- **T3 deployment-model resolution (§5.4.2, Phase 2.5 M4):** the deployment
  layer becomes phone-book input.
  - **Compose env surface:** `environment:` (map/list, bare pass-through
    resolved from the repo `.env` — the yas idiom), `env_file:`, network
    aliases/hostname/container_name, override files; allowlisted onto the
    boundary in raw spelling.
  - **Spring relaxed binding + multi-pass expansion:**
    `${yas.services.customer}` finds `YAS_SERVICES_CUSTOMER`; nested
    placeholders resolve, cycle-bounded.
  - **Profile merge:** `application-<profile>.*` + multi-doc YAML profile
    documents merge over the base — exactly the compose-declared active set,
    else all profiles with the honest `config-profile-merged-all` note.
  - **K8s service DNS** (`.svc`/`.svc.cluster.local` exact; two-label form
    known-identity-only and capped HIGH via the new `indirect` flag),
    loopback classification, **Eureka/Consul `discovery_names`** (first
    writer), **`server.servlet.context-path`** applied to matching, **Zuul**
    routes and **SCG expanded map-form**; unmodelled gateway shapes emit
    `gateway-*-unmodelled:<name>` notes (perceive-and-note).
- **T2 client APIs + URL idioms, tranche 2 (§5.4.2, Phase 2.5 M3 — closes the milestone):**
  - **Feign completeness:** transitive interface inheritance (the shared-
    contract idiom previously produced NO sink), `@RequestMapping(method=…)`
    verbs, constant `name` attributes resolved in-CPG (unresolvable ones
    degrade to an honest `{?}` authority, never an interface-name guess),
    `contextId` ignored, and `url="${key}"` surfaced as a config reference.
  - **`@HttpExchange` declarative interfaces** (mechanism `http-interface`,
    now modelled in the census).
  - **Client base-URL split:** `RestClient.create`/`baseUrl`/`rootUri` bases
    recovered from owner-scoped initializers; unrecoverable bases emit the
    new `base-undetermined` reason code — never a fabricated absolute.
  - **Slicer idioms:** ternary branches (both arms are candidates; covers
    getenv-with-default), parameter-level `@Value`, statement-form
    StringBuilder, `String.concat`/`join`/`formatted`, `MessageFormat`,
    member-held `Map.of` constant maps, varargs array-initializer lowering.
  - **`unsupported-idiom:<name>` reason-code family:** named unmodelled
    constructs (getenv, builder-in-local UCB, unmodelled operators) are now
    countable per idiom instead of anonymous opaque holes.
  - Lower-priority clients (JDK HttpClient, OkHttp, …) reclassified as
    census-triggered on-demand: the `unmodelled_mechanisms` coverage signal
    is the scheduler, per repo, by measured demand.
- **T2 client APIs + URL idioms, tranche 1 (§5.4.2, Phase 2.5 M3):**
  - **RestClient (Spring 6.1+/Boot 3.2+)** modelled as a first-class sink —
    the same fluent shape as WebClient (`.uri(...)` is the sink, the chain
    root carries the verb), mechanism `restclient`, now in
    `MODELLED_CLIENT_LIBRARIES`. This closes the yas lesson: its 34
    RestClient call sites stop being an invisible zero.
  - **UriComponentsBuilder chains** sliced (base + `path`/`pathSegment` in
    call order; `queryParam`/`fragment`/`build*`/`encode` identity-neutral
    and trace-noted; unmodelled steps yield honest holes) — the predecessor
    -study regression, closed.
  - **RequestEntity-form `exchange`** — verb and URL recovered from the
    entity's builder chain off the call site (inline or via method-local
    assignment), and **`URI.create`** unwrapped transparently.
  - petstore-system gains one P8 probe per idiom (StockHistoryClient,
    CheckupScheduleClient, ReservationClient), each proven end to end as a
    HIGH-confidence analyzed edge through the public API.
- **`wadi export` (§14, Phase 2.5 M2):** the third consumption surface.
  `GET /api/v1/snapshots/{id}/export` streams every artifact of a succeeded
  snapshot as NDJSON with an `ExportManifest` trailer (counts-last so a
  truncated stream is always detectable); `wadi export <snapshot-id> --dir`
  writes the §14 on-disk layout — `manifest.json` + per-collection JSON
  arrays + `icfgs/<endpoint_id>.json` — every file validating against the
  published schemas. The CLI verifies the manifest before writing anything
  (no partial bundles), refuses a non-empty directory without `--force`, and
  re-exports are byte-identical except the manifest's `produced_at`.
  Only succeeded snapshots export (409 otherwise — a partial artifact set is
  a misleading half-map).

## 0.2.0 — 2026-08-02 (the benchmark-accuracy release)

Three verified tranches driven by cross-tool benchmarking on FudanSELab
train-ticket (upstream + aitest fork) and NashTech yas, with CIMET run
first-hand at identical commits. Headline: upstream TrainTicket now analyzes
at 262/262 endpoints, 161 stitched edges with an HTTP verb on every one,
zero undetermined calls, and an unreachable inventory of exactly the 5
hand-verified dead-code calls + 2 async roots (tracked for the next phase).
All contract changes additive (schemas 1.1.0 → 1.4.0).

### Fixed
- **URL slicer budget honesty (§5.2.5):** depth now measures indirection, not
  expression size — long `+`-concatenated URLs no longer starve the
  interprocedural/constant-map stages (21 false "honest unknowns" on
  train-ticket-aitest were budget starvation misreported as semantic
  unknowns). Truncation propagates and is marked `slice-budget-truncated`.
- **HTTP verbs from `exchange`/`execute`/`method` arguments** (literal
  `HttpMethod.X`), plus HEAD/OPTIONS name mappings — verb-aware endpoint
  matching collapses false multi-candidate fan-out (369 → 164 true edges).
- **WebClient fluent chains:** the `.uri(...)` step is the sink (URL + verb
  now recovered; previously every WebClient sink exported null labeled
  `resttemplate`).
- **Owner-scoped field slicing** — same-named fields in other classes no
  longer bleed into URL candidates.
- **DI resolution resilience (§5.2.6):** short-name normalization, name+arity
  fallback when unresolved types make exact signature matching impossible
  (tagged `wadi-di=name-arity`), transitive interface→abstract→impl
  resolution preferring body-carrying leaves, self-type linking for
  intra-class calls the frontend leaves unlinked, and inherited client fields
  typed through the declared-member hierarchy.
- **Service-marker classification matches word boundaries** —
  `@ControllerAdvice` in a shared module no longer flips it to a service and
  silently disables the source union (yas common-library).
- Colliding artifactId display names fall back to module directory names
  (TrainTicket's two gateways both declare `gateway`).
- Multi-document `application.yml` parses its base document (previously
  zeroed ALL config facts) with a `config-multi-doc-partial` note.

### Added
- **Staged source union (§5.2.6):** Maven module-graph parsing (pure XML),
  service/library/noise classification (`ServiceKind.LIBRARY`,
  `ServiceBoundary.library_roots`), and per-service parse inputs that include
  transitive in-repo library sources — shared modules like `ts-common`
  (41 dependents) and yas `common-library` (15 dependents) resolve as
  first-class source. Recovered 25 cross-service calls on upstream
  TrainTicket alone.
- **Honesty machinery:** unreachable-sink inventory (dead code excluded from
  the map by design, now queryable — 224 dead call sites counted on
  train-ticket-aitest), suspected sinks for HTTP-shaped calls on unresolvable
  receivers, per-service extraction failure isolation
  (`ServiceBoundary.extraction_error`), and a machine-readable
  unresolved-reason registry (`UNRESOLVED_REASON_CODES`).
- **Client-library census (§5.4.2):** deterministic import scan recorded as
  `ServiceBoundary.client_libraries`; coverage reports gain
  `unmodelled_mechanisms` — a zero-edge system is now distinguishable from a
  correct zero-edge answer (yas: "0 call sites, RestClient present and
  unmodelled in 14 services").
- **Endpoint declaration idioms:** multi-path mapping arrays (one endpoint
  per entry) and static-final constant path prefixes incl. nested holders
  (`Constants.ApiConstant.X`), resolved from in-CPG initializers — yas
  endpoint truth 194/194 where raw-text alternatives fabricate paths.
- **Discovery hygiene:** `src/test` + `src/it` + `old-docs` + hidden shadow
  trees excluded from every CPG; no-Java modules skipped.
- The outbound-call coverage matrix (architecture.md §5.4.2) and the
  analysis-unit decision record (§5.2.6), incl. the permanent rejection of
  `--fetch-dependencies` (executes build tooling). Deferred classes tracked
  as issues #1–#6.

## 0.1.1 — 2026-08-01

### Fixed
- `wadi-sh` is now installable from PyPI: the wheel pins `wadi-contracts==`
  exactly and the release pipeline publishes both packages as a pair
  (0.1.0 shipped only `wadi-sh` with an unpinned contracts dependency).

### Added
- `make bump V=x.y.z` sets the release version everywhere the release guard
  checks; the guard enforces the pairing on every `v*` tag.
- Apache-2.0 license metadata on the published packages and images.

## 0.1.0 — 2026-08-01 (Phase 1: backbone + vertical slice)

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
