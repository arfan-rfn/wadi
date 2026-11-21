# Trace from the reviewed plan to the base migration record

This table maps each requirement of `reviewed-plan.md` to the part of the base migration record
(`docs/architecture.md` §11, "The base migration", recorded 2026-11-20) that carries it. The plan
was reviewed in rounds, and a later requirement often replaces an earlier one. A row that says
"replaced by" names the requirement that holds the final value. The record states final values
only.

The author of the record wrote this table. An agent that did not write the record checks it
before the record merges, because the third spec review and the second engineering review were
not re-verified by a further pass. The check confirms that every row points at text that exists
and says the same thing, and that no requirement is missing.

Line numbers are those of `reviewed-plan.md`, which holds lines 3 to 372 of the full plan (full-plan line N is line N+6 here). A few rows cite the full plan's review record or its decision audit trail, which are kept with the full plan outside the repository. Item numbers in the plan differ from the record from
item 5 on: plan item 5 (the fold) is record item 6, plan item 6 (the edge shape) is record item 7,
plan item 7 (the environment) is record item 8, and plan item 8 (import) is record item 5.

Record parts are named by their lead: Goal, Approved now, Release 1a to 1d (with the bold lead of
the bullet), Item 2 to Item 9, Checkpoints, Rules, Corpora, Ground truth, Guarantees (numbered
exit tests and the closing paragraph), Out of scope, Steps table, Version table, Superseded text,
Rejected, Not decided.

## The plan body (lines 9 to 201)

| Plan section | Record |
|---|---|
| Goal | Goal, reworded as at line 288 |
| What the migration is and is not (the eight assumptions) | Not repeated. The table stays in `target-architecture-plan.md` §4.6 |
| The change to the 2026-11-18 build order | Approved now, Steps table. "Import moves last" replaced by line 356 |
| Sequence, items 1 to 9 | Release 1a to 1d, Item 2 to Item 9, renumbered as noted above |
| Rules while it runs | Rules, Version table, Release 1b (five rows) |
| Corpora and ground truth | Corpora, Ground truth, replaced in part by line 357 |
| When the base is done | Guarantees 1 to 8 |
| Out of scope | Out of scope. Splitting `create_app` (H6) comes from the engineering review's "NOT in scope" list in the full plan's review record |
| What exists today | Not carried. Corrected at line 257 |
| First pull request | Not decided (issues), this pull request (`CLAUDE.md`, `AGENTS.md`, the status table) |
| Open points | Not decided. Each of its bullets (lines 196 to 201) has its own row below |

## Accepted requirements

| Line | Requirement | Record |
|---|---|---|
| 196 | Whether ICPC's source can be shared with examiners | Not decided |
| 197 | Which microSecEnD application is the third corpus | Corpora (`sqshq/piggymetrics` proposed), Not decided |
| 198 | T3 taken as recommended | Item 6, Not decided |
| 200 | D5 taken as suggested | Item 4 (origin and members), Not decided |
| 204 | E0, override the "when the order may change" sentence | Replaced by line 218, then by line 359. Checkpoints, Superseded text |
| 205 | E1, import probe in the spike | Item 2 (import probe) |
| 206 | E2, completeness test | Release 1a (checks on the tool), widened by line 243 |
| 207 | E3, mutation test | Release 1a (checks on the tool), Release 1c (validation), widened by line 277 |
| 208 | E4, environment on each measurement | Replaced by line 238. Rules (measurements) |
| 209 | E5, threats to validity | Guarantees (closing paragraph) |
| 210 | E6, fold property tests | Replaced by line 221. Item 6 |
| 211 | E7, lifecycle state-machine test | Item 4 (the lifecycle test), widened by line 373 |
| 212 | Determinism gate before the spike | Replaced by lines 230, 252, 280, 362. Release 1b (the determinism gate), Item 2 (start condition) |
| 213 | `AGENTS.md` updated with `CLAUDE.md` | This pull request, not the record |
| 214 | Numbers carry their source | Not carried. The record quotes no test count, and its one size (about 8,000 endpoints at ten times ICPC) rests on ICPC's 804 endpoints in §5.2.12 |
| 215 | Group header, spec review round 1 | None |
| 216 | Step mapping | Steps table. Plan item numbers translated |
| 217 | Superseded sentences | Superseded text |
| 218 | Three checkpoints | Replaced by line 359. Checkpoints |
| 219 | Snapshot lifecycle owned by item 4 | Item 4 (lifecycle, reads and the CLI). "Carries the members it does not replace" replaced by line 372 |
| 220 | Fold over more than one reader | Replaced by line 270. Item 6 |
| 221 | Fold laws on record sets | Item 6 (property tests) |
| 222 | Fold layering, scale loader | Item 6 (storage keeps projecting, scale check), Guarantees 6 |
| 223 | Canonical export format | Release 1a (keys, format). Edge key widened by line 263, node key by line 366, name by line 316 |
| 224 | Order inside item 1 | Replaced by line 362. Release 1a to 1d |
| 225 | Collisions and the natural key | Release 1a (keys), Item 3 (id form). Ground-truth part replaced by line 340 |
| 226 | Scorer scope | Release 1c (the scorer). Enforcement timing replaced by line 362, Release 1d (the freeze) |
| 227 | Upgrade, a seventh failure case | Release 1b (the version check), Guarantees 5 |
| 228 | Private corpus | Corpora (ICPC paragraph), Release 1a (reproduction, release attachments). Hash evidence replaced by line 357 |
| 229 | ICPC labeling | Corpora (ICPC paragraph) |
| 230 | Determinism, one definition | Release 1b (the determinism gate), narrowed by line 252, machines replaced by line 357 |
| 231 | Constraint rows with checker and schedule | Release 1b (five constraint rows). Command renamed by line 316, writer map by line 370 |
| 232 | Environment in full | Item 8 |
| 233 | What the test readers emit | Guarantees 4, Item 4 (readers), Item 7 |
| 234 | The probe needs a fixture split, eight days | Item 2 |
| 235 | Real inputs for the spike | Item 2 |
| 236 | Import corpus | Item 5 |
| 237 | Prerequisites before item 1's record | Replaced by line 357. Corpora table (pinned before 1a), Release 1b (second machine) |
| 238 | Environment on a measurement | Rules (measurements) |
| 239 | Scale thresholds | Thresholds replaced by lines 264, 347. Guarantees 6. The replica rename stands and line 265 adds the identity key, Item 6 (scale check) |
| 240 | Corpora count | Replaced by line 357. Corpora |
| 241 | First pull request files the deferred items | Not decided (issues, with these labels) |
| 242 | Group header, spec review round 2 | None |
| 243 | "Same map" covers what is served | Release 1a (three parts, checks on the tool), Guarantees 1 |
| 244 | Status of a fact one reader covers | Replaced by line 270. Item 6 |
| 245 | How a fact with no static record is served | Item 6 |
| 246 | Named exceptions to "additive only" | Item 7, Rules (consumers hold still, including the web map rule from plan lines 116 to 117) |
| 247 | The CLI holds still too | Item 4 (reads and the CLI), Item 5 (CLI commands), Item 8 (CLI option), Rules |
| 248 | Lifecycle, in full | Item 4 (lifecycle, jobs). Carrying analyzed members replaced by line 372 |
| 249 | ICPC evidence | Corpora (ICPC paragraph) |
| 250 | The amendment's own format | Rejected. Gate experiment timing replaced by line 358 |
| 251 | Where the constraint rows and the version check land | Release 1b. Writer-map amendment replaced by lines 273, 370 |
| 252 | Determinism gate, narrowed | Release 1b (the determinism gate) |
| 253 | Exit test 4, made meetable | Item 4 (readers), Guarantees 4. Touch list widened by line 344 |
| 254 | Superseded sentences, a minimum | Superseded text |
| 255 | Corrected counts | Guarantees 5 and 7, recounted with disk full and five rows |
| 256 | ICPC and the second machine | Replaced by line 357 |
| 257 | Database drivers in `wadi-testing` | Release 1b (five constraint rows, the import-boundary row) |
| 258 | Entity-access M5, precisely | Release 1c (the scorer, labeled saves), Out of scope (the gate run and its flags) |
| 259 | The spike's input | Item 2 (first task, OpenAPI document) |
| 260 | The test reader, in order | Item 4 (readers), Item 6 (two-source test), Item 7 (site-less edge). T4 in Not decided |
| 261 | Extent of ground truth | Ground truth |
| 262 | Import content | Item 5 (format coverage, round trip, same bundle twice, boundary-only bundles, section 11 decisions) |
| 263 | Edge key in the canonical map | Release 1a (keys) |
| 264 | Scale, how it is judged | The 1.25 times rule replaced by line 347. The rest (both sizes on one release, a repeated miss filed as an issue) in Guarantees 6 |
| 265 | Replicas for the scale test | Item 6 (scale check), beside the rename of line 239 |
| 266 | The import split | Item 5 |
| 267 | Group header, spec review round 3 | None |
| 268 | The stored edge keeps `provenance` | Item 7 |
| 269 | A read of a snapshot that has not succeeded | Item 4 (reads and the CLI, including the web map's error state) |
| 270 | The base fold returns sources and no status | Item 6 |
| 271 | Edges pass through in the fold's item | Item 6, Item 7 (folding at stitch time) |
| 272 | Five constraint rows and when each runs | Release 1b (five constraint rows). Scorer timing replaced by line 362 |
| 273 | The writer map is data | Item 4 (readers). Static map in 1b per line 370 |
| 274 | Job types | Item 4 (jobs) |
| 275 | Two test readers, two paths | Item 4 (readers), Guarantees 4 |
| 276 | Scorer abstentions | Release 1c (abstentions) |
| 277 | Mutation test, extended | Release 1a (checks on the tool) |
| 278 | The bundle promise has an artifact | Item 9 |
| 279 | What the version check refuses | Release 1b (the version check) |
| 280 | Scope of the determinism gate | Release 1b (the determinism gate, five constraint rows) |
| 281 | Where the spike's output lives | Item 2 (output) |
| 282 | Decisions taken as recommended | Not decided |
| 283 | Where the canonical export runs | Release 1a (the tool, three parts). Views part replaced by line 367 |
| 284 | Hardware, in full | Replaced by line 357. Release 1b (second machine, image ids), Corpora (ICPC) |
| 285 | The owner's adjudication load | Ground truth |
| 286 | Effort correction for the canonical map | Checkpoints (each release's record states its estimate) |
| 287 | Group header, CEO review | None |
| 288 | The goal, reworded | Goal |
| 289 | Kill criteria for the spike | Item 2 (last bullet) |
| 290 | Effort and a stop rule | Checkpoints |
| 291 | The fold is plumbing | Item 6 (sources and no status, property tests) |
| 292 | "Same map" on systems not tuned on | Rules (how a change is checked), Guarantees (closing paragraph) |
| 293 | Labeler caveat | Ground truth |
| 294 | One clean text | The form of the record |
| 295 | Framing | Guarantees (closing paragraph) |
| 296 | Copy job failure | Item 4 (jobs) |
| 297 | Atomic lifecycle write | Item 4 (lifecycle, the lifecycle test) |
| 298 | No third matcher | Replaced by line 339 for the scorer. Not carried for the canonical map, which keys facts by natural key and has no route-matching step |
| 299 | Job logs | Item 4 (jobs) |
| 300 | Release notes | Rules (release notes) |
| 301 | Import size | Item 5 |
| 305 | One error model | Release 1b (one error model) |
| 306 | MCP failures are failures | Release 1b (one error model), Item 4 (reads and the CLI) |
| 307 | What the 409 covers | Item 4 (reads and the CLI) |
| 308 | Two version refusals | Release 1b (the version check). "Newer records" includes a newer minor, see Additions |
| 309 | The analysis-in-progress refusal | Item 4 (reads and the CLI, lifecycle) |
| 310 | A wait has a bound | Item 4 (jobs, lifecycle, reads and the CLI) |
| 311 | Messages state retry safety | Item 4 (reads and the CLI) |
| 312 | The restitch refusal | Item 4 (reads and the CLI) |
| 313 | Zero services in every repository | Release 1d (a repository with no service) |
| 314 | The origin carries no secret and no machine path | Item 4 (origin and members) |
| 315 | Ground-truth file validated before scoring | Release 1c (validation) |
| 316 | Names | Release 1a (the tool, the diff), Release 1b (the determinism gate prints the keys that differ), Release 1c (the scorer) |
| 317 | One version table | Version table |
| 318 | Reproduction | Release 1a (reproduction; the 15-minute target is decision 32 of the full plan's audit trail), Corpora (ICPC paragraph) |
| 319 | The reader guide | Item 4 (readers), Guarantees 4 (time taken, what was read, the closed pull request's diff committed) |
| 320 | Restitch output | Item 4 (reads and the CLI) |
| 321 | MCP descriptions | Item 6, Item 7 |
| 322 | The environment option | Item 8. Per-environment question moved by line 334 |
| 323 | The bundle size limit | Item 5 |
| 324 | Deferred items | Not decided (issues). `wadi snapshots rm` replaced by line 337, Item 4 |
| 328 | A site-less edge is served | Item 7 |
| 329 | How a reader's edge reaches the edge set | Item 7 |
| 330 | One source per edge in the base | Replaced by line 375 (the contract accepts one or more sources, the stitcher keeps one). Item 7 |
| 331 | Status transitions | Item 4 (lifecycle) |
| 332 | Orphans and staleness | Item 4 (lifecycle) |
| 333 | The version check has one seam | Replaced by line 364. Release 1b (the version check) |
| 334 | The environment question moves to item 4 | Item 4 (lifecycle), Not decided |
| 335 | Graph rebuild | Item 4 (jobs), Guarantees 5 |
| 336 | The copy job | Item 4 (jobs, including the reclaimed copy job), widened by line 373 |
| 337 | Retention | Item 4 (reads and the CLI), Guarantees 5 (disk full) |
| 338 | Flow-graph node ids, in full | Item 3, tie-break from line 366. The record corrects the plan's citation: `assembler.py:357` is the entity-access join, and remote calls bind by file and line at `:496-505` |
| 339 | The scorer is independent | Release 1c (the scorer) |
| 340 | The ground-truth key carries handler class and method | Ground truth |
| 341 | Abstentions cannot hide errors | Release 1c (abstentions) |
| 342 | The canonical map's rules are owner-read | Release 1a (format, checks on the tool), Rules (review) |
| 343 | The fold is enforced | Item 6, Item 4 (readers, natural-key index) |
| 344 | How readers load | Item 4 (readers), widened by line 372 to the stitcher and the MCP server |
| 345 | Import safety | Item 5 |
| 346 | Item 1 is three releases | Replaced by line 362 |
| 347 | How scale is judged, corrected | Guarantees 6. Byte growth replaced by the per-route budget of line 376 |
| 348 | Cheaper checks | Rules (how a change is checked), Corpora (ICPC backup) |
| 349 | A failed snapshot stays inspectable | Item 4 (reads and the CLI) |
| 350 | The failure tests name their reason | Guarantees 5 |
| 351 | Cross-machine determinism names its risks | Release 1b (the determinism gate) |
| 352 | Release workflow attaches the maps | Release 1a (reproduction) |
| 353 | Group header, first gate | None |
| 354 | What is approved now | Approved now |
| 355 | What the spike hands to the decision | Item 2 (output) |
| 356 | Import early, promise late | Item 5, Item 9, Version table |
| 357 | ICPC is supplementary | Corpora |
| 358 | The gate experiment, earlier | Release 1c (the gate experiment), after the four-release split of line 362 |
| 359 | Checkpoints, restated | Checkpoints |
| 360 | The owner's read is unchanged | Rules (review) |
| 361 | Group header, second engineering review | None |
| 362 | Item 1 is four releases | Release 1a to 1d |
| 363 | The floor for an older stack is release 1b | Release 1b (tolerant control-plane reads) |
| 364 | The guard lives in storage | Release 1b (the version check, and the not-ready check of item 4 in the same handle), Item 4 (reads and the CLI) |
| 365 | Which releases bump the contracts major | Release 1d (the fixes), Item 3, Item 7, Version table |
| 366 | A node tie-break | Release 1b (a node tie-break), Version table |
| 367 | Views captured from the running stack | Release 1a (three parts, the capture, checks on the tool) |
| 368 | The tool is checked against itself | Release 1a (format, the diff, checks on the tool) |
| 369 | Redaction in the canonical map | Release 1a (redaction) |
| 370 | One-writer row uses a static map in 1b | Release 1b (five constraint rows), Item 4 (readers) |
| 371 | The amendment has a trace table | This file |
| 372 | Design input for item 4 | Item 4 (origin and members). The owner confirmed it at the plan's final gate (only imported members are carried), as the full plan's audit trail records |
| 373 | Design input for item 4, continued | Item 4 (lifecycle, jobs, reads and the CLI, the lifecycle test) |
| 374 | Design input for the fold | Item 6 |
| 375 | Design input for the edge shape | Item 7 |
| 376 | Design input for the scale gate | Item 3 (size measured), Item 6 (byte budget), Guarantees 6 |
| 377 | Design input for import | Item 5, Item 4 (rebuild tests) |

## Additions

The record carries these points that no plan line states. The owner reads them with the record.

| Record | Addition | Why |
|---|---|---|
| Release 1d (the fixes), Not decided | #28 is fixed in release 1d at the latest, and whether pull request #76 merges on its own before release 1a is for the owner | Line 73 puts #28 among step 1's fixes. The brief at the plan's final gate recommended landing #76 first, and the owner has not answered that recommendation |
| Release 1a (redaction) | The value of a config setting quoted in endpoint auth evidence is redacted | #28 is not fixed in 0.9.2, whose auth evidence quotes up to five `spring.security.*` settings as `key=value` (`auth_merge.py:813-822`). Line 369's list would let those values reach a map attached to a release |
| Release 1b (the version check), Guarantees 5 | The snapshot carries its full contracts version, and an older stack refuses records of a newer minor as well as a newer major | Line 333 has the snapshot carry the major only. Every artifact model forbids unknown fields, so a newer minor would still fail with a validation error on an older stack, which is the defect #37 names, while line 308 says an older stack that meets newer records tells the reader to upgrade |
| Corpora (held-out set) | If the 17 microSecEnD applications are the held-out set, the pinned one is labeled and the held-out set is the other sixteen | Follows from pinning one of the 17 (line 357) while T9 recommends the 17 as the held-out set |
| Corpora, Not decided | `sqshq/piggymetrics` is proposed as the microSecEnD application | Line 197 leaves the choice open. The author proposes it, and it awaits the owner |
| Item 7 | The record of item 7 notes that `auth_propagation` is read from the call-site node | Read from the code (`graph.py:342-343`), as design input for the list of routes that leave out site-less edges |
| Superseded text (five conditions) | Releases 1a to 1c meet condition 3 with a canonical-map diff opened in both directions, and release 1c also commits the baseline | Condition 3 of 2026-11-18 asks for a scorer run before and after, which no release before the scorer's baseline can produce. The 2026-11-18 paragraph "Inside step 1" already leaves step 1's record to say how B1 and B2 are opened |

The superseded list goes beyond the minimum of lines 217 and 254, because line 254 asks for the 2026-11-18 record to be read sentence by sentence. The status table of `target-architecture-plan.md` is also brought up to date in this pull request, which no plan line asks for.

## Counts

Rows: 11 for the plan body and 172 for accepted requirements. Of the 172, 6 are group headers,
16 were replaced by a later requirement (the record cell starts with "Replaced by"), 14 more were
replaced in part, and 2 (lines 213 and 214) are carried by this pull request or not carried, with
the reason given.
