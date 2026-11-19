# Contract Triangulation Plan

**Status:** proposal, not yet a decision record. Compiled 2026-08-25 against wadi 0.8.2
(contracts 1.25.0, export 2.13.0).

**Read with the direction record (added 2026-11-18).** `architecture.md` §11 now holds a direction
record and a build order of eleven steps. Where this plan differs from
`target-architecture-plan.md`, that plan governs. The rest of this document is unchanged. It
differs on these points.

- **Only C5 is in the build order.** It is the declared reader of step 8. C0 to C4 and C6 are
  unscheduled.
- **The roadmap in section 9 is replaced.** The route "3, 5, 6, 11" gives way to the build order.
- **M1's two terms name a source. They do not carry several sources.** The target plan rejects
  more values on the one provenance scalar as the way to hold more than one source, and gives
  each call and endpoint a sources list. Step 8's decision record says how
  `provider-declared` and `consumer-inferred` appear in that list.
- **M4 and M5 are open, with a second proposal beside this plan's.** This plan prefers an analyzed
  service marked `provider-declared`. T12 of the target plan suggests the placeholder id rule for
  a service known only from a spec. The owner decides before step 8, and M5 cannot be changed
  afterwards.
- **Question 1 of section 12 is out of date.** Phase 2.10, §5.2.17 and 0.9.0 went to entity
  access.

"M5" in this plan is the identity rule of section 7. It is not milestone M5 of Phase 2.10. The
open questions of section 12 move to GitHub issues with the `decision` label, and a decision
record in `architecture.md` closes each one.

**Purpose.** wadi extracts a contract for every endpoint from the provider's source code. That is
*one* view of an interface. This document proposes two more — the contract the provider
**publishes** (its OpenAPI document) and the contract a consumer's code **assumes** — and argues
that the product is not any single view but the **disagreements between them**. It also records
what the model, the vocabulary and the roadmap need in order to hold three views instead of one.

**Why it is separate from `foundation-hardening-plan.md`.** That document audits what is wrong
with what exists, scoped to making Phase 3 safe to build on. This one proposes a capability that
does not exist yet, spanning Phases 5, 6 and 11. They are coupled — four foundation findings are
hard prerequisites here, listed in section 8 — but mixing an audit with a design muddles both.

**What this is not.** It changes nothing in `architecture.md`. Items accepted from here get a
`§5.2.x` decision record in that document first, per the standing rule, and a `TODOS.md` line
each. The tables below are proposals, not landed decisions.

## How to read this

**Reference convention.** A bare `§N` means a section of `docs/architecture.md` — `§7` is its
data-contracts section, `§11` its roadmap, `§5.2.x` its decision records. Sections of *this*
document are written out ("section 4", "C2"). Where `foundation-hardening-plan.md` or
`benchmarking-baselines.md` is meant it is named, and its finding labels (`G7`, `H1`) are used as
written there.

**`UNMEASURED`.** Per §5.2.11's standing rule — *a count is a hypothesis until one of its members
is opened* — every claim in this document that has not been measured against a real corpus is
marked `UNMEASURED` inline. **The central feasibility claim of this plan is one of them.** Section
9 (C0) exists to remove that marker before anything else is built.

---

## 1. The thesis

An interface has three independent sources of truth, and wadi can reach all three:

| View | Provenance | Derived from | Today |
|---|---|---|---|
| **Implemented** | `machine-proven` | the provider's source code | ✅ ships (§5.2.7, §5.2.16) |
| **Declared** | `provider-declared` *(new)* | the provider's published OpenAPI | ❌ not modelled |
| **Assumed** | `consumer-inferred` *(new)* | **the consumer's source code** | ❌ not modelled |

Each pair of views answers a different question, and three of the four answers are findings no
existing tool produces:

| Comparison | Finding | Tense | Prior art |
|---|---|---|---|
| Implemented ↔ Declared | **spec drift** — the published document does not describe the code | present | partially covered (section 3) |
| **Implemented ↔ Assumed** | **integration defect** — the consumer is wrong *right now* | **present** | **none found** |
| Implemented(v2) ↔ Assumed(v1) | **breaking change, attributed** — who breaks, at file:line | future | **none found** |
| Assumed ↔ Assumed, across consumers | **blast radius** — who depends on which field | — | **none found** |

The second row is the one to build first, and section 6 explains why: it needs one snapshot, no
diff engine, no CI integration and no federation, and it produces defects that exist today rather
than warnings about defects that might exist later.

### Why the third view is the load-bearing one

Every tool surveyed in `benchmarking-baselines.md` and in the state-of-the-art sweep (section 3)
derives its contract from the **provider**. That is sufficient to say *what changed* and
insufficient to say *who breaks* — which is the question a provider actually has when deciding
whether to merge.

```
AutoGuard (SANER 2025):  "response field `orderStatus` removed"
Pact / BDCT:             "consumer B's contract test failed"   — only if B wrote one
This proposal:           "removes `orderStatus`, read by ts-preserve-service
                          at OrderClient.java:47 — that service has no test"
```

**Attribution without consumer participation.** That is the contribution, and it lands on a gap
the field has named for itself: the TOSEM 2026 SLR's third open challenge is *information
asymmetry* — *"Maintainers know what changes and why. Consumers often cannot determine either."*
The SLR diagnoses it for package ecosystems, where a manifest at least declares the dependency.
For services **there is no manifest at all**: nothing in a consumer's repository states that it
depends on `ts-order-service.orderStatus`. wadi's remote-call detection plus consumer-side
recovery **reconstructs the manifest that nobody writes**, which is the root cause of why library
ecosystems got tooling for this and web APIs did not.

---

## 2. Why now — the motivation, stated defensibly

The informal version of this argument is "LLMs made people write code 20–100× faster, so contracts
break faster than review can catch." **The multiplier is folklore and should not appear in any
document that leaves this repository.** The defensible version, with citations, is that
*generation scaled and review did not*:

| Evidence | Source |
|---|---|
| 45% of developers using AI tools multiple times daily deploy to production daily or faster, vs 15% of weekly users | AI coding productivity survey, 2026 |
| AI-generated code introduces 1.7–2.7× more defects | ibid. |
| 806 repositories adopting an AI coding tool: **+41% code complexity, +30% static-analysis warnings**; velocity gains transient, debt persists | Cursor adoption study, 2025–26 |
| PR velocity gains are **partially or fully offset by reviewer bottlenecks** | Harness, "the AI velocity paradox" |
| 70% of engineering leaders report code quality has already degraded | 2026 industry survey |

The reviewer-bottleneck finding is the thesis in someone else's words, and it is the same claim
product goal 10 already makes: *the reading loop that used to catch misbehavior is breaking.*

**The stronger move is to measure it ourselves.** wadi can extract contracts at both ends of a
call across a whole system. Nobody else can, which is exactly why nobody has published *"how often
do service contracts break, who notices, and how long does it take."* That measurement is an
original empirical contribution, it costs mostly compute once C0 and C1 exist, and it manufactures
the motivation for the rest of this document. It is proposed as **C6**.

---

## 3. State of the art — where this sits

Condensed from the sweep of 2026-08-25; the full register belongs in
`benchmarking-baselines.md`, which this section does not duplicate.

| Cluster | Representative work | Status vs this plan |
|---|---|---|
| Provider spec recovery from source | **AutoOAS** (Klagenfurt 2024) — 7 Spring projects: methods 100% P/R, **parameters 73% P / 69% R**, responses 99% P / 97% R, runtime ~11 s. **Respector** (ICSE 2024) — static + symbolic execution over bytecode, recovers parameter constraints, mean runtime 52.6 min | **Occupied.** Table stakes. Do not claim novelty here |
| Spec-to-spec diffing | **AutoGuard** (SANER 2025) — AutoOAS + openapi-diff, GitHub Action, fails CI. Claims *"first tool for reporting individual breaking changes in REST APIs directly integratable into the development process."* `oasdiff`, `pb33f/openapi-changes`, Buf, GraphQL Inspector | **Occupied.** AutoGuard's own limitation: reports changes from OpenAPI descriptions, *"which do not capture semantic dependencies."* The SLR's independent verdict: *"framework-specific; semantic blindness"* |
| Spec-vs-implementation drift | **Respector** reported inconsistencies between developer specs and implementations. **Godefroid et al.** (ISSTA 2020) separated *specification regressions* from *service regressions*; 17 Azure API versions → 14 regressions (5 spec, 9 service). Industry drift rate **15–30%** without automated validation | **Partly occupied.** All of it is runtime/black-box or single-service. Static, source-derived, cross-service drift checking is open — but narrow |
| Consumer-driven contract testing | Pact, Spring Cloud Contract; **Schwarz et al.** (STVR 2025) SLR + action research; **bi-directional contract testing** (consumer contract ⊆ provider OpenAPI, no shared test execution) | **Adjacent.** Contracts are hand-authored or mock-derived. Requires both sides to participate |
| Cross-service program analysis | **Micans** (ISSTA 2025) — first pointer analysis for microservice systems, built on **Tai-e**, handles RPC + messaging + DI + endpoint config. Cerny/Taibi line: CIA SLR (JSS 2024, 1,669 → 29 studies, 19 tools), SANER 2025, FSE 2025 demo, SAVAT (ECSA 2025) | **The substrate competitor.** Java-only; wadi's polyglot claim is the differentiator *if* Phase 8 lands. Reading Micans is already action item 1 in `benchmarking-baselines.md` and is still open |
| Consumer-side field usage from code | — | **Nothing found.** See section 10, risk R5: this is a negative result from a rapid review, not a proof |

**What actually breaks in web APIs**, from the field's largest corpus (Serbout & Pautasso, via the
TOSEM 2026 SLR) — this is the target list, and two entries are already blocked on foundation
findings:

| Breaking change | Scale | Can wadi represent it today? |
|---|---|---|
| Response property **type** change | **23,048 occurrences across 714 APIs — the most frequent of all** | Yes |
| Response **enum value** removal | 21,210 across 319 APIs | **No** — `foundation-hardening-plan.md` **G6** |
| Response required property removal | 12,587 across 409 APIs | Partially — nullability is not modelled |
| Path removal without deprecation | 1,211 of 3,075 APIs | Yes |
| **Modifying authority levels** for existing endpoints | listed; DHIS2 moved `POST /predictor/run` from `F_PREDICTOR_ADD` to `F_PREDICTOR_RUN` | **Yes, and uniquely** — §5.2.9's enforcement model. **Nothing in the SLR's 43 detection techniques does this** |

That last row is the cheapest publishable claim in this document and it needs no new extraction.

---

## 4. What exists today, verified

Checked against the code on 2026-08-25, not inferred:

| Capability | Where | State |
|---|---|---|
| Provider request/response shapes | `Endpoint.request_schema`, `.response_schema`, `.type_defs` (`endpoint.py:554-574`) | ✅ ships |
| Shape vocabulary with honest terminals | `ShapeKind` = object/scalar/array/map/ref/cycle/truncated/unresolved/**always-null** | ✅ ships |
| Evidence marking on shapes | `ShapeOrigin` = declared / return-expression | ✅ ships — **the precedent this plan extends** |
| Declared statuses | `Endpoint.declared_statuses[]` with `StatusOrigin` | ✅ ships |
| Structured auth | `Endpoint.auth` — the §5.2.9 enforcement model | ✅ ships |
| Outbound call sites | `RemoteCall` — site, mechanism, verb, sliced url + confidence, `auth_propagation_state`, `reachable`/`reachability` (`comms.py:70`) | ✅ ships |
| Call → endpoint matching | `StitchedEdge`, `TargetKind` = analyzed/external/placeholder/undetermined | ✅ ships |
| Provenance vocabulary | `Provenance` = machine-proven / config-resolved / heuristic / llm-guessed / human-asserted / **federated** (`enums.py:26-34`) | ✅ ships; `federated` reserved, unused |
| Identity stability | `endpoint_id = hash(service_id, verb, full_uri)`; §7 identity rule | ✅ ships |
| Artifacts-only coupling | §11: *"the stitcher never consumes source code — only artifacts (P2) — so the versioned artifact contracts + published JSON Schemas already are the federation protocol"* | ✅ **the property that makes this whole direction cheap** |

**Planned but not built** — §11's design note (`architecture.md:1380`) schedules for Phase 5:

> at each tagged call site, dataflow slices record what the caller sends and *which response
> fields it actually reads* (the load-bearing subset, with code locations)

So `sends[]`/`reads[]` are planned **as call-site enrichments on `RemoteCall`**. What is planned
nowhere:

1. Those facts assembled into **a contract in its own right** — an artifact shaped like
   `Endpoint`'s contract fields, so the two are comparable objects rather than a field-name list
   on one side and a `TypeShape` on the other.
2. **The response type the consumer declares.** §5.2.7 is explicitly scoped *"provider side
   only"*, and that scoping hid the cheapest evidence source in the whole plan (section 5).
3. Status codes the consumer handles, and the error paths it assumes.
4. Any comparison model.
5. A source kind, identity rule, or provenance term for a contract that never came from source
   code at all.

---

## 5. The two tiers of consumer evidence

A consumer states its expectations in two different ways, and they mean different things. Keeping
them separate is what decides whether this feature is useful or noisy.

### Tier A — declared expectation

The type the consumer deserializes into. **`TypeShapes` pointed at a different type**: wrapper
unwrapping, generics from declaration text, `type_defs` dedup and the honest terminals are all
provider/consumer agnostic. This is why the expensive-looking half of the plan is nearly free.

| Client shape | What is declared | Expected recoverability |
|---|---|---|
| **Feign / `@HttpExchange`** | `OrderDto getOrder(@PathVariable String id)` — verb, path, params, return type | Near-complete. This is an OpenAPI document written in Java, and the Spring pack already reads those annotations on the provider side |
| **RestTemplate / WebClient** | `getForEntity(url, OrderDto.class)`, `.bodyToMono(OrderDto.class)` | High — the deserialization target is a declared type |
| **Typed vendor SDK** (Stripe) | `charge.outcome.network_status` | High; new pack, new `mechanism` value |
| Raw `String` / `JsonNode` / `Map<String,Object>` | nothing | Tier B only |
| Reflective / fully dynamic | nothing | Honest unknown |

All five rows are `UNMEASURED` — the distribution across `train-ticket-aitest` and ICPC has never
been counted. C0 counts it.

### Tier B — actual usage

Which fields of that type the code reads. The hard dataflow, and **the tier where the break
actually is**:

```
Provider removes field `email`
  → consumer's DTO still declares it   (Tier A) → Jackson tolerates the absence, field is null
  → consumer reads it                  (Tier B) → NPE, or silent wrong behaviour   ← the break
```

Tier A alone would flag every field of every DTO as a dependency, which is the over-reporting
failure mode. §11's plan is therefore right to name *"actually reads"* as the target. Tier A's
jobs are the **request** side (what the consumer sends is a declared type, fully recoverable), the
**fallback** when field-access dataflow fails, and the **surface** that bounds Tier B's search.

The two tiers are marked exactly as `ShapeOrigin` already marks `declared` vs `return-expression`
— same precedent, same reason: both are symbolic truth, resting on premises of different strength.

### The P10 corollary this needs

§5.2.13 established that over-approximation is honest only where it *adds* restriction. The
contract analogue, and it must be recorded before any code:

> **An undetermined field-read counts as depended-upon, never as safe-to-remove.**

Unknown fails closed. A tool that tells someone it is safe to delete a field it merely failed to
analyse is worse than no tool.

---

## 6. The comparisons, and what each one costs

| # | Comparison | Inputs | Needs a diff? | Needs federation? | Output |
|---|---|---|---|---|---|
| 1 | Implemented ↔ Assumed | one snapshot | no | no | **integration defects, present tense** |
| 2 | Implemented ↔ Declared | one snapshot + an OpenAPI document | no | no | spec drift |
| 3 | Implemented(v2) ↔ Assumed(v1) | two snapshots | yes | no (same system) | attributed breaking changes |
| 4 | Assumed ↔ Assumed | one snapshot | no | no | blast radius per field |
| 5 | any of the above across orgs | bundles | yes | **yes** | cross-team pre-deploy warning |

**Comparison 1 is the sleeper.** Example, expressible entirely in vocabulary that already ships:

> `ts-preserve-service` reads `order.contactsName` at `OrderClient.java:47`.
> `ts-order-service` sets that field to `null` on every construction path (`ShapeKind.ALWAYS_NULL`).

That is a defect that exists **today**, found on **one snapshot of a system already analysed end
to end**, with no diff engine, no CI gate and no second version. `always-null` was added in 0.7.0
for a different reason and turns out to be exactly the terminal this comparison needs.

Whether any such pair exists in the two corpora is `UNMEASURED`. C0 checks it — and if the answer
is zero, that is a real result that reshapes the plan rather than a reason to keep going.

This inverts §11's framing. The design note puts all the value behind *"cross-snapshot diffing on
stable IDs yields attributable breaks"*, which requires two snapshots and a diff engine before
anything is visible. Building the **assumed-contract artifact** first yields findings on snapshot
one; the diff then becomes a second consumer of the same data rather than a prerequisite.

---

## 7. Model and vocabulary changes

Six changes. Four are model/vocabulary; two are resequencing (section 9). None is a redesign — the
artifacts-only coupling rule (P1/P2) is what makes that true.

### M1 — `Provenance` gains `provider-declared` and `consumer-inferred`

The current vocabulary has no term for either new view. A contract read from a published OpenAPI
document is not machine-proven (nothing was proven), not heuristic, not human-asserted (no
reviewer confirmed it) and not federated (it is not a wadi bundle). It is **authoritative about
intent and unverified against implementation** — a distinct epistemic status that P7 and P10 both
require be distinguishable.

This pays for itself immediately: **published specs are wrong 15–30% of the time**, so when both a
`provider-declared` contract and a `machine-proven` extraction of the same service exist,
*disagreement between them is the spec-drift finding* (comparison 2). It falls out of the
vocabulary rather than needing a feature.

`consumer-inferred` is the same move for the third view.

*Rejected: reusing `heuristic` for either.* Confidence and provenance are already two orthogonal
fields that are never blended (§7, `StitchedEdge`); collapsing "where did this come from" into
"how sure are we" is the exact error that separation exists to prevent.

### M2 — `ExpectedContract`, a first-class artifact

Working name, subject to section 12 question 2. Worker-owned (P4 — the extraction worker already
owns `RemoteCall`), keyed to a stitched target, and shaped so it is directly comparable to the
provider-side fields on `Endpoint`:

| Field | Source | Notes |
|---|---|---|
| `remote_call_id` | — | the call site this was derived from |
| `target_endpoint_id` | stitcher | **null when the call did not resolve** — see below |
| `http_verb`, `uri_template` | `RemoteCall` | already recovered |
| `request_schema: TypeShape` | Tier A | the type the consumer serialises |
| `response_schema: TypeShape` | Tier A | the type the consumer deserialises into |
| `type_defs` | Tier A | same dedup mechanism as `Endpoint` (§5.2.16) |
| `fields_read: list[FieldRef]` | Tier B | wire path + source anchor per read |
| `fields_read_resolution` | — | complete / partial / **undetermined** (fails closed, section 5) |
| `statuses_handled: list[int]` | Tier A/B | which codes the consumer branches on |
| `auth_sent` | existing | `RemoteCall.auth_propagation_state` |
| `evidence_tier` | — | `declared` \| `usage`, per the `ShapeOrigin` precedent |

An `ExpectedContract` with a null `target_endpoint_id` is not waste — it is an **unmatched
consumer**, which is already one of §5.6's four named LLM gap classes, and it now has real content
to show instead of a count.

*Rejected: extending `RemoteCall` in place.* A contract and a call site are different things with
different lifetimes; `RemoteCall` is one candidate outbound call, and one call site can produce N
stitched edges (§7). Folding a contract into it would make ambiguity unrepresentable.

### M3 — a source kind for a contract that never came from source code

`System.repos[{source: url | local path}]`, with `artifact-bundle` reserved for Phase 11. **An
OpenAPI document is neither.** A spec-sourced service has endpoints but no repo, no SHA, no CPG,
no ICFG.

This touches a load-bearing invariant: **Snapshot = a frozen commit-set `{repo → sha}`** (§4). A
spec-sourced service has no SHA to freeze. §11's org-hub design already generalises exactly this —
*"the single-commit-set invariant generalizes to a recorded set of (bundle, version, produced-at)
with staleness surfaced per bundle"* — so the shape of the answer exists; it is scheduled three
phases later than this direction needs it.

### M4 — `TargetKind.EXTERNAL` currently has no interior, and now needs one

`StitchedEdge.external_host` is documented *"Normalized host[:port] — set for EXTERNAL targets
only"* (`stitching.py:86`), and §5.4 defines an external API as *"a real dependency edge to a node
with no interior."* That was correct when nothing could be known about it.

Once a provider's OpenAPI is ingested, that node **has** endpoints, shapes and auth. Two axes are
being conflated: *where the target sits* (analyzed/external/placeholder) and *what is known about
it* (provenance). An external API with an ingested contract is best modelled as an **analyzed
service carrying `provider-declared` provenance**, which keeps the stitcher's matching logic free
of a special case.

### M5 — endpoint identity for a non-analyzed service

`endpoint_id = hash(service_id, verb, full_uri)`, and `service_id` derives from a discovered
boundary (repo + build root). Stripe has no build root. Derive it from the spec URL, a
user-declared name, or `info.title`?

This is the §7 *"nearly free now, nearly impossible to retrofit"* rule. It must be settled before
the first spec-sourced endpoint is written, or cross-snapshot joins break on precisely the
artifacts most worth diffing.

**A second identity hazard, specific to this plan:** an `ExpectedContract` keys on a target
endpoint id computed from the **consumer's** recovered URL, while the `Endpoint` it must join to
computed its id from the **provider's** route. Any divergence in normalization between the two
sides silently produces zero matches, and a zero here looks identical to "no consumers." A pinned
test belongs in the same commit as the artifact. (§5.2.11's T0 already fixed one instance of
exactly this: a slash-less class-level `@RequestMapping` whose `full_uri` disagreed with the
caller's URL.)

### M6 — a vendor SDK is not an HTTP client

The client-library census vocabulary is `resttemplate · webclient · feign · restclient ·
http-interface · jdk-httpclient · okhttp · retrofit · apache-httpclient · unirest`. A Stripe SDK is
none of them: it is a typed vendor client whose field access is `charge.outcome.network_status`,
not a JSON path. New `mechanism` value, and probably a new pack class.

Worth noting that the honesty surface already handles this correctly — `unmodelled_mechanisms`
would truthfully report *"Stripe SDK present in N services, unmodelled"* rather than reporting
zero calls. The instrument works; only the coverage is missing.

---

## 8. Hard prerequisites from `foundation-hardening-plan.md`

Four findings in that document gate this one. They are not optional here:

| Finding | Why it blocks this plan |
|---|---|
| **G7** — validation constraints absent | A contract without constraints cannot express "the consumer sends a 4-char string, the provider now requires 8." That document already sequences G7 early and out of band for Phase 9; this is a second named consumer |
| **G6** — enum-typed fields become empty objects | **Response enum value removal is the second most frequent web-API breaking change** (21,210 occurrences across 319 APIs). wadi currently cannot represent it on either side of the comparison |
| **G5** — wire shapes do not walk supertypes | An inherited field absent from the provider shape but read by the consumer produces a **phantom break** — a false positive in the flagship output |
| **H1** — `schema_version` written everywhere, read nowhere | Today a one-machine annoyance (`extra="forbid"` + closed enums ⇒ an older reader hard-fails on a newer artifact). **Under federation it is the failure mode**: team A's wadi publishes, team B's older wadi ingests, hard fail. §7 already *specifies* the correct behaviour for bundle ingestion — validate at the door, flag unknowns by name — while the implementation does the opposite. Federation moves this from P1-annoyance to prerequisite |

Additionally, `TODOS.md`'s **"the corpus measurements are not reproducible from the repo"** (P1)
blocks C6 entirely, and is the same item `foundation-hardening-plan.md` W0/B3 addresses.

---

## 9. Work packages

Labels are **C0–C6**, deliberately disjoint from that document's W0–W8.

| Package | Contents | Blocks | Rough size |
|---|---|---|---|
| **C0** Feasibility measurement | Count Tier A and Tier B recoverability across both corpora; look for one real comparison-1 pair | **everything** | small |
| **C1** Assumed contract, Tier A | `ExpectedContract` (M2), Tier A extraction, identity + join test (M5) | C2, C3, C4 | medium |
| **C2** Assumed contract, Tier B | field-access dataflow, `fields_read_resolution`, fails-closed rule | C4 (attribution quality) | **large, highest risk** |
| **C3** Comparison 1 — present-tense defects | contract-checker service (§10 pattern), findings artifact, MCP + UI surface | — | medium |
| **C4** Comparison 3 — attributed breaking changes | cross-snapshot diff, `--fail-on contract-break` (Phase 6) | — | medium |
| **C5** Provider-declared ingestion | M1, M3, M4, M6; OpenAPI as a source kind; comparison 2 | external-API story | medium |
| **C6** The empirical study | contract-break frequency and detection latency across a corpus over time | publication | medium |

### Sequencing, and why

1. **C0 first, and it is a genuine go/no-go.** The entire plan rests on consumer-side
   recoverability, which has never been measured. If Tier A lands where token propagation did
   (**0 of 157 call sites on train-ticket**, §11's own recorded limitation), the thesis needs
   rethinking, not more building. That prior is the single strongest reason to measure before
   committing.
2. **C1 before C2.** Tier A reuses machinery that already works and yields a usable product even
   if Tier B lands badly. Tier B is the same analysis class as token propagation and should not be
   on the critical path of the first deliverable.
3. **C3 before C4.** One snapshot before two. C3 needs no diff engine, no CI coupling and no
   second version, and it is the better demonstration: *"here are four defects in your system
   right now"* beats *"we will warn you when you break something later."*
4. **C5 is independent** and can run in parallel — it touches intake, provenance and the stitcher's
   target model, and nothing in C1–C4 does.
5. **C6 last**, and gated on `TODOS.md`'s reproducibility item.

### Roadmap consequence

This direction reorders §11's tail. Federation moves from *"pick it up whenever the org need
materializes"* to the thesis:

```
today:      3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11
this route: 3 → 5 (C0–C4) → 6 (gate + auth base) → 11 (C5 + federation) → 4 / 7 / 8 …
```

§11 states federation is independent-by-construction with only two prerequisites — `wadi export`
(shipped, Phase 2.5) and the shared-deployment auth base (Phase 6) — so there is no structural
obstacle, only a decision. **Phase 4 cannot slide as far as the arrow suggests**: its hints
infrastructure is the prerequisite for Phase 7's promotion loop, and the "human confirms the true
contract" step in this direction *is* that loop.

---

## 10. Risks

| # | Risk | Why it matters | Mitigation |
|---|---|---|---|
| **R1** | **Tier B may not be recoverable.** Field-access dataflow through a deserialized object is the same analysis class as token propagation, which fires **0/157** on train-ticket | The attribution claim depends on it | C0 measures it before anything is built. C1 ships value without it |
| **R2** | **Adoption asymmetry.** AutoGuard is a GitHub Action with ~11 s runtime; wadi is a ~10 GB Docker stack, and CI gating is where this competes | The most likely practical failure, and it has nothing to do with novelty | Design a thin per-service mode before Phase 6, not after |
| **R3** | **Standards plays fail on adoption, not merit.** "Publish your contract in our format" turns a working tool into a campaign | Would sink the external-API story | **Do not invent a format.** Stripe, GitHub, Twilio and AWS already publish OpenAPI; consume it. The consumer side works with **zero provider adoption** — that asymmetry is the most valuable property of the whole external-API idea |
| **R4** | **Scale of ingested specs.** Stripe's OpenAPI is thousands of operations with deeply shared types; §5.2.15's 114 MB expansion blowup was the same shape | Could reproduce a solved problem | `type_defs` (§5.2.16) is why this survives; `MaxNodes` remains the backstop |
| **R5** | **The novelty claim rests on a negative result from a rapid review.** No academic work found on consumer-side field usage — searched, not proven absent | A single prior paper would reframe the contribution | Formal database queries (ACM DL, IEEE, Scopus, dblp) before any submission. Read Micans first |
| **R6** | **Federation freshness.** The gate is only as fresh as the consumer's last published bundle | An answer that reads as current but is not | §11's composite snapshots + per-bundle staleness already design for it. State it as a designed limitation in the output, not a caveat discovered later |
| **R7** | **Polyglot is unproven.** Micans is Java-only, which is a differentiator only if Phase 8 ships | The main defence against the substrate competitor is currently architectural, not demonstrated | Do not make the polyglot claim in writing until one non-Java service is analysed end to end |

---

## 11. Exit criteria

1. **C0 has run and its numbers are recorded — including if they kill the plan.** Tier A and
   Tier B recoverability are counted per client shape across both corpora, and the search for a
   real comparison-1 pair has returned an instance or an argued zero.
2. `Provenance` carries `provider-declared` and `consumer-inferred`, each with a docstring
   stating what it does *not* assert.
3. An `ExpectedContract` exists for every stitched call site where the mechanism is modelled, and
   the count of sites where it does **not** exist is on the coverage report with a reason code —
   never silence (P10).
4. `fields_read_resolution` is `undetermined` wherever the dataflow did not complete, and no
   consumer of the artifact treats `undetermined` as "safe to remove."
5. The consumer-side/provider-side id join has a pinned test, and the number of
   `ExpectedContract`s that fail to join is reported rather than dropped.
6. Comparison 1 produces at least one **verified** finding on a real corpus — verified meaning a
   human opened both sides and confirmed it, per §5.2.11.
7. G5, G6, G7 and H1 are closed, or each is explicitly recorded as an accepted limitation with the
   comparison it weakens named.
8. Every figure quoted in any resulting paper is reproducible from a `make` target.

---

## 12. Open questions for the owner

1. **Phase and section numbering.** `foundation-hardening-plan.md` already proposes Phase 2.10 /
   §5.2.17 / 0.9.0 for itself. This work is larger and spans three existing phases. Does it become
   Phase 5's redefinition, or a new phase number?
2. **`ExpectedContract` naming.** Alternatives considered: `AssumedContract`, `ConsumerContract`,
   `ExpectedInterface`. The vocabulary matters more than usual here because the artifact's whole
   job is to be *not* the truth — it is what one side believes. Owner's call.
3. **M4's direction.** Fold an OpenAPI-backed external API into `ANALYZED` with
   `provider-declared` provenance, or add a fifth `TargetKind`? The first keeps the stitcher
   simple; the second keeps "we have source for this" readable at a glance.
4. **M5's identity rule.** Spec URL, user-declared name, or `info.title` for a spec-sourced
   service id? Blocks C5 and cannot be retrofitted.
5. **H1's direction** (shared with `foundation-hardening-plan.md` question 4). Refuse-at-the-door
   versus a read-side compatibility mode — now with a federation consumer, which may change the
   answer.
6. **Does C6 come first?** The empirical study is the cheapest publication and it manufactures the
   motivation for everything else, but it is currently sequenced last because it depends on C1/C2.
   A weaker version using only provider-side contracts across snapshot pairs could run today.
7. **Nullability.** "Response required property removal" is 12,587 occurrences across 409 APIs and
   `TypeShape` has no nullability field. Is that a `FieldShape` addition here, or a foundation
   finding belonging in the other document?
8. **Does this amend §5.2.7 in place or open a new §5.2.x?** §5.2.7 is explicitly scoped *"provider
   side only"*, and that scoping is exactly what hid Tier A. Amending it in place would erase the
   evidence of how the omission happened, which has some value.
