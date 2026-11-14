## Implementation plan
# Implementation plan: entity access per endpoint (Phase 2.10)

Status: APPROVED by the user on 2026-11-13 (decision D11), after an eng review and a Codex
outside review. Three decisions remain open and are listed at the end. Compiled 2026-11-13 against commit `118eb91` (wadi 0.8.2,
contracts 1.25.0, export 2.13.0 as read by Python and 2.12.0 as stamped by Scala).

Inputs: `docs/designs/entity-access.md` (approved design, with amendments R1-1 to R1-13) and
`docs/entity-access-plan.md` (decisions Q1 to Q27 and the corpus measurements). This plan turns
them into milestones, contract shapes, files and tests, and settles the reviewer's minor
findings R1-14 to R1-27. Every name below is a proposal until the final gate.

## Goal

For each endpoint, publish which entities it may touch and with which operation, with the basis
for each claim, over REST, the MCP server and the UI. For each entity, publish which endpoints
touch it. Account for every repository call site, including the ones the analysis cannot bind.

## Not in scope

- Dirty-checking detection. Unclaimed and named as unmeasured (Q2, Q25).
- Cascaded operations (Q17). `DataModel.relations` stays unpopulated.
- `EntityManager`, `JdbcTemplate`, Elasticsearch and other mechanisms (Q4).
- Lambda bodies in the ICFG. That is finding A1 in `foundation-hardening-plan.md` (Q9).
- Entity nodes in Neo4j (Q20).
- Conditions on an operation. The fact is "may", never "always" (Q16).
- Withholding "no repository call found" when an unmodelled persistence type is reachable. A TODO
  for the ICPC milestone (R1-7).
- Refactors of shared components. The Data list is a new component beside `CallTree`.

## Contract changes

One contracts bump (1.26.0) and one export bump (2.14.0) carry every shape the phase needs,
including the fields the split milestone fills later. The Scala constant `ExportSchemaVersion`
moves from 2.12.0 to 2.14.0 in the same change, which closes hardening finding H2 (R1-21).

### `wadi-contracts`

- `EntityOperation`: `create`, `read`, `update`, `delete`, `create-or-update`, `unknown`.
  `create-or-update` is one value, never two verbs on one fact (R1-5).
- `EntityAccessBasis`: `method-name`, `query-text`, `argument-origin`, `existence-guard`.
- `EntityAccessSite`, one per repository call site (eng review E1, outside finding C1):
  - `repository` and `method_name`: the receiver's declared type and the called method.
  - `basis`: the `EntityAccessBasis` behind the site's operations.
  - `accesses`: a list of `EntityAccess`. A derived method has one. A query that deletes
    `Invoice` while reading `Customer` has two, each with its own operation.
- `EntityAccess`: `entity` (type name, or `None` for "entity undetermined"), `data_model_id`
  (when the entity is in `data_models`), `operation`, and `candidate_operation`, which is set
  only on a demoted fact and is evidence, never a claim (R1-11).
- `IcfgNode.entity_access_sites: list[EntityAccessSite]`, default empty, the way
  `remote_call_ids` is a list. A statement with two repository calls carries two sites (R1-2).
  Sites are counted as sites and accesses as accesses, never mixed.
- `EndpointEntityAccess`, the summary row: `entity`, `data_model_id`, `operations` (sorted, no
  duplicates) and `call_sites`.
- `Endpoint.entity_access` and `EndpointSummary.entity_access`:
  `list[EndpointEntityAccess] | None`. `None` means the snapshot predates the phase. An empty
  list means analyzed and nothing found (R1-6).
- `DataModelField.declared_type`: the field's type as written in source, generics kept.
- `DataModel.storage_name`: populated from `@Table(name=)` or `@Document`. `DataModel.declared_by`:
  `annotation` or `repository-argument` (Q1, Q15).
- `DataModel.type_full_name` (the qualified class name) and `DataModel.jpql_name` (the
  `@Entity(name=)` value when set). The query reader needs both, and `data_model_id` is derived
  from the qualified name so two classes with one simple name in a service get two ids (C2).
  This changes every existing `dm_` id once. Nothing reads those ids today.
- `EntityAccessAccounting`, an optional field of its own on the service boundary, written by the
  worker (`None` on a snapshot from before the phase). It is not part of `AnalysisCoverage`,
  which is an in-CPG methods metric with its own validator (E2). It counts repository call
  sites: total, bound to an entity and a verb, `create-or-update`, `unknown` verb, undetermined
  entity, project-implemented repository method, `flush`, and in the export but in no endpoint
  flow (R1-1). It also records which gate flags were on, because the stitcher cannot know (E3).
- `EntityCoverageSection` on `CoverageReport` (per snapshot), built by the stitcher in
  `services/stitcher/src/wadi_stitcher/coverage.py` the way `AuthCoverageSection` is: the sum of
  the per-service accounting, the unmeasured cases (cascades, setter updates, other mechanisms),
  and the gate flag state the workers recorded.
- `EntityUsageView`, the reverse view: `analyzed: bool` and one row per entity (name, service,
  `data_model_id`, storage name, how it was declared) with, per operation, the endpoints that
  may perform it. Entities no endpoint reaches are rows with empty lists (Q6).
- `summarize_entity_access(...)`: a pure function in the contracts package that folds
  per-call-site facts into summary rows and folds summary rows into `EntityUsageView`. The
  worker, the orchestrator and the MCP server all call it, so the composition exists once
  (R1-22). `resolve_type_shape` is the precedent for shipping a reader in the contract.

### Export (Scala to worker)

The export already emits one `sinks` row per database call site, keyed by `call_id`
(`ExportSink`, `libs/wadi-joern-client/src/wadi_joern_client/export.py:344`). The phase adds an
optional nested `db` object to rows of kind `db`. It does not add a second inventory of the same
call sites (E1). An export without the object still parses.

- `implemented_in_project` (bool): the called method has a body in the project, which is a
  `default` method or a custom repository fragment (C3).
- `repository`: the receiver's declared type. `entity_type_text`: the bound entity type
  argument as written, or null when the chain cannot be bound (R1-4).
- `method_name`, and `query`: `{text, native, named_ref, modifying}` when the repository method
  carries `@Query`, `@Modifying`, or resolves to a `@NamedQuery` or `@NamedNativeQuery`.
- For a save: `argument_origin` (`read`, `constructed`, `parameter`, `mixed`, `other`),
  `lookup_same_repository` (bool) and `guard_arm` (`found`, `not-found`, `none`).
- For a save whose argument is a parameter: the origins at each caller, one hop.

`models` rows gain `type_full_name`, `jpql_name`, `declared_type` per field, `storage_name`,
`declared_by`, and a row for an entity that only a repository names.

## Classification rules (worker, as data)

A verb table in the worker maps raw facts to `(operation, basis)`:

1. A method with `query` facts: before milestone M6, `unknown`. From M6, the query reader
   decides. The method name never decides for an annotated method (R1-12).
2. Otherwise the method name, and only for a method Spring Data implements. A call with
   `implemented_in_project` set is `unknown`: membership of a repository does not establish what
   a hand-written body does (C3). For the rest: `find*`, `get*`, `read*`, `query*`, `search*`,
   `count*`, `exists*`, `stream*` are `read`. `delete*` and `remove*` are `delete`. `save*` and
   `insert*` go to rule 3. `flush` is not an entity operation and is counted on its own.
   Anything else is `unknown`. A golden pins the table against the inherited method sets of
   `CrudRepository`, `JpaRepository` and `MongoRepository` (E5).
3. A save. Candidate from `argument_origin`: `read` gives `update`. `constructed` with no lookup
   on the same repository gives `create`. `constructed` with a lookup consults `guard_arm`:
   `not-found` gives `create`, `found` gives `update`, `none` gives `create-or-update`. `mixed`,
   `other` and an unresolved `parameter` give `create-or-update`.
4. A parameter resolved through one caller hop takes the callers' origin only when every caller
   agrees. Callers that disagree, or an origin that is still a parameter after one hop, give
   `create-or-update` (R1-27).
5. The gate. Each basis has a flag per verb in the verb table. With the flag off, rule 3's
   candidate is recorded in `candidate_operation` and the published operation is
   `create-or-update`. Both flags ship off. Each flag stores the rules version it was scored
   against, where the rules version is a hash of the verb table and the raw-fact fields. A unit
   test fails when a flag is on for a different rules version, so a rule change cannot keep
   publishing on a stale score (E4).
6. A query that names several entities yields one access per entity, each with the operation the
   query applies to that entity. A delete with a subquery deletes one and reads the other (C1).

Query reader (M6), selection rule (R1-24): `nativeQuery = true` or a `@NamedNativeQuery` is read
as SQL, and its table names resolve through `storage_name`. A `@Query` on a Mongo repository is
JSON: verb `unknown`, entity from the repository. Everything else is JPQL: the verb is the first
keyword, entity names match `@Entity(name=)` first and then the class name, case-sensitively,
against the service's own entities, and a join target resolves through the field's
`declared_type`. What the reader cannot resolve keeps the verb and yields an undetermined entity.

## Read paths

- `wadi-storage`: `list_endpoint_entity_access(snapshot_id)` returns a projection (endpoint id,
  method, URI, service id, `entity_access`), and `list_data_models_for_snapshot(snapshot_id)`
  reads every service's models in one query (R1-8).
- Orchestrator: `Endpoint` and `EndpointSummary` carry the summary on the existing detail and
  list routes. New `GET /api/v1/snapshots/{id}/entities` returns `EntityUsageView`.
- MCP server: `endpoint_detail` carries the summary, `endpoint_icfg` call rows carry
  `entity_access_sites`, and the new `entity_usage(snapshot_id, entity?, service_id?)` returns the
  reverse view. Each says the snapshot predates entity facts when `entity_access` is `None`.
- Forwarding endpoints (Q26): the Data list names the outbound calls from
  `EndpointDetailView.outbound`, which already exists. The MCP `endpoint_detail` tool returns an
  `Endpoint`, not that view (`services/mcp-server/src/wadi_mcp/service.py:71`), so M3 adds the
  endpoint's outbound edges and whether the snapshot is stitched to its response, composed by a
  shared function and not by importing the orchestrator (C5).
- Cross-service composition (Q5, M8): one hop over stitched edges, the bound the MCP server's
  existing expansion uses. Depth one needs no cycle guard. Deeper traversal waits on hardening
  finding A2 (R1-23).

## UI

Files: a new `frontend/components/explorer/data-list.tsx` beside `call-tree.tsx`, a new
`frontend/components/home/data-pane.tsx` beside `auth-pane.tsx`, and edits to
`frontend/components/endpoint/workspace-interior.tsx`,
`frontend/components/endpoint/workspace-store.ts` and
`frontend/components/home/overview-home.tsx`. The approved wireframe is the starting layout.

- Workspace left pane: a Calls / Data switch. The mode and the selected entity are in the URL as
  `pane=data` and `entity=<qualified type name>`, beside the existing `node`, `focus` and
  `expand` parameters (R1-26). One form only (E6).
- Data list states: populated, forwards only, no repository call found (with the v1 limits),
  verb not read, snapshot predates entity facts, fetch failed. A call with a verb and an
  undetermined entity is listed in a row labeled "entity not determined" (R1-25).
- Selecting an entity highlights its call sites with the existing trace highlight.
- Home page: `?view=data`, the entity by operation matrix. Each cell is a count of endpoints.
  `create-or-update` has its own column, and the columns follow the `EntityOperation` enum. The
  Notes column holds, per entity: "no detected delete call", "declared, no detected access", and
  "repository only, no annotation" (R1-15). A note is a statement about what was detected, so
  the service's unresolved counts (unknown verb, undetermined entity, in no endpoint flow) sit
  beside it (C6).

## Milestones

| | Milestone | Ships |
|---|---|---|
| M0 | Probe: on a fixture CPG, which node holds a repository's `extends` clause text. Already known from `joern-platform/target/petstore-export/export.json`: an inherited call is named by the receiver's interface (`com.acme.pets.PetRepository.save:<unresolvedSignature>(1)`) | a paragraph in the decision record |
| M1 | Fixture `spring-data-crud-matrix`, Scala raw facts on `sinks` rows, `SpringDataCrudMatrixConformanceTest`, export 2.14.0 | |
| M2 | Contracts 1.26.0, worker classification with both gate flags off, accounting, the stitcher's coverage section, `make schema` | |
| M3 | Storage projections, REST, MCP (with outbound edges on `endpoint_detail`), `summarize_entity_access` | |
| M4 | UI: Data list, home matrix | release 0.9.0 |
| M5 | Labeled set, scorer, the two bases through the gate | data-only release |
| M6 | Query reader | patch release |
| M7 | yas, then ICPC: base-interface repositories measured before and after, dirty-checking measurement | |
| M8 | Cross-service composition, cut to a TODO if M1 to M7 run long | |

Release 0.9.0 is the name-level train-ticket slice (R1-20). M5 and M6 change data and worker
logic and add no contract field, so a 0.9.0 reader reads their snapshots.

## Fixture goldens, by name (R1-18)

Each golden asserts its raw facts, its candidate operation and a detected-site count.

1. `inherited-find-by-id` 2. `inherited-save-read-origin` 3. `inherited-delete`
4. `derived-find-by-status` 5. `derived-delete-by` 6. `derived-count-exists`
7. `query-jpql-select` 8. `query-jpql-update-modifying` 9. `query-jpql-join-association`
10. `query-jpql-keyword-entity` 11. `query-native-table` 12. `query-named`
13. `query-mongo-json` 14. `base-interface-repository` 15. `save-constructed-no-lookup`
16. `save-guard-not-found-arm` 17. `save-guard-found-arm` 18. `save-guard-early-return`
19. `save-upsert-by-branch` 20. `save-parameter-callers-agree`
21. `save-parameter-callers-disagree` 22. `save-parameter-from-request-body`
23. `save-via-helper-wrapper` 24. `delete-then-save` 25. `two-calls-one-statement`
26. `save-in-lambda` 27. `dirty-checking-setter` 28. `forwarding-endpoint`
29. `repository-only-entity` 30. `unbindable-entity-chain`
31. `query-delete-with-subquery` (two accesses, two operations) 32. `repository-default-method`
33. `repository-custom-fragment` 34. `inherited-method-table` 35. `flush-not-an-operation`
36. `same-simple-name-two-packages`

## Tests

- Scala: `SpringDataCrudMatrixConformanceTest` over the fixture CPG.
- Cross-language: a Python golden over the Scala export, as `test_real_auth_matrix.py` does.
- Worker: table tests for each classification rule in both flag states, accounting totals, the
  `None` against empty-list distinction.
- Contracts: validators (a demoted fact has `create-or-update` and a candidate, a published
  single verb has no candidate), `summarize_entity_access` folds.
- Storage: the two projections against Mongo, with docs-examined equal to docs-returned.
- Orchestrator and MCP: route and tool tests, including an old snapshot and the check that one
  `create-or-update` save reads differently from one create plus one update.
- Frontend: state derivation for the six Data list states, the URL round trip, the matrix.
- Stitcher: `EntityCoverageSection` sums and the pre-phase `None` case.
- Regression contract for transitive repository detection (Q10, E7): on the nine existing
  fixtures the set of db-tagged call ids is unchanged, and existing goldens change only by added
  fields. `test_export_contract_compat.py` gains the 2.13.0 export without the `db` object.
- Vocabulary: the new enums join `test_worker_vocabulary_liveness.py` and the
  `unexercised_vocabulary` report, so a zero says whether it was measured (E8).
- Measurements, each committed as a script. The repository call-site oracle reads
  comment-stripped corpus source and never the export, because an export cannot reveal a call
  its producer omitted (C4). Its sites are reconciled with wadi's one by one. The scorer for the
  labeled set reads a stored export. Payload and latency are measured on the list route,
  `/entities` and `entity_usage`, before and after. The twenty-endpoint manual check per corpus
  stays, including endpoints where the oracle and wadi agree.
- Gates, as CI runs them (E9): `make lint`, `make typecheck`, `make test`, `make schema` and
  `make sync-compose` staleness, `sbt test` and `sbt assembly`, `make verify-frontend`,
  `make e2e`.

## Decision record and TODOs

After approval and before code: `architecture.md` gains §5.2.17 (the decision, its rationale and
the rejected alternatives, including the per-corpus gate scope and approaches A and C), a
Phase 2.10 entry in §11, the new shapes in §7, `entity_usage` in §8, and the Neo4j deferral
against §6. `TODOS.md` gains one entry per item under "Not in scope" plus: existence checks with
an early return, and the outside ground truth from the CLOSER 2023 authors.

## Open decisions for the user

1. The precision bar (number, point estimate or lower bound, minimum labeled members).
2. The scope of a gate verdict: release gate across labeled corpora (proposed) or per corpus.
3. Who labels the saves.
## Review record

### Phases

- Phase 1 (CEO): skipped by the user's choice on 2026-11-13 (decision D10). Not reviewed.
  Strategy, premises and alternatives were covered in office hours.
- Phase 2 (design): skipped by the user's choice (D10). Not reviewed. The wireframe was approved
  in office hours.
- Phase 2.5 (DX): skipped by the user's choice (D10). Not reviewed.
- Phase 3 (eng): ran on 2026-11-13 as a standalone `/plan-eng-review`. The `/autoplan` guard
  refuses its eng phase while the CEO phase is open, and no CEO close was faked, so that
  pipeline was ended and the eng review run by hand. Decisions were auto-decided on the six
  `/autoplan` principles, which the user chose, and are listed in the audit trail for one final
  gate.

### Scope challenge

Target: this plan. Report file: this file.

- **Complexity.** About 26 files change or are created across six components (Scala export and
  pass, `wadi-contracts`, `wadi-joern-client`, `wadi-storage`, worker, stitcher, orchestrator,
  MCP server, frontend), with four new modules [estimated]. The complexity gate trips. The
  feature list cannot shrink without dropping a decided surface, so the original arrangement
  stands, with one reduction: E1 removes the new export section.
- **What already exists.**
  - One `sinks` row per database call site, keyed by `call_id` (`export.py:344`). Reused (E1).
  - `sinks_by_node` groups several sinks per statement (`assembler.py:204`). Reused.
  - The list route's exclusion projection (`artifacts.py:113`), so `EndpointSummary` gains the
    summary by adding the field. Reused.
  - Coverage sections are built in the stitcher (`coverage.py:90`, `:227`). Reused.
  - The MCP server reads `wadi_storage` directly (`service.py` imports), so a pure function in
    the contracts package serves all three readers. Reused.
  - `EndpointDetailView.outbound` (`views.py:344`). Reused by the UI. Not available to MCP (C5).
  - `test_real_auth_matrix.py`, `test_export_contract_compat.py` and
    `test_worker_vocabulary_liveness.py` are the patterns for the new tests.
  - New code, not reuse: reading a repository's `extends` clause, the query reader, the save
    origin and guard facts, the Data list, the matrix.
- **TODOS cross-reference.** The P1 entry "A minor schema bump is not readable by the previous
  release" applies: a 0.8.2 reader fails on 1.26.0 documents. It stays where it is. The P1
  entry "The corpus measurements are not reproducible from the repo" is partly paid by
  committing the oracle and the scorer.

Reality rows:

```
REALITY: premise-table finding 11 premises, 8 verified, unverified=3 (extends-clause text source; ICPC db calls unmarked today; lambda-hosted db calls present in export.sinks) libs/wadi-joern-client/src/wadi_joern_client/export.py:344
REALITY: already-done pass no commit on origin/master since 2026-11-12 touches joern-platform, libs, services or frontend Makefile:29
REALITY: surface-check pass make lint, typecheck, test, schema, sync-compose, verify-frontend and e2e exist; endpoint_detail and endpoint_icfg exist; /entities, entity_usage and ?view=data are new Makefile:40
REALITY: binding-decisions pass no branch decisions on record; the plan follows Q1 to Q27 and the design's amendments docs/entity-access-plan.md:1
REALITY: numbers pass 36 goldens counted in this file; nine existing fixtures counted in joern-platform/fixtures; versions read from the contracts version module and the Scala export constant libs/wadi-contracts/src/wadi_contracts/version.py:9
REALITY: deferred-asks pass no linked issue docs/designs/entity-access.md:1
REALITY: pr-count finding no ship policy file, default one PR per wave; the plan implies four waves (0.9.0, M5, M6, M7 with M8), each with its own review and CI gate docs/designs/entity-access-implementation-plan.md:1
```

### Findings

Native findings are E1 to E9. Outside findings (Codex, completed) are C1 to C6.

| Id | Severity | Conf. | Finding | Evidence | Disposition |
|---|---|---|---|---|---|
| E1 | CRITICAL | 9 | A new `data_access` export section would be a second inventory of call sites the export already lists | `export.py:344` `class ExportSink`, `kind: str ... db \| http-client \| mq` | Accepted: nest a `db` object on `sinks` rows |
| E2 | INFORMATIONAL | 9 | Entity accounting was placed inside `AnalysisCoverage`, an in-CPG methods metric with a validator; the stitcher was not named as touched | `boundary.py:105`, `coverage.py:227` | Accepted: sibling field, stitcher added |
| E3 | INFORMATIONAL | 8 | The stitcher cannot report which gate flags were on | flags live in the worker | Accepted: worker records flag state |
| E4 | INFORMATIONAL | 7 | Nothing enforces "a rule change resets the flag" | design R1-13 | Accepted: rules version on each flag, test fails on mismatch |
| E5 | INFORMATIONAL | 6 | The name table omits `search*` and inherited methods such as `flush` and `saveAndFlush`. Medium confidence, from the Spring Data API and not from a repository line | plan rule 2 | Accepted: enumerate and pin by golden |
| E6 | INFORMATIONAL | 8 | `entity=<id or name>` is two ways to say one thing | plan UI section | Accepted: qualified type name |
| E7 | CRITICAL | 8 | Transitive repository detection changes which calls are tagged, with no regression contract for the nine fixtures | `SpringPacks.scala:687` `inheritsFromTypeFullName.exists(...)` | Accepted: regression contract in Tests |
| E8 | INFORMATIONAL | 8 | New enums are outside the vocabulary-liveness check | `test_worker_vocabulary_liveness.py` | Accepted |
| E9 | INFORMATIONAL | 9 | The Tests section named no CI gate | `Makefile:12` to `:83` | Accepted |
| C1 | CRITICAL | 8 | One entity and one operation per call cannot represent a query that deletes one entity and reads another | plan contract | Accepted: a site holds a list of accesses |
| C2 | CRITICAL | 9 | The export keeps only the simple class name, so `@Entity(name=)` matching is impossible and two same-named classes share an id | `WadiExport.scala:149` `"entity" -> typeDecl.name`, `ids.py:118` | Accepted: `type_full_name`, `jpql_name`, id from the qualified name |
| C3 | CRITICAL | 8 | A repository `default` method or custom fragment has a hand-written body; its name does not establish its verb | `SpringPacks.scala:695` tags every call owned by a repository type | Accepted: `implemented_in_project`, verb `unknown` |
| C4 | CRITICAL | 9 | The plan had the call-site oracle read the export, which cannot reveal calls the exporter omitted. This was my drafting error against design success criterion 4 | plan Tests section | Accepted: the oracle reads source |
| C5 | INFORMATIONAL | 9 | MCP `endpoint_detail` returns `Endpoint`, so a forwarding endpoint would stay unexplained there | `service.py:71` | Accepted: outbound edges added in M3 |
| C6 | INFORMATIONAL | 8 | "No endpoint deletes it" is a definitive negative over incomplete extraction | plan UI section | Accepted: "no detected delete call" with unresolved counts |

### Architecture

```
 Java source ──► Joern CPG ──► SpringDataSinkPass (transitive, Q10) ──► tags sink=db
                                   │
                    WadiExport: sinks[] rows (kind=db) + nested `db` raw facts     models[] rows
                    (repository, entity_type_text, method, query, save origin,     (+ type_full_name,
                     guard arm, implemented_in_project)                             jpql_name, storage)
                                   │ export 2.14.0
                                   ▼
        extraction worker: verb table + gate flags ──► EntityAccessSite[] on ICFG nodes
                │                                  ──► Endpoint.entity_access (summary)
                │                                  ──► DataModel records
                │                                  ──► ServiceBoundary.entity_access_accounting
                ▼ MongoDB (worker is the only writer of these four)
   ┌────────────┼──────────────────────────────┬─────────────────────────┐
   stitcher     orchestrator                   MCP server                frontend
   EntityCoverage   list + detail routes        endpoint_detail (+outbound)   Data list (6 states)
   Section          GET /snapshots/{id}/entities endpoint_icfg                home ?view=data
                    └── summarize_entity_access (wadi-contracts) ──┘ entity_usage
```

- **Paths.** Happy: site bound to entity and verb. Nil: `entity_access` is `None` on an old
  snapshot, and every reader says so. Empty: analyzed and no site, "no repository call found"
  with the v1 limits. Error: a failed fetch shows no claim. Each is in the plan.
- **Two shapes.** The new public surface is the composition. Shape 1 is one pure function in
  the contracts package over projected rows. Shape 2 is a Mongo aggregation in `wadi-storage`
  that returns the reverse view. Shape 2 moves the counting rule for `create-or-update` into a
  pipeline string and cannot serve the worker's own fold. Shape 1 hides more behind less and
  the rows are small after projection, so Shape 1 stands.
- **Red flags.** Hand-synced list: the matrix columns must follow the `EntityOperation` enum
  (applied to the UI section). Two ways to do one task: E1 and E6, both fixed. Split ownership:
  none, the worker writes all four entity facts and the stitcher writes the report.
- **Security.** One new read-only route and one new read-only tool, with the same exposure as
  `/auth`. No new mutation. No issues found.
- **Rollback.** The fields are additive, but an older release cannot read 1.26.0 documents
  (existing P1 TODO). Rolling back means analyzing again or dropping the snapshot.

### Code quality

No issues found beyond E5 and E6. The plan adds no shared helper other than
`summarize_entity_access`, which has three proposed callers (worker, orchestrator, MCP server)
and replaces three would-be copies.

### Tests

Frameworks: pytest (`make test`), sbt (`cd joern-platform && sbt test`), the frontend suite
behind `make verify-frontend`, and `make e2e`.

```
CODE PATHS (all proposed)                                USER FLOWS (all proposed)
[+] SpringDataSinkPass, transitive                       [+] Workspace Data list
  ├── [GAP] base-interface repository detected            ├── [GAP] switch Calls to Data, URL round trip
  ├── [GAP] nine fixtures: db call ids unchanged (E7)     ├── [GAP] select entity, call sites highlight
[+] WadiExport sinks[].db                                 ├── [GAP] forwards only
  ├── [GAP] entity_type_text bound / unbindable           ├── [GAP] no repository call found, with limits
  ├── [GAP] implemented_in_project (C3)                   ├── [GAP] verb not read
  ├── [GAP] save origin: read, constructed, parameter     ├── [GAP] snapshot predates entity facts
  ├── [GAP] guard arm: found, not-found, early return     └── [GAP] fetch failed shows no claim
  ├── [GAP] query facts: JPQL, native, named, Mongo      [+] Home matrix
  └── [GAP] 2.13.0 export without `db` still parses       ├── [GAP] columns follow the enum
[+] worker classification                                 ├── [GAP] cell lists its endpoints
  ├── [GAP] each rule, both flag states                   └── [GAP] notes carry unresolved counts (C6)
  ├── [GAP] one access per entity in a query (C1)        [+] MCP agent
  ├── [GAP] flag on for a stale rules version fails (E4)  ├── [GAP] [→E2E] entity_usage on a fresh snapshot
  ├── [GAP] accounting buckets sum to the total           ├── [GAP] old snapshot says it predates
  └── [GAP] None against empty list                       └── [GAP] forwarding endpoint lists outbound (C5)
[+] summarize_entity_access
  ├── [GAP] sites to summary, summary to usage
  └── [GAP] create-or-update never merges into create or update
[+] storage projections
  └── [GAP] IXSCAN, docs examined equals docs returned
[+] stitcher EntityCoverageSection
  └── [GAP] sums, and None for a pre-phase service
[+] whole stack
  └── [GAP] [→E2E] fixture through the real Joern container (make e2e)

COVERAGE: 0/30 paths tested (the code does not exist yet)  |  GAPS: 30 (2 E2E, 0 eval)
```

Every gap is named in the plan's Tests section or its goldens. Regression rule: E7 is the one
existing behavior at risk, and its contract is in the plan. No LLM or prompt change is in scope.
Test plan artifact: `docs/designs/entity-access-test-plan.md`.

### Performance

- `/entities` and `entity_usage` read one projected row per endpoint. For ICPC that is 804 rows
  [measured count from the project notes], each a few hundred bytes [estimated]. The filter and
  sort match `list_endpoints_for_snapshot`, whose index was audited in Phase 2.9.5.
- `list_data_models_for_snapshot` filters on `snapshot_id` alone. Whether `data_models` has an
  index that serves it is unknown. The storage test asserts IXSCAN, so a missing index fails.
- The list row grows by the summary. Its size on ICPC is unknown and is measured before the
  release, against the 2,479,867 B baseline from Phase 2.9.5 [re-measure before gate].
- The Scala pass adds one def-use query and one caller hop per save: 217 saves in train-ticket
  and 53 in ICPC [measured in the plan doc by ripgrep, comments not stripped].

No issues found that change the plan.

### Failure modes

| Path | Realistic failure | Test | Handling | Seen by user |
|---|---|---|---|---|
| Entity resolution | `extends` clause not readable from the CPG | golden `unbindable-entity-chain` | "entity undetermined", counted | yes, in the Data list |
| Name table | a `default` method named `findX` that writes | golden `repository-default-method` | `unknown` | yes |
| Gate | a rule edited after scoring | E4 unit test | build fails | developer |
| Old snapshot | `entity_access` absent | route and tool tests | "predates entity facts" | yes |
| Old reader, new data | 0.8.2 reads 1.26.0 | none | hard failure, existing P1 TODO; `wadi status` reports release skew | yes, as an error |
| Reverse view | reads full documents by mistake | storage test on projection | fails the test | no |
| Oracle | reads the export | fixed in the plan (C4) | n/a | n/a |

Critical gaps (no test, no handling, silent): 0.

### Decision audit trail

| # | Decision | Class | Principle | Rationale | Rejected |
|---|---|---|---|---|---|
| 1 | Skip CEO, design and DX reviews | user answer D10 | n/a | The user chose eng only | Full pipeline |
| 2 | Keep the feature list, original arrangement | mechanical | P1 | Every surface is a settled decision | Cutting a surface |
| 3 | E1: nest raw facts on `sinks` rows | taste | P4 DRY | One inventory of call sites | New `data_access` section |
| 4 | E2, E3: accounting as a sibling field, flags recorded by the worker | mechanical | P5 | Matches how coverage is built today | Extending `AnalysisCoverage` |
| 5 | E4: rules version on each gate flag | taste | P5 | Makes R1-13's reset rule mechanical | A written convention |
| 6 | E5, E8, E9: table pinned by golden, liveness, gates named | mechanical | P1 | Completes the test plan | n/a |
| 7 | E6: `entity=<qualified type name>` | taste | P5 | One form, readable, stable | The `dm_` id |
| 8 | E7: regression contract for the nine fixtures | mechanical | P1 | Existing behavior at risk | n/a |
| 9 | C1: a site holds a list of accesses | mechanical | P1 | A query can apply two operations | One access per site |
| 10 | C2: export qualified name and JPQL name; `dm_` id from the qualified name | taste | P1 | Needed by the query reader; removes a collision. Changes every `dm_` id once | Keep the id, disambiguate only collisions |
| 11 | C3: project-implemented repository methods read `unknown` | mechanical | P10 | The name proves nothing about a hand-written body | Trust the name |
| 12 | C4: the oracle reads source | mechanical | P1 | Restores the approved design | Export-based oracle |
| 13 | C5: outbound edges on MCP `endpoint_detail` | mechanical | P1 | The MCP surface must explain forwarders too | UI only |
| 14 | C6: notes say "no detected ..." with unresolved counts | mechanical | P10 | A detected absence is not an absence | Definitive wording |

User challenges: none. No finding asks to change a direction the user set.

Approval readiness: PASS for rows 2 to 14. They were auto-decided and then approved together by
the user's answer to D11 ("Approve and write the record") on 2026-11-13.

### Parallelization

| Step | Modules touched | Depends on |
|---|---|---|
| M0 probe, M1 fixture and Scala | `joern-platform/` | none |
| M2 contracts and joern client | `libs/wadi-contracts/`, `libs/wadi-joern-client/` | M1's row shape |
| M2 worker and stitcher | `services/extraction-worker/`, `services/stitcher/` | contracts |
| M3 storage, orchestrator, MCP | `libs/wadi-storage/`, `services/orchestrator/`, `services/mcp-server/` | contracts |
| M4 UI | `frontend/` | contracts (generated types), M3 routes |

Lane A: M0 then M1. Lane B: contracts, then worker and stitcher. Lane C: storage, orchestrator
and MCP, after contracts. Lane D: UI, after contracts, against a hand-made snapshot until M3
lands. Contracts are the shared module and go first, alone. Then B, C and D run in parallel.

## Implementation Tasks

Synthesized from this review's findings. Effort assumes the default ratios (features about 30x,
tests about 50x).

- [ ] **T1 (P1, human: ~1d / CC: ~30min)** — joern-platform — Nest `db` raw facts on `sinks` rows, no new section
  - Surfaced by: Scope challenge E1
  - Files: `joern-platform/src/main/scala/wadi/export/WadiExport.scala`, `libs/wadi-joern-client/src/wadi_joern_client/export.py`
  - Verify: `cd joern-platform && sbt test`, `uv run pytest services/extraction-worker/tests/test_export_contract_compat.py`
- [ ] **T2 (P1, human: ~1d / CC: ~30min)** — contracts — `EntityAccessSite` with a list of accesses; `type_full_name`, `jpql_name`; `dm_` id from the qualified name
  - Surfaced by: Outside voice C1, C2
  - Files: `libs/wadi-contracts/src/wadi_contracts/` (`icfg.py`, `datamodel.py`, `ids.py`, `endpoint.py`, `views.py`)
  - Verify: `make test-unit`, `make schema`
- [ ] **T3 (P1, human: ~4h / CC: ~15min)** — joern-platform — Export `implemented_in_project`; worker publishes `unknown` for those calls
  - Surfaced by: Outside voice C3
  - Files: `WadiExport.scala`, `services/extraction-worker/src/wadi_worker/assembler.py`
  - Verify: goldens `repository-default-method`, `repository-custom-fragment`
- [ ] **T4 (P1, human: ~1d / CC: ~30min)** — verification — Source-reading call-site oracle and the regression contract for the nine fixtures
  - Surfaced by: Outside voice C4, Tests E7
  - Files: a committed oracle script, `joern-platform/src/test/scala/wadi/`
  - Verify: oracle and wadi reconciled site by site on train-ticket; `sbt test`
- [ ] **T5 (P2, human: ~4h / CC: ~15min)** — worker, stitcher — Accounting as a sibling field with gate flag state; `EntityCoverageSection` in the stitcher
  - Surfaced by: Architecture E2, E3
  - Files: `libs/wadi-contracts/src/wadi_contracts/boundary.py`, `stitching.py`, `services/stitcher/src/wadi_stitcher/coverage.py`
  - Verify: `make test`
- [ ] **T6 (P2, human: ~2h / CC: ~10min)** — worker — Rules version on each gate flag, with the failing-build test
  - Surfaced by: Architecture E4
  - Files: `services/extraction-worker/src/wadi_worker/`
  - Verify: `make test-unit`
- [ ] **T7 (P2, human: ~3h / CC: ~15min)** — MCP server — Outbound edges and stitched state on `endpoint_detail`
  - Surfaced by: Outside voice C5
  - Files: `services/mcp-server/src/wadi_mcp/service.py`, the shared composition
  - Verify: MCP tool test on a forwarding endpoint
- [ ] **T8 (P2, human: ~2h / CC: ~10min)** — frontend — Notes read "no detected ..." with unresolved counts; matrix columns from the enum; `entity=<qualified type name>`
  - Surfaced by: Outside voice C6, Code quality E6
  - Files: `frontend/components/home/data-pane.tsx`, `frontend/components/endpoint/workspace-store.ts`
  - Verify: `make verify-frontend`
- [ ] **T9 (P2, human: ~2h / CC: ~10min)** — tests — Inherited-method table golden, vocabulary liveness for the new enums
  - Surfaced by: Code quality E5, Tests E8
  - Files: `services/extraction-worker/tests/test_worker_vocabulary_liveness.py`, the fixture
  - Verify: `make test`

### Completion summary

- Step 0: Scope Challenge — scope accepted as-is
- Reality rows: 7/7 applicable rows emitted, 3 unverified premises
- Architecture Review: 4 issues found (E1 to E4)
- Code Quality Review: 2 issues found (E5, E6)
- Test Review: diagram produced, 30 gaps identified, all proposed code
- Performance Review: 0 issues found
- NOT in scope: written (the plan's own section)
- What already exists: written
- TODOS.md updates: 0 new beyond the plan's own list; applied after the gate
- Failure modes: 0 critical gaps flagged
- Unresolved decisions: 3 in this review (precision bar, gate verdict scope, who labels)
- Outside voice: Codex, completed, 6 findings, all accepted
- Parallelization: 4 lanes, 3 parallel after contracts / 1 sequential
- Lake Score: N/A (no question was scored for completeness)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | skipped by user (D10) | not reviewed |
| Outside Review | Codex, plan review | Independent 2nd opinion | 1 | completed | 6 findings, 6 accepted |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES OPEN | 9 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | skipped by user (D10) | not reviewed |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | skipped by user (D10) | not reviewed |

- **OUTSIDE COVERAGE:** Codex, plan-review phase, completed, 6 findings (4 high, 2 medium), all accepted into the plan.
- **CROSS-MODEL:** No overlap. The native review found structure and test gaps (E1 to E9). Codex found four correctness gaps the native review missed (C1 to C4), one of them an error introduced when this plan was drafted (C4).
- **VERDICT:** ENG reviewed with every finding applied to the plan; eng review required to clear after the three open decisions are answered. CEO, design and DX not reviewed.

**UNRESOLVED DECISIONS:**
- The precision bar: the number, point estimate or lower bound, and the minimum labeled members per basis.
- The scope of a gate verdict: a release gate across labeled corpora (proposed) or per corpus.
- Who labels the saves.
