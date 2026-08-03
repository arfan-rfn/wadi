# Changelog

All notable changes to wadi. One version spans the whole release set
(CLI, images, contracts — architecture.md §13).

## Unreleased

### Added — Phase 2.6: control-flow fidelity (§5.2.8)
- **M1 — the construct matrix (survey → record → fix → pin).** New
  `control-flow-matrix` fixture (compilable + runnable Spring Boot module,
  one handler per Java control construct) surveyed empirically BEFORE any
  fix; findings recorded per construct in the new §5.2.8. The coarsening
  then learned to tell the truth: every CFG node carries `construct_kind`
  (if/switch/switch-arrow/for/foreach/while/do-while/try/catch/finally/
  throw/break/continue/goto) and a real `line_end` extent; a switch is a
  `branch` node keeping its selector, with labeled `case` (+ values) /
  `default` edges, explicit `fallthrough` (the old projection rendered
  fallthrough as a fake loop), and the infeasible switch→join edge removed
  when a default exists; loops label body/exit `true`/`false` plus a `back`
  flag on cycle-closing edges; if-without-else emits its `false` join edge;
  try/catch/finally are routing nodes with `exception` edges into handlers
  (the schema's dormant kind finally has a writer); the projection walks
  through statement-less CFG nodes, restoring `synchronized` bodies and
  labeled jumps (labeled `break` redirected to the loop's exit — upstream
  re-enters at the labeled statement, wrong for break); **sinks inside
  branch conditions, throws, and for-headers now produce sink rows,
  RemoteCalls, and closure widening** (previously invisible end to end).
  Export 2.5.0, contracts 1.8.0, both additive. 29 per-construct golden CFG
  shapes pinned (`expected/cfg/`, full node/edge structure). Recorded
  upstream limits: javasrc2cpg drops the catch parameter (typed
  throw→handler linkage deliberately absent, never guessed); empty-body
  loops carry no back edge (statement-level self-loops unrepresentable).
- **M2 — always-on structural invariants.** Every snapshot is now a CFG
  test: the worker checks every method's RAW exported CFG (pre-patching,
  where reachability is still falsifiable) and aggregates violations as
  `ServiceBoundary.cfg_anomalies` → `CoverageReport.cfg_anomalies`
  (per-service `checked` flag: None/unchecked ≠ clean — P10), rendered by
  `wadi coverage`, the coverage pane, and the baseline harness. Codes:
  `disconnected-node`, `branch-arity`, `loop-no-back-edge`, `dangling-edge`,
  `exit-unreachable` (registered vocabulary, validator-enforced).
- **M3 — the bytecode oracle.** `BytecodeOracleTest` diffs javac's own
  branch/switch/back-jump counts (ASM over the compiled matrix fixture,
  `--release 21`) against the graph: **29 methods, 25 exact, 4 whitelisted
  javac desugarings (short-circuit, ternary, switch-on-string,
  yield-lowering), 0 unexplained** — and the up-front whitelist SHRANK on
  measurement (enhanced-for, try-with-resources, labeled jumps, lambdas all
  exact). Phantom branches (graph > bytecode) and missed loops are never
  whitelisted. Counts pinned; runs in CI on every commit.
- **M4 — dynamic trace inclusion.** The matrix fixture boots under the
  JaCoCo agent, every endpoint is driven through both branch outcomes over
  HTTP, and the recorded coverage is diffed against a fresh wadi analysis:
  every executed handler line maps to an ICFG node, every both-ways branch
  sits on a node the graph renders as branching (attribution artifacts —
  closing braces, chain continuations, `synchronized` headers — classified
  structurally and recorded in §5.2.8). The layer promptly caught a real
  runtime-only bug: the fixture compiled without `-parameters`, so every
  parameterized endpoint 500'd under Spring Boot 3 — exactly the class of
  truth only execution catches.
- **The trust boundary (exit criterion)** is recorded in §5.2.8: what the
  ICFG guarantees (enumerated constructs with discriminators, labeled
  outcomes, invariant-checked snapshots, oracle- and trace-verified
  fixtures) vs. what it deliberately does not (path feasibility, implicit
  exception edges, typed throw→handler, expression-level flow, context
  sensitivity). Phase 3+ layers cite it.

### Fixed
- The ICFG explorer's flow tab shows loop counts and construct chips; the
  method rollup no longer conflates branches and loops.

## 0.2.5 — 2026-08-03 (Phase 2.5: accuracy & visibility)

### Added
- **T4 — reachability roots (§5.4.2, Phase 2.5 M7):** the reachable closure
  is now rooted at **endpoints ∪ async roots** and traverses the four edge
  classes the endpoint-only BFS missed (each grounded in an empirical
  javasrc2cpg survey recorded in §5.4.2):
  - **METHOD_REF targets** — lambdas (`<lambda>N`, LAMBDA modifier) and
    method references (`this::x`) bind via METHOD_REF, not CALL;
    `CompletableFuture.runAsync(() -> client.get(...))` was invisible.
  - **Anonymous-class bodies and constructed classes behind external
    supertypes** — an anonymous `new Runnable(){...}` resolves its `<init>`
    as a call but the overrides dispatch through the external interface;
    reaching a ctor enqueues the class's methods (all of them for anonymous
    classes; the public/protected override surface for a named
    `class PollThread extends Thread` — the upstream-TrainTicket wait-order
    flow that call-edge BFS could never see).
  - **Constructor/`<clinit>` bodies** — traversed via class-load/instance
    semantics: if any method of a class runs, its static initializer ran and
    an instance was constructed — which is what makes **DI-bean
    constructors** reachable (Spring beans are never `new`ed in user code).
  - **Non-endpoint roots** — a tagging pass (`async-root=<kind>`, tag
    registry 1.3.0) marks `@Scheduled`/`@EventListener`/
    `@KafkaListener`/`@RabbitListener`/`@JmsListener` methods,
    `ApplicationRunner`/`CommandLineRunner.run`, `@Bean` factory methods,
    and public methods of stereotype components implementing an external
    supertype (`@Component implements feign.RequestInterceptor` — the
    framework-callback case). Roots come from service-own sources only
    (§5.2.6 duplication rationale). MQ semantics stay Phase 3.
  Export 2.4.0 (`async_roots` section) → contracts 1.7.0
  (`ServiceBoundary.async_roots`: kind + signature + anchor). **A
  controller-less service is now non-empty** — the new `sweeper` fixture
  module (P8) proves the whole story: 0 endpoints, 1 scheduled root, 1
  stitched edge, honest 1/2 coverage (its `main` stays unreached). The
  coverage denominator widens in lockstep: lambda bodies count as
  production methods; constructors stay out (javasrc2cpg synthesizes a
  default per class, indistinguishable from an explicit empty one) while
  their bodies still feed the closure. The explorer service list shows an
  async-root count so root-only services stop looking empty. The first
  benchmark round also exposed a crasher class: the generated
  `referencedMethod`/`referencedTypeDecl` accessors treat REF edges as
  mandatory and THROW on unresolvable method refs (`Unknown::x`) — 34
  benchmark services died on it; every REF traversal now uses the tolerant
  `_refOut` spelling, and the fixture carries an unresolvable-method-ref
  trap so the regression is structurally impossible. Measured before/after
  (M1's instrument, †=identical commits): analysis coverage upstream
  62.2%→87.1%, aitest 30.8%→50.9%, yas 29.0%→59.7% — with endpoints and
  analyzed edges byte-stable (262/161, 365/167, 194/40). The upstream
  unreachable inventory went 7→6: M1's "2 async-root entries" resolved to
  one genuine T4 reclaim (`PollThread.doPreserve`, now honestly
  `undetermined` — its URL authority is runtime data) and one hand-verified
  dead method (`AsyncTask.sendAsyncCallToPaymentService` has no caller at
  this revision — `@Async` is invoked by user code, not the framework, so
  it is correctly NOT a root).
- **Frontend workbench: coverage-first + endpoint end-to-end story (§5.3,
  Phase 2.5 M6):** the explorer gains a Coverage view (default landing:
  analysis-coverage stat tiles with "N of M" context, per-service bars,
  edges-by-target chips, the unresolved-call list with machine-readable
  reason codes, placeholder/external inventories, unmodelled client
  libraries, config conflicts — every unknown a rendered state, never a
  blank) and an endpoint Overview tab telling one endpoint's whole story:
  auth tri-state (required / open-evidenced / honest unknown), parameters,
  request/response wire shapes (§5.2.7 TypeShape trees with Jackson wire
  names and unresolved/cycle/truncated terminals), outbound calls in the
  endpoint's flow (per-call verb, URL template, mechanism, target
  resolution + confidence — a ternary fan-out shows both candidates on one
  site), and downstream endpoints. Source is rendered on demand from
  wadi's pinned-SHA store via the new `SourceView` contract (anchor-
  highlighted, delombok'd variants flagged as the text analysis saw) —
  never preloaded. UI patterns recorded from the M6 Mobbin/domain research
  (stat-tile "N of M" context, API-reference field anatomy; method chips
  stay the only saturated element). Vitest + testing-library cover the
  honesty states.

### Fixed
- **ICFG call markers survive statement coarsening (P10):** sinks anchor to
  the coarsened statement, which is not always a CALL node —
  `return restTemplate.getForObject(...)` coarsens to RETURN,
  `if (client.get(...) != null)` to BRANCH. The assembler gated marker
  attachment on CALL and the `IcfgNode` contract enforced the same wrong
  assumption, so such endpoints served ICFGs with zero `remote_call_ids` /
  `sink` marks while their stitched edges existed — the endpoint page read
  "no remote calls" for call-rich endpoints (found by the M6 browser
  verification against the live fixture). Markers are now legal on every
  statement kind (only synthetic entry/exit forbid), with regression tests
  at both layers.
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
