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
