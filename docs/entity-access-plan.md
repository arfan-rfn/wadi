# Entity access plan

**Status:** proposal, not a decision record. Compiled 2026-11-13 against commit `118eb91`
(wadi 0.8.2, contracts 1.25.0). Nothing in this document is built.

**Purpose.** For each endpoint, wadi should say which entities the endpoint touches and how:
create, read, update or delete. REST, the MCP server and the UI should all carry the fact. This
document records the 27 decisions from the design interview of 2026-11-13 and the measurements
behind them. It is the input to `/office-hours` and `/autoplan`.

**What this is not.** It changes nothing in `architecture.md`. The phase gets a `§5.2.x` decision
record in that document first, per the standing rule, and a `TODOS.md` line for each deferral.
Field names, route shapes and milestone boundaries here are proposals for the planning stage.

**Amended by.** `docs/designs/entity-access.md` (office hours, 2026-11-13) amends Q1, Q9, Q10,
Q11, Q12, Q14, Q15 and Q18 and adds a precision gate in front of Q22 and Q23. Where the two
documents differ, that one is current. `docs/designs/entity-access-implementation-plan.md`
(approved 2026-11-13) then fixes the contract shapes and milestones, and `architecture.md`
§5.2.17 is the decision record.

**How to read the evidence.** "Measured" means a command ran on 2026-11-13. "Read" means someone
opened the code. "Unconfirmed" means the statement was read from code and not checked on a
snapshot. `Qn` is the question number from the interview. A bare `§N` is a section of
`docs/architecture.md`.

---

## 1. What exists today

All read on 2026-11-13. None of it was checked on a snapshot in that session.

- `SpringDataSinkPass` tags every call on a Spring Data repository interface with `sink=db`, and
  the ICFG node carries `sink: db`. It does not record the verb.
- `SpringModelPass` tags `@Entity` and `@Document` classes. The worker writes them to the
  `data_models` collection with their fields. Only the export stream reads that collection.
- Nothing links a database call to an entity. javasrc2cpg drops generic arguments, so
  `JpaRepository<Order, String>` loses `Order`. The export has to read it from source text, the
  way `TypeShapes` does for members.
- Only Spring Data repository interfaces count as database calls. `EntityManager`,
  `JdbcTemplate`, `MongoTemplate`, MyBatis and `@Query` are unmarked.
- `SpringDataSinkPass` checks direct parents only (`SpringPacks.scala:686`), so a repository
  that extends a project base interface is probably invisible. Unconfirmed.
- `forEach(x -> repo.save(x))` reaches no endpoint ICFG (`foundation-hardening-plan.md`, A1).
- The endpoint workspace has three permanent panes (call tree, flow canvas, source) and no tabs.
- Architecture goal 5 is "what data each endpoint touches". No phase plans it.

## 2. Measurements

### Persistence mechanisms in the three corpora

Measured with ripgrep over main sources. Tests and `target/` are excluded. Comments are not
stripped, so these counts include dead code.

| | train-ticket | yas | ICPC (backend + base) |
|---|---|---|---|
| `@Entity` files | 197 | 41 | 138 |
| Spring Data repository interfaces | 101 | 41 | 111 |
| `save` / `saveAll` / `saveAndFlush` calls | 225 | 82 | 53 |
| `delete*` calls | 93 | 55 | 38 |
| `@Query` | 39 (18 native SQL) | 34 | 688 |
| `EntityManager` files | 0 | 0 | 8 (12 calls) |
| `JdbcTemplate` | 0 | 1 class | 0 |
| Elasticsearch | 0 | 1 repository, 1 `ElasticsearchOperations` user | 0 |
| MyBatis, `MongoTemplate`, Redis | 0 | 0 | 0 |
| Repository writes inside a lambda | 0 | 0 | 3 |
| `cascade =` declarations | 0 | 9 | 86 |

Three facts about ICPC came out of the same pass.

- All 111 ICPC repositories extend the project's `ICPCRepository<E>`, which extends
  `JpaRepository<E, Long>`.
- At least 617 of the 688 `@Query` annotations are `@Query(name = ...)`. The query text sits in
  726 `@NamedQuery` annotations on the entity classes.
- 165 of the 187 files that use `@Transactional` contain no `save`, `persist` or `merge` call.
  Updates there may run through dirty checking or a shared base service. Nobody has opened
  enough methods to say which.

### How train-ticket updates reach the database

Measured on `train-ticket-aitest` from source with comments stripped and `.evosuite-work`
excluded. The wadi stack was down, so no number here comes from a snapshot.

Train-ticket has 37 `PUT` and `PATCH` handlers. The service method behind each one was opened.

| How the update reaches the database | Handlers |
|---|---|
| Repository read, setters, explicit `save` in the same method | 20 |
| No local write. The handler forwards a `PUT` to another service | 8 |
| Read through a helper that returns a `Response` wrapper, setters, explicit `save` | 4 |
| Old row deleted, newly built object saved (`UserServiceImpl.updateUser`) | 3 |
| Existence check, then a newly constructed object with the same key is saved | 2 |
| Setter on a loaded entity with no `save` (dirty checking) | 0 |

- Dirty checking does not occur in train-ticket. Of 2,800 methods, 78 read an entity, call a
  setter and call `save`. Six do the first two without `save`. All six are copies of
  `alterOrder`, which passes the object to a sibling `saveChanges` that saves it.
- Of the 60 `@Transactional` annotations, 16 sit on repository interface methods and 44 on
  service methods. A sample of the lines that follow them named only delete and update methods.
  Not all 44 were opened.
- This result does not transfer to ICPC. See Q25.

A regex pass classified where the argument of each of the 217 `save` calls comes from. The
counts include copies vendored across services, and only about eight members were opened, so
the bucket sizes are estimates.

| Origin of the `save` argument | Calls |
|---|---|
| Constructed in the method, after a lookup on the same repository | 71 |
| Read from the repository in the same method | 68 |
| Method parameter | 42 |
| A repository read or a new object, depending on the branch | 14 |
| Constructed in the method, no lookup | 13 |
| Other local (helper return, cast) | 9 |

Four members of the first bucket were opened. One is a create (`PaymentServiceImpl.pay`) and
three are updates (`ConfigServiceImpl.update`, `TrainServiceImpl.update`,
`UserServiceImpl.updateUser`). Q22 and Q23 exist because of this bucket.

The scripts that produced these numbers were throwaway and are not in the repository. The
planning stage should decide whether the oracle from Q21 replaces them.

## 3. Decisions

Every decision below was put to the user and accepted. Later answers amended four of them, and
the amended form is the one recorded.

### The fact

| Q | Decision | Cost or consequence |
|---|---|---|
| Q1 | An entity is a type that a data access names, scoped to its service. The repository's type argument defines it. `@Entity` and `@Document` classes count even when no endpoint reaches them. Identity is service plus type name. | `Order` in two services is two entities. DTOs never count. |
| Q2 | Only a call that reaches the datastore is a touch. Reading a field of a loaded object is not. | Dirty-checking updates are unclaimed in v1 and named in the coverage report as unmeasured. |
| Q3 | The vocabulary is `create`, `read`, `update`, `delete`. A database call whose verb cannot be read is `unknown`. There is no `write`. | Amended by the user: speak CRUD wherever the code allows it. |
| Q11 | A `save` that cannot be split carries both `create` and `update` and reads "create or update". Every fact carries a `basis` (`method-name`, `query-text`, `argument-origin`, `existence-guard`). The HTTP method never decides alone. | A bounded def-use query per `save` in the Scala pass, covering the calling method plus one caller hop. |
| Q22 | `update` when the saved object came from a read of the same entity. `create` when the code constructs the object and the method does not also look up the same repository. Constructed after a lookup reads "create or update". | Amends Q11. About a third of train-ticket saves fall in this case before Q23 applies. |
| Q23 | The extractor reads which arm of the existence check holds the `save`. The not-found arm gives `create` and the found arm gives `update`, with `basis: existence-guard`. It applies only when the check and the `save` use the same repository and the `save` sits directly inside the `if` or `else`. | One more raw fact per `save` and three more fixture cases. A check on one key can guard a save of another, which would publish a wrong verb. |
| Q16 | The fact means "at least one path through this endpoint performs this operation". It makes no claim about conditions. | The condition chips have open correctness findings and stay out of this fact. |
| Q17 | Cascades are out of v1. `delete(order)` reports `Order` only. | The coverage section lists cascaded children as unmeasured. |

### Extraction

| Q | Decision | Cost or consequence |
|---|---|---|
| Q4 | v1 covers Spring Data repositories only: inherited CRUD methods, derived query names, `@Query`, `@Modifying`. | The largest other mechanism is `EntityManager` at 12 calls in ICPC. |
| Q9 | The lambda fix (A1) is not a prerequisite. Database calls inside lambdas go to the existing `unreachable_sinks` export section. | Amends Q8. Three call sites in three corpora. A1 stays in the hardening plan. |
| Q10 | Repository detection becomes transitive, so `IssueRepository extends ICPCRepository<Issue>` is a repository and `E` resolves to `Issue`. | Changes existing behaviour. ICPC endpoints gain `sink: db` nodes and `touches-db` badges. Before and after counts are measured and one changed endpoint is opened. |
| Q12 | The extractor reads `@Query` text and follows `@Query(name = ...)` to its `@NamedQuery`. The verb comes from the first keyword and the entities from the `from`, `join`, `update` and `delete` clauses. Native SQL resolves table names through `@Table(name = ...)`. | A keyword-level reader, not a SQL parser. What it cannot resolve keeps the verb and names the entity as undetermined. |
| Q14 | The Scala pass emits raw facts per call (repository, resolved entity type, method name, query text, argument origin, guard arm). The Python worker classifies the verb from a data table. The worker stores the result on each ICFG call node and as a summary on the endpoint document and the list row. | The summary is stored twice so the list and system views never read an ICFG. |
| Q15 | `data_models` becomes the entity record. It gains a storage name (`@Table`, `@Document("pets")`), how the entity was declared, and entities that only a repository names. | No second entity artifact. |

### What consumers see

| Q | Decision | Cost or consequence |
|---|---|---|
| Q5 | The stored fact on an endpoint lists what its own service touches. The orchestrator composes the cross-service view at read time from stitched edges and labels each entry with its hop. | Extra read-time work in the orchestrator and the MCP server. |
| Q6 | "Entity coverage" means two things in v1. The system view shows which endpoints touch each declared entity and with which operations. The extraction accounting shows how many database calls were bound to an entity and a verb. | Test coverage of entities is out. |
| Q7 | The left pane of the workspace gains a Calls / Data switch. Selecting an entity highlights its database calls on the flow canvas with the existing trace highlight. The home page gains a system Data view with the entity by operation matrix. | No new top-level tab. |
| Q18 | The per-endpoint summary travels on the existing endpoint and detail routes. One new route, `GET /snapshots/{id}/entities`, returns every entity with the endpoints and operations that touch it, computed at read time the way `/auth` is. | Nothing new is stored for the reverse view. |
| Q19 | `endpoint_detail` carries the summary. `endpoint_icfg` call rows gain entity and operation. One new MCP tool, `entity_usage`, answers the reverse question. | The MCP tools get their own acceptance check. |
| Q26 | An endpoint that writes nothing locally and forwards the request shows "no local entities, forwards to `PUT ts-station-service /stations`", built from the outbound-call facts wadi already has. This ships even if the cross-service milestone is cut. | No new analysis. 8 of train-ticket's 37 update handlers are forwarders. |

### Sequencing and validation

| Q | Decision | Cost or consequence |
|---|---|---|
| Q8 | This is its own phase, 2.10, before Phase 3. It does not wait for the rule-packs plan. The verb table is data, so that plan can absorb it later. | Amended by Q9. |
| Q13 | A measurement decides whether v1 detects dirty checking. The user moved the first measurement from ICPC to train-ticket. It is done, and the answer for train-ticket is no. | Section 2 has the numbers. |
| Q24 | The milestones build the train-ticket slice end to end first (extraction, REST, MCP, UI), then yas, then the ICPC work (Q10, Q12). The fixture carries the ICPC shapes from the first milestone. | ICPC shows almost no entity facts until its milestone. |
| Q25 | v1 ships without setter detection. The twenty-endpoint check runs on ICPC when its milestone starts, before any ICPC entity number is published. | Until then ICPC snapshots carry the Q2 coverage note. |
| Q20 | The cross-service composition from Q5 is the final milestone and is cut to a TODO if earlier milestones run long. Neo4j gets no entity nodes in this phase. | §6 promises "every DB it touches" as a Neo4j query. The decision record names that deferral. |
| Q21 | Validation has three layers. A new fixture, `spring-data-crud-matrix`, has goldens for every shape. An independent oracle per corpus counts repository call sites from comment-stripped source. Twenty endpoints per corpus are opened by hand, including ones where the oracle and wadi agree. | §5.2.11's rule applies in both directions. |
| Q27 | This document records the decisions. `architecture.md` changes at the planning stage. | |

## 4. Shapes the fixture must cover

Collected from Q21, Q22, Q23 and the train-ticket sample.

- A method inherited from `CrudRepository` and a derived query name (`findByStatus`).
- `@Query` with JPQL, `@Query` with native SQL, and `@Query(name = ...)` resolved through
  `@NamedQuery`.
- A repository behind a project base interface.
- `save` of an object read in the same method (update).
- `save` of a constructed object with no lookup (create).
- `save` of a constructed object inside the not-found arm of an existence check (create).
- `save` of a constructed object inside the found arm (update).
- `save` after an existence check that returns early (create or update).
- `save` of a method parameter, resolved through one caller hop.
- `save` of an object that is a read or a new object depending on the branch (create or update).
- A read that arrives through a helper returning a wrapper, then `save` (create or update).
- Delete followed by `save` of a rebuilt object (delete, plus create or update).
- A `save` inside a lambda (reported in `unreachable_sinks`).
- A dirty-checking update (unclaimed, counted as unmeasured).
- An endpoint that only forwards to another service.

## 5. Deferred, each needing a `TODOS.md` line

- Dirty-checking detection, pending the ICPC measurement (Q25).
- Cascaded operations, which need `DataModel.relations` populated (Q17).
- `EntityManager`, `JdbcTemplate`, Elasticsearch and other mechanisms (Q4).
- Lambda-hosted database calls in the ICFG, which is A1 (Q9).
- Entity nodes in Neo4j (Q20).
- Cross-service composition, if the final milestone is cut (Q20).
- Existence checks with an early return, which Q23 leaves as "create or update".

## 6. Unconfirmed

- Whether ICPC's database calls are unmarked today. Read from `SpringPacks.scala:686`, not
  checked on a snapshot.
- How ICPC performs updates. Q25 measures it.
- The split of the 71 "constructed after a lookup" saves between creates and updates. Four of
  the 71 were opened.
- The handler for `PUT /trains` in ts-assurance-service calls `TrainServiceImpl.update`. The
  copy that was read is the one in ts-security-service.
- Three long method bodies were read to 40 lines only: `InsidePaymentServiceImpl.pay`,
  `InsidePaymentServiceImpl.payDifference` and `RebookServiceImpl.rebook`.
