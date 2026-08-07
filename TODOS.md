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

### A library compiled into a service is modelled as a peer service
**Priority:** P1
**Opened:** v0.8.0

`global.icpc:base` is a jar inside `contest`, and the snapshot pipeline gives it
its own service. The annotations and two of the authorizers live there, so in a
per-service CPG the `Admin` typeDecl is external and its binding is invisible —
cause (3) in §5.2.12, and the reason the M1 acceptance run had to build one CPG
across both repos rather than go through the worker. Until this is modelled,
this class of system must be analyzed with the library in scope or the
vocabulary silently shrinks. **Measured end to end: 8 annotations derived with
both repos in one CPG versus 7 through the shipping pipeline, and 643 guarded
endpoints versus 566 — the per-service CPG costs 77 endpoints their guard.**

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
