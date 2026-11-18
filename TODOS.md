# TODOS

Open work is tracked in GitHub issues: https://github.com/arfan-rfn/wadi/issues

Open an issue instead of adding an entry here. Give it one priority label and one area label:

- Priority: `P0` ships-blocking, `P1` next tranche, `P2` scheduled, `P3` wanted, `P4` someday.
- Area: `area:extraction`, `area:stitcher`, `area:coverage`, `area:verification`, `area:auth`,
  `area:infrastructure`, `area:analysis-surfaces`, `area:entity-access`.
- `known-limitation` marks a gap wadi knows about and reports instead of hiding (P10). A defect
  gets `bug`.

Close an issue from the pull request that fixes it, with `Fixes #N` in the description.

## Where the old entries went

Older documents name entries of this file by title. On 2026-11-18 each open entry moved to the
issue listed below, with its text unchanged. The completed entries and the full history are in
this file's git log (`git log -p -- TODOS.md`).

### Extraction — response shapes (§5.2.7)

| Issue | Priority | Entry |
|---|---|---|
| [#29](https://github.com/arfan-rfn/wadi/issues/29) | P1 | Characterize the 78 unresolved response payloads |
| [#30](https://github.com/arfan-rfn/wadi/issues/30) | P2 | Resolve cross-service payloads in the stitcher |

### Extraction — unbound callees (§5.4.2 T5)

| Issue | Priority | Entry |
|---|---|---|
| [#31](https://github.com/arfan-rfn/wadi/issues/31) | P4 | 77 `unresolved-receiver` sites are a javasrc2cpg limitation |

### Coverage — vocabulary exercised only by fixtures

| Issue | Priority | Entry |
|---|---|---|
| [#32](https://github.com/arfan-rfn/wadi/issues/32) | P2 | Four vocabularies have never run against a real corpus |

### Verification

| Issue | Priority | Entry |
|---|---|---|
| [#33](https://github.com/arfan-rfn/wadi/issues/33) | P1 | The corpus measurements are not reproducible from the repo |

### Auth — project-defined vocabularies (§5.2.12)

| Issue | Priority | Entry |
|---|---|---|
| [#34](https://github.com/arfan-rfn/wadi/issues/34) | P1 | The aspect that actually answers 403 is not detected |
| [#35](https://github.com/arfan-rfn/wadi/issues/35) | P2 | Enforcement scope is URI-granular, with no HTTP method |

### Infrastructure

| Issue | Priority | Entry |
|---|---|---|
| [#36](https://github.com/arfan-rfn/wadi/issues/36) | P2 | An OOM-killed analyzer reports as a DNS failure |
| [#37](https://github.com/arfan-rfn/wadi/issues/37) | P1 | A minor schema bump is not readable by the previous release |
| [#38](https://github.com/arfan-rfn/wadi/issues/38) | P2 | `wadi status` reported the compose file, not the containers |

### Analysis surfaces not yet consumed

| Issue | Priority | Entry |
|---|---|---|
| [#39](https://github.com/arfan-rfn/wadi/issues/39) | P3 | CORS/CSRF policy is published but not scoped to endpoints |

### Entity access (§5.2.17, Phase 2.10)

| Issue | Priority | Entry |
|---|---|---|
| [#40](https://github.com/arfan-rfn/wadi/issues/40) | P1 | Three decisions the gate needs are open |
| [#41](https://github.com/arfan-rfn/wadi/issues/41) | P2 | Dirty-checking updates are unclaimed |
| [#42](https://github.com/arfan-rfn/wadi/issues/42) | P2 | "No repository call found" is not withheld when another mechanism is reachable |
| [#43](https://github.com/arfan-rfn/wadi/issues/43) | P2 | Database calls inside lambda bodies reach no endpoint flow |
| [#44](https://github.com/arfan-rfn/wadi/issues/44) | P3 | Cascaded operations are not followed |
| [#45](https://github.com/arfan-rfn/wadi/issues/45) | P3 | Other persistence mechanisms are unmarked |
| [#46](https://github.com/arfan-rfn/wadi/issues/46) | P3 | An existence check with an early return stays "create or update" |
| [#47](https://github.com/arfan-rfn/wadi/issues/47) | P3 | Entity nodes in Neo4j |
| [#48](https://github.com/arfan-rfn/wadi/issues/48) | P3 | Outside ground truth for entity access on TrainTicket |
| [#49](https://github.com/arfan-rfn/wadi/issues/49) | P2 | A method reached only through a bound method reference gets no db row |
| [#50](https://github.com/arfan-rfn/wadi/issues/50) | P2 | Collision losers' ICFGs survive the collision filter |
| [#51](https://github.com/arfan-rfn/wadi/issues/51) | P3 | A custom repository fragment's body is outside the endpoint flow |
| [#52](https://github.com/arfan-rfn/wadi/issues/52) | P2 | Store-specific Spring Data repositories are not detected |
| [#53](https://github.com/arfan-rfn/wadi/issues/53) | P3 | No standing index-scan test for the older hot read paths |
| [#54](https://github.com/arfan-rfn/wadi/issues/54) | P3 | A 1.0.x ICFG shows no outbound edges on the detail route |
| [#55](https://github.com/arfan-rfn/wadi/issues/55) | P1 | Native SQL cannot name an entity that declares no `@Table` |
| [#56](https://github.com/arfan-rfn/wadi/issues/56) | P2 | The identity rule knows only Spring's id methods |
| [#57](https://github.com/arfan-rfn/wadi/issues/57) | P3 | The query reader leaves HQL selects that start at `from` unread |
| [#58](https://github.com/arfan-rfn/wadi/issues/58) | P3 | Implicit joins through a path in a `where` clause are not claimed |
| [#59](https://github.com/arfan-rfn/wadi/issues/59) | P3 | A flush-only endpoint reads "No repository call found" |
| [#60](https://github.com/arfan-rfn/wadi/issues/60) | P3 | Two entities with one simple name differ only on hover in the Data matrix |
| [#61](https://github.com/arfan-rfn/wadi/issues/61) | P3 | The undetermined-entity row carries no text for an unbound type argument |
| [#62](https://github.com/arfan-rfn/wadi/issues/62) | P1 | A statement's second call into project code is not followed |
| [#63](https://github.com/arfan-rfn/wadi/issues/63) | P2 | The save's existence check is looked for only in the saving method |
| [#64](https://github.com/arfan-rfn/wadi/issues/64) | P2 | Transitive detection and the hard matching cases have no real-corpus measurement |
| [#65](https://github.com/arfan-rfn/wadi/issues/65) | P3 | The query reader's remaining silent misses |
| [#66](https://github.com/arfan-rfn/wadi/issues/66) | P3 | An entity named only through a marker-typed receiver has no entity record |
| [#67](https://github.com/arfan-rfn/wadi/issues/67) | P3 | Small reader gaps left by the 1.27.0 change |
| [#68](https://github.com/arfan-rfn/wadi/issues/68) | P1 | A vocabulary change must keep 0.9.0 accounting readable |
| [#69](https://github.com/arfan-rfn/wadi/issues/69) | P2 | Review notes left open at 0.9.0 |
| [#70](https://github.com/arfan-rfn/wadi/issues/70) | P2 | Re-measure train-ticket on the shipped export |
| [#71](https://github.com/arfan-rfn/wadi/issues/71) | P3 | `e2e/` is outside pyright's include |

## Opened with the move

Three defects in 0.9.0 were filed at the same time:

- [#26](https://github.com/arfan-rfn/wadi/issues/26) A call that matches no endpoint on two candidate services fails the whole stitch
- [#27](https://github.com/arfan-rfn/wadi/issues/27) A call id hashes the rendered URL, user info and query string included
- [#28](https://github.com/arfan-rfn/wadi/issues/28) `spring.security.*` values reach the UI, REST API, MCP server and export as written
