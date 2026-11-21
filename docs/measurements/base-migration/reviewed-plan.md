# Reviewed plan for the base migration

This is the plan that the base migration record in `docs/architecture.md` §11 was written from, kept as evidence. It is the text the owner approved on 2026-11-20: the plan body, then the requirements accepted during review, in the order they were accepted. A later requirement replaces an earlier one where they conflict. The record in `docs/architecture.md` is the binding text, and `amendment-trace.md` beside this file maps each requirement to it.

Item numbers in this file differ from the record from item 5 on. Here item 5 is the fold, 6 the edge shape, 7 the environment and 8 import. In the record item 5 is import, 6 the fold, 7 the edge shape and 8 the environment.

---

# Base migration: move wadi onto the target record model

Drafted 2026-11-19 from a three-round interview with the owner. The owner accepted every
recommendation. This file is the plan under review. The binding text will be a decision record in
`docs/architecture.md` §11 that amends "Direction and migration rules" of 2026-11-18.

## Goal

Move the existing application onto the record model of `docs/target-architecture-plan.md` with no
new feature. The static analyzer stays the only reader. The map that REST, MCP and the web UI
serve must come out the same. After the migration, each later piece (a config reader, a declared
reader, the access prober, the trace importer, the hub) is added without changing the base.

The owner's bar: the base is the foundation of a product for industry use and of a PhD thesis. It
must be shown correct by tests an outsider can rerun, on real corpora.

## What the migration is and is not

It is not a rewrite. The target plan keeps the analyzer, the stitcher, the orchestrator, MongoDB
and Neo4j. The migration changes the record model in the places where it assumes code is the only
source (`target-architecture-plan.md` §4.6):

| # | Assumption today | Where |
|---|---|---|
| 1 | An edge needs a static call site | `libs/wadi-contracts/src/wadi_contracts/stitching.py:68`, `libs/wadi-storage/src/wadi_storage/graph.py:269-297` |
| 2 | One source per edge | `stitching.py:92-97`, `services/stitcher/src/wadi_stitcher/matching/base.py:101-103` |
| 3 | One writer replaces the whole edge set | `libs/wadi-storage/src/wadi_storage/stitch.py:26-36` |
| 4 | A snapshot is one commit set with no environment | `libs/wadi-contracts/src/wadi_contracts/system.py:49-63`, `libs/wadi-storage/src/wadi_storage/mongo.py:68-103` |
| 5 | One merged environment per service | `services/extraction-worker/src/wadi_worker/appconfig.py:133-134` |
| 6 | Node and call-site ids depend on position or run | `services/extraction-worker/src/wadi_worker/assembler.py:461`, `libs/wadi-contracts/src/wadi_contracts/ids.py:108-110` |
| 7 | Discovery is Maven plus a root compose file | `services/extraction-worker/src/wadi_worker/boundary.py:350-360` |
| 8 | Endpoint existence carries no provenance | `libs/wadi-contracts/src/wadi_contracts/endpoint.py:535`, `views.py:278`, `:326` |

Assumptions 5 and 7 stay as they are. They belong to the config reader and to the rule packs.

## The change to the 2026-11-18 build order

The record of 2026-11-18 lands each record change with the first reader that needs it: the
sources list with the config reader (step 6), the optional call site with the trace importer
(step 10). It puts import at step 3.

This plan pulls the remaining record shapes into the migration and moves import to the end.

- Pulled forward: a sources list that holds one source, the fold as the only read path, the
  environment on the snapshot, an edge that does not require a static call site, and
  content-derived flow-graph node ids.
- Not pulled forward: the comparison rules of the five statuses. With one reader every fact reads
  "static only". The rules for confirmed, contested, observed only and declared only arrive with
  the reader that needs them.
- Import moves last because the bundle format is the one thing with a compatibility promise. It
  is fixed after every record shape is final, so no reader for an older bundle shape is needed.

The risk of pulling shapes forward is that no real second reader has tested them. The review of
2026-11-17 raised this. The answer is a wider shape spike (item 2) and a permanent test reader
(item 4).

## Sequence

Each item except the spike opens with its own decision record as a documents-only pull request,
and ships as a release with a committed measurement. The spike ships nothing.

1. **Step 1 as recorded, with four additions.** B1 (the URL slicer stops depending on wall-clock
   time) and B2 (the service id stops depending on a folder) land first. Then the scorer, ground
   truth and a committed baseline (#33). Then the fixes for facts known to be wrong: A5, #34, and
   the `bug` issues #26 and #28. Additions: (a) a repository that yields no service becomes a
   coverage-report finding that names what was searched (`pipeline.py:139` logs it today and the
   snapshot succeeds empty); (b) the endpoint collision count is reported on every corpus; (c)
   step 1 measures whether Joern's node ids repeat across two runs of one commit; (d) the
   canonical export, a full dump of the map in natural keys, becomes a make target. When step 1
   closes, the map is frozen.
2. **The shape spike.** Three throwaway readers on the petstore fixture: its OpenAPI document, a
   hand-written Kubernetes manifest and a hand-written trace file. One week. The branch is never
   merged. Its one output is a list of what the proposed shapes got wrong. Every shape record in
   items 3 to 7 is written against that list.
3. **Keys.** Each record stores natural keys beside its hashed id (service name, verb, route
   template, class and method). Flow-graph node ids stop depending on the run: method key, source
   anchor, ordinal. They still depend on position, as the call-site id does. If the collision count of item 1 is not zero, the disambiguator lands here.
4. **Origin and record sets.** One optional origin field on the envelope. Records stay keyed by
   snapshot, so storage reads do not change (D5, the "inside" option). A snapshot lists its
   members, and a restitch writes a new snapshot, so no write deletes a set that a published
   snapshot was built from. The snapshot lifecycle rules of the target plan's step 2 land here. A reader interface is defined (a job type, a
   collection, an adapter to the shared keys). The static analyzer is refit to it as reader one.
   A small test reader in `libs/wadi-testing` implements it and runs in CI.
5. **The fold.** A pure function in `wadi-contracts`. REST and MCP read the map only through it.
   Over one source it returns every fact as "static only" with the list of readers that covered
   it. Edge facts fold when the stitcher writes the edge set, because Neo4j is built from that
   set (plan §4.3).
6. **Edge shape.** The stored `StitchedEdge` carries a sources list in place of one provenance value. The views
   keep `provenance` and gain `sources`.
   `remote_call_id` becomes optional. Neo4j edges stop hanging off `RemoteCall` nodes only.
7. **Environment on the snapshot**, with one default environment (plan T2).
8. **Export per service and the import job**, with bundle format version 1. The proof is the
   two-repository test of `bundle-import-and-hub-plan.md` §9.
9. **The closing release.** Every exit test passes on every corpus. `architecture.md` gains a
   section that states what the base guarantees and what it does not.

## Rules while it runs

- **How a change is checked.** Each pinned corpus is analyzed with the previous release and with
  the new one, and the canonical exports are diffed. The export is written in natural keys and
  leaves hashed ids out, because ids change at B2 and at item 3. An unchanged map is the pass
  condition from item 3 on. A changed fact is opened and named in the release notes, or it is a
  defect.
- **No dual writes.** A snapshot is disposable (record of 2026-11-18), so a rollback is a revert
  and a re-analysis.
- **Versions.** Contracts take a major bump at each breaking record change. Wadi stays on 0.x.
  The bundle format gets its own version, starting at 1 in item 8.
- **Consumers hold still.** REST and MCP responses change only by additive fields. The frontend
  changes only by regenerated types and keeps one provenance chip.
- **New enforced rows in `CONSTRAINTS.md`**, added before item 3: no import between services
  (P1), one writing service per collection (P4), a read-side `schema_version` check that refuses
  a newer record with both versions named (#37), and identical canonical exports from two
  analyses of one checkout.
- **Review.** Every item gets the review by several independent reviewers before release. The
  owner reads every decision record, every release, and every change to a ground-truth file, the
  scorer, the CI configuration, `CONSTRAINTS.md` or the build order.
- **P4 at the database.** Separate Mongo users with per-collection write roles wait for the hub
  step, when a shared install exists.

## Corpora and ground truth

- Pinned corpora: `train-ticket-aitest` (commit `a84716f`, the only one on the owner's machine
  today), ICPC, one microSecEnD application, and yas. ICPC is treated as private until the owner
  says otherwise, so yas is the public corpus beside train-ticket.
- Ground truth is made without reading wadi's output, in natural keys. Two agents on different
  model providers label it. The owner rules where they disagree. A person checks a seeded
  random sample of 40 endpoints per corpus by hand. The agreement rate and the
  error count of ground truth are published beside wadi's score.
- The held-out set of 17 systems (T9) is not an exit condition of the migration. It starts once
  the scorer runs and must exist before the first reader that changes call edges.

## When the base is done

1. **Same map.** On every pinned corpus the canonical export of the closing release equals the
   export taken when step 1 closed, or each changed fact is opened and named.
2. **Determinism.** Two analyses of one checkout, on one machine and on two machines, produce
   identical canonical exports and identical content-derived ids.
3. **Split equals joint.** Two services analyzed apart and imported together stitch the way one
   joint analysis does.
4. **Additivity.** At the closing release a second test reader, written against the documented
   interface by an agent that did not write the base, lands with a diff confined to its own
   package and its registration.
5. **Failure.** Six cases each leave the previous snapshot readable and report a named reason:
   the worker is killed during extraction, Mongo drops during a write, an import is interrupted
   or rejected, two analyses start on one system at once, an older stack reads newer records, and
   Neo4j is wiped and rebuilt from Mongo. In the last case the rebuilt graph equals the original.
6. **Scale.** Read paths stay bounded at ten times ICPC (about 8,000 endpoints), reached by
   importing replicated bundles. Every hot query is an index scan.
7. **Rules as checks.** The four new `CONSTRAINTS.md` rows are enforced in CI.
8. **Review and approval.** The independent reviewers have reported, the measurement is
   committed under `docs/measurements/`, and the owner approves.

After that a breaking change to a record shape needs a decision record, a major contracts bump
and a bundle format bump. An additive change stays a minor bump (§7).

## Out of scope

Any new reader. The comparison rules of the five statuses. The identity profile, the credential
broker and the access prober. The rule engine and rule packs. Discovery beyond Maven, including
Gradle (#5). The hub's authentication. Database-level write roles. Entity-access M5, M7 and M8,
with both gate flags left off. Distributed execution, sharding and a job queue change. Image size
and the 10 GB memory limit.

## What exists today

- About 1,700 test cases by grep (1,177 Python, 335 frontend, the rest Scala), 11 fixtures, the
  construct goldens, the auth goldens, the bytecode oracle and the conformance e2e.
- `e2e/test_baseline_snapshot.py`, an opt-in harness that analyzes a benchmark repository through
  the real Joern container and can keep each service's export.
- `GET /snapshots/{id}/export`, the whole-snapshot export.
- `make measure-repository-sites`, `reconcile-repository-sites`, `blind-sample` and
  `blind-score`, the measurement tools of the entity-access run under
  `docs/measurements/entity-access/`.
- Zero cross-service imports and zero database drivers outside `wadi-storage`, by convention.
  No check enforces either.
- No scorer, no ground-truth file, no `decision` label on GitHub.

## First pull request

A documents-only change to `docs/architecture.md` §11: a decision record that amends the build
order with the content above, in the document's format (decision, rationale, rejected
alternatives). With it: the `decision` label, and one issue per open decision that blocks a
migration item. The status table in §2 of `target-architecture-plan.md` is updated. `CLAUDE.md`
"How the migration runs" is updated to match.

## Open points

- Whether ICPC's source can be shared with thesis examiners.
- Which microSecEnD application is the third corpus.
- T3 of the plan (fold computed or stored) is taken as recommended: edge facts at stitch time,
  the rest at read time.
- D5 of the bundle plan (how the origin is stored) is taken as suggested: one optional field on
  the envelope. The spike can overturn it.

<!-- autoplan-accepted:ceo -->
- E0. The amendment record states that it overrides the sentence "When the order may change" of the 2026-11-18 record, and sets two new checkpoints where the order is reconsidered: after the shape spike reports, and after item 8 (import) passes or fails. Verification: the amended text is read against `docs/architecture.md:1269` in the documents-only pull request.
- E1. The shape spike also runs an import feasibility probe: two services of the `petstore-system` fixture are analyzed apart, their whole-snapshot exports are merged by hand, the stitcher runs on the merged set, and the edge set is compared with the joint analysis. The spike's output list records every difference. If the edge sets differ for a reason the record shapes cannot fix, the order is reconsidered at the first checkpoint before item 3 starts.
- E2. The canonical export has a completeness test: it walks every field of every contract model that a snapshot stores and fails when a field is neither written to the export nor named on an exclusion list with a reason. Hashed ids, timestamps and run ids are the expected exclusions.
- E3. The export diff and the scorer each have a mutation test with three seeded changes to a stored fixture snapshot: one stitched edge removed, one `authenticated` claim flipped, one route template renamed. Each tool must report all three. The test fails if any seeded change passes unreported.
- E4. Every committed measurement under `docs/measurements/` records the wadi version, the wadi-joern image digest, the corpus commit, and the command that produced it.
- E5. The guarantee section that item 9 adds to `docs/architecture.md` has a "threats to validity" subsection: corpus selection, ground-truth labeler error, and what a synthetic test reader cannot show about a real one. It states that the stitcher's join rules per source are outside the additivity guarantee.
- E6. The fold has property tests for three laws: the result does not depend on the order of reader record sets, folding an already folded input changes nothing, and adding a record set never removes a value that was present.
- E7. The snapshot and job lifecycle has a stateful property test that generates sequences of analyze, import, restitch, job failure and worker restart, and asserts after every step: at most one unfinished snapshot per system, a stale unfinished snapshot is marked failed, and the current map is always a succeeded snapshot that stays readable.
- Determinism gate (from premise P3). Item 2 does not start until two analyses of `train-ticket-aitest` at `a84716f` on one machine produce identical canonical exports. If Joern's output order varies between runs, the canonical export sorts and normalizes it, because Joern stays stock (P5).
- The first pull request updates `AGENTS.md` together with `CLAUDE.md`, and `diff <(tail -n +4 CLAUDE.md) <(tail -n +4 AGENTS.md)` is empty.
- Numbers in the plan carry their source: 1,177 Python and 335 frontend test cases are grep counts, the Scala count is an estimate, 804 endpoints for ICPC comes from §5.2.12, and `a84716f` is `git rev-parse` on the owner's machine.
- Spec review, round 1 (2026-11-19). The bullets below were accepted from its findings. Where one conflicts with a bullet above, the later bullet governs.
- Step mapping. The amendment record carries a table from the steps of 2026-11-18 to this plan's items: step 1 is item 1; the shape spike is item 2; step 2 is item 4; step 3 is item 8, except its two id changes; the sources list of step 6 and the optional call site of step 10 are item 6, as shapes only; steps 4 to 11 keep their relative order after item 9. The call id that hashes its URL without user name, password and query string (#27) lands in item 3. One edge id per outcome of a call lands in item 1, because it is the fix for #26.
- Superseded sentences. The amendment record lists every sentence of the 2026-11-18 record it replaces: build-order rows 2, 3, 6 and 10, the shape spike paragraph, "one promise starts at step 3" (it now starts at item 8), the review assignment by step, "alongside steps 2 and 3", and the two "not decided" questions on the owner's read and on review depth, which the owner settled in the interview (Q6).
- Checkpoints, replacing the two named in E0. The order is reconsidered at three points: after the shape spike reports, when the gate experiment reports, and after item 8 passes or fails.
- Snapshot lifecycle. Item 4 builds the lifecycle rules of the target plan's step 2 (`target-architecture-plan.md:1334-1347`): at most one unfinished snapshot per system, a stale unfinished snapshot is marked failed, a read of a pending or running snapshot returns its status and no records, an analysis carries the members it does not replace, and a restitch makes a new snapshot with the same members. Today `app.py:280-314` has no guard against two analyses and `app.py:442` puts a succeeded snapshot back to running on restitch. The stateful test of E7 lands with item 4 without the import action. Item 8 adds the import action to it.
- The fold over more than one reader. The fold keeps every reader's value with the reader's name, for each fact. A fact that one reader covers reads "static only". A fact that more than one reader covers reads "not compared", with the reason that no comparison rule exists yet, until the reader that needs a rule brings it. Item 5's decision record fixes the list of facts the fold returns: endpoint existence, the authorization claim, the request shape, the response shape, declared statuses, entity access, and each call edge.
- Fold laws, replacing the wording of E6. The laws are stated on the list of record sets the fold receives: any order of the sets gives the same result, passing one set twice gives the same result as passing it once, and adding a set never removes a value another set supplied.
- Fold layering. Storage keeps projecting and bounding in Mongo, as the list routes of §5.2.15 do, and the fold runs on the projected records. A scale check runs at item 5 with a loader in `libs/wadi-testing` that writes renamed replicas of a real snapshot through the storage API, and again at item 9 through imported bundles.
- Canonical export format. Item 1's decision record fixes it: one sorted list per fact class, keyed by natural key; a flow-graph node is identified by its method key, source anchor, construct kind and ordinal; an edge by caller service, caller anchor, target service name, target endpoint key and outcome; no source text, hashed id, timestamp or run id. The export carries its own schema version, frozen at 1 when item 1 closes. Each later diff runs over the fields of version 1. Each release lists the fields it added and the mapping for any field it replaced, such as `provenance` to `sources`.
- Order inside item 1: the canonical export with its completeness and mutation tests; an export of each pinned corpus on 0.9.2; B1, then B2, each with its diff opened; the determinism gate; the scorer, ground truth and the baseline; the fixes, each shown wrong before and right after; the freeze.
- Collisions and the natural key. If the endpoint collision count is not zero on any corpus, the natural key of a collided endpoint adds the handler's class and method, in the canonical export and in ground truth, from item 1 on. The id form changes in item 3.
- Scorer scope. The scorer reports precision, recall and F1 for these fact classes: endpoints (verb and route template), the authenticated claim, roles and authorities, service-to-service edges, endpoint-to-endpoint edges, and entity access per endpoint including labeled saves, which is the requirement of Phase 2.10 M5. It enters `CONSTRAINTS.md` under "Measured, not yet enforced" when item 1 ships and under "Enforced with numbers" when item 4 ships.
- Upgrade, a seventh failure case. A newer stack that reads records of an older major contracts version returns a typed error that names both versions and tells the reader to re-analyze. It never serves those records and never crashes.
- Private corpus. The wadi repository is public. For ICPC the repository holds only the hash of each canonical export, the count per fact class and the scores. Its exports and its ground truth stay on the owner's machine. For the public corpora the repository holds hashes, counts and scores, and the full canonical exports are attached to the GitHub release. Where an exit test says "every pinned corpus", the evidence for ICPC is hash equality.
- ICPC labeling. ICPC source goes to no model provider beyond those the owner already uses on it, unless the owner consents in writing. By default both ICPC labelers run on the provider already in use, with no shared context.
- Determinism, one definition, replacing the one-machine wording above. Two analyses of one checkout produce byte-identical canonical exports and identical content-derived ids (service, endpoint, method, call, edge and flow-graph node ids). System, snapshot and job ids are run ids and are excluded. The gate before item 2 needs two runs on one machine and one run on a second machine with a different operating system and checkout path.
- `CONSTRAINTS.md` rows, with checker and schedule. Import boundaries: `uv run lint-imports` (import-linter, a new development dependency), at task end and in CI. One writer per collection: a test in `libs/wadi-storage` that maps each collection to one writing package, where a test reader writes only its own collection and the worker writes imported records; at task end and in CI. Schema version: a unit test and a Mongo integration test of the typed error; at task end and in CI. Determinism: `make canonical-export` run twice with a byte comparison; at the release checkpoint, beside `make e2e`. The file's sentence "adds no new tool" is updated in the same owner-approved change.
- Item 7 in full. The environment is one string field on the snapshot, named `default` when none is given. It is in no key and no index. It appears once, in the header of the canonical export. Test: a snapshot created with another environment name reads back with that name through REST and MCP.
- What the test readers emit. Each test reader writes one endpoint record whose key matches an existing endpoint, one whose key matches none, and one call edge with no static call site. The tests assert that all three are stored, are served through the fold with their sources, and that the edge is in Neo4j. This is what exercises item 6.
- The probe needs a fixture split. `joern-platform/fixtures/petstore-system` is one repository with a root pom (`bundle-import-and-hub-plan.md:825-828`). The probe's first task splits it into two checkouts with `common` as a sibling library. The spike's time box becomes eight working days.
- Real inputs for the spike. Each spike reader reads at least one real artifact from a pinned public corpus where one exists. `train-ticket-aitest` has compose files and an OpenTelemetry collector config, and no Kubernetes manifest and no OpenAPI document. yas is checked first for Helm charts and a generated OpenAPI document. Where no real artifact exists, the spike's output list says the shape was tested on a hand-written input only.
- Item 8's corpus. `train-ticket-aitest` at `a84716f`, split into two checkouts by a committed script. It has no root pom and each `ts-*` service is its own module. ICPC is added if its repositories call each other.
- Prerequisites before item 1's decision record merges (`architecture.md:1280`): all four corpora are named and pinned by commit, and a machine with at least 10 GB for Docker is available for ICPC. The owner's Mac gives Docker 5.78 GiB today (`docker info`). Each release check costs two analyses per corpus.
- Environment on a measurement, replacing the image digest of E4. A measurement records the local image id, the wadi commit, the Joern pin, the corpus commit and the command. The registry digest is added to the release notes after the tag publishes the image.
- Scale thresholds. At ten times ICPC each per-service and per-endpoint read answers within twice its time at one times ICPC, each system-wide read (graph, coverage, authorization view, entities) answers in under 2 seconds at the 95th percentile, and every query examines as many documents as it returns. The one-times numbers are measured in item 1. A replica is renamed by a service-name prefix applied to its services and to the hosts its calls name, so its edges stay inside the replica.
- Corpora count. Ground truth is labeled for all four corpora. yas is the fourth by the owner's decision (Q8), which adds one labeling pass to the three the record names.
- The first pull request also files the two deferred items as issues: the TLA+ model (P4, `area:infrastructure`) and the public benchmark comparison (P3, `area:verification`).
- Spec review, round 2 (2026-11-19). The bullets below were accepted from its findings and govern over anything earlier.
- "Same map" covers what is served. The canonical export has three parts: the stored records, the served views, and the Neo4j graph. The served views are the normalized REST and MCP responses of every list and detail read (services, endpoints, endpoint detail and flow graph, remote edges, system graph, authorization view, entities, coverage), for every service and endpoint of the corpus. The Neo4j part lists every node and relationship in natural keys. The completeness test of E2 covers the view models too. Exit test 1 compares all three parts.
- Status of a fact that one reader covers. Each reader declares its kind. A fact that one reader covers reads "single source" with the reader's name and kind. It reads "static only" only when that reader is the static analyzer. The names "declared only" and "observed only" arrive with those readers.
- How a fact with no static record is served. Item 5's decision record chooses the view form. The default is an additive list beside the existing one, so every existing view field keeps its type. A test reader's unmatched endpoint belongs to an existing service, named by its canonical service name.
- Named exceptions to "additive only". In item 6, `RemoteEdgeItem.remote_call_id` and `RemoteEdgeItem.mechanism` (`views.py:49`, `:52`) become nullable, and the frontend gains a null guard where it reads them. This is the one frontend code change beyond regenerated types, and the release notes name it.
- The CLI holds still too. `wadi restitch --wait` follows the snapshot id the restitch route returns (`cli/src/wadi_cli/main.py:951` polls the id it was given today). Item 7 adds an optional environment to the analyze request and one CLI option for it. Item 8 adds the export-per-service and import commands of the bundle plan's section 5.
- Lifecycle, in full. The whole of `target-architecture-plan.md:1334-1347` governs item 4, including the success rule, "the current map is the succeeded snapshot admitted last", replacing a member only on a successful extraction, removing one only on affirmative evidence, restitching only the newest snapshot whose filling jobs succeeded, and the record copy job that the "inside" option needs. No snapshot is deleted automatically during the migration. Item 4's measurement records the stored bytes per restitch and per carried member. If that cost is too high, the "beside" option is reconsidered at the next checkpoint.
- ICPC evidence. The published hash is taken over the version-1 fields of the canonical export. When an ICPC fact changes, the repository names the change by a count per fact class, and the members are listed in a file the owner holds.
- The amendment record's own format. It lists its rejected alternatives: keeping the order of 2026-11-18, pulling the comparison rules of the statuses forward too, keeping import at step 3, dual writes, and a second build beside the first. It restates that the gate experiment starts once the scorer runs and reports before the rule engine step.
- Where the constraint rows and the version check land. The new `CONSTRAINTS.md` rows and the read-side schema version check land in item 1, after the determinism gate. Item 1's decision record amends §7 with the refuse-with-both-versions rule (#37). The seventh failure case is tested there. The writer map of the one-writer row is amended at item 4 (the test reader) and at item 8 (imported records), each with the owner's approval.
- The determinism gate before item 2, narrowed. It compares the canonical export and a sorted manifest that maps each natural key to its service, endpoint, method, call and edge id. Flow-graph node ids join the manifest at item 3, when they stop depending on the run.
- Exit test 4, made meetable. Item 4 adds one job type, `read`, that carries the reader's name, and one reader registry. Index creation, the writer map, the export's field classification and job dispatch all derive from a registry entry. A new reader's diff is then confined to three places: its own package, one new module in `wadi-contracts` for its record models with the regenerated schemas and types, and one registry entry. Exit test 4 checks exactly that.
- Superseded sentences, a minimum and not the whole list. The amendment is written by reading the 2026-11-18 record sentence by sentence. Beyond the sentences already listed, it replaces row 1's corpus count, the references to step 3 in rows 4 and 11, the "Inside step 1" paragraph, and the two "Not decided" sentences on the identity order and the third corpus. `CLAUDE.md` says the target plan governs; the amendment adds that where it differs from the plan's sections 4.7 and 15, the amendment governs.
- Corrected counts. Exit test 7: five new rows, four enforced in CI and the determinism row at the release checkpoint. Exit test 5: seven cases, of which six leave the previous snapshot readable and the seventh returns the typed error.
- ICPC and the second machine. ICPC's second determinism run happens on a machine the owner controls. The public corpora may use a cloud machine. The second machine is a prerequisite beside the 10 GB machine.
- A correction to "What exists today". `libs/wadi-testing/src/wadi_testing/fixtures.py:82` and `:156` import `pymongo` and `neo4j`, so database drivers exist outside `wadi-storage` in the test fixtures. The import-boundary row allows that file by name. The test readers and the scale loader write only through the `wadi-storage` API.
- Entity-access M5, precisely. Out of scope: the run that scores the two bases and any change to the two gate flags. In scope: the scorer's entity-access class and its labeled saves.
- The spike's input. The spike's first task writes a draft-shapes file on the spike branch from sections 4.4 to 4.7 of the target plan and section 5 of the bundle plan. That file is what the three readers and the probe test. The petstore fixture has no OpenAPI document today, so the spike generates one with springdoc or writes it by hand, and the output list says which.
- The test reader, in order. In item 4 it writes endpoint records, as a `read` job inside the extraction worker (T4 as recommended). In item 5 its tests add the fold assertions. In item 6 it adds the edge with no static call site. It is registered only in test configuration and never in a shipped image.
- Extent of ground truth. Endpoints, the authenticated claim, roles and authorities, and service-to-service edges are labeled for every handler of each corpus. Endpoint-to-endpoint edges and entity access are labeled on a seeded sample, with the sample size and the confidence bound published. The measurement names the person who did the hand check.
- Item 8's content. Bundle format 1 covers sections 5.1 to 5.5 of the bundle plan and the tests of its section 9, including the round trip and importing the same bundle twice. Whether boundary-only bundles (section 5.6) are in version 1 is decided in item 8's record. The open decisions of that plan's section 11 are filed as `decision` issues that block item 8.
- The edge key in the canonical export. An edge is keyed by caller service, caller anchor, the call's URL template without user info and query string, target service name, target endpoint key and outcome. An edge with no static call site is keyed by its reader's name and that reader's own record key. Item 1 also reports the count of service-name collisions per corpus.
- Scale, how it is judged. Both scales are measured on the same release, at item 5 and at item 9. A release is blocked when a query examines more documents than it returns, or when a read is more than 1.25 times slower than on the previous release at the same scale. The absolute thresholds stay as targets. A miss that the previous release also shows is recorded with its cause and filed as an issue.
- Replicas for the scale test. Each replica gets its own repository identity key, and the loader recomputes every id and every reference from that key with the id functions of `wadi-contracts`. A name prefix alone would collide on the unique indexes (`mongo.py:68-95`), because a service id holds no service name (`ids.py:87-95`).
- Item 8's split. The `train-ticket-aitest` checkout has no `ts-common` directory and no root pom (`ls` on the owner's machine), so the split script moves two disjoint sets of `ts-*` directories into two repositories. The joint baseline analyzes those same two repositories as one system, so edge ids can agree (`bundle-import-and-hub-plan.md:829-830`).
- Spec review, round 3 (2026-11-19). The bullets below were accepted from its findings and govern over anything earlier. No fourth pass re-verified them.
- The stored edge keeps `provenance`. In item 6 the stored `StitchedEdge` gains `sources` and keeps `provenance`, and a validator requires `provenance` to equal the value derived from `sources`. `GET /snapshots/{id}/export` streams that model (`services/orchestrator/src/wadi_orchestrator/export.py:51-52`), so the route changes only by an added field. This replaces "in place of one provenance value".
- A read of a snapshot that has not succeeded. REST answers 409 with a typed body that holds the snapshot's status and a reason. MCP returns the same typed result. The frontend shows that status in its existing error state. This is a third named exception to "additive only", beside the two nullable fields, and the release notes of item 4 name it. Today only the export route checks for a succeeded snapshot (`app.py:359`).
- The base fold returns sources and no status. For each fact the fold returns the list of sources, each with the reader's name, the reader's kind and its value. It returns no status field. All five statuses of the target plan's section 4.4 arrive together with the first comparison rule, in the reader step that needs it. This replaces the "static only", "single source" and "not compared" wording above. The amendment governs over sections 4.3 and 4.4 of the target plan on this point and lists them among the superseded text.
- Item 5 and edges. In item 5 edges pass through the fold unchanged. Folding edge sources at stitch time starts in item 6, when the sources list exists.
- The five new `CONSTRAINTS.md` rows and when each runs: import boundaries, in CI; one writer per collection, in CI; the schema version check, in CI; determinism, at the release checkpoint; the scorer's no-regression rule, at the release checkpoint, measured from item 1 and enforced from item 4.
- The writer map is data. The one-writer row is written once. The test derives its map from the reader registry, so a new reader changes the registry and not `CONSTRAINTS.md`. This replaces "amended at items 4 and 8 with the owner's approval". A new reader still needs its own decision record.
- Job types. `extract` stays the static analyzer's job type. `read` carries the name of any other reader. The copy job of item 4 and the import job of item 8 get their own types. A reader may own several collections, as the static analyzer does. Item 4's record fixes where the registry lives.
- Two test readers, two paths. The permanent test reader of item 4 keeps its record models in `libs/wadi-testing` and registers through the registry's public call in test configuration. The second reader of exit test 4 uses the production path: a registry entry in the shipped module and a module in `wadi-contracts`. Its pull request is opened, must pass CI, has its diff measured, and is closed without merging, so no test model enters the shipped schemas. It emits the three record kinds listed above and its diff touches no stitcher file.
- Scorer abstentions. A withheld claim, a denied route, an unreadable `{?}` rule and an undetermined edge are scored as a third outcome, abstained, reported beside correct and wrong. They count in neither precision nor recall.
- Mutation test, extended. Besides the three seeded changes in stored records, the test seeds one change that appears only in a served view and one that appears only in the Neo4j part, and requires the diff to report both.
- The bundle promise has an artifact. Item 8 commits one version-1 bundle of the fixture as a golden file, and a test imports it on every later release.
- What the version check refuses. The check applies to artifact records. System, snapshot and job records stay readable across versions, so the stack can still list snapshots and start the re-analysis it asks for.
- Scope of the determinism gate. The gate before item 2 covers every pinned corpus that is on a machine by then, and at least `train-ticket-aitest` and yas on two machines. The constraint row runs on the `petstore-system` fixture at each release checkpoint. The corpora are compared in each item's measurement.
- Where the spike's output lives. The list is committed on `master` at `docs/measurements/base-migration/shape-spike.md`. The spike's code stays on its branch.
- Decisions taken as recommended, and where each is settled: T4 and D5 in item 4's record, T3 in item 5's record, T2 in item 7's record. Each is filed as a `decision` issue in the first pull request and closed by that record.
- Where the canonical export runs. It runs inside the compose network through `wadi-storage`, as a module in `libs/wadi-testing` behind `make canonical-export`. It adds no public route.
- Hardware, in full. Exit test 2 on ICPC needs two machines the owner controls, each with at least 10 GB for Docker. The two machines may hold different image ids, because an arm64 and an amd64 image differ; they must hold the same wadi commit and the same Joern pin. The owner has one Mac at 5.78 GiB today, so this is an open point for the owner.
- The owner's adjudication load. After the first corpus the measurement records how many disagreements the owner ruled on. If a corpus exceeds 50, the owner rules on a seeded sample of 50, a third labeler settles the rest, and the measurement says so.
- Effort correction. The canonical export of E2 was estimated S. With the served views and the Neo4j part it is M to L.
- CEO voice and sections (2026-11-19). The bullets below were accepted from the independent CEO review and from Sections 1 to 10. Five larger changes it proposed are User Challenges UC1 to UC5 and are not applied.
- The goal, reworded to what is guaranteed. After the migration a later piece adds its own records, one registry entry and its join rule in the stitcher. It changes no existing record shape, no read path and no existing view field. The plan no longer says a piece is added "without changing the base".
- Kill criteria for the spike. Before the spike runs, the amendment names the defects that send a shape back to "lands with its reader": a shape that a real artifact cannot be mapped onto without losing a value, a shared key that two real sources compute differently, and a difference in the import probe that record shapes cannot fix. A shape for which the spike finds no real artifact is reported as untested, and the owner decides at the spike checkpoint whether it stays in the migration.
- Effort and a stop rule per item. Each item's decision record states an effort estimate. When an item passes twice its estimate, the order is reconsidered before more work is done on it.
- The fold is plumbing. The plan describes the base fold as the single read path that groups records by fact and lists their sources. It makes no claim about comparison. The three property tests stay.
- "Same map" on systems wadi was not tuned on. From item 3 on, each release also diffs canonical exports on the 17 microSecEnD applications. This needs no ground truth. The guarantee section says the base was shown on Java, Spring and Maven systems only.
- Labeler caveat. Agreement rates are published per corpus. Where both labelers ran on one provider, the measurement says so.
- One clean text. The amendment record in `docs/architecture.md` is written as one consolidated text from this plan and its accepted list. No "later bullet governs" wording reaches the repository.
- Framing. The guarantee section states the claim as per-endpoint completeness with evidence for each fact, and names runtime service maps as existing work the base does not compete with.
- Copy job failure. A copy job that fails part-way fails the new snapshot and leaves the source snapshot untouched. The lifecycle test injects that failure.
- Atomic lifecycle write. The one-unfinished-snapshot rule is a single conditional write in Mongo. The lifecycle test runs both completion orders of two racing analyses, and of an analysis racing a restitch.
- No third matcher. The scorer and the canonical export match routes with `simplify_uri` and the stitcher's path matcher. They add no new URI matcher.
- Job logs. Each job logs its record origin once, and the copy job logs the records and bytes it copied and how long it took.
- Release notes. Each item's release notes say that snapshots must be re-analyzed after upgrading.
- Import size. Item 8's decision record sets a size limit for an uploaded bundle.
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- One error model. Item 1 defines one problem-details model in `wadi-contracts` (RFC 9457 shape) with a stable `code`, a doc anchor, the fix, the recovery with its side effects, and caller-safe context. Every error path this migration adds uses it: snapshot not ready, version refusal, analysis in progress, restitch refused, copy failed, import rejected, import interrupted, unknown reader. The CLI maps these errors by code and prints the fix. An error-code page under `docs/` holds the anchors.
- MCP failures are failures. An MCP tool that cannot serve a snapshot returns `isError: true` with the same code, the snapshot's status and the next call to make. It never returns an empty result for a snapshot that has not succeeded.
- What the 409 covers. The not-ready refusal applies to artifact and view reads only. The snapshot record, its job records, its job errors and its coverage findings stay readable for a running or failed snapshot, because `wadi analyze --wait`, the frontend's poll and `wadi coverage <id>` after a failed restitch depend on them (`cli/src/wadi_cli/main.py:959`).
- Two version refusals. An older stack that meets newer records says to upgrade wadi. A newer stack that meets older records says to run `wadi analyze` on the system. Each has its own code, and both state that nothing was changed.
- The analysis-in-progress refusal names the running snapshot's id and the command that follows it. The stale threshold is stated in item 4's record and is a `WADI_*` setting.
- A wait has a bound. A job whose type or reader no worker knows fails when it is enqueued. A sweeper marks an unclaimed job's snapshot failed after the stale threshold. `--wait` gains `--timeout`.
- Messages state retry safety. The import-interrupted, copy-failed and storage-dropped errors say that the new snapshot failed, that the previous map is untouched, and that the same command can be retried.
- The restitch refusal names the snapshot that can be restitched.
- Zero services in every repository. When every repository of a system yields no service, the snapshot fails with a named reason that lists what was searched and links #5. When only some repositories yield none, the snapshot succeeds, the coverage report carries the finding, and `wadi analyze` prints it on stderr when it ends. This replaces "the snapshot succeeds empty" for the all-empty case.
- The origin carries no secret and no machine path. A record's origin never holds URL user info or an absolute local path. A test asserts both on a local-path analysis.
- The ground-truth file is validated before scoring. A malformed or duplicate key is reported with its file and line and is never scored as a miss.
- Names. The test artifact is called the canonical map, to keep it apart from the whole-snapshot export route, the bundle and the Joern export. The commands are `make canonical-map`, `make canonical-diff A= B=`, `make score CORPUS= TRUTH=` and `make reproduce CORPUS=`. `canonical-diff` exits 0 when the maps are equal, 1 when they differ and 2 on an error, prints one line per changed fact in natural keys, and offers JSON output. A determinism failure prints the differing keys.
- One version table. The amendment record holds one table of the four version numbers a reader meets: contracts, the Joern export, the bundle format and the canonical map schema.
- Reproduction. `docs/measurements/base-migration/README.md` gives the copy-paste sequence, the expected hash and the measured duration for each corpus. `make reproduce CORPUS=petstore-system` is the short first step. The duration is measured once on a clean machine and committed. `train-ticket-aitest` is named as the corpus that runs in under 6 GB. The guarantee section says the ICPC evidence cannot be rerun by an outsider.
- The reader guide. Item 4 ships `docs/writing-a-reader.md` with the three-place diff as a worked example and updates the playbook in `docs/architecture.md` §10. The diff of the closed second-reader pull request is committed under `docs/measurements/`. Exit test 4 records how long that reader took and what its author read beyond the guide.
- Restitch output. `wadi restitch` prints the old and the new snapshot id, and `--json` carries both. The frontend navigates to the new id. This is a fourth named frontend change, beside the null guard and the not-ready state.
- MCP descriptions. Items 5 and 6 update the MCP tool descriptions for the fields that become nullable and for the list of facts with no static record, and each item's measurement shows the MCP tool exercised.
- The environment option. Its help text says what an analysis under another environment name does to the current map. `wadi snapshots` shows each snapshot's environment. The name is validated for characters and length. Item 7's decision record settles whether the current map is kept per environment.
- The bundle size limit is a `WADI_*` setting, and a rejection states the limit and the bundle's size.
- Deferred, filed as issues with the first pull request: `wadi cancel <snapshot>`, `wadi snapshots rm`, a bulk re-analysis on upgrade, the problem model on errors that exist today, and a contributing guide.
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- A site-less edge is served. Item 6 changes the graph read so it no longer requires a call-site node (`libs/wadi-storage/src/wadi_storage/graph.py:355-360`). Its test asserts that the test reader's edge is returned by every edge-serving REST route and MCP tool, and that a null `remote_call_id` or `mechanism` stays null on the wire and is never the string "None".
- How a reader's edge reaches the edge set. Item 6's decision record defines an edge-observation record that a reader writes to its own collection, a generic pass-through in the stitcher that turns observations into stored edges, the id function for an edge with no call site, and the confidence and provenance values such an edge carries. The stitcher stays the only writer of the edge set. Exit test 4's "no stitcher file" then holds for a reader whose edges need only the pass-through. A reader that confirms or contests an existing edge brings a join rule, which is outside the additivity guarantee.
- One source per edge in the base. A validator requires the `sources` list of a stored edge to hold exactly one entry. A reader observation that coincides with a static edge is stored as its own edge and is not merged. Merging arrives with the first join rule. The guarantee section says the list form is untested beyond one entry.
- Status transitions. Every snapshot status change is one compare-and-set write, and a terminal status never changes. One function owns the transitions. The monitor's success rule is written over job types in general, so read, copy, rebuild-graph and import jobs are covered.
- Orphans and staleness. The sweeper fails a snapshot that has no job as well as one whose job went unclaimed. Staleness is judged by the job's lease, not by the snapshot's age. At startup the orchestrator marks legacy unfinished snapshots failed before it builds the unique index for the one-unfinished rule.
- The version check has one seam. The snapshot record carries the contracts major that wrote it. A shared request dependency checks it once per request, which covers Mongo projections, aggregations and Neo4j reads. System, snapshot and job records are read tolerantly, so an older stack can still list them. The seventh failure case is tested on a route that uses `from_doc`, on an aggregation route and on a graph route.
- The environment question moves to item 4. Whether the current map is kept per environment is settled in item 4's decision record, because it changes the key of the one-unfinished write, the rule for carrying members and the lifecycle test. Item 7 then only adds the field and its display. This replaces "item 7's decision record settles".
- Graph rebuild. Item 4 adds a rebuild-graph job type that writes Neo4j from Mongo for one published snapshot and changes no Mongo record. Failure case 6 uses it. A graph read that finds no graph for a succeeded snapshot answers with a typed error that names the rebuild.
- The copy job. It first deletes any record already under the new snapshot id, then copies server-side with `$merge`. Its record lists the collections it copies, which include the flow-graph parts and exclude the edge set and the coverage report, since the stitch regenerates those. A reclaimed copy job produces the same records.
- Retention. `wadi snapshots rm <snapshot>` lands in item 4 and refuses the current map. The monitor queries unfinished snapshots only. "Disk full" joins the failure cases: the snapshot fails with a named reason and the previous map stays readable. This replaces the deferral of `wadi snapshots rm` in the DX list.
- Flow-graph node ids, in full. The ordinal comes from a traversal that is fixed by source position and construct kind, never from Joern's export order. A node with no source anchor gets its ordinal within its method. A node in staged library code is keyed by the library's own repository path. The stored id is a short digest, and the parts are separate fields. A test asserts that the node key the canonical map computes in item 1 equals the one the assembler computes in item 3. The remote-call join at `assembler.py:357` moves to the new id.
- The scorer is independent. The scorer imports no worker, stitcher or `simplify_uri` code. It has its own small placeholder normalizer with a table test. Ground-truth edges name the target endpoint key, so the scorer matches no paths. This replaces "no third matcher" for the scorer.
- The ground-truth key always carries handler class and method as a secondary part. It never depends on wadi's collision count. This replaces the conditional rule above.
- Abstentions cannot hide errors. The scorer publishes the answered fraction per fact class. The no-regression rule flags a fact that was correct at the last release and is abstained at this one.
- The canonical map's rules are owner-read. Its exclusion list and its normalizer join the files the owner reads on every change. It sorts only lists with set semantics and keeps the served order of ordered lists, such as flow-graph nodes, in the views part.
- The fold is enforced. An import contract forbids a route module from importing an artifact reader directly. A test asserts that the test reader's matched endpoint shows two sources on every route in the served-views list. Each registry entry declares an index on its natural key.
- How readers load, and what exit test 4 may touch. Readers are named in a `WADI_*` setting that the worker and the orchestrator both load, so an unknown reader is refused at enqueue in any process. Item 4's record fixes the list of places a new reader may touch: its package, its `wadi-contracts` module with regenerated schemas and types, its registry entry or setting default, the worker's dependency files, and the import contract. A conformance e2e variant runs the test reader's `read` job in a container.
- Import safety, as requirements on item 8's record. Import is refused when no token is configured. Every content-derived id is recomputed from the bundle's content and a mismatch rejects the bundle whole. Limits apply to the decompressed size and the record count as well as the upload size. Source-on-demand refuses a repository that is not registered on the system and answers with a typed "source not available" for an imported member. MCP results carry each record's origin.
- Item 1 is three releases. 1a: the canonical map tool, the error model, the constraint rows, the version check, B1, B2 and the determinism gate. 1b: the scorer, ground truth and the baseline. 1c: the fixes for known wrong facts and the freeze.
- How scale is judged, corrected. A release is blocked when a query examines more documents than it returns or when a response grows in bytes at the same data. Time is compared only for reads slower than 50 milliseconds. Each scale measurement records the machine, the data size, the number of runs and the 50th and 95th percentiles. This replaces the 1.25 times rule.
- Cheaper checks. A release is compared with the canonical map stored when the previous release was measured, so each corpus is analyzed once per release, not twice. The owner keeps a backup of ICPC's full maps, since the repository holds only their hashes.
- A failed snapshot stays inspectable. Its boundary list stays readable beside its snapshot record, jobs, job errors and coverage findings.
- The failure tests name the reason they expect. The storage-drop case expects the sweeper's stale reason.
- Cross-machine determinism names its risks: file enumeration order, a case-insensitive file system, and any dependency resolution over the network. The gate's measurement says how each was controlled.
- The release workflow attaches the canonical maps of the public corpora to each GitHub release (`.github/workflows/release.yml` uploads no asset today).
- Gate, revision 1 (2026-11-20). The owner answered `rec`. The bullets below apply the four User Challenges the owner accepted and govern over anything earlier in this plan.
- What is approved now (UC1). The amendment record approves item 1, as releases 1a, 1b and 1c, and item 2, the shape spike. Items 3 to 9 are a provisional sequence. None of them starts, and no decision record for any of them merges, until the owner decides at the spike checkpoint and that decision is recorded in `docs/architecture.md`. At that checkpoint the owner chooses between the provisional sequence, a changed sequence, and one real second reader built as a thin slice on a public corpus that settles the shapes by use. Every requirement this plan places on items 3 to 9 stays as the design input for that decision. The amendment record presents items 3 to 9 as provisional and not as the build order.
- What the spike must hand to that decision. The spike's list says, for each proposed shape, whether a real artifact was mapped onto it, what was lost, and whether the shape should stay in a base migration or land with its reader. The import probe stays in the spike, because its result is evidence for the same decision.
- Import early, promise late (UC2). If the provisional sequence proceeds, the import job and the export per service land right after item 4 as bundle version 0, which carries no compatibility promise and says so in its manifest. The two-repository test runs there. Bundle version 1 is frozen at the closing release, and the golden bundle is committed then. A version-0 bundle is never accepted by a release that has frozen version 1. This replaces "import moves last".
- ICPC is supplementary (UC3). The pinned corpora for every gate and exit test are `train-ticket-aitest`, yas and one microSecEnD application. Ground truth is labeled for those three. ICPC is measured when a machine with 10 GB for Docker is available, its results are published as hashes, counts and scores marked supplementary, and no item waits on it. The prerequisites before item 1's record are then: the three public corpora pinned by commit, and a second machine for the determinism run, which may be a cloud machine. This replaces the four-corpus and two-owner-machine requirements above.
- The gate experiment, earlier (UC4). The gate experiment runs after release 1b as the first use of the scorer. Release 1b's decision record states its cost estimate before it starts. Its report is an input to the spike checkpoint if it has arrived by then, and no fold work starts before it reports. This replaces "reports before the rule engine step".
- Checkpoints, restated. The order is reconsidered after the spike reports, when the gate experiment reports, and after import version 0 passes or fails its two-repository test.
- The owner's read is unchanged (UC5 declined). The owner still reads every change to a ground-truth file, the scorer, the canonical map's rules and the CI configuration.
- Second Eng pass (2026-11-20). An independent reviewer read the plan after the gate decisions and raised 25 findings, 6 of them high. All are accepted below. The first nine bullets bind item 1, which is approved. The rest are design input for the provisional items.
- Item 1 is four releases. 1a: the canonical map tool and a capture of each pinned corpus on 0.9.2, with no behaviour change. 1b: tolerant control-plane reads, the error model, the constraint rows, the version check, the exporter tie-break, B1, B2 and the determinism gate. 1c: the scorer, ground truth and the baseline. 1d: the fixes for known wrong facts and the freeze. Triggers that named a provisional item are tied to these releases: the scorer's no-regression rule is enforced from 1d. This replaces the three-release split.
- The floor for "an older stack reads newer records" is release 1b. In 1b, reads of system, snapshot and job records ignore unknown fields and unknown job types, and a test loads a record that carries both. Stacks older than 1b are outside the guarantee, because `WadiModel` forbids extra fields (`base.py:16`) and `JobType` is a closed enum.
- The guard lives in storage. The version check and the not-ready check sit in a snapshot-scoped read handle in `wadi-storage` that every artifact read and every graph read requires. The MCP server reads `wadi-storage` directly (`services/mcp-server/src/wadi_mcp/service.py:26`), so a FastAPI dependency alone would not cover it. A test walks the FastAPI route table and the MCP tool list and fails when an artifact read skips the handle. Both refusals are tested on MCP tools as well as on REST.
- Which releases bump the contracts major. The amendment record lists them: 1d (the edge id rule of #26, which `StitchedEdge` recomputes in a validator at `stitching.py:139-149`), and items 3 and 6 if they proceed. A test reads an edge written under the old id rule on the new stack and expects the typed refusal, not a validation error.
- A node tie-break that does not depend on Joern. Release 1b adds a column or a child-index path to the Scala exporter (`wadi_joern_client/export.py:248-264` carries neither today), before the canonical map schema is frozen. A fixture has two calls on one line and a Lombok-generated method. Without it, two nodes of one kind on one line can only be ordered by Joern's id.
- The served views are captured from the running stack. The canonical map's stored-record part and graph part are read through `wadi-storage` inside the compose network. Its served-views part is captured over HTTP and over the MCP transport, so route wiring, serialization and the MCP wrappers are covered. The 0.9.2 baseline is captured from the 0.9.2 servers. The view-only seeded change of the mutation test is injected at the route. This replaces "it runs through wadi-storage" for the views part.
- The canonical map tool is checked against itself. The raw capture of each public corpus is kept. At each release the previous raw capture is normalized again with the new tool and must give the previous canonical map. The format rules are written down: key order, number format and line endings. A determinism difference is classified as order or content. Sorting may hide an order difference only, and a content difference blocks.
- Redaction in the canonical map. Config values under a boundary's `network.env`, user info in any URL, and local checkout paths in `repo` or in `commits` keys are redacted before a map is hashed or attached to a release, and a test asserts it.
- The one-writer row uses a static map in release 1b. It derives from the reader registry only if item 4 proceeds.
- The consolidated amendment has a trace table. Each accepted bullet of this plan maps to a paragraph of the amendment record, and an agent that did not write the record checks the table, because the third spec pass was never re-verified.
- Design input for item 4. A snapshot records the contracts major, the commit and the source snapshot of each member, and the copy job refuses a source written under another major. In the base only imported members are carried: a service whose extraction fails stays failed and visible, as it does today (`pipeline.py:191-196`), and is not replaced by an older member. Determinism and canonical-map checks run on a fresh system. The snapshot records which readers and collections filled it, and the worker, the stitcher, the orchestrator and the MCP server all derive the reader set from that record.
- Design input for item 4, continued. The sweeper fails a snapshot's jobs in the same pass as the snapshot. The worker checks the snapshot's status when it claims a job and at each heartbeat. The lifecycle test gains "sweep, then worker restart". The analyze route reserves with the conditional write first, then resolves refs, then enqueues, so a reservation may exist without commits. The copy job uses replace-on-match on the unique key and verifies per-collection counts against the source. A snapshot record gains `superseded_by`, shown in REST, MCP and the UI, and the snapshot list is paginated. Deleting a snapshot runs as jobs to each owning service and refuses a snapshot that an unfinished one is copying from.
- Design input for item 5. The record classifies each route as folded or as a static-reader aggregate labelled with the reader's name. Counts, endpoint dependencies, the entities view and the coverage report are aggregates. The "two sources" test applies to folded routes only.
- Design input for item 6. The contract accepts one or more sources. "Exactly one in the base" is an invariant of the stitcher asserted by a test, so the first join rule needs no contracts major bump. The record lists the routes that exclude site-less edges by definition, such as call-target resolution. The frontend change is sized from the seven files that use `remote_call_id` as a join key, not as one null guard.
- Design input for the scale gate. Each item's record declares a byte budget per route, and the gate is growth beyond it, since natural keys and `sources` add bytes on purpose. Flow-graph document size and part count are measured before and after item 3.
- Design input for import. Import never replaces a locally analyzed member without an explicit flag. Free text in a bundle is capped and stripped at import and marked untrusted in the MCP tool descriptions. An archive bundle is checked for path traversal and symbolic links. A bundle with a duplicate natural key is rejected. Neo4j rebuild is tested after a partial wipe and after a failed rebuild.
<!-- /autoplan-accepted:eng -->
