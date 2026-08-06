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

### Five vocabularies have never run against a real corpus
**Priority:** P2
**Opened:** v0.7.0

Each is fixture-proven and reads zero on `train-ticket-aitest` because that
corpus does not contain the idiom. By the `unexercised_vocabulary` logic wadi
itself ships, a zero here proves nothing about whether the path works:

- `authorities` — the corpus uses only `hasAnyRole`; the role/authority split
  shipped in 0.6.0 has never been exercised outside the matrix fixture.
- `denied` — no `denyAll()` route survives in the corpus.
- `withheld` — every auth idiom in the corpus is now readable.
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
