# Changelog

All notable changes to wadi. One version spans the whole release set
(CLI, images, contracts — architecture.md §13).

## 0.8.2 — 2026-08-09 (a list route serves a list shape)

0.8.1 made a shared jar's types resolvable, and shape recovery did exactly what
it should with them — without a ceiling. One service's endpoint list went from
1.9 MB to **114 MB**, and the browser parsed all of it before drawing a row, so
the endpoint workspace looked frozen. Fixing it turned up three more things
that were hiding behind it.

### Fixed

- **A service's endpoint list is a list, not 804 whole endpoints.** The two
  wire-shape fields were 124 MB of a 126 MB response; every other field of
  every endpoint together is 2.5 MB. The list route now serves an
  `EndpointSummary` and the shapes come with the per-endpoint detail the peek
  already fetches. **114,546,092 → 2,479,867 bytes, 10.7–14.5 s → 0.09 s.**
  They are absent from the type rather than set to null: `null` already means
  "no request body" on 673 of those 804 endpoints, and a list that nulls them
  for size cannot be told from one reporting a fact.
- **Source for library code resolves.** A library's sources are staged into the
  application's parse, so every anchor in library code named a path that exists
  in the analyzed tree and in no repository's history — source-on-demand 404'd
  on all of them, which on a real system is most of what you land on when
  following a call. Staged paths now resolve against the library's own
  repository at its own pinned commit.
- **Switching project or snapshot works.** Both rows in the scope switcher were
  wired to a callback the menu never calls, so clicking one did nothing at all.
- **An endpoint's contract no longer renders as a result while it is loading,
  or after it fails.** A pending fetch shows as pending and a failed one says
  so with a retry, instead of falling through to "No request body on this
  endpoint" — a claim about an endpoint nothing had read.
- **Two guards that differ only in fields the chip does not draw collapse to
  one chip** instead of painting the same relation twice and colliding on the
  React key (60 of 804 endpoints on a real system).
- **`wadi up` converges onto a running stack** instead of refusing because its
  own orchestrator holds the API port, and no longer reads a socket left by a
  dead client as a conflict.
- **`wadi analyze --wait` survives a flaky connection.** A single dropped poll
  ended the wait with "the wadi API is not answering — try: `wadi up`". Seen on
  a real 4.5-minute run: the connection dropped 64 seconds in, the orchestrator
  logged nothing and never restarted, and the snapshot went on to **succeed** —
  so the CLI reported a healthy analysis as a dead API and sent the reader to
  restart the thing that was working. Transport failures and timeouts are now
  retried within a bounded window and shown while they last, and giving up says
  the run may still be going and how to check it.
- **`make test` no longer deletes your running stack.** Three CLI tests invoked
  `wadi down` while stubbing two of its three teardown steps; the third shells
  out to docker and removes every container on the wadi network in the release
  image namespace — which is why exactly the five `ghcr.io/wadi-sh/*`
  containers vanished on every run and `mongo`/`neo4j` never did. The CLI test
  suite now refuses any real subprocess and fails the test that attempts one,
  because stubbing the three known cases would have left the trap armed.
- **The e2e analyzer container is memory-bounded.** Its analyzer
  container carried no memory limit, which does not mean "no limit" — it means
  the JVM sizes its heap against the whole Docker VM. Beside a running stack,
  whose own analyzer reserves 10 GB of a 15.6 GB VM, the two overcommit and
  Docker starts killing containers: the stack's non-database services vanish
  mid-run and the e2e fails intermittently. Bounded to 4 GB against a measured
  peak of 807 MiB. CI never saw this — a fresh runner has no competing stack.

### Added

- **`endpoint_detail` on the MCP server.** Moving the wire shapes off the list
  row left `list_endpoints` — an agent's only route to a request or response
  shape — without them, and no detail tool existed. The surface whose whole
  purpose is agent-readable ground truth could not say what an endpoint accepts
  or returns. It resolves type references by default, or hands back the shared
  form for a caller that would rather resolve them itself.

### Changed

- **A wire shape is emitted as a graph of types, not a tree.** Expanding it as
  a tree writes the same definition once per path that reaches it: one real
  response emitted **2,365 object definitions of which 113 were distinct** —
  one type spelled out 79 times — for 3 MB, roughly 772,000 tokens, which no
  reader could hold. Each type is now written once under the endpoint's
  `type_defs` and referenced wherever it occurs. On the fixture that reproduces
  it: **8.27 MB → 7,926 bytes, complete, with nothing truncated.**
  - **Recursion is now exact.** A type that reaches itself references its own
    definition, where the `cycle` terminal could say a loop existed but not
    what was in it.
  - **A definition no longer depends on where it was discovered**, so the same
    type cannot come out complete on one path and truncated on another.
  - The node budget stops being load-bearing and goes back to being a backstop;
    it is deliberately not retuned.
  - Shapes written before this release are fully inline, contain no references,
    and read exactly as they did.

- **Recovered shapes are bounded by size, not only by depth.** Cycle detection
  is per walk path, which leaves sibling branches free to re-expand the same
  entity subgraph — exponential against a bidirectional model, and one endpoint
  reached 3 MB nested 25 deep. A shape that hits the ceiling says `truncated`,
  the terminal that already meant exactly that. Existing snapshots keep the
  shapes they were written with; this changes what new analyses record.
- **What each endpoint calls downstream is one database aggregation** rather
  than reading every flow graph in the service to union a handful of ids:
  **804 round trips and 104,985 nodes materialised → one aggregation**, 4.4 s →
  0.08 s.
- **A snapshot's artifacts never expire from the client cache.** Snapshots are
  immutable and pinned, so re-opening a service you have already looked at
  costs nothing. The system and snapshot lists still refresh, because new runs
  appear there.
- **Loading is visible.** Placeholders had 3% contrast against the panel they
  sit on and lived only in section bodies, which a collapsed section does not
  draw. They have their own colour token now, and the section header carries a
  spinner and the word `loading` whether the section is open or shut.

### Contracts

- `wadi-contracts` **1.25.0** — adds `EndpointSummary` (the list-row projection
  of an endpoint), `Endpoint.type_defs`, the `ref` shape kind, and
  `resolve_type_shape` for consumers that want a tree. Additive: no stored
  artifact loses a field, and shapes without references are unaffected.
- Export schema **2.13.0** — endpoints carry `type_defs`.

## 0.8.1 — 2026-08-07 (a library is not a service)

A shared internal jar that lives in its own repository was being analyzed as if
it were a service of its own. The cost was mostly not what you would guess:
**335 of 336 unresolved response shapes on a real system were types that jar
declares**, invisible from inside the graph of the application that returns them.

### Fixed

- **A library compiled into a service is no longer modelled as a peer service.**
  Two things were wrong at once. Dependency resolution ran per repository while
  the answer needs the whole system, so a `<dependency>` on a module in a
  sibling repo resolved against a map that could never contain it — no edge, no
  library, its own service. And a module carrying a `@RestController` was read
  as deployable, which a library shipping a reusable web fragment plainly is
  not. Modules are now pooled across every repository of a system before
  anything is classified, and what marks a service is an entry point or war
  packaging, not web presence.
- **A library's sources reach the application that deploys them.** They are
  staged into its parse, so the types it returns are visible where they are
  used. On the system that prompted this: response shapes resolved **468 →
  803**, endpoints carrying a guard **562 → 643**, and the authorization
  vocabulary recovered its eighth annotation.
- **The library's own routes belong to whoever mounts them.** Its one endpoint
  now reads as served by the application, which is what that application's
  security config always said. Total endpoints are unchanged.

### Changed

- The analyzer container is sized for a source union rather than a single
  module: a service parsed together with its library is the sum of both, and
  the old limit killed the parse outright. **A wadi stack now wants about 10 GB
  available to Docker.**
- `library_roots` on a service boundary can name a module in a sibling
  repository. A bare root still means the service's own repo.

## 0.8.0 — 2026-08-06 (the words a project invents for its own policy)

Wadi could only recognise authorization it had been taught the name of. Measured
on a real enterprise system (804 endpoints, 118 controllers), that meant 637
endpoints publishing `roles: []` with nothing beside it while a project-defined
vocabulary of eight annotations governed them, and nine endpoints publishing as
`authenticated=false` — no authentication, evidenced — on routes that require it.

### Added

- **The authorization vocabulary is derived, not matched.** A security
  annotation is no longer a name on a list; it is an annotation whose consumer
  can deny the request, which is a property of the graph. Wadi reads the binding
  three ways — an AspectJ advice parameter type, an `@annotation(...)`
  designator, and a `getMethodAnnotation(X.class)` read inside an interceptor —
  and the scope that follows is exactly the methods carrying the annotation, so
  a guard reports on the endpoints it governs instead of blanketing a service.
  Run cold against a system it had never seen, it recovered all eight of that
  system's annotations with no names supplied.
- **Relationship-scoped authorization is something the map can say.**
  `@ContestManager(context = Contest.class)` requires that the caller manage
  *the contest this request names* — a fact about a pair, not about the
  principal, and the commonest authorization model there is (ownership,
  tenancy, every resource-scoped role). Endpoints now carry `relationships[]`
  beside `roles[]` and `authorities[]`, with the resource it is required on and
  any permissions demanded alongside it. Where several guards apply and how they
  combine could not be read, `composition_unresolved` says so rather than
  letting the requirements read as exact.
- **Gating constructs are identified by whether they can deny, not by name.**
  An aspect that records its verdict on a request-scoped bean gates just as
  surely as one that throws; what separates a guard from instrumentation is that
  a guard must know who the caller is. A tracing aspect over the same handlers
  is left alone.

### Fixed

- **Nine endpoints published as public require authentication.** A path template
  in an endpoint's URI could absorb a literal in a security rule, so
  `/help/cms/{space}/{page}` inherited the `permitAll` written for
  `/help/cms/virtpublic/**` — true of the single request whose space is
  literally `virtpublic`, false of every other. Matching now reports whether it
  was reached exactly or speculatively, and only rules that can *weaken* a claim
  — a `permitAll`, a chain bypass — refuse to act on speculation. Rules that add
  restriction keep over-approximating, which is the safe direction.
- **A guard scoped to one endpoint no longer lends itself to a sibling.** An
  annotation-bound guard on `/common/country/{a2}` was ant-matched against
  `/common/country/export`, so an admin-only route would have covered every
  route beside it.
- **A handler serving several routes guards all of them.** Only the first route
  was read, leaving the rest looking unguarded.
- **A rule written with a path template still covers the whole route it names.**
  `/orders/{orderId}` and `/orders/{id}` are the same route and the variable
  names need not agree; reading that as a partial match would have stopped a
  real `permitAll` from answering, publishing an over-restrictive claim. Only a
  literal absorbed by a template is partial.
- **A guard's policy is read from the whole annotation.** It was parsed from a
  truncated first line, so a long annotation could lose the second of two
  candidate resource types and name the first one instead of declining.

### Changed

- Contracts 1.23.0, export 2.12.0. Every addition carries a default, so stored
  artifacts and older exports load unchanged. `covers_route` is deliberately
  separate from `resolution`: a rule can be read perfectly and still govern part
  of a route, and the two answer different questions.
- The system auth view and endpoint rows name the relation a caller must stand
  in rather than showing a bare "protected" with an empty role list — on the
  measured system that shape is 562 of 804 rows.
- The wadi mark ships with the frontend.

## 0.7.4 — 2026-08-06 (a design system, not a repaint)

Frontend only; no contract, CLI, or analysis behaviour changes.

The UI read as a template — a blue-slate ground in dark mode, pure-white cards
on a pure-white page in light mode, six unrelated radius values, and text that
was hard to read for a reason that was not its size.

- **Colour.** `components.json` declared `baseColor: slate`, so the ground
  carried real chroma at hue 265. Replaced with an achromatic palette. The
  load-bearing decision is that hue is a data channel and nothing else: wadi
  already spends 17 hues on facts (five HTTP verbs, seven flow constructs, an
  eight-step role wheel), leaving no gap for a brand hue. The old teal
  `--primary` sat 5 degrees from `--role-2` and carried more chroma than every
  flow token, while four comments in the codebase asserted that "the one
  saturated element in the UI stays the HTTP-method chip". Chrome is now
  near-white on dark / near-black on light; the one chromatic piece of chrome
  is the focus ring, held below every data token so it separates by saturation
  rather than by hue.
- **Elevation.** Light mode had `--background` and `--card` both at pure
  white, so a card had nowhere to lift to. The ladder is bg/panel/card/raised.
- **Legibility.** 34 uses of `text-muted-foreground/40..80` put an
  already-low-contrast token behind opacity, landing near 2.4:1 against a
  4.5:1 floor — a bigger cause of "hard to read" than size. Resolved to three
  real foreground steps. 61 arbitrary sizes down to 8px collapse onto a closed
  scale with an 11px floor.
- **Geometry.** One five-step radius scale; 29 bare `rounded` were Tailwind's
  own 4px default and never touched `--radius`.
- **Density.** Fitting more information is answered by spacing, not smaller
  type: `data-density` drives row height, padding and gap for ~20% more rows
  per screen with every glyph unchanged, stamped before first paint.
- **Type.** IBM Plex gives way to Geist, chosen on measurement. Every
  mainstream monospace is exactly 0.600em advance, so changing mono buys no
  density; what differs is x-height, which governs legibility at the 11px
  floor. Geist Sans is 3.1% narrower and 2.7% taller than Plex Sans, and Geist
  Sans and Geist Mono share an x-height exactly — this UI mixes them inline
  constantly.
- **Primitives.** Migrated from Radix to Base UI (shadcn's default since July
  2026); all 15 `@radix-ui` packages and `cmdk` are gone. Eight `ui/`
  components that no code imported were removed rather than migrated.
- **Fixes found by using it:** a menu crash (`MenuGroupContext is missing`),
  menus that could not scroll past the viewport, a hydration mismatch on the
  overview home, a primary action styled as a tinted outline, and a snapshot
  menu whose selected row was a tick 340px from where reading starts.

0.7.3 was tagged during a GitHub Actions outage and never published — its
release run failed the §13 version guard because nothing had been bumped.

## 0.7.2 — 2026-08-06 (errors that tell you how to recover)

Three failures reported in one session, all the same defect: the CLI said
something confident and wrong about what had just happened, and never once said
what to do next.

- `wadi analyze --repo <github url> --name yas` **silently ignored `--repo`**,
  reused a system registered from a local path, cloned that instead, and failed
  on it. Nothing in the output said the flag had been dropped.
- A first clone of a large repo outlived the 30s client timeout, and the CLI
  answered **"is the stack up? (wadi up)"** — to a user whose stack was healthy
  and whose snapshot was `running`. Worse, retrying as invited starts a *second*
  snapshot beside the first.
- A damaged git checkout produced a **wall of raw git output** with no
  interpretation and no next step.

Every error path in the CLI printed `[red]{exception}[/red]` and exited. That
reads as an accusation rather than help. A user who hits an error is already
stuck; the message is the only thing between them and being unstuck.

### Changed
- **Every error now says what failed, why, and what to run** — one shape across
  all 24 error paths: a plain-language headline, the underlying detail as
  indented evidence, what is still true *despite* the failure, and runnable
  commands. Suggested commands are soft-wrapped so a long path stays
  copy-pasteable instead of being broken mid-token.

### Fixed
- **A timeout is no longer reported as an unreachable stack.** `ApiTimeoutError`
  is now distinct from `ApiUnreachableError` — the old code caught
  `httpx.TransportError`, which covers both, so a request that was *succeeding*
  server-side told the user their stack was down. The message now says the work
  may still be running, says how long it waited, and points at
  `wadi snapshots <system>` rather than inviting a duplicate run.
- **A name collision is explained instead of silently resolved.** `analyze`
  reuses a system by NAME; when the registered sources differ from the ones you
  asked for it now names both, says reusing would analyze something you did not
  ask for, and suggests a free name — verified free against the API, so the
  suggested command runs as printed.
- **Docker failures are diagnosed**: daemon not running, port already taken, and
  the generic case each get their own headline and first move.
- Repository failures distinguish *unreachable* from *damaged git metadata*, and
  the suggested `git fsck` carries the real path rather than a placeholder.

## 0.7.1 — 2026-08-06 (a self-upgrade that verifies it happened)

`wadi upgrade` announced success without checking. Reported against 0.7.0: the
CLI said `upgraded to 0.7.0`, removed the six 0.6.0 images, and `wadi --version`
still answered `0.6.0` — leaving a CLI whose images had just been deleted.

Two causes, one of which is the more serious:

**A zero exit is not evidence.** `uv tool upgrade` prints "Nothing to upgrade"
and exits 0 when its cached index shows nothing newer, and `run_upgrade` checked
only the return code. Everything after it — the prune, the success line — ran on
an upgrade that had not happened. This is the failure class wadi exists to
prevent, in wadi's own tooling: a confident claim with no verification behind it,
followed by a destructive action taken on the strength of it.

**And the reason there was nothing to upgrade:** the CLI asks PyPI directly over
HTTP for the latest version, while uv resolves from a cached package index. The
moment someone runs `wadi upgrade` is exactly when that cache is most likely
stale — minutes after a release. Measured on the 0.7.0 report: a cached resolve
returned 0.6.0 while `--refresh` returned 0.7.0 for the same PyPI state.

### Fixed
- **The upgrade is verified before anything is claimed or deleted.** After the
  installer runs, the CLI asks the `wadi` executable what version it is now —
  the only channel-agnostic check, since this process still has the old
  `CLI_VERSION` baked in and parsing installer output would need one rule per
  channel. If the version did not move, the CLI says so, names the likely cause,
  and **leaves the old images in place** so the version you are still running
  keeps working. If the check cannot run at all, that is reported as unverified
  rather than as either success or failure — an unknown is not a negative (P10).
- **The uv command forces a fresh index for this package**
  (`--reinstall-package`, which implies `--refresh-package`). Scoped to
  `wadi-sh` so an upgrade never invalidates the cache for everything else.

## 0.7.0 — 2026-08-06 (Phase 2.9.2: extraction fidelity — what "still missing" actually was)

A full re-measurement of `train-ticket-aitest` (365 endpoints / 22 services) to
answer "what is extraction still missing?" The answer was mostly *not what it
looked like*, and that finding shaped the release.

**Endpoint extraction was already complete: 365 of 365.** The one controller
with no extracted endpoints is wholly enclosed in `/* */`; the service impls
that looked like missed call sites are a method whose only caller is commented
out and classes no controller in their own service reaches. An independent
DI-aware reachability oracle agreed with wadi on 365 of 382 call sites with
**zero over-reports**. The corpus, not the extractor, accounted for the bulk of
what read as missing.

What WAS missing was narrower and sharper — and three of this phase's own
conclusions were wrong before measurement corrected them. Each survived because
an aggregate moved in the expected direction; each fell the moment one of its
members was opened against source. **A count is a hypothesis until you open one
of its members** is the standing lesson, recorded in §5.2.11.

**Re-analysis is worth it:** contracts moved to 1.21.0 and the export to 2.11.0.

### Added
- **Response payloads, not just envelopes.** Every endpoint used to publish
  `{status, msg, data}` with `data` an unbound `T` — a shape naming the wrapper
  and withholding the only field a reader wants. No signature carries the type
  (services declare a RAW `Response`); the producer's return statement does. Now
  read from there, on the declared path as well as the recovered one.
  **Measured: 0 → 213 of 291 envelopes answered.**
- **`always-null` as its own shape terminal.** A field every construction sets
  to `null` is EMPTY, not unknown. Whole TrainTicket services are written this
  way, and calling them `unresolved` claimed an analysis failure about code that
  states plainly it sends no payload.
- **Declared HTTP statuses per endpoint** — 365/365 carry at least one, each
  marked with how it was read (`builder` / `explicit` / `annotation` /
  `default`). Named `declared_` deliberately: a 500 from an exception, a 403
  from the security layer and a 404 from the dispatcher appear in no handler
  source, so this is never the complete set.
- **Response shapes recovered from the return expression** where the signature
  declares a raw wrapper. TrainTicket writes `public HttpEntity query(...)` 376
  times against 9 generic ones, so the signature genuinely names no payload.
  **Measured: unresolved 274 → 11.** `TypeShape.origin` keeps an inferred shape
  distinguishable from a declared one.
- **CORS, CSRF and rejection handling reach the reader.** The pack had tagged
  them since export 2.8.0 and the client had parsed them just as long — into a
  model no service read. Read and discarded is indistinguishable from never
  extracted. Now on the service boundary and in coverage, never merged into an
  endpoint's auth claim: they decide which ORIGIN may call, not which principal.
- **Token propagation on every outbound call** — `forwarded` /
  `not-forwarded` / `undetermined`. Was `null` on 382/382. The negative is
  claimed only where provable (a request built with no headers at all), never
  inferred from silence.
- **Reachability provenance** on remote calls (`endpoint` / `async-root` /
  `unreached`), so an excluded call says whether a startup root reaches it.
- **`unexercised_vocabulary`** in coverage — the idioms a snapshot contains zero
  of, so `denied: 0` stops reading as evidence the denial path works.

### Fixed
- **Two admin-only config endpoints were published as public.** `POST` and
  `PUT /api/v1/configservice/configs` moved from an evidenced `false` to
  `true [ADMIN]`. Two controllers write `@RequestMapping("api/v1/...")` without
  a leading slash; a wildcard-free rule requires an exact match, so the
  slash-less URI matched neither `ROLE_ADMIN` rule and fell through to a later
  `permitAll`. Served routes are now root-anchored. **No identity churn** —
  `endpoint_id` already hashed the normalized form, verified across all 365.
- **The unbound-callee classifier manufactured 585 binding failures.** Every
  one was `Response.<init>` on a Lombok `@AllArgsConstructor` DTO: matching a
  declaration by NAME let a bodiless stub stand in for a constructor never
  present in source, pre-empting the `lombok-generated` branch. It now requires
  a declaration with a BODY. **`declared-not-bound` 585 → 0** — the corpus has
  no call-binding holes.
- **Two latent bugs found in pre-landing review**, neither reachable on this
  corpus but both now fixture-guarded: the type-argument binding counted static
  fields the shape walk hides (an envelope with a `static final Logger` would
  silently bind nothing, or misalign every field index after it), and the
  status reader scanned every constructor argument, so an integer BODY in the
  100-599 range would publish a status the endpoint never sends.

### Changed
- `unresolved-receiver` split into `declared-not-bound`, `not-declared` and
  `unparseable-callee`. One code served as both a finding and the classifier's
  fall-through, so a regression collapsing every classification into the
  default would still have looked covered.

## 0.6.0 — 2026-08-05 (Phase 2.9: auth fidelity — the enforcement model)

An audit against the live train-ticket snapshot found the auth layer publishing
`authenticated: false` — "no authentication, evidenced" — for endpoints that
require `ROLE_ADMIN`. A `SecurityConfig` rule wadi could not read was *dropped*,
so the endpoint fell through to a later `permitAll()` and a wrong security fact
went out with full confidence. That is the outcome §12 exists to prevent.

The model now asks a different question: **what could gate a request to this
endpoint, and did we read all of it?** Every gating construct — annotation,
filter-chain rule, chain bypass, interceptor, servlet filter, aspect, in-handler
check — is one enforcement record, and the claim is withheld when an unread guard
could change it. That rule is a contract validator, not a convention.

**Re-analysis is worth it:** stored contracts moved to 1.15.0 and the Joern
export to 2.7.0. Measured on train-ticket (262 endpoints / 41 services), `null`
claims went **48 → 0**, and every remaining no-claim now names the guard it could
not read.

### Added
- **The system auth view** (`?view=auth`) — every endpoint's auth state on one
  screen, with totals and filters for protected / unprotected / denied /
  withheld / no-evidence. "Which endpoints here are unprotected?" stopped being
  a walk over every service.
- **Enforcement outside Spring Security is visible** — gating interceptors,
  servlet filters, aspects and checks written inline in a handler are detected
  narrowly, on evidence that they can answer 401/403, so a logging interceptor
  never withholds a claim while a real guard does.
- **Config-defined authorization** — `@ConfigurationProperties`-bound rule sets
  are correlated against the parsed YAML, so a service whose policy lives
  entirely in `application.yaml` (no literal path anywhere in the Java) reports
  its real rules. All 15 yas modules recovered.
- **How authentication happens, per endpoint** — jwt-bearer, oauth2-resource-server,
  http-basic, form-login, x509 and the rest, with `.disable()` honored. A custom
  filter is promoted past "custom-filter" only on evidence *inside* the filter;
  naming a mechanism from a class name would be a fabricated fact.
- **A fourth honest state, `withheld`** — distinct from "no evidence" everywhere
  it appears. Both mean "no claim", but one is a gap in wadi and the other a
  possible hole in your system, and they call for opposite responses.
- **`denied`** — a route behind `denyAll()` is unreachable, not protected, and
  now reads that way instead of counting as live surface.
- **Auth coverage on every report** — claim states and unreadable guards by kind,
  so blind spots stay queryable rather than prose.

### Changed
- **The overview and the endpoint workspace were rebuilt.** Endpoint rows carry a
  second line naming who can reach them, coloured from a snapshot-wide role
  palette; clicking one opens a peek with the contract — cross-service calls
  first, then access, parameters, and request/response shapes — and a single way
  into the flow. The workspace is call tree | flow | source, permanently: the
  Graph/Source toggle and the inspector tabs are gone, the contract having moved
  one screen earlier.
- **The source panel shows one card per file** — its own edges, its own header,
  numbered by where the flow first reaches it. The handler's file opens on
  arrival and the rest open on click, or on their own when a selection lands
  inside them. A closed file fetches nothing, so a ten-file endpoint no longer
  pays ten whole-file requests before you read the first one.
- **Roles and authorities are separate facts.** `hasRole("X")` and
  `hasAuthority("X")` match different grants in Spring; both now reach the UI
  without either being renamed as the other.

### Fixed
- **Security rules stopped inheriting the wrong HTTP verb.** The verb was read
  from the whole fluent chain, so the first `HttpMethod.X` in a config stamped
  every later rule — 12 endpoints in `ts-travel-service` alone went unknown
  because of it.
- **A rule that could not be read is no longer dropped.** It is emitted as a
  hole, so the walk stops there instead of falling through to whatever permissive
  rule comes next. This is the defect that produced the wrong `false`.
- **Non-literal rule patterns resolve** — constants, arrays and `${placeholders}`
  — instead of vanishing.
- **A literal rule no longer governs a templated sibling.** Path matching treats
  an endpoint's `{orderId}` as matching any literal, which is safe for a rule
  that adds restriction and wrong for one that removes an endpoint: a
  `denyAll()` on `/orders/legacy` was withdrawing `/orders/{orderId}`.
- **Inert security annotations are marked, not counted.** Spring Security 6
  defaults `securedEnabled` and `jsr250Enabled` to false, so a `@Secured` that
  enforces nothing was being reported as enforcement.
- **Custom composed annotations and inherited policies resolve** — `@IsAdmin`
  declared as `@PreAuthorize(...)`, and a rule declared on a parent class or an
  implemented interface, were both invisible.
- **Code in the source panel keeps its syntax colours in every theme.** Leftover
  template stylesheet rules overrode the highlighter and keyed their dark variant
  off the OS preference while the app themes by class — so choosing the dark
  theme on a light-mode machine gave you black text on a white pill over dark
  code.
- **Every button reports itself to the keyboard and the pointer.** The auth
  view's filters had neither a focus ring nor a pointer cursor.

## 0.5.3 — 2026-08-04

Local-stack reliability. The stack could take itself down while idling, and
could not be fully torn down or cleaned up once it had. No contract, schema, or
analysis change — nothing needs re-analysis.

### Fixed
- **The Joern health probe no longer kills Joern.** It submitted
  `POST /query {"query":"1"}` every 10s — but that endpoint is a REPL
  *evaluation*, permanently binding a `resN` val and its compiled wrapper class
  in the shared interpreter, and the probe never collected the result. Measured
  ~0.9MiB leaked per probe (452MiB → 981MiB over ~650 probes, reaching
  `res646`), exhausting the heap within hours of *idling* — which is why
  `wadi up`/`wadi ui` began failing with `container wadi-wadi-joern-1 is
  unhealthy`, and why an analysis could fail with every service reporting
  `CPGQL server unreachable: Connection reset by peer`. The probe is now
  `GET /result/<fixed-uuid>`: a full round-trip through the server's router that
  touches no interpreter state.
- **Joern gets the memory the compose file reserves for it.** The JVM was
  running on its ergonomic default heap — 25% of `mem_limit`, 1.5g of 6g. Now
  `-XX:MaxRAMPercentage=75.0` (~4.5g).
- **`wadi down` tears the stack all the way down.** `wadi mcp` starts the one
  container compose does not own, so compose left it running and then could not
  remove the network it held open (`Network wadi_default Resource is still in
  use`). The container is now named and labeled, cleaned up when the CLI exits
  or is terminated, and swept by label at the start of `wadi down` — which
  reports each one it stops. `down` also passes `--remove-orphans`.
- **Extraction no longer leaves its build scratch behind.** `/workspace/<snapshot>`
  (repo checkout, staged parse roots, Joern export files — all derived, all
  already consumed into Mongo) is removed when the job ends, success or failure.
  It had reached 43 directories / 3.3GB, and because `/workspace` doubles as
  Joern's project root, every stale directory became a bogus project that Joern
  rescanned and stack-traced over on each boot (3,183 log lines on a cold start).

### Added
- **`wadi upgrade`** — promised in §15 since Phase 1, now implemented. Resolves
  the latest release from PyPI, stops the stack, upgrades through whichever
  channel installed the CLI (uv / pipx / Homebrew — detected, not configured),
  then prunes the superseded version's images. `--check` reports only.
- **`wadi prune`** — removes images and rendered compose files from older
  versions. Every release publishes a full image set, so upgrades accumulate
  multi-GB copies (21 stale images across 5 versions on one machine). Analysis
  data is never touched: it lives in the `wadi_*` volumes, which no cleanup path
  considers.

## 0.5.2 — 2026-08-04

The endpoint workspace stops losing track of what you selected. Every change
here is UI over unchanged data — no contract, schema, or analysis change, and
nothing needs re-analysis.

### Added
- **The source panel shows whole methods, not whole files.** It rendered every
  line of every touched file — 389 lines to show the 27 an endpoint runs, of
  which ~7% carry a graph node. The unit of disclosure is now the method,
  matching what the rest of the workspace already reasons in. Everything
  between methods folds into a `⋯ N lines · a–b` strip that opens on click, and
  the file header counts what is folded, so hidden is never silent (P10). A
  method spans annotation through closing brace, joined from the entry and exit
  node anchors: the assembler already anchors the exit node at Joern's
  `method.lineNumberEnd`, so the real extent was in every existing artifact one
  node away.
- **Soft wrap, a filterable file index, a pinned method name, and marked
  clickable lines** in the source panel. Wrap is a per-user preference in
  localStorage, never the URL — how you read code is not what a shared link is
  about. The file chips filter instead of scrolling, and yield automatically if
  a selection targets a hidden file.
- **Selecting a method shows on the canvas.** An expanded method draws no card,
  so it had no selection ring: choosing one from the call tree or a call link
  in source moved the URL and highlighted the source region while the graph
  showed nothing. Lanes now carry their own selected state, and a lane header
  click selects its method.

### Changed
- **Clicking a node opens the code, not a facts panel.** Selection landed on
  the inspector's Selection tab, hiding the source panel that was already
  tracking the selection. Every selection path — canvas, call tree, call links
  inside source — now lands on Source, with one rule in the store rather than
  one per caller. Remote-target ghosts keep the Selection tab: they have no
  source of their own, and their resolution, confidence, and provenance are
  stated nowhere else (P10).

### Fixed
- **A selection could point at something the canvas was not drawing.** Clicking
  a line in source, following a deep link, or pressing Back selected a
  statement whose method was collapsed — the URL said `stmt:…`, source
  highlighted the line, and nothing on the graph was ringed. The canvas now
  opens whatever hides the selection: the owning method, or the condensed run
  holding it (runs are drawn under their own id, so a member's id matched
  nothing). Resolution is one step at a time and converges.
- **The graph did not always bring a selection into frame.** The rule tested a
  node's centre point, so a lane with its middle on screen counted as visible
  while its header sat above the pane. It now frames the node's full extent,
  leaves the viewport alone when the node is already whole on screen, and
  frames the top of anything taller than the pane.
- **Duplicate governing-condition chips on remote targets.** A ghost unions
  conditions across every call site reaching it, and several sites commonly sit
  under the same branch. Undeduped, the two-chip budget spent both slots on one
  condition and React saw two children with the same key. Deduping before the
  cap also recovers a second, genuinely different condition the map was
  dropping.
- **A method beyond a truncated source window rendered the wrong code under its
  name.** The orchestrator caps a source response at 2000 lines; a region
  starting past that window is now dropped rather than clamped onto the last
  loaded line.
- **`scrollIntoView` is guarded as an optional call**, so an environment
  without it cannot abort the render pass that opens a fold.

## 0.5.1 — 2026-08-04

### Fixed
- **Canvas nodes were unclickable.** React Flow stamps `pointer-events: none`
  on a node's wrapper whenever the node is neither selectable nor draggable
  and no node-level mouse handler is registered — which is every node this
  canvas draws, because selection belongs to the workspace store rather than
  to React Flow. Clicks fell through the card into the pan surface, so select,
  expand and drill-in were all dead to the mouse while still rendering as
  interactive. Lane headers kept working (they already opted back in), which
  is what disguised how broad it was. Present since the lanes canvas landed in
  Phase 2.8 and shipped in 0.5.0; a test now pins both halves — that React
  Flow really does disable pointer events under these props, and that every
  node type really does turn them back on.

## 0.5.0 — 2026-08-04 (Phase 2.8: the endpoint workspace)

The 0.4.0 Flow workspace put the call tree, canvas, and source in one
fixed-width three-pane tab; at real scale (234 nodes on the aitest cancel
endpoint) the graph rendered as an unreadable smear and the source strip
truncated every line. This release splits browsing from the deep-dive and
rebuilds the canvas around execution order (architecture.md §11 Phase 2.8).

### Added
- **A dedicated endpoint workspace** at its own route
  (`/s/{snapshot}/e/{endpoint}`), full viewport: persistent identity header,
  resizable call-tree rail | center lens | tabbed inspector, deep-linkable
  via `?node&focus&expand&lens&tab&file`. Browser back returns to the
  overview.
- **The lanes canvas** — the flow is a vertical stack of per-method lanes in
  call-tree order (a callee always sits below its first call site), each
  laid out independently in source order, so the canvas reads top-to-bottom
  like a document instead of sprawling like a map. Interprocedural calls
  route through a left gutter; remote/DB/MQ targets pin to a right rail at
  their call-site height — the collapsed view alone answers "what does it do,
  who does it talk to".
- **Focus and wayfinding:** focus-on-method re-roots the view to that method
  and its callees (reversible via a clickable breadcrumb), search runs over
  the whole closure and auto-expands the method containing a hit (with
  next/prev), a trace toggle highlights the path from the handler to the
  selection, and expand-all is gated behind an actionable node-budget
  confirm. Keyboard: `↑/↓` execution order, `Enter` expand, `f` focus,
  `/` search, `Esc` unwind.
- **Graph ⇄ Source lenses** over one selection: source now gets the full
  center surface instead of a 36% strip, with every touched file in a single
  scroller and sticky per-file headers (the nested-scroll smell is gone).
- **Tabbed inspector:** Selection (node identity, governing conditions,
  per-edge resolution with confidence/provenance, source peek → open in
  source) and Endpoint (auth evidence, params, request/response shapes,
  outbound calls).
- **`GET /snapshots/{id}/endpoints/{eid}/detail`** → `EndpointDetailView`
  (**contracts 1.12.0**, additive, read-only): the endpoint plus its outbound
  edges filtered server-side to that endpoint's call sites, the touched-file
  list, and honest `icfg_available` / `stitched` flags. Source stays fetched
  on demand.
- **Contracts 1.12.0 — the honesty fields (§5.4.2 T5).** `IcfgNode` gains an
  optional `callee_unbound_reason`, and `EndpointDetailView` gains
  `unopenable_calls` (per-reason counts for this endpoint's flow) and
  `icfg_schema_version`. All additive and absent-means-unknown: on an ICFG
  written before 1.12.0 a null reason and an empty `unopenable_calls` mean
  "not recorded", never "this call opens fine" — which is why the view states
  the graph's version rather than leaving the empty list to be misread.

### Changed
- The main UI is now a **snapshot overview home** (`/s/{snapshot}`) —
  coverage-first, system map, and a two-column services/endpoints browser
  with summary rows (auth state, param count, recovered shapes).
- One source renderer everywhere: the drill-in peeks and the full lens share
  the same shiki pipeline, so code looks identical in both.
- Canvas colors moved onto oklch design tokens (`--flow-*`); edge kind is
  encoded by hue, dash, and label together, so color is never load-bearing.
  Unresolved targets remain the only destructive-toned element and are never
  hidden by collapsing, condensing, or focusing (P10).
- Selection no longer triggers graph layout: clicking a node re-renders only
  the nodes that subscribe to it, and expanding one method re-lays out only
  that lane.

- **The source panel is now the workspace's default surface, not a
  destination.** The inspector opens on `Source`, and whatever is selected on
  the canvas or in the call tree is highlighted in it immediately — no "open in
  source" step. Selecting a method lights its **whole body**; selecting a
  statement or branch lights exactly its own lines. Clicking a line of code
  selects its node on the graph, so navigation runs both ways. The highlight is
  a persistent tinted band with an accent rule rather than a flash that fades
  after a second, long lines scroll inside the code column against a pinned
  gutter instead of being truncated with an ellipsis, and a missing `min-w-0`
  that let a long line stretch the whole panel past its slot — taking the tab
  bar and file index off-screen — is fixed.

### Fixed
- **Degenerate constructs no longer go silent in the CFG (§5.2.8 T3,
  export 2.6.0).** The always-on `cfg_anomalies` invariants flagged 9
  violations on a 22-service snapshot; all three shapes behind them turned
  out to be real defects, and each was probed into a new `DegenerateController`
  fixture and measured against a live CPG before anything was changed.
  - An `if` arm written only to say nothing happens (`//do nothing`) claims no
    statements, so labeling arms by containment dropped that arm's edge to
    plain `flow` — the graph could not say which way control went. Arms are
    now labeled by which of them *reaches* each target. When both arms are
    empty they converge on one edge that cannot carry two labels; that stays
    `flow` and is recorded as a non-representable rather than half-named.
  - A branch or loop that ends its method had **no edge at all** for the arm
    not taken: the export is deliberately exit-free, and the assembler's exit
    patch keys on has-any-out-edge, so a one-armed branch looked connected.
    The graph now says *"on false, the method returns"* — an arm-labeled edge
    to the method's exit, surfaced on the canvas as a `false → returns` chip
    (the lanes view draws no exit nodes, so the edge would otherwise have been
    correct in the contract and invisible in the product). Empty-body loops
    are untouched: fabricating a body arm would assert a body that isn't there.
  - A `try` whose body is entirely commented out entered through its own
    CATCH, presenting the handler as normal flow, and orphaned the statement
    after it into a false second entry point. A try now enters through its
    body block, an empty body routes handlers as `exception`, and normal
    completion is wired explicitly.
- `branch-arity` is reformulated to the defect it can still catch (a construct
  naming no outcome at all) with a new `unlabeled-arm` code for the labeling
  failure; loop arms are checked for the first time. The assembler and the
  invariants share one predicate for "this arm leaves the method", so they
  cannot disagree about which silences are honest.
- The export schema version reads 2.6.0 on both sides — T5's `unbound_reason`
  had shipped with only its docstrings bumped.

  Measured by re-analysing the 22-service benchmark: **`branch-arity` went 6 →
  0**, and `ts-auth-service /api/v1/auth` now carries the `false` edge into its
  method exit that the graph previously could not state. `disconnected-node`
  holds at 3, all inside one method with a fully commented-out `try` body:
  that try is its method's last statement, so normal completion has nowhere to
  go, and two statements inside its handler are disconnected for reasons not
  yet measured. Left counted in `cfg_anomalies` rather than suppressed.

- **Three ways the graph could still assert something false (pre-landing
  review).** Each reproduced against a live CPG first and is now pinned by a
  fixture, because a wrong edge is worse than a missing one: it is confidently
  wrong on the one surface whose whole claim is that it maps the code.
  - An empty `try` nested in an if-arm or at the tail of a loop body found no
    next sibling — normal completion went unwired, and a construct whose every
    successor is a handler is taken to have left the method, so the graph said
    *"on normal completion this returns"* about code that plainly continues.
    Completion is now searched **outward** through the AST, and back to the
    loop header at the tail of a body.
  - An empty `try` with a statement before it was skipped entirely by that
    statement, leaving the try with no incoming edge, a second entry point
    patched in, and two independent predecessors on the statement after it.
    Predecessors now route through the try. An enclosing branch is handled
    separately: consuming its edge would stamp the skipping arm's label on the
    path *into* the other arm, so it gets its own arm-labeled edge instead.
  - `while (true)` / `for (;;)` present the same label set as a trailing loop —
    body arm plus a back edge, no exit arm — so an exit arm was synthesized for
    a method that cannot return. The condition now tells them apart, and
    `exit-unreachable` stays live on them: a method whose only way out is a
    loop it cannot leave HAS an unreachable exit, and that is worth counting.
- **Three unbound-reason mislabels, each of which stated a positive falsehood
  in the UI.** A receiver javasrc2cpg could not bind was reported
  `third-party` ("declared outside every analyzed source root") rather than
  `unresolved-receiver`; `inherited-external` ("declared by a framework
  supertype, not by the type in your repo") fired on any class with any
  external supertype, so `implements Serializable` was enough; and the
  accessor test matched any name merely *starting* with get/set/is, so
  `settle()` on a Lombok type read as a generated accessor with no source.
  The classifier is also **total** now — a null reason strictly means the call
  bound, never "unclassifiable".
- **The source panel could highlight the wrong lines.** The source route split
  content with `str.splitlines`, which breaks on form feed, vertical tab and
  U+2028; compilers do not, so every ICFG anchor after one of those characters
  pointed at the wrong line — while the gutter printed numbers that agreed
  with themselves. An anchor is a compiler line number, so the route now
  counts lines the way a compiler does.
- The bytecode oracle's false-positive budget counts back-jumps: `while (true)`
  folds to an unconditional `GOTO`, so a budget of conditional jumps alone
  called a correct loop node a phantom branch. Constant-true conditions and
  try-with-resources join the §5.2.8 desugaring whitelist.
- The unbound-reason classifier memoizes per `(type, method)` instead of
  walking a declaring type's whole AST once per call site — on the benchmark
  that is 1,881 call sites over 617 distinct callees, 92.9% of them taking the
  annotation-scanning path.
- **Failures no longer read as analysis results (P10).** An unreachable API
  rendered "No systems yet — run `wadi analyze .`" on the landing page and a
  blank pane in the services browser; a failed ICFG fetch rendered "no flow
  graph was extracted for this endpoint — the handler could not be resolved",
  blaming the analysis for a network error. An ELK rejection left a silent
  blank canvas, and a failed "load more lines" reset its spinner and showed
  nothing, so the file appeared to end. Each now says what actually happened.
- **The MCP roll-up carries `callee_unbound_reason`.** REST and the frontend
  got the T5 reasons; the agent-facing surface did not, and an agent has less
  recourse than a human — it cannot go and look.
- Endpoint-workspace load no longer fetches and syntax-highlights every
  touched file up front (§5.3 says on demand; it was doing all of them), and
  the `/detail` aggregate parallelizes its four independent reads and tests for
  the coverage report's existence instead of deserializing it whole.
- `Cmd+F`/`Ctrl+F` no longer re-roots the canvas while you reach for Find, the
  canvas shows a focus ring for the keymap it owns, and a line of code is
  reachable by keyboard as well as by click.

### Removed
- The single-route explorer, its detail pane, the second (unhighlighted)
  source renderer, and the old canvas. Pre-2.8 deep links other than
  `?snapshot=`/`?endpoint=` (which still forward) no longer resolve.

## 0.4.0 — 2026-08-03 (Phase 2.7: the visual map)

### Added
- **The Flow workspace** — the endpoint's whole story in one three-pane,
  three-way-synced view (`?tab=flow`, deep-linkable incl. `?node=`):
  - **Endpoint source map (M1):** every file the endpoint touches as
    navigable sections, whole-file fetched lazily per file (§5.3 — never
    preloaded), executed extents highlighted from ICFG anchors, untouched
    code dimmed but never hidden, construct/sink gutter marks, and call-site
    lines jumping to their callee's section. Shiki highlighting with
    per-language lazy grammars (polyglot-ready). Backend hardening
    (contracts 1.9.0): `SourceView.total_lines`/`truncated`, a 2000-line
    window cap that pages honestly, and tree paths rejected with 400.
  - **Call tree (M2):** handler-rooted hierarchy from the ICFG's call
    edges — callees at their call sites, recursion as a cycle chip,
    per-row sink/construct badges.
  - **Semantic-zoom canvas (M3):** Level 0 draws method cards + call edges
    with remote/DB/MQ targets lifted up as ghost stubs; expanding a method
    reveals its statement subgraph (condition text on branches, labeled
    `true`/`false`/`case v1,v2`/`default`/`fallthrough`/`exception` edges,
    animated back-edges); linear statement runs condense into expandable
    "*n statements*" nodes. React Flow + deterministic ELK layout.
- **The system Map view (M4):** a new read-only
  `GET /snapshots/{id}/graph` (`SystemGraphView`, contracts 1.10.0) serves
  the whole snapshot in one read; the Map draws services (gateway icons,
  anomaly badges, extraction-failure holes) with edges aggregated per
  caller→target, styled by confidence — and the unknowns are FIRST-CLASS:
  external hosts, placeholders, and per-caller `unresolved` sinks
  (undetermined facts are edge-less in Neo4j by design and now join the
  map from the Tier-1 stitched set — an omission the new e2e caught).
  Edge click opens the call sites with slicer/gateway evidence; service
  click scopes the Explorer. Pre-stitch, `stitched=false` says why edges
  are absent (never an empty lie).
- **Story & trust (M5):** outbound calls carry their governing branch
  ("calls ts-preserve-service *when `order.getStatus() == NOTPAID …`*")
  from an interprocedural nearest-branch walk (recorded heuristic);
  unresolved calls and CFG-anomaly sample sites drill into
  source-on-demand in place; deep links restore the entire workspace.

### Changed
- Explorer selection state (system/snapshot/service/endpoint/view/tab/node)
  mirrors into the URL — any view is shareable and reload-stable.

## 0.3.0 — 2026-08-03 (Phase 2.6: control-flow fidelity)

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
