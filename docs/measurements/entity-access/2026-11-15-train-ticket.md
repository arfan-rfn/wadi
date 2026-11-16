# train-ticket-aitest at a84716f, wadi 41ecddc, 2026-11-15

Snapshot: `snap_b58fd7a5e7d84d0bbbafad5253e36633`, analyzed through a stack whose images were
built from `41ecddc` (export 2.15.0, contracts 1.27.0, rules version `76ef0bd2dfc9b37a`, Scala
save rules `a78b455c8f42aee3`). Seed: 20261115. N: 40, plus the 14 endpoints of the hard stratum.

Readers: two independent agents, each given one half of `blind.json` (27 endpoints) and read
access to the corpus. Each was told not to read the wadi repository, not to call any wadi API and
not to open `key.json`, and to label each endpoint from the Java source alone: start at the
handler, follow calls inside the service, stop at RestTemplate, Feign and message calls, and
write each Spring Data repository call as an entity (simple class name) with the operations some
path may perform. Their call chains and judgement calls are in `notes-reader-a.md` and
`notes-reader-b.md`. The two halves are disjoint, so this run has no figure for agreement
between readers.

## Accounting

All 22 services report. 384 repository call sites: 353 in an endpoint flow and 31 in no flow;
274 bound, 101 `create-or-update`, 9 undetermined entity, 0 `unknown`, 0 flush, 0 implemented in
the project. `gated_operations` is `create, update`. The partitions are the same as at the M6
build (`snap_15b25b8b`).

## Changes since the M6 build

Six in-flow sites changed, every one a save's candidate and basis
(`sites-changed-since-r3.txt`). All six were opened.

| Site | Before | Now | What opening it showed |
|---|---|---|---|
| ts-delivery `InsidePaymentServiceImpl.java:172` (`addMoney`) | existence-guard, candidate `update` | argument-origin, no candidate | `if (findByUserId(id) != null)` tests a `List`, which is never null, and the arm saves a new UUID-keyed row. The review's case (A1). |
| ts-delivery `InsidePaymentServiceImpl.java:259` (`drawBack`) | same | same | Same shape. |
| ts-config, ts-route, ts-user `UserServiceImpl.java:168` (`updateUser`) | existence-guard, candidate `update` | argument-origin, no candidate | `findByUserId` is a derived finder, not one of Spring's id methods, so the found arm no longer gives `update` (B5). The method deletes the old row and then saves a newly built user with the same id. Both readers called that save an update or both create and update, so withholding the candidate loses nothing a reader agrees on. |
| ts-security `ConfigServiceImpl.java:52` (`update`) | existence-guard, candidate `update` | argument-origin, no candidate | `findByName` where `name` is `Config`'s `@Id`: an identity lookup in substance, so the old `update` candidate was right. The identity rule knows only Spring's id methods (`findById`, `getById`, `getReferenceById`, `existsById`), so this is a candidate lost, not a false one. Tracked in `TODOS.md`. |

The review's third case, `ts-price InsidePaymentServiceImpl.initPayment` (an `Optional` compared
to null), is in no endpoint flow (its only caller is a `CommandLineRunner`), so it is not in the
diff above. Its export row moved from `guard_arm = not-found` to `none`.

## Reconciliation

| Measure | Count |
|---|---|
| Oracle sites | 857 |
| Wadi sites | 384 |
| Agree on location | 384 |
| Oracle only (in an exported method) | 473 (0) |
| Wadi only | 0 |
| Entity: agree / disagree / withheld | 384 / 0 / 0 |
| Operation: agree / disagree | 344 / 0 |
| Operation: one-sided query / both query / unpublished | 0 / 9 / 31 |

There are no entity disagreements, no operation disagreements and no one-sided queries. The
pairing check holds: 384 agreeing sites less 31 unpublished is 353, the snapshot's
`in_endpoint_flow`.

The entity comparison reads wadi's entity from the export's repository type argument. The 9
query sites are native SQL on entities that declare no `@Table`, and the snapshot publishes their
read on an undetermined entity. The reconciliation does not see that; the hand check below does.

Oracle-only sites: the same 473 as at R1, identical by (file, line, method). At R1 reviewer D
swept all 473: 359 sit in methods with no name-level caller, 52 have callers only in code outside
the export, and 62 (36 methods) have callers that are name collisions. Every one opened was dead,
and none was reachable from an endpoint. They were not reopened for this run, because the set
and wadi's 384 are unchanged.

## Blind hand check

| Stratum | Endpoints | Full agreement | With an error | Error rate upper bound (95%, one-sided) |
|---|---|---|---|---|
| Random | 40 | 26 | 0 | 7.2% |
| Hard | 14 | 1 | 4 | 54.0% |

| Pair verdict | Random | Hard |
|---|---|---|
| Exact | 13 | 4 |
| Less specific | 13 | 9 |
| Withheld | 1 | 4 |
| Over-claim | 0 | 0 |
| Miss | 0 | 4 |

The scoring rules are in `libs/wadi-testing/src/wadi_testing/measure/blind_sample.py` and were
fixed before scoring. Less specific is `create-or-update` where the truth is `create` and/or
`update`, which the shipped gate publishes for every save. Withheld is `unknown`, or an
undetermined entity covering a true access. Neither counts as an error. The hard stratum is
every endpoint with two or more entities or three or more call sites (a census of 14, not a
sample), so its bound speaks only for itself.

Every endpoint with an error, and the one withheld pair in the random stratum:

| Endpoint | Truth | Wadi | What opening it showed |
|---|---|---|---|
| b011, b041 `POST /api/v1/contactservice/contacts` (two services) | Contacts read, create | Contacts `create-or-update`; undetermined `read` | The read is `findByAccountIdAndDocumentTypeAndDocumentType`, a native `@Query` on table `contacts`. `Contacts` declares `@Entity` and no `@Table`, so the reader does not guess the table name and leaves the entity undetermined. Wadi publishes the read, on no entity. The rule scores that as a miss on the `Contacts` row, because `Contacts` has a named row (from the save). |
| b012, b042 `POST /api/v1/contactservice/contacts/admin` | Contacts read, create | Contacts `create-or-update`; undetermined `read` | Same query, same cause. |
| b014 (random, withheld) | Station read | undetermined `read` | Native SQL on `station`; `Station` declares no `@Table`. Same cause, scored withheld because the endpoint has no named row. |

All four errors and the one withheld pair have one cause: native SQL on an entity with no
`@Table`, the open decision recorded in `TODOS.md` ("Native SQL cannot name an entity that
declares no `@Table`"). Using Spring Boot's default physical naming would bind every one of them.
No endpoint in either stratum has an over-claim.

Reader judgement calls that touched the score: `updateUser` (b005, b038, b053) deletes a row and
saves a newly built one with the same id; reader A labelled the save `update` and reader B
`create` and `update`. Wadi publishes `create-or-update`, which is less specific either way. Both
readers labelled the Contacts save `create` and noted that a client-supplied id would make it an
update.

## Inputs

| File | sha256 (first 16) |
|---|---|
| `oracle.json` | `e60a4690d8756fb5` |
| `snapshot.ndjson` | `ef98b28d7d297c8e` |
| `coverage.json` | `8bbc1a3df9343f28` |
| `reconciled.json` | `d8811593db1562eb` |
| The M6 build's bundle (`snap_15b25b8b`), for the diff | `3089c8032cc83d74` |
| exports: ts-admin-service | `adb68ebc8d6c5fb5` |
| ts-assurance-service | `49d721732a1c562a` |
| ts-auth-service | `6be8059e005db370` |
| ts-cancel-service | `45fd865de748d202` |
| ts-config-service | `e9944e26db62be8b` |
| ts-consign-service | `145b074b4bec744d` |
| ts-contacts-service | `d9d4484459449032` |
| ts-delivery-service | `0e7b205d0b20fcd7` |
| ts-food-service | `40b59ddd20bc0be0` |
| ts-gateway | `a3b5b8ae68b3f85d` |
| ts-new-gateway | `032a8e85e16fe393` |
| ts-notification-service | `e2085fa5e01ff34f` |
| ts-order-related-service | `377eed7bb27386ac` |
| ts-order-service | `7c455af2d1701906` |
| ts-preserve-service | `4ec83b089c08b410` |
| ts-price-service | `77d26eef5768fa99` |
| ts-rebook-service | `00ace410d6ad3cc8` |
| ts-route-service | `7d0c6e63b1dc4272` |
| ts-security-service | `62f0765a74f4e0a6` |
| ts-station-service | `9f102069abf37cca` |
| ts-travel-service | `64f6714db8fb0ad6` |
| ts-user-service | `c5d71a78221e5c82` |
