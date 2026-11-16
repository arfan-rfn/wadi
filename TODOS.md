# TODOS

Open work, grouped by the component that owns it, then by priority. Every entry
here is a limitation wadi *knows about* — the standing rule is that an accepted
gap gets a queryable line, never silence (P10). Items proven closed move to
**Completed** at the bottom with the version that closed them.

Priority: **P0** ships-blocking · **P1** next tranche · **P2** scheduled ·
**P3** wanted · **P4** someday.

---

## Extraction — response shapes (§5.2.7)

### Characterize the 78 unresolved response payloads
**Priority:** P1
**Opened:** v0.7.0

213 of 291 envelope payloads resolve. Of the remaining 78, exactly one category
is verified: **proxy handlers** (`getAllContacts` calls `ts-contacts-service`
and returns `re.getBody()`) construct no envelope, so the payload type genuinely
lives across a service boundary and `unresolved` is correct from inside one CPG.

The other 77 have **not** been individually characterized. Do not read 73% as
"the rest is understood" — that is exactly the aggregate-hides-a-defect pattern
that produced three wrong conclusions in this phase.

Next step: classify the 78 by producer shape before deciding whether any tranche
is warranted.

### Resolve cross-service payloads in the stitcher
**Priority:** P2
**Opened:** v0.7.0

The proxy-handler subset above is answerable, just not from one CPG: the
stitcher already knows the remote endpoint, and that endpoint's own response
shape is already extracted. Joining them would close the category properly
rather than leaving it `unresolved`.

---

## Extraction — unbound callees (§5.4.2 T5)

### 77 `unresolved-receiver` sites are a javasrc2cpg limitation
**Priority:** P4
**Opened:** v0.7.0

These are frontend sentinel types — the receiver's type could not be bound at
all, so nothing downstream can name the callee. wadi cannot close this from
here. 77 of ~8,600 unbound calls; explicitly rejected as a tranche ahead of
Phase 3 (§5.2.11). Listed so the rejection stays visible rather than becoming
folklore.

---

## Coverage — vocabulary exercised only by fixtures

### Four vocabularies have never run against a real corpus
**Priority:** P2
**Opened:** v0.7.0

Each is fixture-proven and reads zero on `train-ticket-aitest` because that
corpus does not contain the idiom. By the `unexercised_vocabulary` logic wadi
itself ships, a zero here proves nothing about whether the path works:

- ~~`authorities`~~ — **exercised in 0.8.0**: the ICPC corpus publishes 14
  distinct permission constants across 282 endpoints, read from the arguments of
  a project-defined annotation (§5.2.12).
- `denied` — no `denyAll()` route survives in either corpus.
- ~~`withheld`~~ — **exercised in 0.8.0**: fired on 7 ICPC endpoints before the
  relationship model landed, and the state left `unexercised_vocabulary`. It
  reads 0 again now because every annotation-bound guard resolves — which is the
  counter working, not the path going untested.
- `async-root` reachability — measured 0 across 14 services; no HTTP sink is
  reachable only from a startup root there.
- `declared-not-bound` — 585 → 0 after the T7 fix, so the code path that emits
  it now has no live producer on this corpus.
- Redirect/4xx/5xx statuses — the corpus declares only 200/201/202.

Next step: find or build a corpus that exercises them, or accept fixture-only
proof explicitly per vocabulary.

---

## Verification

### The corpus measurements are not reproducible from the repo
**Priority:** P1
**Opened:** v0.7.0

Every figure quoted in the v0.7.0 CHANGELOG and §5.2.11 (274 → 11 unresolved,
0 → 213 payloads answered, 585 → 0 declared-not-bound, 365/365 statuses) was
produced by an ad-hoc script outside the repo. They are correct as of
`snap_69fd4635`, but nobody can re-derive them without rewriting the script.

Next step: land the measurement as a test or a `make` target so the numbers
become a standing check rather than a claim in a document.

v0.9.0 paid part of this for entity access: the repository call-site oracle and its reconciler
are committed (`make measure-repository-sites`, `make reconcile-repository-sites`), the
baseline harness can store each service's export (`WADI_BASELINE_EXPORT_DIR`), the blind hand
check is drawn and scored by `make blind-sample` / `make blind-score`, and each run's summary is
committed under `docs/measurements/entity-access/`. The older phases' numbers are still
ad hoc.

---

## Auth — project-defined vocabularies (§5.2.12)

### The aspect that actually answers 403 is not detected
**Priority:** P1
**Opened:** v0.8.0

ICPC's `UserAuthorizer` is the construct that throws `AccessDeniedException` for
every controller method in the system, and M1 does not see it. Its own body
neither denies visibly nor reads identity: it calls `permissionChecker.isAllowed()`
on a request-scoped bean that the *other* advice writes, and the identity access
lives in an inherited `AbstractAuthorizer.validate()`.

**Do not close this by adding `AccessDeniedException` to `RejectionMarkers`.**
That was tried on paper and is worse than the gap: `UserAuthorizer` is
`execution(...)`-scoped, so detecting it emits one `{?}` and withholds all 804
endpoints — re-creating the wall of unknowns M1 exists to avoid, and destroying
the ~157 genuinely-unguarded finding. Growing a name list is also the exact
anti-pattern §5.2.12 records.

The real shape is a **deferred-verdict consumer**: advice whose decision derives
entirely from state other advice wrote, which adds no requirement of its own and
must not withhold. Recognising it is the prerequisite for detecting this class
safely.

### Enforcement scope is URI-granular, with no HTTP method
**Priority:** P2
**Opened:** v0.8.0

`ExportAuthEnforcement` carries `pattern` and no verb, so an annotation-bound
guard on `GET /x` also covers `POST /x`. The direction is safe — it withholds
more, never publishes an endpoint as open — but it costs precision in exactly
the number the tranche exists to surface. **Measured on ICPC: 804 endpoints over
734 distinct URIs, with 63 URIs served by more than one verb (133 endpoints).**
133 is the upper bound on endpoints that could be over-withheld; how many of
those 63 URIs actually carry *differing* guards across verbs is **not measured**,
so the real cost is somewhere in [0, 133]. Closing it is an export-schema field,
not a `wadi-contracts` change.

---

## Infrastructure

### An OOM-killed analyzer reports as a DNS failure
**Priority:** P2
**Opened:** v0.8.1

When the Joern container is OOM-killed (exit 137), the worker's next request
fails with `CPGQL server unreachable: [Errno -2] Name or service not known` —
a message that names neither memory nor the container that died, and sends the
reader looking at networking. Found while sizing for source unions (§5.2.14),
where it cost real diagnosis time.

The worker should distinguish "the container is gone" from "the name does not
resolve", and say which. Checking container liveness on a connection failure,
or surfacing the exit code, would turn a misleading error into an actionable
one.

### A minor schema bump is not readable by the previous release
**Priority:** P1
**Opened:** v0.8.2

§7 says additive change → bump minor, which implies an older reader tolerates
it. None does. Every contract model is `extra="forbid"` and every vocabulary is
a closed enum, so **any** additive field or enum member makes the previous
release fail hard on the new release's artifacts — and `schema_version` is
stamped on every document but consulted by no reader.

Observed, not theorised: a 0.8.2 stack wrote endpoints at 1.25.0, an older
stack came back up against the same Mongo, and the list route 500'd with
`Extra inputs are not permitted: type_defs` and `Input should be 'object',
'scalar', … input_value='ref'`. From the UI it read as a wadi bug.

`extra="forbid"` is deliberate and worth keeping — it is what caught the
`type_defs` projection leak the same day. The gap is that nothing decides what
an older reader should DO with a newer artifact. Options: refuse at the door
with a message naming both versions, or add a read-side compatibility mode for
minor-newer documents. Either is a decision, and it belongs in §7 before it is
implemented.

### `wadi status` reported the compose file, not the containers
**Priority:** P2
**Opened:** v0.8.2

Two CLI releases on one machine share the compose project name `wadi`, and each
renders a compose file pinning ITS OWN images, so whichever ran last silently
recreates every container on its own version. `wadi status` printed the images
the compose file pins rather than the ones the containers actually run, so a
stack running 0.8.1 reported 0.8.2 for hours.

Partly closed in 0.8.2: `status` now compares its own version against the API's
reported version — the one fact in that output that cannot lie — and says what
`wadi up` will do about it. Two things remain. The warning only exists in the
NEW CLI, so an older one still downgrades a stack silently; and `compose ps`
output is still the compose file's view, which is the misleading half.

---

## Analysis surfaces not yet consumed

### CORS/CSRF policy is published but not scoped to endpoints
**Priority:** P3
**Opened:** v0.7.0

`RequestPolicy` carries a `scope` (`/api/v1/**`), and endpoints carry a URI, but
nothing matches them. A reader asking "is CORS open on THIS endpoint?" still has
to compare by eye. Deliberately not merged into the auth claim — these decide
which origin may call, not which principal — but a scoped read is still useful.

---

## Entity access (§5.2.17, Phase 2.10)

Opened with the decision record on 2026-11-13, before any code. If milestone M8 (cross-service
composition) is cut, it gets an entry here at that point.

### Three decisions the gate needs are open
**Priority:** P1 (blocks milestone M5, not M0 to M4)
**Opened:** v0.8.2

The precision bar for a single `create` or `update` claim: the number, whether it is a point
estimate or a lower confidence bound, and the minimum labeled members per basis. The scope of
a verdict: a release gate across labeled corpora (proposed) or per corpus. Who labels the
saves. The bar has to be written before any save is labeled.

### Dirty-checking updates are unclaimed
**Priority:** P2
**Opened:** v0.8.2

A setter on a managed entity inside `@Transactional` updates a row with no `save` call. v1 does
not detect it and the coverage section names it as unmeasured. Train-ticket has none (0 of 37
update handlers). ICPC is unmeasured: 165 of its 187 `@Transactional` files contain no save
call. Milestone M7 opens twenty ICPC update endpoints before any ICPC entity number is
published, and that result decides whether detection is built.

### "No repository call found" is not withheld when another mechanism is reachable
**Priority:** P2
**Opened:** v0.8.2

An endpoint whose only write is `entityManager.persist` reads "no repository call found" with
the v1 limits beside it. The stronger form withholds the negative when the endpoint's closure
reaches an unmodelled persistence type. Decide at the ICPC milestone, which has 12
`EntityManager` calls.

### Database calls inside lambda bodies reach no endpoint flow
**Priority:** P2
**Opened:** v0.8.2

They are counted in the per-service accounting as "in no endpoint flow" and are in no
endpoint's entity summary. The fix is finding A1 in `docs/foundation-hardening-plan.md`.
Three such writes exist across the three corpora, all in ICPC.

### Cascaded operations are not followed
**Priority:** P3
**Opened:** v0.8.2

`delete(order)` reports `Order` only. Following a cascade needs `DataModel.relations`, which
nothing populates. ICPC has 86 `cascade =` declarations and yas has 9.

### Other persistence mechanisms are unmarked
**Priority:** P3
**Opened:** v0.8.2

`EntityManager` (12 calls in ICPC), `JdbcTemplate` (1 class in yas), Elasticsearch (yas),
MyBatis, `MongoTemplate`. Each needs its own sink detection, its own way to name the entity and
its own fixture.

### An existence check with an early return stays "create or update"
**Priority:** P3
**Opened:** v0.8.2

The existence-guard basis reads a `save` that sits directly inside the `if` or `else` of the
check. `if (!found) return ...; repo.save(x)` needs dominance reasoning and is left two-valued.
Measure how many train-ticket saves land there before building it.

### Entity nodes in Neo4j
**Priority:** P3
**Opened:** v0.8.2

§6 promises "every DB it touches" as a Neo4j traversal. Phase 2.10 answers from Mongo and
composes one cross-service hop at read time.

### Outside ground truth for entity access on TrainTicket
**Priority:** P3
**Opened:** v0.8.2

Abdelfattah et al. (CLOSER 2023) built a hand-validated set of 1,364 CRUD operations on
TrainTicket. Ask the authors for it. It is a different revision from `train-ticket-aitest`, so
check how much of it maps before relying on it.

### A method reached only through a bound method reference gets no db row
**Priority:** P2
**Opened:** v0.9.0

`widgetWriter::storeViaRef` is a bound method reference on a field. In the `save-origin-mini`
fixture the method it names emitted no `db` sink row, so it appears to be outside the export
closure. §5.2 says method references are followed. Nobody has checked whether the REF edge is
missing or the closure skips it. Found while building the save facts.

### Collision losers' ICFGs survive the collision filter
**Priority:** P2
**Opened:** v0.9.0

`resolve_id_collisions` drops a losing endpoint's ICFG by `endpoint_id`
(`services/extraction-worker/src/wadi_worker/assembler.py`), but a loser shares the kept
endpoint's id, so its ICFG passes the filter. `write_icfg` upserts on
`(snapshot_id, endpoint_id)`, so the stored graph can belong to the dropped handler, and that
handler's repository calls are counted as in endpoint flow. This predates Phase 2.10.

The final-tree review (adversarial #1) found a second effect: the kept endpoint's
`entity_access` is computed from its own graph before the drop, so when the loser's graph is the
one stored, the Data list and MCP `endpoint_detail` disagree with the canvas and `endpoint_icfg`.
The comment above the in-flow accounting says the opposite of what happens. `artifacts.endpoints`
and `artifacts.icfgs` are built in lockstep, so the fix is to drop graphs by position, not by id.

### A custom repository fragment's body is outside the endpoint flow
**Priority:** P3
**Opened:** v0.9.0

`SpringDIPass` does not link `OrderRepository.archiveOld` to `OrderRepositoryImpl.archiveOld`.
The export finds the implementation to set `implemented_in_project`, so the call reads
`unknown` correctly, but the ICFG dead-ends at the call and the fragment's own repository calls
reach no endpoint.

### Store-specific Spring Data repositories are not detected
**Priority:** P2
**Opened:** v0.9.0

Since export 2.15.0, `SpringDataRepositories.Markers` is an exact list of qualified names, and the
transitive walk follows only parent types inside the project. So `interface X extends
CassandraRepository<...>` (and the Elasticsearch, R2DBC, Neo4j and Couchbase equivalents) is
never detected, with or without the jar, and every endpoint of such a service publishes
`entity_access: []` with `call_sites: 0` and no note. Spring Data 2.x `RxJava2CrudRepository` and
`RxJava2SortingRepository` matched the old package-substring rule and no longer do. A call that
resolves to `JpaSpecificationExecutor` (`repo.findAll(spec)`) is tagged by its declaring type,
which has no marker parent, so it may go untagged. yas uses Elasticsearch. Either add the store
markers with a fixture, or withhold "no repository call found" for a service with store-module
types (final-tree review, adversarial #2).

### No standing index-scan test for the older hot read paths
**Priority:** P3
**Opened:** v0.9.0

§5.2.15 audited eight read paths by hand. The profiler-based helper in
`libs/wadi-storage/tests/test_entity_access_reads.py` covers only the three entity reads.
Extending it to the rest turns the audit into a check.

### A 1.0.x ICFG shows no outbound edges on the detail route
**Priority:** P3
**Opened:** v0.9.0

`wadi_storage.compose.endpoint_outbound` reads `IcfgNode.remote_call_ids` only, as the detail
route always did. An ICFG written before 1.1.0 carries only the deprecated `remote_call_id`,
so `/detail` and MCP `endpoint_detail` return an empty `outbound` for it while MCP
`cross_service=true` reads both fields.

### Native SQL cannot name an entity that declares no `@Table`
**Priority:** P1 (decide before releasing M6)
**Opened:** v0.9.0

The query reader resolves a native table only through `DataModel.storage_name`, which comes from
`@Table`/`@Document`, and does not guess a naming strategy. On train-ticket-aitest every one of the
9 query sites is native SQL on such an entity, so M6 moved all 9 from the repository's entity
with `unknown` to an undetermined entity with `read`: the verb is now right and the entity is
lost. The project sets no `spring.jpa.hibernate.naming.physical-strategy`, and Spring Boot's
default (`CamelCaseToUnderscoresNamingStrategy`) maps `TrainType`, `Contacts`, `Station`,
`PriceConfig` and `Route` to exactly the tables those queries name. Proposed: fall back to that
default when the service's config sets no physical strategy, and record it as a decision in
§5.2.17 first. Measure the effect on yas and ICPC the same way.

The 2026-11-15 blind check put a number on it: all 4 endpoint errors in the hard stratum, and the
one withheld pair in the random stratum, are this case (`Contacts` and `Station`), because the
read lands on an undetermined entity instead of the entity's own row
(`docs/measurements/entity-access/2026-11-15-train-ticket.md`).

### The identity rule knows only Spring's id methods
**Priority:** P2 (before M5 scores `existence-guard:update`)
**Opened:** v0.9.0

The found arm of an existence check gives an `update` candidate only when the lookup is
`findById`, `getById`, `getReferenceById` or `existsById` (review B5). A derived finder on the
entity's `@Id` field is an identity lookup too: `ts-security-service`'s `Config.update` tests
`findByName` where `name` is the `@Id`, and lost a correct candidate on 2026-11-15. Recognizing
it needs the entity's id field in the export, which `data_models` does not carry yet. Nothing
false is published either way; the cost is a candidate M5 would have scored.

### The query reader leaves HQL selects that start at `from` unread
**Priority:** P3
**Opened:** v0.9.0

`from Order o where ...` is valid HQL with an implied select. The reader follows only the four
leading verbs, so such a query keeps the pre-M6 `unknown`. Count them on ICPC before building.

### Implicit joins through a path in a `where` clause are not claimed
**Priority:** P3
**Opened:** v0.9.0

`select o from Order o where o.customer.vip = true` reads `Customer` without naming it in a
declaring position, so the reader claims only `Order`. Reads are under-claimed there.

### A flush-only endpoint reads "No repository call found"
**Priority:** P3
**Opened:** v0.9.0

`flush()` is deliberately not an entity operation, so an endpoint whose only repository call is
`flush` summarizes to `[]` and the Data list says "No repository call found." while the canvas
shows a db icon on that call. Found by the release QA on `POST /crud/flush-not-an-operation`. The
state can check the ICFG for db sink nodes without sites and say "no entity access found" there.

### Two entities with one simple name differ only on hover in the Data matrix
**Priority:** P3
**Opened:** v0.9.0

`com.acme.crud.billing.Account` and `com.acme.crud.crm.Account` render as two "Account" rows on the
home `?view=data` matrix. The qualified name is only the cell's `title`. Show the package, or the
distinguishing suffix, when two rows share a simple name.

### The undetermined-entity row carries no text for an unbound type argument
**Priority:** P3
**Opened:** v0.9.0

A call on `BaseRepository<E>` that binds no entity has `entity_type_text = null`, as contract A1
says, so the "entity not determined" row has nothing to show a reader about what it saw. The
repository type is on the site; whether to show it there is a UI decision.

### A statement's second call into project code is not followed
**Priority:** P1
**Opened:** v0.9.0

Found while building the rigor review's fixtures (F1). The ICFG puts one callee on a statement
node, so in `a.count() > 0 && helper.existsIn(...)` the flow never enters `existsIn`, and any
repository call or outbound call inside it is missing from that endpoint. Repository calls made
directly in the statement are not affected: a node lists every site it holds (R1-2). The fixture
was restructured around it, so no golden covers the shape yet. It affects endpoint completeness
wherever a condition or an expression chains two calls into project methods.

### The save's existence check is looked for only in the saving method
**Priority:** P2
**Opened:** v0.9.0

Review A6. `lookup_same_repository` asks whether the saving method reads the same repository
type. An existence check in the caller, in a helper, or on another repository of the same
entity (train-ticket's travel and preserve services each have two repositories on `Order`)
gives `constructed` with no lookup, which is a `create` candidate. The split is gated, so
nothing false is published, but M5 must settle this before it scores `argument-origin:create`.

### Transitive detection and the hard matching cases have no real-corpus measurement
**Priority:** P2
**Opened:** v0.9.0

Reviews A7 and D9. `RepositoryDetectionRegressionTest` holds three database calls on the older
fixtures, and every train-ticket repository is direct, so transitive detection is exercised only
by the crud-matrix fixture. The ICPC claim (111 repositories through a project base) is not
measured on this branch. On train-ticket the reconciler met no two calls on one line, no
multi-line call and no overload, so those matching rules are proven only by synthetic tests.
M7 (yas, ICPC) is where both get a real corpus.

### The query reader's remaining silent misses
**Priority:** P3
**Opened:** v0.9.0

Review B7, after the hardening. The reader still drops an access without a flag for an implicit
join through a path (see the entry above), `treat(...)`, `delete ... using`, `straight_join`,
and the second table of a MySQL multi-table delete (`delete o, l from ...`). None claims a false
verb; each loses an entity the text names. The module docstring lists them.

### An entity named only through a marker-typed receiver has no entity record
**Priority:** P3
**Opened:** v0.9.0

F1 finding 5. A call on `CrudRepository<Foo, Long>` where `Foo` has no `@Entity` and no
repository of its own binds `Foo`, but no `data_models` row is written for it. The reverse view
still lists it (a row from the access, with no storage name), so nothing is lost; the record is.

### Small reader gaps left by the 1.27.0 change
**Priority:** P3
**Opened:** v0.9.0

- MCP `endpoint_detail` shows `call_sites_by_operation: null` on a summary written before
  1.27.0 with no note saying why, where `entity_usage` explains it.
- Two frontend fixtures still cast whole payloads (`tests/data-list-state.test.ts:40`,
  `tests/entity-sites.test.ts:23`).
- One type that arrives as two Data list rows (with and without a model id) shares one
  `entity=` selection key, so selecting one selects both.

### A vocabulary change must keep 0.9.0 accounting readable
**Priority:** P1 (bound to the next change to `EntityOperation` or `EntityAccessBasis`)
**Opened:** v0.9.0

Pre-landing review finding #4. `EntityAccessAccounting` requires exactly the current operation and
basis keys (a zero is written, never left out, E8), and the model is read back from every stored
boundary and coverage report. Adding a value (M5 is the likely first) would make every 0.9.0
document fail to load. That change must add a read rule in the same commit: accept a document
missing the new key and read it as "not measured by that version" (§5.2.17, "Found by the
pre-landing review").

### Review notes left open at 0.9.0
**Priority:** P2
**Opened:** v0.9.0

Below-floor findings from the three pre-landing passes, recorded here rather than fixed in 0.9.0.

- **Query text keeps Java string syntax.** `unquote` strips only the outer quotes, so a text
  block (`"""..."""`) reads as an empty quoted identifier, `\n` glues onto the next keyword, and
  `\"Orders\"` names a table `Orders\`. Each degrades to `unknown` or undetermined, so nothing
  false is published, but coverage drops on Java 15+ code. No fixture uses either.
- **MariaDB executable comments** (`/*M! ... */`) are still dropped as comments; MariaDB runs
  their text. Refuse them as `/*!` is refused.
- **The flow-stops note counts only each statement's primary call.** In
  `mapper.toDto(svc.load(id))` an unbound `svc.load` gets no reason, so `[]` shows with no note.
- **`not-declared` counts as may-hide-project-code**, though its main source is a static import
  such as `ResponseEntity.ok`, which the T5 golden calls benign. Probably split the reason.
- **Two HTTP calls with one URL on one line share a remote-call id** (service, file, line, URL),
  so one is dropped and its verb lost. Not a regression; the id format would have to change.
- **REST `/detail` still fails on the graph.** It waits about 57 s on an unreachable Neo4j and
  returns 500, and it returns 500 on a chunked ICFG missing a part, where MCP `endpoint_detail`
  now degrades. Statement-level chips still show only `node.sink`.
- **MCP `endpoint_detail` reads a missing ICFG as a clean flow.** Flow marks `None` (no stored
  graph) gives `entity_facts: analyzed` with no note and `outbound: []` with `stitched: true`.
- **Two descriptions trail the 0.9.0 fixes.** The Data view's withheld tooltip says a withheld
  column counts only what query text states, which is no longer so once some flags are on. The
  `endpoint_detail` tool description gives one cause for `outbound: null`, and now there are two.
- **`entity_usage` and `/entities` on a running snapshot.** A service whose extraction has not
  started is absent from the view and from `unexamined`, so asking for its entity answers "not
  declared or touched here". The UI caches that answer as immutable.
- **The Data matrix says "predates" for every unanalyzed view**, including one whose services all
  failed extraction, while MCP names the failure.
- **The Data list ignores `stitched: false`.** Before stitching a forwarding endpoint with
  `entity_access: []` reads like one that calls nothing.
- **The stale-flag ratchet checks the wrong version.** The build-time test compares enabled gate
  flags to `RULES_VERSION`, computed without `save_origin_rules`, while the worker gates on
  `export_rules_version(export)`. Every shipped flag is off, so nothing publishes wrongly yet.
- **`e2e/test_baseline_snapshot.py` reruns keep a stale named export.** `name_by_service` skips
  the rename when `<service>.json` exists, so the reconciler reads last run's file.

### Re-measure train-ticket on the shipped export
**Priority:** P2
**Opened:** v0.9.0

The 2026-11-15 measurement ran on an earlier 2.15.0 build of this branch (`41ecddc`), before
every sink call got its own row. Repository sites should not move, since `db` rows were already
per call, but remote-call counts can. Re-run the measurement on 0.9.0 and update
`docs/measurements/entity-access/` if any number changes.

### `e2e/` is outside pyright's include
**Priority:** P3
**Opened:** v0.9.0

`e2e/test_baseline_snapshot.py` has four strict-mode errors in its schema spot-check that CI
never reports.

---

## Completed

### `--wait` reported a healthy run as a dead API
**Closed:** v0.8.2

`wait_for_snapshot` polled every 2 s on a keep-alive connection and treated the
first transport failure as fatal. On a real ICPC analysis the connection
dropped 64 seconds into a 270-second run — 32 polls reached the server, then
nothing — and the CLI printed "the wadi API is not answering" with "try:
`wadi up`", against a stack that was up. The orchestrator logged no error, did
not restart, and the snapshot **succeeded**.

The trigger is environmental (this Docker VM drops connections under analysis
load, same pressure as the entry below) and the CLI behaviour was wrong
regardless: a failed poll says nothing about the run, which proceeds in the
orchestrator either way. Failures are retried within a 60 s window and shown
while they last; giving up now says the run may still be going and points at
`wadi status` / `wadi snapshots` rather than at restarting a healthy stack.


### `make test` deleted the developer's running stack
**Closed:** v0.8.2

Every run, all session — misread first as memory pressure, then as an
unexplained environment fault, and "fixed" once by capping the e2e analyzer's
memory, which was a real improvement and not this. Settled by recording
`docker events` live across a run instead of reasoning about it: five
containers `kill` -> `die exit=137` -> `destroy` inside one second, which is a
deliberate `docker rm -f`, not an OOM.

`wadi down` tears the stack down in three steps and the tests stubbed two:

    reap_managed_containers()   # stubbed
    run_compose(["down", ...])  # stubbed
    finish_network_teardown()   # NOT stubbed -- shells out to docker

That third call removes every container on the wadi network whose image is in
the release namespace, which is exactly the signature observed: the five
`ghcr.io/wadi-sh/*` containers destroyed, `mongo` and `neo4j` — public images,
"foreign" by that function's own rule — untouched. Three tests hit it.

Stubbing those three would have fixed the instance and left the trap armed, so
`cli/tests/conftest.py` now refuses any real subprocess from `compose` and
fails the test that tries. It caught all three immediately. A CLI whose job is
driving Docker should not be unit-tested against the live daemon.

*The standing lesson:* two confident explanations preceded the right one, and
both were built from correlation. The event stream answered it in one run.


### The e2e analyzer container had no memory limit
**Closed:** v0.8.2

Not the cause of the disappearing stack — that was the entry above — but a real
defect found looking for it. The e2e ran its analyzer with no `--memory`, which
does not mean "no limit": the JVM sizes its heap against the whole Docker VM.
Beside a live stack whose own analyzer reserves 10 GB of 15.6 GB, the two
overcommit. Bounded to 4 GB against a **measured peak of 807 MiB**.


### `wadi up` could not converge onto a running stack
**Closed:** v0.8.2

`compose.check_port_free` bound a bare socket and read any `OSError` as a
conflict, which caught two things that are not one. Its own stack: with wadi
up, the orchestrator holds the API port, so `wadi up --expose-db` refused to
run and the only route to changing a flag was `wadi down` first — §13 records
converging re-runs as the intent, and this is what stopped them. And a socket
a dead client left behind: a stopped dev server that had been talking to 9234
kept it unbindable with no LISTEN anywhere, so the port read as taken with
nothing on it.

`SO_REUSEADDR` settles the second (the probe never accepts a connection — it
only asks whether a listener could exist). For the first, ownership is now a
question for docker rather than the socket: a bind failure on a port published
by a container labelled with our own compose project is a converging re-run,
not a collision. A stranger on the port still fails, loudly, and a machine
with no docker still reads as contested.


### `endpoint-dependencies` took ~4.4 s to return 125 bytes
**Closed:** v0.8.2 (§5.2.15)

The view needs one set of remote-call ids per endpoint and nothing else, but
the only way to get them was `get_icfg` per endpoint — on ICPC `contest`, 804
graphs reassembled from their chunks and validated into Pydantic models, to
answer in 125 bytes. The same defect as the endpoint list one route over, found
while profiling it: read everything to produce almost nothing.

The union is computed in a Mongo aggregation instead, with a second pass over
`icfg_parts` merged in — a chunked graph leaves no nodes on its manifest, so a
single aggregation would have returned an empty set for exactly the largest
graphs in a snapshot, silently. **Measured: 4.4 s -> 0.07 s, byte-identical
payload**, and diffed against the old route across all 22 train-ticket services
plus ICPC with 0 mismatches.


### One service's endpoint list was 114 MB and took 12 s
**Closed:** v0.8.2 (§5.2.15)

§5.2.14 made ICPC's library types resolvable, so §5.2.7 expanded them —
correctly, and without a ceiling. `TypeShapes` guards cycles per *path*, which
leaves sibling branches free to re-expand the same entity subgraph, so a
bidirectional JPA graph goes exponential in the depth cap: one endpoint's
response shape reached 3 MB at depth 25 with `label` repeated 520 times. The
browser parsed 114 MB on the main thread before rendering a row, which is what
made the endpoint workspace look frozen.

Fixed in two places, because they fix different populations. The list route
serves a distinct **`EndpointSummary`** — the wire shapes are absent from the
type, not nulled, since `None` already means "no request body" on 673 of those
804 endpoints — projected in the Mongo query rather than in Python, which is
where the latency actually was. That repairs every snapshot that already
exists. **`TypeShapes` gained a node budget** (`MaxNodes = 200`, emitting the
existing `truncated` terminal), which bounds the defect at the source for
snapshots analyzed from here on.

**Measured on ICPC `contest`, 804 endpoints: 114,546,092 B / 10.7–14.5 s ->
2,479,867 B / 0.09 s.** Trimming the response alone was tried first and moved
the payload 47x while leaving the clock at ~11 s — recorded in §5.2.15 as the
standing lesson that a payload measurement is not a latency measurement.

Landing with it: MCP's `list_endpoints` (same defect, into an agent's context
window), the frontend reading both shapes from the detail it already fetched,
`staleTime: Infinity` on every snapshot-scoped read since artifacts are never
rewritten in place, and a visible loading affordance — the skeleton was
`--muted`, a 3% step against `--card`, and lived only in section bodies, which
a collapsed section does not render.


### A library compiled into a service was modelled as a peer service
**Closed:** v0.8.1 (§5.2.14)

Dependency resolution was repo-wide while classification needed to be
system-wide, and web presence was mistaken for deployability — so a shared
internal jar in its own repository got its own service and its own CPG.
**Measured on ICPC: response shapes resolved 468 -> 803 (335 of 336 unresolved
recovered), relationship-scoped endpoints 562 -> 643, relation vocabulary 7 ->
8.** The library's one controller endpoint moved to the app that deploys it,
with the endpoint total unchanged.


### A path template could match a literal into a `permitAll`
**Closed:** v0.8.0 (§5.2.13)

`_ant_match` let an endpoint's `{id}` absorb a literal pattern segment, so
`/help/cms/{space}/{page}` inherited the `permitAll` written for
`/help/cms/virtpublic/**`. Matching now reports whether it was exact or
speculative, and only callers that can be *weakened* by a match — a
`permitAll`, a chain bypass — refuse to act on speculation. **Measured: 9
endpoints moved from evidenced-public to protected, 0 regressions.**

### Response payload depth — envelopes resolved past `T`
**Completed:** v0.7.0 (2026-08-06)

### Declared HTTP statuses per endpoint
**Completed:** v0.7.0 (2026-08-06)

### `auth_policies` consumed end to end (CORS/CSRF/entry-point)
**Completed:** v0.7.0 (2026-08-06)

### Token propagation — three states on every outbound call
**Completed:** v0.7.0 (2026-08-06)

### Served routes root-anchored; two admin endpoints corrected from public
**Completed:** v0.7.0 (2026-08-06)

### Unbound-callee classifier split; 585 false binding failures removed
**Completed:** v0.7.0 (2026-08-06)
