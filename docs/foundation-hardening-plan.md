# Foundation Hardening Plan

**Status:** proposal, not yet a decision record. Compiled 2026-08-23 against wadi 0.8.2
(contracts 1.25.0, export 2.12.0 as stamped / 2.13.0 as declared — see H2).

**Revision 2, same day.** The first pass audited the *seams* — reachability closures, contracts,
merge logic, storage — and inferred the pack interiors from them. Revision 2 reads
`SpringPacks.scala` (endpoint extraction) and `TypeShapes.scala` (wire shapes) line by line, which
produced the **G** findings in *this document's* section 11 (W7), and adds the two things the
first pass omitted entirely: a classification of every finding against the roadmap (section 2 —
*is this a defect or a deferral?*) and the structural pattern the findings share (section 3).
Section 3 is the more important of the two.

**Purpose.** Phase 3 adds new analysis semantics (async edges, auth-consistency findings) on
top of the ICFG, the stitched graph and the enforcement model. This document is the audit of
those three foundations and the work needed to make them safe to build on. It exists because
every Phase 3 layer inherits whatever is wrong here, and two of the findings below are in the
load-bearing claim itself (product goal 10: the developer reads the map, not the code).

**What this is not.** It changes nothing in `architecture.md`. Items accepted from here get a
`§5.2.x` decision record in that document first, per the standing rule, and a `TODOS.md` line
each. The tables below are findings plus proposed fixes, not landed decisions.

**Companion document.** `contract-triangulation-plan.md` (2026-08-25) proposes a forward
capability — consumer-inferred and provider-declared contracts beside the implemented one — and
depends on four findings here: **G5**, **G6**, **G7** and **H1**. G6 and H1 in particular carry
consequences that document names and this one does not: enum value removal is the second most
frequent web-API breaking change in the literature, and H1's schema-compatibility hole becomes a
hard blocker rather than an annoyance once artifacts are exchanged between deployments.

## How to read this

Every finding carries four fields, in this order:

| Field | Meaning |
|---|---|
| **Symptom** | What a user or reviewer sees |
| **Evidence** | How we know — a measurement, a file:line, or a reproduction. Never an argument |
| **Fix** | The change, with the files it touches |
| **Verified by** | The check that proves it landed and keeps it landed |

Findings with no measurement under **Evidence** are marked `UNMEASURED` and must be measured
before they are worked, per §5.2.11's standing rule: *a count is a hypothesis until one of its
members is opened.*

**Reference convention.** A bare `§N` always means a section of `docs/architecture.md` — `§7`
is its data-contracts section, `§11` its roadmap, `§5.2.x` its decision records. Sections of *this*
document are written out ("section 3", "W4"). Where `benchmarking-baselines.md` is meant it is
named.

---

## 1. The findings, at a glance


| # | Finding | Tier | Threatens |
|---|---|---|---|
| **A1** | Lambda bodies reach no endpoint ICFG | soundness | ICFG completeness (goal 10) |
| **A2** | Cross-service flow stops at one hop | soundness | Cross-service claim (goal 4) |
| **A3** | Call-graph edges carry no confidence | honesty | P7 / P10 in the ICFG |
| **A4** | The auth gating discriminator is a name list | generalization | Auth model (goal 9) |
| **A5** | Evidenced-public reachable on an unmodelled auth stack | soundness | The §5.2.9 wrong-fact class |
| **B1** | URL slicer output depends on wall-clock time | reproducibility | Any published number |
| **B2** | Local-path analyses have machine-dependent identity | reproducibility | Artifact portability |
| **B3** | No ground truth, no scorer, no benchmark target in-repo | reproducibility | Every accuracy claim |
| **B4** | Endpoint id collisions drop endpoints, loss unmeasured | accuracy | Endpoint recall |
| **C1** | Auth oracle is Spring-Security-only, and `[]` means two things | honesty | The backstop itself |
| **C2** | Auth oracle covers 1 of 9 enforcement kinds | honesty | Auth blind-spot tracking |
| **C3** | Permissions read only in SCREAMING_SNAKE | generalization | Authority extraction |
| **C4** | `RejectionMarkers` matches `401` inside any literal | precision | Over-withholding |
| **C5** | Apache Shiro's annotation vocabulary is absent | coverage | Non-Spring Java |
| **C6** | Coverage % counts methods the map does not contain | honesty | Consequence of A1 |
| **E4** | The auth fixture varies shape but not vocabulary | validation | Cannot catch A4 |
| **H1** | `schema_version` is written everywhere and read nowhere | compat | Cross-version reads |
| **H2** | Export schema version has drifted between producer and consumer | compat | Version stamp is wrong |
| **H3** | Two independent URI-pattern matchers | DRY | Future divergence |
| **H4** | README describes Phase 1 on a 0.8.2 build | trust | First impression |
| **H5** | No pagination on any list route | scale | Large systems |
| **H6** | `create_app` is 705 lines / 21 routes | maintainability | — |
| **G1** | Bare method-level `@RequestMapping` yields no endpoint | soundness | Endpoint recall |
| **G2** | Verb substring match manufactures phantom endpoints | accuracy | Endpoint precision |
| **G3** | HEAD/OPTIONS/TRACE unreachable inbound, supported outbound | coverage | Verb vocabulary |
| **G4** | Class-level multi-path prefix drops all but the first | soundness | Endpoint recall |
| **G5** | Wire shapes do not walk supertypes | soundness | Schema correctness (§5.2.16) |
| **G6** | Enum-typed fields become empty objects | accuracy | Schema correctness |
| **G7** | No validation constraints; Phase 9 already depends on them | dangling | Phase 9 Tier 1 |
| **G8** | `@RepositoryRestResource` / functional routing unsupported | coverage | Endpoint recall |
| **G9** | An unsupported stack yields a **successful, empty snapshot** | soundness | P10 at repository scale |
| **E1–E3** | Validation layers grade counts, inclusion, and one own-authored fixture | validation | Generalization claims |

The **A/B/C/E/H** findings come from the seam audit (closures, contracts, merge logic, storage).
The **G** findings come from reading `SpringPacks.scala` and `TypeShapes.scala` line by line,
which the first pass did not do. Section 2 classifies every row against the roadmap; section 3
records why they cluster the way they do.

---

## 2. Defect, or future phase? — roadmap attribution

The question this section answers: for each finding, is it a **defect** in something the roadmap
marks shipped, or is it **deliberately deferred** to a later phase that will harden it? The answer
decides whether an item belongs in this plan at all.

Five classes:

| | Class | Meaning |
|---|---|---|
| **D** | Defect | Contradicts something the roadmap marks ✅ shipped |
| **S** | Scheduled | A named phase owns it, correctly |
| **L** | Recorded limit | Documented as a known limitation, unowned, accepted |
| **X** | Dangling dependency | A later phase *depends* on it; no phase *produces* it |
| **U** | Unrecorded | Neither shipped-correct, nor scheduled, nor documented |

| Finding | Class | Basis |
|---|---|---|
| Path feasibility, expression-level flow, `synchronized` | **L** | §5.2.8 trust boundary, explicit |
| Call-site context insensitivity | **L** | §5.2.8 trust boundary, explicit |
| `@Qualifier` bean-name resolution | **S** | `SpringDIPass`: "deferred to Phase 3, recorded here" |
| MQ producer↔consumer pairing | **S** | Phase 3 item 1, explicit |
| Enforcement scope carries no HTTP verb | **L** | `TODOS.md` P2; cost measured at [0, 133] |
| ICPC's deferred-verdict authorizer | **L** | `TODOS.md` P1, with the wrong fix pre-rejected |
| `@JsonInclude`, views, custom serializers | **L** | §5.2.7: "recorded as a refinement" |
| Consumer-side `sends[]` / `reads[]` | **S** | Phase 5, explicit |
| Accuracy dashboard, F1 vs. baselines | **S** | Phase 3 item 5, explicit |
| Non-Spring auth: FastAPI, Django, Express | **S** | Goal 9: "landing with each language's phase" |
| **Apache Shiro / Jakarta-EE-only Java auth** | **U** | Goal 9 maps auth packs to *languages*; Phase 8 is Python/Django/Express. **Java-but-not-Spring is owned by no phase.** |
| **Validation constraints in request schemas** | **X** | Phase 9 Tier 1 reads *"payload vs. recovered request schema **+ validation rules**"*. No phase produces them. |
| A1 — lambda bodies absent from every ICFG | **U** | §5.2.8 trust boundary says *"lambda bodies are their own methods reached via T4"*, which reads as a guarantee they are present |
| A2 — cross-service flow stops at one hop | **U** | Goal 4: *"each endpoint's flow is complete across the whole system"* |
| A3 — DI edge confidence discarded | **U** | `SpringDIPass`: *"tagged distinctly so downstream confidence degrades honestly"* — it does not |
| A4 — `IdentityCalls` is a name list | **U** | §5.2.12: *"not a name on a list … a graph property"* |
| A5 — evidenced-public on an unmodelled auth stack | **U** | §5.2.9 exists to prevent this exact class |
| C1 / C2 — oracle scope and the `[]` ambiguity | **U** | The oracle's own docstring forbids the conflation it performs |
| C3 — SCREAMING_SNAKE-only permissions | **U** | — |
| C4 — `401` matched as a substring of any literal | **U** | — |
| B1 — wall-clock deadline in the slicer | **U** | — |
| B2 — path-derived identity | **U** | §7 identity rule: content-derived and stable across runs |
| B4 — endpoint-id collisions drop endpoints | **L** | Recorded in §7 and surfaced as `EndpointCollision`; the *magnitude* is unmeasured |
| H1 — `schema_version` written, never read | **L** | `TODOS.md` P1, with an observed instance |
| **H2 — export schema version drift** | **D** | CHANGELOG and `CLAUDE.md` record export 2.13.0 as shipped; the producer stamps 2.12.0 |
| **G1 — bare method-level `@RequestMapping` yields no endpoint** | **U** | §5.2.11 concluded endpoint extraction was *"already 365/365"* |
| **G2 — phantom verbs from substring matching** | **U** | — |
| **G3 — HEAD/OPTIONS/TRACE unreachable inbound** | **U** | The contract declares eight verbs; the outbound side recovers HEAD and OPTIONS |
| **G4 — class-level multi-path prefix drops all but the first** | **U** | — |
| **G5 — no supertype walk in wire shapes** | **U** | §5.2.7 enumerates its terminals; a missing inherited field is not one of them |
| **G6 — no enum value enumeration in wire shapes** | **U** | — |
| **G7 — `@RepositoryRestResource` unsupported** | **L\*** | Named in `benchmarking-baselines.md` §10 item 5 only — absent from `architecture.md` and `TODOS.md` |
| **G8 — `RouterFunction` / functional routing unsupported** | **U** | Zero mentions in any document |
| **G9 — unsupported stack ⇒ successful empty snapshot** | **U** | P10 materializes every other unknown; this one is silence, at repository scale. Also the reason W8 Mode B cannot dispatch. |

**The tally: ~8 scheduled or recorded, 2 dangling, 1 hard defect, ~19 unrecorded.**

### What the tally means

The roadmap is a **feature** roadmap. It schedules new capabilities — async semantics, contract
checking, language expansion, federation — and it has no slot for *"the capability we marked ✅ is
narrower than the claim attached to it."* Phase 3 will build auth-consistency analysis on the
enforcement model; nothing in it goes back to ask whether that model can read Shiro. Phase 9 will
build payload simulation on a request schema that has no constraints and no inherited fields.

So the honest answer to *"will a later phase harden this?"* is: **for most of these, no phase is
coming.** That is not a criticism of the sequencing — every phase boundary in §11 is
well-argued — it is a gap in the *kind* of item the roadmap can hold. The **U** class needs a home
that is neither a phase nor prose, which is what the register in the next section proposes.

Two sub-classes deserve separate attention:

- **X — dangling dependencies.** Validation constraints are the clear case: Phase 9's Tier 1 is
  specified as *"payload vs. recovered request schema + validation rules → breaks at the door"*,
  and no phase produces validation rules. This is worse than an unrecorded gap because a later
  phase's design already assumes it exists. Sweep §11 for others before Phase 3 starts.
- **U findings where a comment vouches for behaviour the code does not have.** Three so far:
  `SpringDIPass` on confidence degradation, §5.2.12 on name lists, `auth_oracle` on never
  conflating unknown with clean. These are the most misleading class in the codebase, because a
  reader auditing the design reads the comment and stops.

## 3. The pattern underneath, and the rule it needs

Nineteen unrecorded findings is a number that invites a process answer rather than nineteen point
fixes. Almost all of them share one shape, and the project has already named it.

### The fixture encodes the implementation

§5.2.10 recorded this on 2026-08-05, exactly:

> *"The fixture encodes the implementation. `spring-auth-matrix/SecurityConfig.java` is pure Spring
> Security 5 (`httpBasic().disable()`, `authorizeRequests()`, `antMatchers`), and the config-driven
> chain is written fluently with parameter-injected properties — because that is yas's shape.
> **A fixture authored beside the pass enumerates the shapes the pass handles. P8 makes a fixture
> mandatory; it cannot make it imaginative.**"*

That is the correct diagnosis. It then recurred three more times, unnoticed:

| Pack | Fixture | Shape space it enumerates once | Findings it therefore cannot fail on |
|---|---|---|---|
| `SpringAuthEnforcementPass` | `spring-auth-matrix` | Identity vocabulary: **`getCurrentUserId()`, 5 occurrences, 1 name** | A4, C3 |
| `TypeShapes` | `response-shape-mini` | DTO structure: **no `extends`, no enum field** | G5, G6 |
| `SpringEndpointPass` | all endpoint fixtures | Mapping idioms: **no method-level `@RequestMapping`** | G1, G2, G3 |

§5.2.10's amendment to P8 — *goldens must assert the absence of drops, not only the presence of
expected facts* — was the right instinct and is not sufficient. Absence-of-drops counts things the
fixture **contains**. No golden can count an idiom nobody wrote.

**Proposed P8 counterpart (needs a §2 decision).** A pack's fixture is not complete until its shape
space has been extended by something other than the pass author's imagination. Three admissible
mechanisms, any one of which satisfies it:

1. **Adversarial extension** — a second party (person or model) extends the fixture, having read
   the framework documentation and *not* the pass, and the pass is run against the result before
   the pack is marked complete.
2. **Corpus differential** — the pack is run over a corpus it has never seen and the *idiom census*
   is reported: which shapes appeared, which of them produced no fact. A shape present in the
   corpus and absent from the output is a finding regardless of whether anyone predicted it.
3. **Vocabulary enumeration from the framework, not the corpus** — where the framework publishes a
   closed vocabulary (HTTP verbs, Spring's mapping annotations, the Security DSL), the fixture
   covers the *published* set and any member the pack cannot produce is recorded explicitly. G3 is
   exactly this case: the contract has eight verbs, the extractor can emit five, and no counter
   says so.

Mechanism 3 is the cheapest and should be mandatory; 1 and 2 are alternatives for the open-ended
cases. Note that mechanism 2 is the microSecEnD run already proposed in W6 — the process rule and
the measurement task are the same work.

### A comment is not a test

Three findings are cases where a comment states the correct principle and the code does something
else:

| Location | The comment says | The code does |
|---|---|---|
| `SpringDIPass:99` | name-arity is *"tagged distinctly so downstream confidence degrades honestly"* | The tag is collapsed to a boolean at export and dropped entirely at the contract (A3) |
| §5.2.12 / `SpringSecurityPack` | *"a security annotation is not a name on a list … it is a graph property"* | The binding is a graph property; the **gating test** is a 9-name list (A4) |
| `auth_oracle.py` docstring | *"`None` only when the tree cannot be read; `[]` means checked and clean. The two are never conflated (P10)."* | At the entry gate, a non-Spring service returns `[]` having scanned nothing (C1) |

This is the most misleading class in the codebase: a reader auditing the design reads the comment,
finds it correct, and stops. It is also the cheapest class to eliminate mechanically.

**Proposed rule:** a comment asserting a *property of the output* must have a test asserting the
same property. Not every comment — the vast majority here explain provenance and rationale, which
is the documentation style that makes this codebase readable and must not be disturbed. The rule
binds only on claims of the form "downstream can tell X from Y", "this is never conflated", "this
is not a name list". Each of the three above becomes a one-line assertion.

### The register the U class needs

Nineteen findings that are neither scheduled nor documented need somewhere to live. `TODOS.md`
already holds *accepted* gaps with a queryable line each, which is the right mechanism and the
wrong framing — these are not accepted, they are undiscovered-until-now.

Proposal: `TODOS.md` gains a **"Narrower than claimed"** section, distinct from the existing
priority-ordered lists. An entry there states the *claim* (with its §-reference), the *actual
behaviour*, and the measurement that sizes the gap. An item leaves it in one of two ways — the code
is fixed, or the claim is narrowed in `architecture.md`. Both are fine; silence is not.

That framing matters for the research posture too. Every §5.2.x section is written as a completed
result, and several of them are narrower than they read. Anything published from those sections
should carry its actual scope, which for the auth model today is *Spring Security, three systems,
all Spring*.

## 4. Sequencing, and why


Four constraints fix the order:

1. **Instrument before you change.** W0 (the measurement harness) lands first for the same
   reason §5.4.3's coverage metric landed before T4: without it, every fix below is an
   anecdote instead of a measured before/after. This is the sequencing rule the project has
   already applied once and it applies again.
2. **Reproducibility before measurement is meaningful.** B1 and B2 are two small changes and
   they gate the credibility of everything W0 produces. They ride with W0.
3. **Soundness before depth.** A1 is a hole in the per-endpoint graph; A2 builds depth on top
   of that graph. Fixing A2 first would extend a graph that is still missing nodes.
4. **Auth generalization is independent** and can run in parallel with everything else — it
   touches `SpringSecurityPack.scala` and the auth fixture, and nothing in W1–W3 does.

Proposed grouping:

| Workstream | Contents | Blocks |
|---|---|---|
| **W0** Measurement & reproducibility | B3, B1, B2, B4, H2 | everything |
| **W1** ICFG completeness | A1, C6 | W2, Phase 3 |
| **W2** Cross-service depth | A2 | Phase 3 async |
| **W3** Edge honesty | A3 | Phase 3 auth-consistency |
| **W4** Auth generalization | A4, A5, C1–C5, E4 | Phase 3 auth-consistency |
| **W5** Contract & hygiene | H1, H3, H4, H5, H6 | — |
| **W7** Extraction breadth | G1–G8 | Phase 9 (via G7) |
| **W8** Hybrid extraction layer | §5.6 + E-A/E-B/E-C, two modes | — (gated behind the paper) |
| **W6** Validation breadth | E1–E3 | publication |

W4 and W0 can start together. W1 → W2 is a hard order. W3 is independent of both.

**W7 is sequenced before W6** despite the label: G1, G2 and G4 all move the endpoint count, and
W6's microSecEnD run is the measurement that scores it. Running W6 first would establish a
baseline against a known-wrong extractor. The labels are kept stable because earlier revisions of
this document are already referenced by number.

**G7 (validation constraints) is the exception and should land early, out of band.** It is the
cheapest item in W7, it is the only class-**X** finding with a named downstream consumer, and
Phase 9 cannot start without it.

**W8 is gated and runs last.** It is roughly a quarter of work, nothing in W0–W7 depends on it,
and its three go/no-go experiments cannot run without W0's scorer. It should not start before the
paper is out. **G9 is its hard prerequisite** — with no CPG, no service record and no gap entry,
Mode B has no dispatch point at all; G9 is also worth fixing on its own merits, independently of
whether W8 ever happens.

---

## 5. W0 — Measurement and reproducibility


Nothing else in this document can be reported as an improvement until W0 exists.

### B3 — The corpus measurements are not reproducible from the repo

**Symptom.** Every accuracy figure wadi has published — 365/365 endpoints, 804/804 handlers,
14/14 permissions, 562 endpoints gaining a policy, `withheld` 7 → 0 — was produced by a script
that no longer exists. The conformance suite proves *not broken*; nothing proves *how good*.

**Evidence.** `TODOS.md` records this as P1 and it is confirmed: no ground-truth file exists
anywhere in the tree (`grep -rl 'ground.truth' --include='*.json'` returns nothing), and there
is no `make` target between `test` and `e2e` that scores anything.

**Fix.** A `wadi-bench` package with three pieces, kept deliberately separate:

1. **`bench/groundtruth/<corpus>.yaml`** — the expected facts, hand-verified, committed. One
   file per corpus, pinned to a commit SHA. Start with three: `train-ticket-aitest`, `icpc`,
   and one microSecEnD app. Schema: a list of endpoints (`verb`, `uri`, `auth.authenticated`,
   `auth.roles`) plus a list of expected service-to-service edges. Unknown entries are written
   as `null`, never omitted — the ground truth obeys P10 too.
2. **`bench/score.py`** — reads a wadi export bundle (`wadi export`, which already exists) and a
   ground-truth file, emits precision / recall / F1 per fact class: endpoints, endpoint+verb,
   auth claim, roles, service edges, endpoint-to-endpoint edges. Plus the non-scored honesty
   counters straight off the coverage report (`withheld`, `no_evidence`, `unresolved`,
   `cfg_anomalies`, `endpoint_collisions`).
3. **`make benchmark`** — runs the scorer against a stored bundle and diffs against
   `bench/expected/<corpus>.json`, the same golden pattern the Scala fixtures already use.
   `WADI_REGEN_BENCH=1` regenerates.

Deliberately **not** part of it: running the analysis. Scoring reads a bundle. That keeps the
scorer runnable in CI without Docker and makes the numbers reproducible from an artifact
anyone can be handed.

**Verified by.** `make benchmark` in CI on a committed bundle; the golden diff makes a
regression loud. First run establishes the baseline; every later number is a delta against it.

**Rejected.** *Scoring inside `pytest` against a live stack* — couples the credibility artifact
to Docker availability and makes it unrunnable by a reviewer. *Deriving ground truth from
wadi's own output* — that is not ground truth, that is a snapshot test, and the project already
has those.

### B1 — The URL slicer's output depends on wall-clock time

**Symptom.** The same source can yield a resolved URL on one machine and
`slice-budget-truncated` on another, which changes stitched edges.

**Evidence.** `joern-platform/src/main/scala/wadi/slicing/UrlSlicer.scala:78,119,123` —
`deadlineNanos = 3_000_000_000L`, checked as `(System.nanoTime() - start) < budget.deadlineNanos`
inside `Budget.spend()`. This is the only wall-clock dependency in the analysis path; a sweep
for `Random`, `nanoTime`, `currentTimeMillis` and parallelism across `libs/`, `services/` and
`joern-platform/src/main` returns nothing else. Content-derived ids, `LinkedHashMap`/
`LinkedHashSet` ordering and single-threaded extraction make everything else deterministic.

**Fix.** Delete `deadlineNanos` and the `System.nanoTime()` check. `maxVisited` (512) already
bounds the walk deterministically; if the observed worst case needs a tighter bound, lower
`maxVisited` — a node budget is reproducible, a time budget is not.

**Verified by.** A test that runs the slicer twice over the `restclient-yas-mini` fixture under
artificial load and asserts byte-identical candidate lists. Cheaper and stronger: a CI grep
banning `System.nanoTime`/`currentTimeMillis` in `joern-platform/src/main`, in the same spirit
as the existing GPL license scan.

**Rejected.** *Raising the deadline* — a larger nondeterministic window is still
nondeterministic. *Making the deadline configurable* — moves the reproducibility problem into
the operator's environment, which is worse.

### B2 — Local-path analyses have machine-dependent identity

**Symptom.** `wadi analyze .` on the same commit produces entirely different endpoint ids on two
machines, so two labs cannot compare or join artifacts.

**Evidence.** `libs/wadi-contracts/src/wadi_contracts/ids.py` — `normalize_repo_source` returns a
local path verbatim (`src.rstrip("/")`); `service_id = hash("service", normalized_repo,
build_root)`; `endpoint_id = hash("endpoint", service_id, verb, simplified_uri)`. The `--repo
<url>` path is canonicalized and stable; the local path is not.

**Fix.** Two parts.
- Add an optional `identity_key` to `System`. When present, `service_id` is derived from it
  instead of the repo source, so a local checkout can be pinned to the same identity the URL
  form would give. The CLI grows `wadi analyze . --identity <key>`, and — the useful default —
  when the local checkout has an `origin` remote, derive the key from that remote automatically
  and say so in the output.
- Document in the README that reproducible artifacts come from `--repo <url>` or an explicit
  `--identity`.

**Verified by.** A test asserting that a local checkout with an `origin` remote yields the same
`service_id` as analyzing that remote by URL.

**Rejected.** *Always deriving from `origin`* — a fork or a local-only repo has no meaningful
remote and silently inheriting one would be a wrong identity, not a missing one. *Hashing repo
content* — changes on every commit, which defeats the purpose of a stable id.

### B4 — Endpoint id collisions drop endpoints, and the loss is unmeasured

**Symptom.** `GET /users/{id}` and `GET /users/{name}` both simplify to `/users/{?}`, collide on
`endpoint_id`, and one is dropped. Handled honestly — deterministic winner, `EndpointCollision`
recorded — but it directly lowers the endpoint count that will be published against Code2DFD
(0.66) and RAD (0.79).

**Evidence.** `services/extraction-worker/src/wadi_worker/assembler.py:129` and
`libs/wadi-contracts/src/wadi_contracts/ids.py:endpoint_id`. `UNMEASURED`: the collision count
has not been reported for train-ticket or ICPC. The ICPC figure quoted in `TODOS.md` is
`collisions (0)` on one run, which — if it holds across both corpora — makes this a documented
non-issue rather than a defect.

**Fix.** Measure first. If the count is zero on both corpora, close this with the measurement
recorded and change nothing. If it is not zero, the identity form gains a disambiguator (the
handler's parameter-name tuple) rather than the URI gaining precision — the simplified URI is
load-bearing for stitching and must keep absorbing templates.

**Verified by.** `make benchmark` reports `endpoint_collisions` as a first-class counter.

### H2 — The export schema version has drifted between producer and consumer

**Symptom.** The stamp on every artifact understates what the artifact contains.

**Evidence.** `WadiExport.scala:81` declares `ExportSchemaVersion = "2.12.0"`.
`libs/wadi-joern-client/src/wadi_joern_client/export.py:15` declares
`EXPORT_SCHEMA_VERSION = "2.13.0"`. `CLAUDE.md` and the CHANGELOG both record export 2.13.0 as
shipped with §5.2.16 (`type_defs`) — and the Scala side *does* emit `type_defs`
(`WadiExport.scala`, `if (typeDefs.nonEmpty) obj("type_defs") = typeDefs.toJson`); only the
constant was not bumped. Every export.json under `joern-platform/target/` carries `"2.12.0"`.
Nothing fails today because `ServiceExport.is_compatible` compares only the major
(`split(".", 1)[0]`), which is exactly why it went unnoticed.

**Fix.** Bump the Scala constant to `2.13.0`, and add the test that would have caught it: the
cross-language golden (`services/extraction-worker/tests/test_real_export.py`) already reads a
real export produced by the Scala suite, so it can assert
`export.export_schema_version == EXPORT_SCHEMA_VERSION` outright.

**Verified by.** That assertion, in CI, on every build. The versioning mechanism cannot drift
undetected again.

**Rejected.** *Widening `is_compatible` to compare minors* — that turns a silent stamp error
into a hard failure across a version boundary, which is H1's problem and needs H1's decision
first.

---

## 6. W1 — ICFG completeness


### A1 — Lambda bodies reach no endpoint ICFG

**Symptom.** Work inside a lambda — `orders.forEach(o -> repository.save(o))`,
`items.map(i -> client.get(...))` — appears on no endpoint's flow graph. If the lambda contains
a `sink=db` or `sink=http-client`, the endpoint's map does not show that call. For a product
whose framing is *the developer reads the map, not the code*, this is the failure class §5.2.8's
trust boundary exists to forbid.

**Evidence.** Two closures disagree, and the export cannot carry the difference.

- `WadiExport.reachableClosure` widens over `METHOD_REF` targets, anonymous-class bodies and
  `<init>`/`<clinit>` (§5.4.2 T4). Lambda bodies enter the export.
- `ExportCfgNode` (`libs/wadi-joern-client/src/wadi_joern_client/export.py:222`) carries only
  `call`. **There is no method-ref edge in the wire format.**
- `Assembler._reachable_closure`
  (`services/extraction-worker/src/wadi_worker/assembler.py:317`) follows only
  `node.call.resolved and node.call.callee_id`, so it structurally cannot follow a lambda
  binding.

Measured against the committed fixture exports:

| Fixture | Methods in export | In ≥1 endpoint ICFG | Orphaned | Lambdas in export | Lambdas in any ICFG |
|---|---|---|---|---|---|
| `control-flow-matrix` | 65 | 55 | 10 | 3 | **0** |
| `spring-auth-matrix` | 88 | 20 | 68 | — | — |

`control-flow-matrix` publishes `analysis_coverage: 57/58` (98%) while three of those methods
appear in no ICFG at all.

The service-level graph is unaffected: `Assembler._build_remote_calls` walks `export.sinks`
directly, so a lambda-hosted outbound call still becomes a `RemoteCall` and still stitches. What
is lost is **endpoint attribution** — and therefore the flow canvas, `endpoint_icfg`, and
`downstream`.

**Fix.** Three changes, in order.

1. **Export the binding.** Add `method_refs: list[int]` to `ExportCfgNode` — the ids of methods
   this statement binds via `METHOD_REF` (lambdas, `this::x`, `Foo::bar`). The exporter already
   walks `current.ast.isMethodRef` in `reachableClosure`; the same traversal scoped to a
   statement's subtree, mapped through the existing `nearestEnclosingStatement`, gives the node
   its refs. Export minor bump.
2. **Follow it.** `Assembler._reachable_closure` enqueues `node.method_refs` alongside
   `node.call.callee_id`. `_emit_method_subgraph` emits a `CALL`/`RETURN` edge pair per ref, the
   same way it does for a resolved callee — a lambda invoked by a stream *is* a call, just one
   the frontend spells differently.
3. **Decide the constructor question separately.** `<init>` bodies are also orphaned (7 of the
   10 above). DI-bean constructors were deliberately included in the *export* closure because
   Spring beans are never `new`ed in user code. Whether they belong in a per-endpoint graph is a
   genuine question — a constructor runs once at startup, not per request — and the honest answer
   is probably *no, and say so*. Record the decision; do not fold it into the lambda fix.

**Verified by.** A standing invariant, in the spirit of `cfg_anomalies`: after assembly, the set
of export-closure method ids minus the union of ICFG method ids must be **empty except for
methods on a recorded exclusion list** (`<init>`, `<clinit>`, and async-root closures that no
endpoint reaches). Any other orphan is a new `CfgAnomalyCode.UNATTRIBUTED_METHOD`, counted per
service and surfaced in the coverage report. That makes A1 impossible to reintroduce silently,
and it is the queryable line P10 requires for whatever remains.

Plus a fixture case: a controller whose handler does its database write inside
`list.forEach(x -> repo.save(x))`, with a golden asserting the sink is on the endpoint's ICFG.

**Rejected.** *Inlining lambda bodies into the enclosing statement* — destroys the
construct-level fidelity Phase 2.6 was built for, and a lambda body has its own branches and
loops. *Leaving it and documenting it* — the trust boundary already says lambda bodies are
"reached via T4", which a reader takes to mean the ICFG contains them; documenting harder does
not make the map complete.

### C6 — Coverage percent counts methods the map does not contain

**Symptom.** A user reads `analysis_coverage` as "how much of my code the map walks". It measures
the export closure, which is strictly larger than what any ICFG shows.

**Evidence.** Same table as A1. §5.4.3's definition is internally coherent — it explicitly counts
lambdas in the numerator and explicitly rejects "deriving coverage from ICFG node counts". The
gap is that nothing publishes the delta between the two.

**Fix.** Falls out of A1's invariant: once unattributed methods are counted, the coverage section
gains an `unattributed_methods` figure beside `reachable_methods`. Two numbers, both true, and
the difference is visible rather than inferred. No change to the §5.4.3 definition — it was
right; it was just the only number on the page.

---

## 7. W2 — Cross-service depth


### A2 — Cross-service flow stops at one hop

**Symptom.** Product goal 4 says *"each endpoint's flow is complete across the whole system"*.
Today an agent or a user can see that endpoint A calls endpoint B, and must start over to learn
what B calls. There is no way to ask "what does this request ultimately touch".

**Evidence.**

- **MCP gives exactly one hop.** `services/mcp-server/src/wadi_mcp/service.py:157`,
  `_annotate_cross_service` — its own docstring: *"Depth-1 by design: the downstream list gives
  the analyzed endpoints an agent can recurse into with further endpoint_icfg calls."* It does
  give real `target_endpoint_id`s, so the chain is walkable client-side.
- **Neo4j structurally cannot chain.** The graph is
  `Service -[:EXPOSES]-> Endpoint`, `Service -[:HAS_CALL_SITE]-> RemoteCall`,
  `RemoteCall -[:INVOKES_REMOTE]-> Endpoint`. **`RemoteCall` hangs off the Service, never off
  the calling Endpoint**, and the `RemoteCall` contract carries `method: MethodRef` but no
  caller endpoint. A variable-length Cypher path therefore routes through `Service` at every hop
  and degrades "endpoint A reaches X" into "*some* endpoint of A's service reaches X". The
  orchestrator states the constraint plainly: *"a remote call belongs to an endpoint only via its
  flow"* (`app.py:610`). Tier 2 — the tier that exists for cross-service traversal — cannot do it.
- **REST and UI have nothing.** The only cross-service route, `endpoint-dependencies`, returns
  service-name labels, not target endpoint ids. `grep -rn 'target_endpoint_id' frontend/`
  returns **zero** hits outside generated types: the UI cannot follow a call even one hop.
- **No cycle protection anywhere.** `A → B → A` is ordinary in microservices; nothing tracks a
  visited set, so a recursing agent loops until its context runs out.
- **Confidence does not compose.** Each hop carries its own; nothing combines them, so four
  chained heuristic guesses read like one proven hop.
- **Async hops are dead ends.** Publishers become `mq_interactions`, consumers are detected as
  `async-root` kinds (`kafka-listener`, `rabbit-listener`), and the stitcher only *counts* them
  (`pipeline.py:145`) — it never pairs producer to consumer. `_annotate_cross_service` does not
  look at `mq_interaction_id` at all.

**Fix.** Four changes; the first unblocks the rest and is small.

1. **Record who owns each call site.** Add `caller_endpoint_ids: list[str]` to `RemoteCall`. The
   assembler already knows it — `IcfgNode.remote_call_ids` is built per endpoint in
   `_emit_method_subgraph` — it simply is not written back onto the call fact. One endpoint may
   own a call site through several flows, hence a list; a call reached only from an async root
   has an empty list, which is already meaningful and matches `reachability`.
2. **Give Neo4j the edge.** `Endpoint -[:MAKES_CALL]-> RemoteCall` in
   `GraphRepository.replace_snapshot`. With it, the whole chain is one Cypher query:
   `MATCH path = (e:Endpoint {...})-[:MAKES_CALL|INVOKES_REMOTE*1..N]->(t) RETURN path`.
3. **Ship `flow_trace`.** One implementation, three surfaces — MCP tool, REST route,
   `wadi flow-trace` CLI. Signature:
   `flow_trace(snapshot_id, endpoint_id, max_depth=3, include_async=False)`. Returns a tree of
   hops, each carrying the calling endpoint, the call site anchor, the target, that hop's
   confidence, and a **path confidence** = `min` over the hops (the same rule
   `confidence_min` already applies within a single edge, applied along a path). Every leaf
   carries an explicit terminal: `analyzed` · `external` · `placeholder` · `undetermined` ·
   `depth-limit` · `cycle` · `async-unpaired`. A visited set is carried down the walk and a
   revisit terminates that branch as `cycle` — never silently, because a cycle is a fact about
   the system worth seeing.
4. **Let the UI follow it.** Once `target_endpoint_id` reaches the frontend, "click the
   downstream call, open its flow" is a routing change over data that already exists.

Async pairing (`mq_interaction` producer ↔ `@KafkaListener` consumer) stays Phase 3 item 1, and
`flow_trace` reserves `include_async` plus the `async-unpaired` terminal now so that landing it
is additive rather than a signature change.

**Verified by.** The `petstore-system` two-service fixture grows a third service so a real
A → B → C chain exists, with a golden on the trace shape. A cycle fixture (A → B → A) asserts
the `cycle` terminal fires and the walk terminates. `make benchmark` scores
endpoint-to-endpoint edges, which is the fact class this unlocks and which no prior tool has
published on TrainTicket.

**Rejected.** *Server-side unbounded expansion* — fan-out on ICPC would be enormous and would
put the whole system in one response; `max_depth` plus explicit terminals keeps the answer
bounded and honest. *Computing the trace in the stitcher and storing it* — it is derived data
over two artifacts that already exist, and storing it means invalidating it. *Leaving the walk
to the agent* — the agent cannot dedupe cycles it cannot see, cannot compose confidence, and
pays a round trip per hop into the surface whose entire purpose is to save context.

---

## 8. W3 — Edge honesty


### A3 — Call-graph edges carry no confidence

**Symptom.** In the ICFG, a call resolved to a single proven implementation looks exactly like a
call fanned out to every implementation of an interface because wadi could not tell which. The
reviewer question *"what fraction of your graph edges are over-approximated?"* is currently
unanswerable from the artifacts.

**Evidence.** `SpringDIPass` computes four strategies — `exact`, `primary`, `ambiguous`,
`name-arity` — and tags the call
(`joern-platform/src/main/scala/wadi/passes/SpringDIPass.scala:107`). Its own comment on the
name-arity fallback reads: *"Tagged distinctly so downstream confidence degrades honestly."* It
does not. `WadiExport.scala:1636` collapses the tag to a boolean (`val viaDi =
call.tag.nameExact("wadi-di").nonEmpty`), and `IcfgNode` drops even the boolean —
`grep -rn 'via_di' libs/wadi-contracts/` returns nothing. `IcfgEdge` has `kind`, `case_values`
and `back`, and no confidence field.

This is the sharpest internal inconsistency in the system: the stitcher applies a rigorous
four-tier confidence to URLs and the ICFG applies none to calls, in the artifact that carries
the load-bearing claim.

**Fix.**

1. Export the strategy, not a boolean: `ExportCall.di_strategy: "exact" | "primary" |
   "ambiguous" | "name-arity" | null`. Keep `via_di` for one release as the deprecated boolean,
   the same pattern `remote_call_id` → `remote_call_ids` already used.
2. Carry it to the contract: `IcfgNode.call_resolution`, using the existing `Confidence`
   vocabulary — `exact` → EXACT, `primary` → HIGH (Spring's own documented disambiguation rule),
   `ambiguous` and `name-arity` → HEURISTIC.
3. Count it: the coverage report gains a `call_resolution` breakdown per service, beside
   `analysis_coverage`. That is the number a reviewer asks for, and it becomes a tracked
   per-release figure like the rest.
4. Render it: an over-approximated call is drawn distinctly on the canvas. The visual grammar is
   the designer's call, but it must not be a coloured left bar.

**Verified by.** A fixture with an interface carrying two implementations and no `@Primary`,
asserting `ambiguous` reaches the ICFG node; and `make benchmark` reporting the ratio on both
corpora, which also finally sizes the question.

**Rejected.** *Emitting only the ambiguous case* — a consumer cannot tell "proven" from "not
recorded", which is the unknown-versus-clean conflation P10 forbids. *A new confidence
vocabulary for calls* — one vocabulary, already registered, already understood by every surface.

---

## 9. W4 — Auth generalization


The starting question was whether the auth model is overfit to ICPC. The audit's answer is
specific: **the architecture generalizes, one discriminator does not, and the fixture cannot
detect that because it speaks the same dialect.**

### What is already generic, and must not be disturbed

Recorded because the fixes below should not be read as a rewrite. A search of
`SpringSecurityPack.scala`, `auth_merge.py` and `auth_oracle.py` for
`icpc|contest|trainticket|yas|ts-*-service` finds **every hit inside a comment** explaining a
rule's provenance, and **none in executable code**. Substantively:

- `AccessCallNames` is the complete Spring Security DSL access vocabulary, not a corpus subset;
  `SpringAnnotations` and `Jsr250Annotations` are the complete framework sets.
- The project-defined annotation machinery does exactly what §5.2.12 promised: `relation =
  kebab(annotation.name)` derives from the annotation's own name, `resourceType` from the
  `X.class` shape, and the binding from the advice parameter type, the `@annotation(...)`
  designator, or a `getMethodAnnotation` read. Its comment states the principle and the code
  keeps it.
- Scope is the set of annotated methods, never the registration path.
- The merge logic's reasoning about layered conjunction versus first-match-wins alternatives is
  framework-independent.
- `if not evidence: return EndpointAuth()` — a wholly unmodelled stack lands in `no_evidence`,
  not in a false `authenticated=False`.
- 54 conformance tests with genuine negative controls, including a non-gating aspect with a
  byte-identical binding shape.

### A4 — The gating discriminator is a name list

**Symptom.** A guard written in a vocabulary wadi does not know is invisible, and its endpoints
publish as if it were not there.

**Evidence.** `gates()` is `rejects || decides || judges`
(`SpringSecurityPack.scala:1404`). The branch that fires on voting authorizers is
`judges = touchesIdentity(method) && method.ast.isControlStructure.nonEmpty`, and
`touchesIdentity` is:

```scala
private val IdentityCalls = List(
  "getauthentication", "getprincipal", "getsubject",      // framework APIs
  "getcurrentuser", "getcurrentuserid", "getcurrentusername",
  "getcurrentprincipal", "getloginid", "getloginuser"     // naming conventions
)
```

Three of nine are real framework APIs (Spring Security, JAAS, Shiro). **Six are conventions ICPC
happens to use.** A codebase writing `currentAccount()`, `me()`, `requester()`, `sessionUser()`,
`getActor()`, `resolveCaller()` or `userContext()` scores zero. `DecisionCalls` (13 names) has
the same character on the secondary branch.

§5.2.12 records the lesson as *"a security annotation is not a name on a list, it is an
annotation whose consumer can deny the request — which is a graph property."* That is correct,
and it is what the *binding* logic does. The test that decides whether the consumer can deny is
a name list one level down.

**Fix.** Make identity a **type** property, which is the same move §5.2.12 already made for the
binding. A method touches identity when it reaches a value of a principal type:

- a parameter, field or local whose type is `java.security.Principal`,
  `org.springframework.security.core.Authentication`, `...core.userdetails.UserDetails`,
  `org.apache.shiro.subject.Subject`, `jakarta.servlet.http.HttpServletRequest.getUserPrincipal`;
- any read of `SecurityContextHolder` (already covered, keep it);
- a call whose **return type** is a type the CPG can see carrying an identity shape — a type
  named by an authentication mechanism record, or the declared type of a `@AuthenticationPrincipal`
  parameter anywhere in the same CPG.

Keep `IdentityCalls` as a **named fallback**, demoted below the type test and marked in the
evidence trace so a claim resting on a name match is distinguishable from one resting on a type.
That preserves ICPC's detection while removing the dependency on ICPC's spelling.

**Verified by.** E4's fixture work below, which is what makes this checkable at all.

**Rejected.** *Growing `IdentityCalls`* — the anti-pattern §5.2.12 exists to end, and it never
converges. *Dropping the name list entirely* — ICPC's `TenantDirectory.getCurrentUserId()`
returns a `Long`, so the type test alone would lose the case the tranche was built for; the
honest arrangement is both, with the weaker one labelled.

### E4 — The fixture varies shape but not vocabulary

**Symptom.** The auth fixture cannot fail on A4.

**Evidence.** Every identity read in the entire fixture, all five of them, is the same call:

```
UnusedScopeAuthorizer.java:25,48   getCurrentUserId(
TenantAdminAuthorizer.java:33,65   getCurrentUserId(
RequiresLoginInterceptor.java:29   getCurrentUserId(
```

The fixture renamed the *domain* (Tenant for Contest) and not the *vocabulary*. It enumerates the
shape space excellently — voting versus throwing, annotation-bound versus path-scoped,
JAR-declared annotations, unused annotations, same-shape-but-non-gating — and enumerates the
identity-vocabulary space exactly once, with ICPC's word.

This is P8's own amendment turned on itself: *a fixture must enumerate the framework's shape
space, not the corpus's.* Here the relevant space is "ways to read who the caller is."

There is also **no negative case for a construct that reads identity without gating** — an audit
aspect doing `log.info("user {} called {}", currentUser(), sig)` inside an `if`. That scores
`judges = true` today and would withhold claims across its whole scope. It is ordinary code and
it is untested.

**Fix.** Extend `spring-auth-matrix`:

- Four more **gating** authorizers, each reading identity a different way: a `Principal`
  method parameter; `SecurityContextHolder.getContext().getAuthentication()`; Shiro's
  `SecurityUtils.getSubject()`; and one deliberately idiosyncratic name (`currentAccount()`)
  that only the type test can catch.
- One **non-gating** aspect that reads identity and branches — the audit logger. Its golden
  asserts *no* enforcement record. This is the missing negative control and the likeliest
  false positive in real code.
- One handler using Shiro's `@RequiresRoles("admin")` (see C5).

**Rejected.** *Testing this only on a real corpus* — a corpus proves the shapes it contains and
the next system's shapes are the ones that matter; the fixture is where the space is enumerated.

### A5 — Evidenced-public is reachable on an unmodelled auth stack

**Symptom.** The §5.2.9 wrong-fact class, reachable through a different door: an endpoint
publishes a confident `authenticated=false` while a guard wadi cannot see protects it.

**Evidence.** `no_evidence` protects the case where wadi reads *nothing*. It does not protect the
case where wadi reads something *permissive*. Concretely: a service with
`anyRequest().permitAll()` in a Spring chain **and** a Shiro annotation wadi does not detect →
evidence exists, `gating` is non-empty and permissive, no guard is registered as opaque, so
`_opacity_could_change_the_answer` sees nothing to withhold on → `authenticated=False`, evidenced
public. `UNMEASURED` on a real corpus — no non-Spring-Security system has been analyzed.

**Fix.** A guard's *absence from the model* must be as visible as its presence. Two parts:

1. **A vocabulary census on every snapshot.** The auth oracle (C1) grows a scan for
   auth-shaped constructs it can name but the model does not consume — Shiro annotations, JAX-RS
   `@RolesAllowed` outside the JSR-250 path, `@Secured` variants from other frameworks, and any
   annotation whose name matches an auth-shaped pattern and reaches no enforcement record. Each
   becomes an `AuthGapCode.UNMODELLED_VOCABULARY` finding with its sites.
2. **Withhold on the census, not just on opacity.** When a service reports unmodelled auth
   vocabulary and an endpoint's only gating evidence is permissive, the claim is withheld rather
   than published as `false`. This is the §5.2.9 rule — *an unread guard that could change the
   answer withholds it* — extended from "a guard we saw and could not read" to "a guard we can
   see the shape of and do not model."

**Verified by.** A fixture service with a permissive Spring chain plus a Shiro-annotated handler,
whose golden asserts `withheld`, not `false`. And the W6 corpus run, which is the only thing that
sizes the real-world frequency.

**Rejected.** *Withholding on any unmodelled construct anywhere in the service* — that is the
blanket §5.2.12 spent a tranche removing; the trigger must be "and the readable evidence is
permissive", which is the narrow case where the unknown actually flips the answer.

### C1 — The oracle is Spring-Security-only, and `[]` means two things

**Symptom.** The independent backstop reports "checked and clean" for services it never looked at.

**Evidence.** `auth_oracle.py` gates every file on
`_SECURITY_CONFIG = authorizeHttpRequests|authorizeRequests|authorizeExchange|SecurityFilterChain|
SecurityWebFilterChain|WebSecurityConfigurerAdapter` — six Spring Security identifiers. On a
Shiro, Jakarta-EE or gateway-enforced service nothing matches, nothing is scanned, and the
function returns `[]`, which `build_cfg_anomalies`' sibling convention defines as *checked and
clean*. The module's own docstring says *"Returns None only when the tree cannot be read; []
means checked and clean. The two are never conflated (P10)."* At its entry condition, they are.

**Fix.** A third state. `scan_auth_extraction` returns findings that include an explicit
`AuthGapCode.NO_SECURITY_CONFIG_FOUND` when a service has controllers but no file matched the
entry gate — so "nothing to check here" is a fact rather than a silence. Pair it with the C5
vocabulary broadening so the gate stops being Spring-only in the first place.

### C2 — The oracle covers one of nine enforcement kinds

**Symptom.** A dropped `@PreAuthorize`, a missed aspect, an unread interceptor and a config
policy have no independent check at all.

**Evidence.** `_ACCESS_CALL` counts chain access calls and nothing else. `AuthEvidenceKind` has
nine members: `annotation`, `security-dsl`, `config`, `chain-bypass`, `interceptor`,
`servlet-filter`, `aspect`, `in-handler`, `gateway`, plus `authority-model`. The oracle checks
`security-dsl`.

**Fix.** Extend the same deliberately-dumb regex approach to the cheapest high-value kind:
**annotations**. Count `@PreAuthorize|@PostAuthorize|@Secured|@RolesAllowed|@PermitAll|@DenyAll`
occurrences in stripped source per file, and diff against the annotation evidence the export
carried. That is the kind most likely to be silently dropped by a meta-annotation or inheritance
miss, and it is a dozen lines. Interceptors, filters and aspects are structural rather than
textual and are honestly out of a regex oracle's reach — record that as an accepted limit with
its own line rather than implying coverage.

### C3 — Permissions are read only in SCREAMING_SNAKE

**Evidence.** `EnumConstant = """\b[A-Za-z_][\w.]*\.([A-Z][A-Z0-9_]{2,})\b"""`. Run against
realistic idioms:

| Annotation | Authorities read |
|---|---|
| `@ContestManager(context = Contest.class, acl = ACLEnum.CONTEST_UPDATE)` | `[CONTEST_UPDATE]` |
| `@ScopeRequired(scope = Scopes.READ_ORDERS)` | `[READ_ORDERS]` |
| `@RequiresPermission("contest.update")` | **`[]`** |
| `@HasPermission(Permission.ContestUpdate)` | **`[]`** |
| `@Authorize(role = Role.Admin)` | **`[]`** |
| `@RequiresRoles("admin")` | **`[]`** |

Four of six read nothing. A string-valued permission is at least as common as an enum one, and
`@RequiresRoles("admin")` is mainstream Shiro. The failure lands as `effect=UNKNOWN,
resolution=OPAQUE` → withheld: safe, and it rebuilds the wall of unknowns the tranche removed.

**Fix.** Read three shapes, each with its own confidence: SCREAMING_SNAKE enum constants
(unchanged, exact); a single string-literal argument (high — it is what the developer wrote); a
PascalCase enum constant on a type whose name matches a permission/role shape (heuristic). The
confidence rides into `AuthEvidence.resolution` so a heuristically-read permission is
distinguishable from a proven one.

**Rejected.** *Reading every string argument as a permission* — an annotation carrying a
`message = "..."` would manufacture authorities, which is worse than reading none.

### C4 — `RejectionMarkers` matches `401` inside any literal

**Evidence.** `SpringSecurityPack.scala:1405` —
`method.ast.isLiteral.code.exists(code => RejectionMarkers.exists(code.contains))` with
`RejectionMarkers` including bare `"401"` and `"403"`. `"4013".contains("401")` is true, so a
timeout of `4030`, a port, or an id `1401` makes an unrelated interceptor read as a gate. The
call-code branch guards with `marker.length > 3`; the literal and identifier branches do not.

**Fix.** Apply the same `marker.length > 3` guard to the literal and identifier branches, or
require a word boundary on the numeric markers. Over-withholding is the safe direction but it is
not free — it is the noise that trains readers to ignore the state.

### C5 — Apache Shiro's vocabulary is absent

**Evidence.** `@RequiresRoles`, `@RequiresPermissions`, `@RequiresAuthentication`,
`@RequiresUser`, `@RequiresGuest` appear in no list. Shiro's `getSubject()` is in
`IdentityCalls`, so an aspect route might catch a Shiro-based guard by accident; the annotations
themselves produce nothing.

**Fix.** Add the five names to the annotation vocabulary with their own evidence kind mapping,
and add the fixture handler from E4. Small, and it is the cheapest possible widening of the
framework claim beyond Spring.

### Corpus breadth — the standing caveat

The auth model has been validated against three systems: train-ticket (JWT filter + YAML
policy), yas (OAuth2 + config-bound rules), ICPC (project-defined annotations + AspectJ).
**All three are Spring.** Zero Shiro, zero Jakarta-EE-only, zero gateway-enforced, zero non-Spring
Java. Every generalization claim in §5.2.9–§5.2.13 should carry that sentence until W6 runs.

---

## 10. W5 — Contract and hygiene


### H1 — `schema_version` is written everywhere and read nowhere

**Symptom.** An older stack reading a newer stack's artifacts fails with a raw Pydantic error
that names a field, not a version. From the UI it reads as a wadi bug.

**Evidence.** Already recorded in `TODOS.md` as P1, with an observed instance: a 0.8.2 stack wrote
endpoints at contracts 1.25.0, an older stack came up against the same Mongo, and the list route
500'd with `Extra inputs are not permitted: type_defs`. `schema_version` is stamped by
`ArtifactEnvelope` on every document; the only consumer of any version field anywhere is
`ServiceExport.is_compatible`, at the Scala→Python boundary.

`extra="forbid"` is deliberate and correct — it is what caught the `type_defs` projection leak —
so the fix is not to loosen it.

**Fix.** This needs a §7 decision before code. The recommendation: **refuse at the door with a
message that names both versions.** A read-side check in `wadi-storage` compares the document's
`schema_version` major/minor against the reader's `SCHEMA_VERSION` and, when the document is
newer, raises a typed `ArtifactTooNewError` carrying both versions and the collection. The API
turns it into a 409 with "this snapshot was written by wadi ≥ X; this stack is Y — run
`wadi up` to upgrade." One check, one place, and the failure becomes actionable.

**Rejected.** *A read-side compatibility mode that tolerates unknown fields on minor-newer
documents* — plausible, and it silently discards data the newer producer thought was important;
if it is later wanted, it should be a per-model opt-in, not a global relaxation.

### H3 — Two independent URI-pattern matchers

**Evidence.** `services/stitcher/src/wadi_stitcher/matching/paths.py::path_match` and
`services/extraction-worker/src/wadi_worker/auth_merge.py::_ant_precision`. They answer different
questions — call-path against endpoint identity, security pattern against endpoint URI — but both
encode the same asymmetry: *a template absorbing a literal is honest in one direction and not the
other.* §5.2.13 discovered and fixed that in the auth matcher. Both are currently correct; the
risk is a future fix landing in one.

**Fix.** Extract the segment-matching core into `wadi-contracts` alongside `simplify_uri`, with
one test suite covering both directions and both callers' precision requirements. Not urgent, and
it should happen before a third caller appears.

### H4 — The README describes Phase 1

**Evidence.** `README.md` — *"Current scope (Phase 1): Java/Spring, single-service flow graphs.
Next (Phase 2): cross-service stitching, Spring Security auth extraction, the coverage report."*
against a 0.8.2 build that shipped all of that plus response shapes, the visual map, the endpoint
workspace and the enforcement model. It is the first thing a reviewer, a collaborator or a
prospective user reads.

**Fix.** Rewrite the scope and roadmap paragraphs. Cheap, and it should not wait for the rest of
this plan.

### H5 — No pagination on any list route

**Evidence.** No `limit`/`skip`/`cursor` parameter appears on any of the 21 orchestrator routes.
§5.2.15 fixed the *payload* for the endpoint list via the `EndpointSummary` projection; the
unbounded result set remains (804 rows on ICPC `contest`).

**Fix.** Cursor pagination on the endpoint list and the remote-edges list, defaulting to a
generous page so nothing changes for existing consumers. Low priority until a system larger than
ICPC appears.

### H6 — `create_app` is 705 lines with 21 routes

Mechanical: split into routers by domain (systems/snapshots, services/endpoints, graph, source,
export) matching the single-writer domains. No behaviour change, and it makes the auth-related
route additions from W2 land in a readable place.

---

## 11. W7 — Extraction breadth

Found by reading `SpringPacks.scala` and `TypeShapes.scala` line by line, which the first pass of
this audit did not do — it worked at the seams (closures, contracts, merge logic) and inferred the
interiors. Every finding here is class **U**: no phase owns it, and nothing records it.

Two of them change the endpoint count in opposite directions, so they should land together and be
measured together against W0's scorer.

### G1 — A bare method-level `@RequestMapping` produces no endpoint

**Symptom.** A handler written `@RequestMapping("/x")` with no `method=` attribute is absent from
the inventory. In Spring that mapping serves *every* verb.

**Evidence.** `SpringPacks.SpringEndpointPass.run`. `MappingAnnotations` holds only
`GetMapping`…`PatchMapping`, so `MappingAnnotations.get("RequestMapping")` is `None` and the first
branch never fires. The second branch is guarded by
`MappingAnnotations.values.exists(v => annotation.code.contains(v))` — the annotation text must
contain a verb string. `@RequestMapping("/x")` matches neither branch and emits nothing. Silent:
no tag, no anomaly, no counter. `UNMEASURED` on a real corpus — the idiom is common in
pre-Spring-4.3 code and in codebases that never migrated.

**Fix.** Treat a verb-less method-level `@RequestMapping` as what Spring treats it as: a mapping
for every verb the framework routes. Emitting one endpoint per verb is the literal reading and
would inflate the inventory sevenfold, so the honest form is a single endpoint carrying an
`any-verb` marker — which needs a contract decision, because `Endpoint.http_method` is currently a
required single `HttpMethod`. Two candidates, and this needs the owner's call:

- an `http_method_unspecified: bool` beside the existing field, with the field set to the verb the
  handler's body implies where that is readable and left at a recorded default where it is not; or
- widening `Endpoint.http_method` to accept an `ANY` member of `HttpMethod`, which is smaller but
  puts a non-HTTP value in an HTTP vocabulary.

**Verified by.** A fixture controller with a verb-less method-level `@RequestMapping`, which no
fixture currently has.

### G2 — Verb detection is a substring match, and it manufactures phantom endpoints

**Symptom.** False positives in the endpoint inventory — the failure `SpringEndpointPass`'s own
docstring says an inventory must not make (recorded there about `@FeignClient` interfaces).

**Evidence.** `MappingAnnotations.values.filter(v => annotation.code.contains(v))` matches a verb
name anywhere in the annotation's source text, including inside a route constant's name.
Simulated against the pass's exact predicate:

```
@RequestMapping(value = ApiPaths.GET_ORDERS,  method = RequestMethod.POST)
  emits ['GET','POST']     real ['POST']     PHANTOM: GET
@RequestMapping(value = Routes.DELETE_USER,   method = RequestMethod.POST)
  emits ['POST','DELETE']  real ['POST']     PHANTOM: DELETE
@RequestMapping(value = "/x",                 method = RequestMethod.POST)
  emits ['POST']           real ['POST']     clean
```

SCREAMING_SNAKE route constants routinely contain verb names, so this is an ordinary shape rather
than a contrived one.

**Fix.** Read the verb from the `method =` argument, not from the annotation's text — the same
correction §5.2.9 already applied to security rules (*"the verb read from the argument not the
chain text"*). The pattern is `RequestMethod\.(\w+)` scoped to the `method` attribute's value,
including the array form `method = {RequestMethod.GET, RequestMethod.POST}`.

**Verified by.** A fixture whose route constant is named `GET_ORDERS` and whose mapping is `POST`,
with a golden asserting exactly one endpoint. This is the mechanism-3 case from the P8 counterpart:
the verb vocabulary is closed and published, so the fixture covers it exhaustively.

### G3 — HEAD, OPTIONS and TRACE are unreachable inbound while supported outbound

**Symptom.** wadi can report that a service *calls* `HEAD /x` and can never report that a service
*serves* it.

**Evidence.** `HttpMethod` (`libs/wadi-contracts/src/wadi_contracts/enums.py:6`) declares eight
verbs. `MappingAnnotations` maps five. §5.2.5 explicitly recovers the missing ones on the client
side: *"`headForHeaders` → HEAD, `optionsForAllow` → OPTIONS join the name map."* So three contract
members have no inbound producer, and `unexercised_vocabulary` does not cover HTTP verbs, so
nothing says so.

Worth noting for the competitive framing: `benchmarking-baselines.md` §4.1 criticises Tai-e for
`enum RequestMethod { GET, POST, PUT, PATCH, DELETE } // no HEAD / OPTIONS / TRACE`. wadi's inbound
side has the same limit.

**Fix.** Add `RequestMethod.HEAD`/`OPTIONS`/`TRACE` to the verb reader from G2 — once the verb comes
from the argument rather than a name map, the three fall out for free. `@GetMapping`-style
shorthand annotations do not exist for them, so `@RequestMapping(method = …)` is the only route and
G2's fix is the whole of it.

**Verified by.** Vocabulary liveness extended to `HttpMethod`: every member the contract declares
must have a producer, or be listed as deliberately unproduced. Same mechanism as
`assert_registry_is_live` already applied to `AuthGapCode`, `CfgAnomalyCode` and `ClientLibrary`.

### G4 — A class-level multi-path prefix drops all but the first

**Evidence.** `classPrefix = controller.ast.isAnnotation … .headOption`. Method-level arrays emit
one endpoint per declared path (the yas idiom, correctly handled and pinned); a class-level
`@RequestMapping({"/storefront", "/backoffice"})` contributes only `/storefront`, and every endpoint
under the second prefix is missing.

**Fix.** Cross-product class prefixes with method paths, which is what Spring does. The endpoint
count rises, so it lands with W0's scorer in place.

### G5 — Wire shapes do not walk supertypes

**Symptom.** A DTO extending a base class publishes a shape missing every inherited field —
presented as `kind: object` and complete, not as a terminal.

**Evidence.** `grep -c 'inheritsFrom|transitiveParents|supertype'` in `TypeShapes.scala` returns
**0**. `wireMembers(typeDecl)` reads `typeDecl.member` only, filtered for `@JsonIgnore`, `$`-prefixed
and `STATIC`. There is no supertype traversal anywhere in the file, and `SpringPacks` already has a
`transitiveParents` helper that is not used here.

This is the sharpest P10 violation found in this audit. §5.2.7's terminals — `cycle`, `truncated`,
`unresolved` — all say *the walk stopped and here is why*. A missing inherited field says nothing
at all: the consumer sees a complete-looking object. §5.2.16 states the consumer explicitly —
*"whether the extracted model is sufficient for an LLM to generate tests from"* — and a generator
handed a shape missing its base fields constructs an invalid body with no signal that anything is
absent.

For the competitive framing: `benchmarking-baselines.md` §3.3 singles out AutoOAS as *"the only
tool building named `#/components/schemas` with `allOf` inheritance"* and faults Respector for
flattening it. wadi does neither — it omits.

**Fix.** `wireMembers` walks in-repo supertypes via the existing `transitiveParents`, with subclass
members shadowing same-named base members (Java field hiding). A supertype that is **not** in the
CPG — the common case for a framework or library base — must emit an honest marker rather than
being skipped silently; the natural spelling is a synthetic field-level `unresolved` entry naming
the unreachable supertype, so the reader learns the shape is partial and why.

**Verified by.** A fixture DTO hierarchy: a two-level in-CPG chain, a field-hiding case, and a DTO
extending an off-CPG framework base whose golden asserts the honest marker.

### G6 — Enum-typed fields become empty objects

**Evidence.** `grep -c 'isEnum|java.lang.Enum'` in `TypeShapes.scala` returns **0**. Java enum
constants are `STATIC` members and `wireMembers` filters `STATIC`, so an enum resolves to
`kind: object` with zero fields. A `Status status` field publishes as an object with no
properties rather than as one of a named set.

`WadiExport` already has the predicate — `isEnumTypeDecl(td)` checks `java.lang.Enum` inheritance
for the Lombok accessor logic — so the detection exists and is simply not wired here.

**Fix.** A `ShapeKind.ENUM` terminal carrying its constant names. Additive to `TypeShape`, and the
kind vocabulary already exists as a closed enum on both sides, so this is a minor bump.

**Verified by.** A fixture DTO with an enum field, and vocabulary liveness over `ShapeKind`.

### G7 — Validation constraints are absent, and Phase 9 already depends on them

**Symptom.** A consumer cannot tell a required field from an optional one, or learn any constraint
on it.

**Evidence.** `FieldShape` carries exactly three things: `name`, `java_name`, `shape`. No
`required`, no `nullable`, no constraint of any kind. `@NotNull`, `@NotBlank`, `@Size`, `@Pattern`,
`@Min`/`@Max`, `@Email` are read nowhere. This is class **X**, not merely **U**: Phase 9's payload
simulation is specified as *"Tier 1 (cheap): payload vs. recovered request schema **+ validation
rules** → 'breaks at the door' with code location"*, and no phase produces validation rules.

**Fix.** `FieldShape` gains `required: bool | None` and `constraints: list[FieldConstraint]`, read
from Jakarta Bean Validation annotations on the member. `None` for `required` is the honest default
— absence of `@NotNull` does not prove optionality, since a field may be required by convention or
by a validator wadi does not read. Scope it to the published Jakarta vocabulary and record anything
outside it rather than guessing, per mechanism 3 of the P8 counterpart.

Sequencing note: this is the cheapest item in W7 with the largest downstream consumer, and it is
the one thing here that Phase 9 cannot start without.

### G8 — `@RepositoryRestResource` and functional routing are unsupported

**Evidence.** `ControllerAnnotations = Set("RestController", "Controller")`. Spring Data REST's
`@RepositoryRestResource` — which exposes CRUD endpoints with no controller at all — is named as
unsupported in `benchmarking-baselines.md` §10 item 5, *"explicitly in the endpoint ground truth"*,
and appears nowhere in `architecture.md` or `TODOS.md`. `RouterFunction` / `RouterFunctions.route()`
— the Spring 5 functional style and the WebFlux default — appears in **no document at all**.

**Fix.** `@RepositoryRestResource` first: it is in the microSecEnD ground truth, so W6 will score
against it, and its endpoint set is derivable from the entity plus the annotation's `path` and
`exported` attributes. Functional routing is a larger piece of work (routes are built by a builder
chain, not declared) and should be scheduled by measured demand — the honest interim is an
`unmodelled_endpoint_idiom` census entry, the same demand signal `unmodelled_mechanisms` already
provides for client libraries.

**Verified by.** W6's microSecEnD run, which contains the ground truth for the first and will size
the second.

### G9 — A repository in an unsupported stack produces a successful, empty snapshot

**Symptom.** Point wadi at a Node/Express, Python, Go or .NET repository and the run **succeeds**
with nothing in it. No services, no endpoints, no coverage report entry, no error, no warning the
user ever sees. The UI shows an empty system and gives no reason.

**Evidence.** Service discovery is hard-gated on Maven + Java, in two places:

```python
# boundary.py
def _has_java_sources(module_dir: Path) -> bool:
    main = module_dir / "src" / "main" / "java"
    return main.is_dir() and any(main.rglob("*.java"))
```
```text
build_system="maven",
languages=["java"],     # both literals, not derived
```

So for a non-Java repo `discover_system_services` returns an empty list, and the pipeline takes
this path:

```python
if not discovered:
    logger.warning("no analyzable services found in %s", normalized)  # log only
...
if service_count > 0 and extracted_count == 0:  # never fires:
    raise RuntimeError(...)  # service_count == 0
```

`service_count` stays 0, so the all-services-failed guard is skipped, the job completes without
error, and `monitor.py` marks the snapshot `SUCCEEDED`. **Joern is never invoked** — no CPG is
built for the repository at all.

**Why this is worse than a missing feature.** Every other unsupported thing in wadi is
*materialized*: an unmodelled client library becomes an `unmodelled_mechanisms` entry, an
unreadable guard becomes `withheld`, a dead-end call becomes an `unbound_reason`. This one is
silence, and it is silence at the largest possible granularity — an entire repository. It is the
single clearest P10 violation in the system, and it is also the reason the hybrid layer (W8)
cannot help as currently designed: with no CPG, no service and no gap record, there is no
dispatch point of any kind.

**Fix.** Two parts, both small, and the first is a prerequisite for W8 Mode B.

1. **Language-agnostic discovery.** Recognise a service by any build manifest —
   `pom.xml` / `build.gradle` (java) · `package.json` (javascript/typescript) ·
   `pyproject.toml` / `requirements.txt` (python) · `go.mod` (go) · `*.csproj` (csharp) — and set
   `build_system` and `languages` from what was found rather than from literals. Joern has
   frontends for all of these, so the CPG gets built and everything language-neutral downstream
   (CFG coarsening, reachability, ICFG assembly, storage, API, UI) works immediately.
2. **`service-yielded-nothing` as a named gap.** A discovered service with production methods,
   zero endpoints, zero async roots and 0% analysis coverage is a coverage-report finding with its
   own code, naming the language and what was searched for. The run then says
   *"1 service · javascript · 340 production methods · 0 endpoints · no endpoint idiom
   recognised"* instead of showing an empty page.

Note what (1) buys immediately, before any pack or any LLM: a Go or Express repository gets a real
CPG, a real service boundary, real method-level facts and a real coverage number. It reads as
*"analysed, and here is exactly what we could not interpret"* rather than as nothing.

**Verified by.** An e2e that analyses a tiny Express fixture and asserts the snapshot carries one
service, a non-zero production-method count, and a `service-yielded-nothing` finding. That test
fails today for the most embarrassing possible reason — the snapshot is empty and green.

**Rejected.** *Failing the snapshot when no service is found* — a polyglot system with one Java
service and one Go service must still analyse the Java half; the Go half is a finding, not an
outage. *Warning only in the log* — the log is not a surface any user reads; §5.4 exists precisely
so limitations are queryable.

## 12. W8 — The hybrid extraction layer (§5.6, extended)

**Gated. Do not start this before the paper is out and the three experiments at the end of this
section have passed.** It is roughly a quarter of work and none of W0–W7 depends on it.

### Why this is not a pivot

§5.6 already specifies an LLM enrichment layer, and it was written in the repository's **first
commit** (`1418dd4 initial architectural design`), 185 commits before this document. Its five
decisions stand unchanged:

1. **The coverage report is the work queue** — invoked per named gap, so spend scales with static
   confusion rather than codebase size.
2. **Evidence packets in, constrained choices out** — structured output via `wadi-contracts`
   models; `unknown` always a legal answer.
3. **Proposals are artifacts** — `llm_proposals`, single writer (P4), consumed at the
   `llm-guessed` provenance tier; cached by evidence-packet hash.
4. **The promotion loop** — one-click confirmation turns a proposal into a permanent
   `human-asserted` hint; rejections remembered symmetrically.
5. **Provider-agnostic and capped** — no key ⇒ the core is untouched; local inference as a
   config-gated compose profile, framed as data governance rather than convenience.

Everything below extends that design. It does not replace any part of it.

### The three extensions §5.6 does not cover

§5.6 was scoped to **resolution**: wadi found a gap it could name, and the model selects from a
closed candidate list. That is safe by construction — a target absent from the list cannot be
hallucinated. The audit in this document surfaced two gap classes that shape does not fit, plus a
missing safety step.

| # | Extension | Why §5.6 does not cover it |
|---|---|---|
| **E-A** | **Discovery gaps** | The coverage report has no entry for an endpoint wadi never saw. `@RepositoryRestResource` produces no controller, so it appears nowhere — not as a gap, not as an unknown. The census (section 3) is what converts that silence into a nameable `unexplained-idiom` gap. |
| **E-B** | **Judgment gaps** | *"Is this aspect a guard?"* has no closed answer set, so constrained selection has nothing to select from. Judgments must enter as **evidence**, never as claims. |
| **E-C** | **Verification** | §5.6 needs none, because selection from a list bounds the answer. Discovery is open-ended, so every proposed fact must be checked against the graph before it is published. |

### The layering, measured

What actually transfers to an unsupported stack, and what does not. This is the scope of the
problem, and it is larger than "the LLM finds the endpoints."

| Layer | Framework-agnostic? |
|---|---|
| Joern CPG construction (all frontends) | ✅ |
| CFG coarsening, construct discriminators (§5.2.8) | ✅ language-neutral |
| Reachability closure BFS, ICFG assembly | ✅ language-neutral |
| Chunked storage, REST API, MCP, UI | ✅ |
| Stitcher: path matching, phone book, confidence tiers | ✅ operates on artifacts, never on source (P2) |
| **Service discovery** | ❌ hardcoded to Maven + Java (**G9**) |
| **Endpoint discovery** | ❌ `app.get('/x', h)` vs `@GetMapping` |
| **Sink detection** | ❌ `axios` / `fetch` vs `RestTemplate` / `WebClient` |
| **Auth constructs** | ❌ middleware chain vs `SecurityFilterChain` |
| **Config identity** (port, service name, profiles) | ❌ `.env` / `package.json` vs `application.yml` |
| DI resolution | ❌ per-container, and absent in some ecosystems |

**Roughly 60% of wadi is already framework-neutral** — which is what the P1/P2/P6 separation bought
and it is the reason this workstream is affordable at all. But a new stack needs **five** things
supplied, not one, and any plan that says "the LLM extracts the endpoints" has scoped a fifth of
the work.

### Two modes

The two gap classes have opposite economics and must not share a code path.

| | **Mode A — gap-filling** | **Mode B — cold start** |
|---|---|---|
| Precondition | Static ran and named its holes | Static produced nothing (**G9**'s `service-yielded-nothing`) |
| Trigger | A gap entry with an anchor | A service with production methods and no endpoints |
| Input | Evidence packet built from the CPG at that anchor | File triage over the repository |
| Cost scales with | **How much static failed** | **Codebase size** |
| Verification | Strict, per-anchor | Looser, but still CPG-checked once the model names an anchor |
| Steady state? | Yes | **No — onboarding only** |

Mode B violates §5.6 point 1 by construction: its cost is proportional to the repository, not to
static confusion. That is acceptable exactly once per (framework, idiom), and never as the normal
path. The mechanism that keeps it to once is the rule-promotion loop below.

### The pipeline

The binding constraint is **P2 — the CPG is discarded after extraction.** An `llm-resolver`
running later as a §10 analysis service therefore cannot query the graph: it can neither fetch
context nor verify. The resolution is to split the work across the P2 boundary.

```
┌─ EXTRACTION WORKER (CPG alive) ───────────────────────────────┐
│  1. Joern builds the CPG                        unchanged     │
│  2. Packs tag + export                          unchanged     │
│  3. Assembler builds artifacts                  unchanged     │
│  4. Idiom census: count what was walked past    NEW (§3)      │
│  5. Enumerate gaps -> work queue                NEW           │
│  6. Build one EVIDENCE PACKET per gap from the CPG   NEW      │
│     persist packets, keyed by content hash                    │
└───────────────────────────────────────────────────────────────┘
                    v   CPG discarded — P2 intact
┌─ LLM-RESOLVER (§10 service, own collection — P4) ─────────────┐
│  7. For each packet with no cached answer:                    │
│       ONE turn, schema-constrained output, no tools           │
│  8. Verify against the packet + materialized artifacts        │
│  9. Write `llm_proposals`; mutate no other domain             │
└───────────────────────────────────────────────────────────────┘
                    v
┌─ CONSUMERS ───────────────────────────────────────────────────┐
│ 10. Tier 1 verified -> facts, provenance llm-proposed-verified│
│     Tier 2 judged   -> AuthEvidence(resolution=opaque)        │
│     Tier 3          -> never                                  │
└───────────────────────────────────────────────────────────────┘
```

Building the packet inside the extraction window and running the model outside it is right for
four independent reasons: it preserves P2 exactly; the packet hash is the cache key; the packet is
the audit record; and the model stage becomes **replayable offline from committed packets**, which
is what lets a reviewer reproduce a published number without a Joern container.

### The work queue

Every gap kind already tracked, plus the two new ones. Each entry is
`(gap_kind, anchor, service_id, snapshot_id)`.

| Gap kind | Source | Mode | Tier |
|---|---|---|---|
| `unexplained-idiom` | census (§3) — **new** | A | 1 |
| `service-yielded-nothing` | **G9** — new | **B** | 1 |
| `unresolved-call` + reason code | coverage report | A | 1 |
| `unmodelled-mechanism` | coverage report | A | 1 |
| `unresolved-response-shape` | endpoint artifacts | A | 1 |
| `unread-enforcement` (withheld) | `AuthCoverageSection` | A | 2 |
| `no-evidence` auth | `AuthCoverageSection` | A | 2 |
| `ambiguous-di` | after **A3** lands | A | 2 |
| `cfg-anomaly` | `cfg_anomalies` | — | **never** |

This table is the economics of the whole workstream. On ICPC's 804 endpoints, a queue of ~50 sites
means ~50 calls. **Spend falls as the symbolic layer improves**, which is the property §5.6 point 1
was written to guarantee — and it is the reason the honesty counters are load-bearing here: a gap
that is not marked is a gap the model cannot be dispatched to.

### The evidence packet

Built symbolically. The model receives exactly this and nothing else — no repository access, no
tools, no second turn.

```json
{
  "packet_id": "pkt_<sha256 of every field below>",
  "gap_kind":  "unexplained-idiom",
  "anchor":    {"file": "OrderResource.java", "start_line": 8, "end_line": 20},
  "question":  "endpoint-declaration",
  "source": {
    "primary": "<the method + its annotations, verbatim at the pinned SHA>",
    "enclosing_type": "<class declaration + class-level annotations>",
    "referenced_declarations": ["<@Path>", "<@GET>", "<Order>"]
  },
  "graph_facts": {
    "method_full_name": "com.acme.OrderResource.get:com.acme.Order(java.lang.Long)",
    "parameters": [{"name": "id", "type": "java.lang.Long", "annotations": ["PathParam"]}],
    "return_type": "com.acme.Order",
    "enclosing_type_annotations": ["Path"]
  },
  "answer_schema": "EndpointProposal"
}
```

Two properties carry the design. **The packet is closed** — single-turn structured output is where
small models score 82–88% on BFCL, against 8–56% for multi-turn agentic tool use, so the
back-and-forth agent shape is deliberately excluded. **The packet hash is the cache key** — same
code, same prompt template, same model ⇒ no call at all. Re-analysing an unchanged snapshot is
bit-identical by construction, which is a stronger reproducibility story than temperature 0
(nondeterministic in practice, because reduction kernels are batch-size dependent).

### The three tiers

| Tier | Content | LLM role | Publishing rule |
|---|---|---|---|
| **1** | Endpoints, call sites, annotations, wire shapes, service identity | Proposes | CPG verifies → publish as fact, provenance `llm-proposed-verified`. Any failed check ⇒ **drop**, not downgrade; count as `llm_proposal_rejected` |
| **2** | "Is this a guard?", "what does this idiom mean?" | Judges | Enters as `AuthEvidence(effect=UNKNOWN, resolution=OPAQUE, provenance=llm-judged)` → feeds the existing withholding logic |
| **3** | Control flow, reachability, DI, cross-service matching | **none** | Symbolic only — measured LLM performance here is 0% precision / 0% recall |

Tier 1 verification, concretely:

```
Proposal: "OrderResource.get at line 12 serves GET /orders/{id}"
  ✓ does method `OrderResource.get` exist at line 12?
  ✓ is the literal "/orders" in an annotation on the enclosing type?
  ✓ is the literal "/{id}" in an annotation on the method?
  ✓ does the return type `Order` exist?
  ✓ is `id` a real parameter of that method?
  all pass -> fact.   any fail -> dropped, never stored.
```

**Tier 2 is safe because of `withheld`, and this is the load-bearing point.** A model judgment can
move an endpoint from *evidenced public* to *withheld*. It can never move one to *protected* or
*public*, because `EndpointAuth._claims_are_earned` is a contract validator that raises on a
permissive claim coexisting with an unread gate. The worst outcome of a hallucinating model on
Tier 2 is that wadi admits it does not know — which is the correct answer more often than the
confident one it replaces.

### Rule promotion — how Mode B converges

§5.6 point 4 promotes a confirmed *answer* to a permanent hint. The extension promotes a confirmed
*pattern* to a persistent rule.

```
First Express repository ever analysed
  1. G9 discovery registers the service (package.json), language=javascript
  2. Joern builds a JS CPG                       <- works today, once G9 lands
  3. No pack matches -> gap: service-yielded-nothing
  4. Mode B: triage files (which import express?), propose route patterns
     AND concrete endpoints
  5. Each concrete endpoint is CPG-verified exactly as in Mode A
  6. The PATTERN surfaces for one-click confirmation

Every Express repository after that
  -> the pattern is a rule. Pure symbolic. Deterministic. Zero LLM calls.
```

That is the difference between paying a model forever and paying it once per idiom. The endgame is
already named in the Phase 7 roadmap — *"LLM-drafted packs validated by the conformance suite"* —
and a confirmed pattern with a fixture is exactly that, arrived at by promotion rather than by
authorship.

### The gate: three experiments

Run before committing the quarter. Stop at the first failure.

**E1 — can a small model do Tier 2?** Twenty real constructs from ICPC and train-ticket, including
`UserAuthorizer` (votes on a request-scoped bean, never throws — the shape that defeated the
deny-shape predicate) and `TracingAspect` (identical binding shape, must **not** be reported).
Run at 4B, 14B and frontier. Report accuracy **and false-positive rate separately** — a model that
calls everything a guard withholds the whole system.
*Pass:* ≥90% accuracy with <5% FP at a size runnable locally.
*Prediction on record:* a 4B model fails `UserAuthorizer`.

**E2 — does Tier 1 beat a hand-built pack?** One Quarkus repository, hand-verified ground truth.
Compare verified-proposal F1 against the Spring pack's F1 on Spring.
*Pass:* within 5 points, on a framework nobody wrote code for.

**E3 — what is the real invocation rate?** Count trigger sites on ICPC and train-ticket as they
stand.
*Pass:* <15% of endpoints. At 60% the symbolic layer is not carrying enough and should be fixed
first.

None of the three can be run without W0's scorer. That is the third independent reason it is the
first thing built.

---

## 13. W6 — Validation breadth


The four-layer stack (goldens, always-on invariants, the ASM oracle, JaCoCo trace inclusion) is
genuinely strong and is not in question. What is in question is what it can and cannot conclude.

| Layer | Proves | Cannot prove |
|---|---|---|
| 29 construct goldens | Per-construct shape is pinned | Only shapes an author imagined |
| `cfg_anomalies` | Structural invariants on every real snapshot | Nothing about semantics |
| ASM bytecode oracle | Decision-point **counts** agree with javac | Nothing about edge *targets* — a mis-routed arm passes |
| JaCoCo traces | Executed ⊆ graph (soundness) | Graph ⊆ feasible (precision) |

**E1 — the oracle compares counts, not structure.** A worthwhile extension: derive the bytecode
CFG's **dominator relation** per method and assert the coarse graph's dominators are consistent
with it. That catches a mis-routed edge, which counting cannot. Scoped as a follow-on, not a
prerequisite.

**E2 — nothing measures precision.** Accepted and already recorded in the trust boundary
(edges over-approximate). The honest response is not to fix it but to *size* it: A3's
`call_resolution` breakdown is the first real number on how much of the graph is
over-approximation.

**E3 — both dynamic layers run on a 746-line fixture wadi's own authors wrote.** This is the
corpus-overfitting shape `benchmarking-baselines.md` §10 item 8 identifies in MicroGraal, which
matched TrainTicket ground truth almost perfectly and returned empty output on all 17 benchmark
apps.

**Fix.** Run wadi over the **microSecEnD 17-app set** before anything from this work is published.
The set is small (604–14,527 LoC each), the ground truth is public (182 components + 385
connections + 160 endpoints), and a replication package with all nine prior tools' raw results
exists. Two outputs:

1. An endpoint / connection F1 against a shared benchmark, comparable to Code2DFD's 0.86 and
   RAD's 0.79 — the first such number wadi has.
2. **The auth generalization answer.** Report the
   `authenticated / unauthenticated / withheld / no_evidence` split per app. A high
   `no_evidence` means detection is not generalizing; a high `withheld` means detection works and
   reading does not. Those are different fixes and one run separates them.

That second output is the measurement W4 is currently arguing about, and it should be treated as
W4's exit criterion rather than as a publication task.

---

## 14. What this plan does not fix


Recorded so the boundary is explicit rather than assumed.

- **Path feasibility.** Edges over-approximate; a statically infeasible path may exist. Already
  in the trust boundary and unchanged here.
- **Call-site context sensitivity.** A method is inlined once per ICFG, so paths through a shared
  helper merge and an A-call/B-return path exists in the graph. Documented in the trust boundary.
  Phase 9's payload simulation depends on path reasoning over exactly this graph and will need to
  confront it; this plan does not.
- **Pointer analysis.** DI resolution is class-hierarchy analysis plus Spring's `@Primary` rule,
  not pointer analysis. A3 makes the resulting imprecision *visible*; it does not remove it. This
  is the axis Tai-e will be compared on and the comparison should be made on stated terms.
- **`@Qualifier` bean-name resolution.** Recorded as deferred in `SpringDIPass`; unchanged.
- **MQ producer/consumer pairing.** Phase 3 item 1. W2 reserves the surface (`include_async`,
  `async-unpaired`) so it lands additively.
- **Interceptor/filter/aspect oracle coverage.** Structural, not textual; out of a regex oracle's
  reach, and named as an accepted limit in C2 rather than papered over.
- **Serial extraction.** One Joern container, one service at a time. A scale ceiling, not a
  correctness problem, and parallelising it would need a second container and a determinism
  review.
- **Functional routing (`RouterFunction`).** G8 proposes a census entry, not support. Routes built
  by a builder chain are a real piece of work and should be scheduled by measured demand.
- **Jackson beyond field-level basics.** `@JsonInclude`, views and custom serializers stay a
  recorded refinement per §5.2.7 — shapes are structural truth, not a wire-format simulator.
- **Non-Spring Java auth beyond Shiro's annotation set.** C5 adds five annotation names because
  they are cheap and mainstream. A real Shiro pack — its filter chain, its realms — is a pack, and
  it needs a phase. §2 records that no phase currently owns Java-but-not-Spring.

---

## 15. Exit criteria


The foundation is safe to build Phase 3 on when all of the following hold:

1. `make benchmark` runs in CI and reports endpoint, auth and edge scores against committed
   ground truth for at least three corpora, one of which is not train-ticket or ICPC.
2. No wall-clock dependency exists in `joern-platform/src/main` (CI-enforced), and the same input
   produces a byte-identical export twice.
3. The export-closure minus ICFG-union delta is zero except for a recorded exclusion list, and
   whatever remains is counted as a `cfg_anomalies` code on every snapshot.
4. The producer and consumer export schema versions are asserted equal in CI.
5. `flow_trace` answers a three-hop chain on a fixture, terminates a cycle explicitly, and
   composes confidence along the path.
6. Every ICFG call node carries a resolution confidence, and the coverage report publishes the
   breakdown.
7. The auth fixture contains at least four distinct identity vocabularies among its gating cases
   and at least one identity-reading non-gating case, and the gating test passes on all of them
   through a type property rather than a name match.
8. The auth oracle distinguishes "checked and clean" from "nothing here to check", and reports
   unmodelled auth vocabulary as a finding.
9. wadi has been run over the microSecEnD 17-app set and the per-app auth claim split is
   recorded.
10. Every member of `HttpMethod`, `ShapeKind` and `AuthEvidenceKind` either has a producer or is
    listed as deliberately unproduced — the `assert_registry_is_live` mechanism, extended to the
    vocabularies it does not yet cover.
11. `FieldShape` carries `required` and `constraints`, so Phase 9's Tier 1 has the input its
    design already assumes.
12. A wire shape whose supertype is unreachable says so; no shape is published as complete while
    silently missing inherited fields.
13. Every **U**-class finding in §2 has left the class — fixed in code, or narrowed in
    `architecture.md`, or moved to the `TODOS.md` "Narrower than claimed" register with a
    measurement. Silence is not an exit.
14. The P8 counterpart (§3) is recorded as a §2 principle, and mechanism 3 — vocabulary
    enumerated from the framework rather than the corpus — is enforced for every pack whose
    framework publishes a closed vocabulary.
15. A repository in an unsupported stack produces a **service record, a CPG, a production-method
    count and a named `service-yielded-nothing` finding** — never a successful empty snapshot
    (**G9**). This is an exit criterion regardless of whether W8 is ever built.
16. *(W8 only)* All three gate experiments (E1–E3, section 12) have run and their results are
    recorded — including if they failed. A failed gate is a valid outcome and closes W8; an
    unrun gate does not.

Items 1–4 are the reproducibility floor and should land first. Items 5–6 unblock Phase 3's
auth-consistency walk, which needs both a chain and a confidence on it. Items 7–9 are W4's exit.
Items 10–12 are W7's. Items 13–14 are the process exits, and they are the ones that decide
whether this document has to be written again in six months. Item 15 is G9 and stands alone.
Item 16 gates W8.

---

## 16. Open questions for the owner


1. **Phase and section numbering.** This work is larger than a tranche and smaller than a phase.
   Proposal: **Phase 2.10 — Foundation hardening**, recorded as §5.2.17, shipping as 0.9.0.
   Needs a decision before anything lands, since the standing rule is that the decision record
   precedes the implementation.
2. **B4 scope.** Measure endpoint-id collisions on both corpora first. If the count is zero,
   close it with the measurement and change nothing.
3. **A1's constructor question.** Are `<init>` bodies part of a per-request flow? The honest
   answer is probably no, with a recorded exclusion. Worth deciding explicitly rather than
   inheriting whatever the fix happens to do.
4. **H1's direction.** Refuse-at-the-door versus a read-side compatibility mode. This is a §7
   decision and it changes what an operator experiences during a partial upgrade.
5. **Third benchmark corpus.** One microSecEnD app for the committed ground truth — which? The
   candidate with the most auth surface is `piomin/sample-spring-oauth2-microservices`.
6. **G1's contract shape.** A verb-less method-level `@RequestMapping` serves every verb.
   `Endpoint.http_method` is a required single `HttpMethod`. Add `http_method_unspecified` beside
   it, or widen the enum with `ANY`? The first keeps the HTTP vocabulary clean and costs a field;
   the second is smaller and puts a non-HTTP value in an HTTP enum. This blocks G1.
7. **The P8 counterpart (§3).** Which of the three mechanisms become mandatory, and does the rule
   bind retroactively — i.e. do the four packs already marked complete have to satisfy it before
   Phase 3 starts, or only on their next change?
8. **Sweep the §11 roadmap for other dangling dependencies.** G7 was found by accident, because Phase 9's
   text names validation rules explicitly. Nothing has checked whether the other capability design
   notes assume inputs that no phase produces. That sweep is an afternoon and it belongs before
   Phase 3 is scoped.
9. **What to do about the §5.2.x sections that read as complete.** Several are narrower than they
   read — the auth model most of all, whose actual scope is *Spring Security, three systems, all
   Spring*. Amend each section in place, or add a scope line to the ones affected? This is a
   publication question as much as a documentation one.
10. **Does W8 amend §5.6 in place, or add §5.6.1?** The five original decisions stand unchanged and
    were written in the first commit; the three extensions (E-A/E-B/E-C) and the two-mode split are
    additive. A sub-section keeps the original design's provenance visible, which has some value
    given how well it has held up.
11. **Which language does G9 target first?** Discovery needs one manifest reader per ecosystem.
    Node/Express is the cheapest and the best Mode-B test case; Python/FastAPI is the one Phase 8
    already schedules. Doing the Phase 8 language first would make W8 Mode B and Phase 8 the same
    piece of work.
