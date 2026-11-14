# Benchmarking Baselines

**Purpose:** the single reference for every tool, dataset and published score wadi can be
compared against. Compiled 2026-08-18 against wadi 0.8.2.

This is a **reference document, not a decision record** — it changes nothing in
`architecture.md`. It exists because wadi's accuracy claims are currently self-reported, and
§5.4.3 / `TODOS.md` both record that as an open gap.

## How to read this

| Marker | Meaning |
|---|---|
| ✅ | Verified directly on 2026-08-18 (GitHub API, repo source, or the paper PDF) |
| 📄 | Reported by the literature sweep; **not** independently reproduced here — verify before citing |
| ⛔ | No LICENSE file = all rights reserved. Fine to run for comparison numbers; **not** available to vendor or build on |

Repo metadata (stars, licence, last push) was read from the GitHub API on 2026-08-18 and will
drift. Re-check before quoting.

---

## 1. The shortlist — what to actually run, in order

| # | Tool | Why it is on the list | Licence |
|---|---|---|---|
| 0 | **"Bridge the Islands"** (ISSTA 2025) | Not a tool — a paper. *Read it before running anything.* Only work claiming wadi's exact territory (cross-service pointer analysis for Java microservices). Decides whether the slicer + phone book are still differentiated | paper |
| 1 | **Tai-e** | The only tool competing on DI-aware ICFG **and** endpoint extraction. Spring plugin shipped June 2026 | LGPL-3.0 — benchmark only |
| 2 | **Code2DFD** | Best overall tool in the field (F1 0.86). Runs clean from a repo URL | custom |
| 3 | **RAD** + **RAD-source** | Endpoint leaders (F1 0.79 / 0.67), 0.03 s/app | ⛔ none |
| 4 | **MicroDepGraph** | Precision leader (0.99) | ⛔ none |
| 5 | **AppThreat atom** | Joern-derived, emits OpenAPI paths today. Same substrate, different pack — cleanest pack-vs-pack comparison | MIT |
| 6 | **Respector** | Only artifact that lets you compare *parameters and response schemas*, not just endpoint counts | MIT |
| — | **opalj/JCG** | Optional: external dynamic oracle for the ICFG soundness claim | ⛔ none |

Items 2–4 are exactly the ensemble that reaches the field's best combined score (F1 0.91), so
beating them individually **and** together is the whole Field-A claim.

---

## 2. Field A — Microservice architecture recovery

Extracts components / connections / endpoints. Scored on the shared 17-app microSecEnD dataset
by Schneider et al., EMSE 30:128 (2025).

### 2.1 Register

| Tool | Repo | Extracts | Technique | Licence ✅ | Last push ✅ | ★ ✅ |
|---|---|---|---|---|---|---|
| **Code2DFD** | `tuhh-softsec/code2DFD` | Cp, Cn, E + security properties | Iterative **keyword search** over source + Docker + Compose; 40 technology extractors; no AST | custom (NOASSERTION) | 2024-10-27 | 10 |
| **MicroDepGraph** | `clowee/MicroDepGraph` | Cp, Cn | Docker Compose parsing + Java API-call detection | ⛔ none | 2021-11-24 | 14 |
| **Attack Graph Generator** | `tum-i4/attack-graph-generator` | Cp, Cn + attack graphs | Docker Compose topology parser | ⛔ none | 2021-01-28 | 34 |
| **microMiner** | `di-unipi-socc/microMiner` | Cp (static phase only) | Kubernetes manifests → microTOSCA | MIT | 2020-11-21 📄 | 11 📄 |
| **RAD** | `cloudhubs/rad` | Cn, E, `@RolesAllowed` | Java **bytecode** annotation detection | ⛔ none | 2022-05-20 | 1 |
| **RAD-source** | `cloudhubs/rad-source` | Cn, E | Same, over source (JavaParser) | ⛔ none | 2023-05-05 | 3 |
| **Prophet** | `cloudhubs/prophet` | Cp, Cn, E + context map | Annotations + naming heuristics; every folder = a component | Apache-2.0 | 2024-05-07 | 3 |
| **MicroGraal** | `cloudhubs/graal-prophet-utils` | Cn, E + context map | GraalVM Native Image → Graal IR pattern matching on bytecode | ⛔ none | 2025-05-11 📄 | 8 📄 |
| **ContextMap** | contextmap.io | Cn, E | Maven plugin; only Feign / HttpExchange clients | proprietary | **domain parked** 📄 | — |
| **Prophet2** | `cloudhubs/prophet2` | Cp, Cn, E | Rust; language-agnostic AST (LAAST) | — | 2023-08-31 📄 | — |
| **microTOM** | `di-unipi-socc/microTOM` | Cp | Kubernetes; identical static phase to microMiner | MIT | 2023 📄 | — |
| **authz-flow-analysis** | `cloudhubs/authz-flow-analysis` | Cn, E + **CRUD per endpoint** | Rust / LAAST via `source-code-parser` | ⛔ none | 2022-05-16 📄 | 1 📄 |
| **protoc-gen-scip** | `CUHK-SE-Group/protoc-gen-scip` | Cn (gRPC only) | SCIP indexes + protoc plugin | — | 2023 📄 | — |

### 2.2 Published scores (EMSE 2025, 17 apps, 727 ground-truth items)

| Tool | Components F1 | Connections F1 | **Endpoints F1** | Overall F1 |
|---|---|---|---|---|
| **Code2DFD** | **0.98** | **0.87** | 0.66 (P 0.87 / R 0.54) | **0.86** |
| MicroDepGraph | 0.87 | 0.67 | — | 0.74 |
| Attack Graph Generator | 0.80 | 0.54 | — | 0.60 |
| microMiner | 0.71 | — | — | 0.71 |
| **RAD** | — | 0.00 | **0.79** (P 0.94 / R 0.68) | 0.37 |
| RAD-source | — | 0.04 | 0.67 (P 0.89 / R 0.54) | 0.29 |
| Prophet | 0.23 | 0.02 | 0.00 | 0.08 |
| MicroGraal | — | 0.00 | 0.00 | 0.00 |
| ContextMap | — | 0.00 | 0.00 | 0.00 |

**Best 4-tool ensemble (Code2DFD + MicroDepGraph + RAD + RAD-source): F1 0.91.**

Execution time per app: RAD 0.03 s · RAD-source 0.04 s · Prophet 0.17 s · microMiner 0.20 s ·
Attack Graph Generator 1.3 s · MicroDepGraph 1.5 s · Code2DFD 7.3 s · **MicroGraal 60 s**.

### 2.3 Strengths and weaknesses

| Tool | Strengths | Weaknesses |
|---|---|---|
| **Code2DFD** | Best balanced accuracy in the field; only tool with security annotations in scope; **traceability back to evidencing source snippets**; runs from a bare GitHub URL with no build; 7 s/app; own paper reports P 0.93 / R 0.85 | Text keyword matching, not AST — porting past Java/Spring needs syntax changes and never shipped; **auth is service-level stereotypes + a bag of path strings**; its `@PreAuthorize` extractor discards the SpEL expression and the HTTP method, and its own code comments say nested (class-level) mappings are not considered, so extracted paths are often wrong 📄; entire `HttpSecurity` understanding is four substring tests 📄; **no unknown state** — an unreadable guard silently vanishes; endpoint recall only 0.54; 22 months stale |
| **MicroDepGraph** | Highest precision in the field (0.99); trivially fast; simple and predictable | Recall 0.51 on connections; **no endpoints, no auth, no data**; needs a Neo4j it does not document (crashes after writing the SVG); dead since 2021; ⛔ unlicensed |
| **Attack Graph Generator** | Highest recall on connections (0.86); attack-graph generation downstream | Precision 0.39 — heavy false positives; documented only for Ubuntu 16.04 (EOL); only the Topology Parser component is usable; dead since 2021; ⛔ unlicensed |
| **microMiner** | High component precision (0.97); the only Kubernetes-based entry | Components only; connections come from its *dynamic* phase, excluded here; needed source patching to run; dead since 2020 |
| **RAD** | **Best endpoint F1 in the entire field (0.79)**; fastest tool measured (0.03 s); reads `@RolesAllowed`, so it is the one prior system publishing a cross-service endpoint→roles model | Detected **zero** connections on the benchmark; annotation-only (no `SecurityFilterChain`, no `@PreAuthorize` SpEL, no meta-annotations, no config-bound policy) 📄; **no unknown state**; its original evaluation is mutation injection into one 4-service app the authors wrote themselves 📄; ⛔ unlicensed |
| **RAD-source** | Source-based twin of RAD; near-identical endpoint quality; 0.04 s | Same as RAD plus: sample output in its own README carries **no URI at all**, parameters as unparsed annotation text, response type a bare FQN often `java.lang.Object` 📄; ⛔ unlicensed |
| **Prophet** | Broadest nominal scope (components, connections, endpoints, context map); the academic ancestor of the cloudhubs line; Apache-2.0 | Near-total failure on the benchmark (overall F1 0.08); treats **every folder as a component**; could not resolve constants in paths, emitting literals like `/api/ENDPOINT_NAME` 📄; workings undocumented in both paper and repo |
| **MicroGraal** | Matched hand-verified TrainTicket ground truth almost perfectly (see §5.3); bytecode-based, so it works with no source; novel Graal IR approach | **Empty output on all 17 benchmark apps** while executing without error — the field's clearest corpus-overfitting case; slowest tool by 40×; needs a custom GraalVM fork; ⛔ unlicensed |
| **ContextMap** | Only commercial entry; free Community tier; CI/CD-native; Maven-only, matching wadi's own scope | Zero connections and zero endpoints on the benchmark; detects only Feign / HttpExchange clients; needs every microservice's `pom.xml` edited; **domain now parked** 📄 |
| **authz-flow-analysis** | The **only** tool in the field with authorization in scope (CRUD per endpoint) | Excluded from the comparison because nothing else could be compared to it; 1★, dead since 2022; ⛔ unlicensed |

---

## 3. Field B — Java source → OpenAPI

Extracts endpoints / parameters / response codes / data models — the closest match to wadi's
`Endpoint` contract.

### 3.1 Register

| Tool | Repo | Technique | Licence | Activity | Cost per project |
|---|---|---|---|---|---|
| **Respector** (ICSE 2024) | `nntzuekai/Respector` ✅ | Static + **symbolic execution** on bytecode (Soot + Z3) | MIT ✅ | 2023-12-30 ✅, 17★ | avg **3,155 s**, worst 3.2 h |
| **AutoOAS** (arXiv:2410.23873) | **no repo** — Zenodo zip `10.5281/zenodo.13916835` ✅ | Source parsing with **Spoon**; no bytecode, no compile, no boot | CC-BY-4.0 (data) | preprint, Oct 2024 ✅ | median **7.6 s** |
| **springdoc-openapi** | `springdoc/springdoc-openapi` | **Runtime introspection**; delegates schemas to swagger-core `ModelConverters` (Jackson reflection) | Apache-2.0 | active, 3.7k★ 📄 | app boot |
| **RAD-source** | `cloudhubs/rad-source` | JavaParser annotation scan | ⛔ none | 2023-05-05 ✅ | 0.4 s |
| **jaxrs-analyzer** | `sdaschner/jaxrs-analyzer` | Pure **bytecode**, explicitly no reflection, no running app | Apache-2.0 | v0.17 (2018) 📄 | fast |
| **SmallRye OpenAPI** | `smallrye/smallrye-open-api` | Build-time **Jandex index** (Quarkus / MicroProfile) | Apache-2.0 | active 📄 | build |

### 3.2 Published head-to-head (Lercher et al., 7 Spring Boot projects, GT+)

552 methods / 7,174 parameters / 605 responses.

| Characteristic | AutoOAS | Respector | Prophet | springdoc |
|---|---|---|---|---|
| Methods (P / R) | 1.00 / 1.00 | 1.00 / 1.00 | 0.93 / 0.51 | 0.29 / 0.31 |
| Parameters (P / R) | 0.73 / 0.69 | **0.34 / 0.34** | 0.05 / 0.00 | 0.01 / 0.00 |
| Responses (P / R) | 0.99 / 0.97 | 0.70 / 0.86 | 0.89 / 0.46 | 0.27 / 0.29 |
| Named schemas w/ inheritance | yes | no — inline, flattened | no — class name only | yes |

> **Do not quote this table without the caveat.** AutoOAS's column is a **self-evaluation** on a
> ground truth its own authors corrected, published as a preprint with no public repo. Respector
> — an ICSE paper with a badged MIT artifact — self-reported **100% P / 94.4% R on parameters**
> on its own 15-API corpus and scores **0.34 / 0.34** here. A ~3× swing on a corpus change is the
> most important number in this document. **Always report the corpus with the figure.**
> springdoc's 0.29 is a harness artifact: the authors could not find a working run configuration
> for 3 of 7 projects.

### 3.3 Strengths and weaknesses

| Tool | Strengths | Weaknesses |
|---|---|---|
| **Respector** | Runnable, MIT, ACM *Available + Reusable* badged; only tool recovering **parameter constraints via symbolic execution**; finds parameters encapsulated in request bodies and controller fields; also emits global variable reads/writes and **inter-endpoint dependencies**; found 228 endpoints, 2,795 parameters and 502 responses missing from developer-written specs 📄 | **52 minutes per project average, 3.2 h worst case**; its own numbers do not replicate on an independent corpus (parameters 0.34/0.34); emits **anonymous inline schemas with inheritance flattened** — its own paper's Figure 2 shows `"properties": {}` for a real response type 📄; requires compiled bytecode; unmaintained since Dec 2023 |
| **AutoOAS** | Best published static numbers; **only tool building named `#/components/schemas` with `allOf` inheritance**; 400× faster than Respector; handles `@ExceptionHandler`/`@ControllerAdvice` exception→status translation, regex patterns from `/{id:regex}`, and per-`@Profile` specs; requires no compile and no boot | **No public repository** — source only inside an anonymised 109 MB Zenodo zip; preprint with no venue; Spring Boot only; **explicitly does not follow calls out of the handler**, so it misses any return type the signature does not carry, and reports 0% recall on projects using raw `HttpServletRequest` 📄 |
| **springdoc-openapi** | Production-grade, 3.7k★, actively released; the de-facto correct answer where it runs; **only tool handling `@JsonProperty` renames and map `additionalProperties` correctly** | **Must boot the application** — unrunnable on 3 of 7 benchmark projects, which is the whole of its 0.29 score; runtime reflection means no answer for code that will not start |
| **jaxrs-analyzer** | Pure bytecode, explicitly no reflection, **no running app**; the most interesting dormant oracle in the set | JAX-RS only; last release 2018 |
| **SmallRye OpenAPI** | Build-time index, no app boot; actively maintained | Quarkus / MicroProfile family — only relevant if wadi ever targets it |

---

## 4. Field D — Program-analysis substrates

The engines wadi is built on or beside. **This is where the sharpest current competitor sits.**

### 4.1 Tai-e — the closest direct competitor

| | |
|---|---|
| **Repo** | `pascal-lab/Tai-e` — Pascal Lab, Nanjing University ✅ |
| **Licence** | **LGPL-3.0** ✅ — benchmark against it, do **not** build on it |
| **Activity** | 1,803★, last push 2026-08-14 ✅; 378 commits in 12 months 📄 |
| **Spring plugin** | Landed **2026-06-09**, shipped in **v0.5.4 (2026-06-22)** 📄 |
| **What it has** | `pta` (pointer analysis), `cg`, **`icfg` (`ICFGBuilder`)**, inter-const-prop, taint — plus `plugin/spring/di/` and `plugin/spring/wec/` ✅ |

Verified plugin contents ✅:

```
plugin/spring/
├── SpringAnalysis.java, SpringPluginConfig.java
├── di/    DiAnalysis, BeanDefinitionCollector, FactoryBeanCollector,
│          XmlConfiguration, SyntheticSpringMain
└── wec/   RequestMethod, WebEndpoint, WecAnalysis, WecCollector, WecResultProcessor
```

Its endpoint model, read from source ✅:

```java
public record WebEndpoint(JClass containingClass, JMethod handlerMethod,
                          Set<String> paths, Set<RequestMethod> requestMethods,
                          Map<String,Integer> paramName2ParamIndex)

enum RequestMethod { GET, POST, PUT, PATCH, DELETE }   // no HEAD / OPTIONS / TRACE
```

| Strengths | Weaknesses |
|---|---|
| The **only** tool competing on DI-aware ICFG *and* endpoint extraction simultaneously; real pointer analysis underneath; DI coverage is broad (`@Component`/`@Service`/`@Repository`/`@Configuration`/`@RestController`/`@ConfigurationProperties`, JSR-330 `@Inject`, JSR-250 `@Resource`, MyBatis `@Mapper`, `@Bean`, `@Autowired` on ctors/fields/methods) 📄; parses XML `<bean>` config; composes class-level prefix with method path and reads either `value` or `path` alias; two months old and actively developed | **No auth or authorization model at all**; **no request/response wire shapes**; no declared status codes; verbs stop at five (no HEAD/OPTIONS/TRACE) ✅; **no Feign / RestTemplate / outbound-call / cross-service linking code exists in the public tree** — so no stitching, no phone book, no confidence tiers, no coverage report; LGPL-3.0 blocks reuse; path variables, `produces`/`consumes` and WebFlux unverified either way |

> **Standing correction this forces.** "Nobody else builds ICFGs" is no longer true and would not
> survive review. The differentiated claim is narrower: statement-level coarsening with
> **construct discriminators**, per-endpoint rooting, the four-layer validation stack, and a
> published trust boundary stating what the graph does *not* guarantee.

### 4.2 "Bridge the Islands" — the paper to read first

Zhang, Liang, Li, Tan, Xu, Li — **"Bridge the Islands: Pointer Analysis for Microservice
Systems"**, **ISSTA 2025**, [doi:10.1145/3728896](https://doi.org/10.1145/3728896). Billed as
*"the first pointer analysis for Java Microservice systems."* Same lab as Tai-e; implementation
**not located in the public tree** 📄 — likely a separate artifact or unmerged branch.

The only work claiming wadi's exact territory from the program-analysis side. **Highest-value
follow-up in this whole document.** Read specifically what it does about outbound calls and URL
resolution — that is where wadi's slicer and phone book live.

### 4.3 The rest of the substrate

| Project | Repo | Relevance | Strengths | Weaknesses |
|---|---|---|---|---|
| **Joern** (upstream) | `joernio/joern` ✅ | wadi's own engine | Apache-2.0; **3,430★**; **v4.0.605 released 2026-08-18** — extremely active ✅; `joern-slice data-flow` ships backwards interprocedural slicing (default depth 20, filterable by method/param type/annotation) — wadi's URL-recovery primitive 📄 | The **only** Spring artefact in the whole repo is one query, `SpringExpressionLanguageInjection.scala` 📄. Everything above the primitive is the pack author's problem — i.e. wadi's contribution |
| **AppThreat atom** | `AppThreat/atom` ✅ | **Fairest same-substrate baseline** | MIT ✅, 97★, pushed 2026-08-07 ✅; `atom --extract-endpoints` + `atom-tools convert -f openapi3.0.1 -t java` emits an **OpenAPI 3.x paths object** today 📄; polyglot (Java, JS/TS, Python, PHP, Ruby, C/C++); three slice types incl. reachables | Emits paths, not contracts — its own README says path item objects will be populated "in future iterations" 📄; no auth model, no stitching, no per-endpoint ICFG; built on `chen`, a hard Joern fork |
| **AppThreat chen** | `AppThreat/chen` ✅ | Joern fork powering atom | Apache-2.0, active (2026-08-07) ✅; tags flows `pii`, `pci-dss`, `gdpr`, `service-egress`, `service-ingress` 📄 | **Fully detached fork** — republished as `io.appthreat` with zero `io.joern` deps ✅; own CPG schema versioning; permanently off upstream |
| **SootUp** | `soot-oss/SootUp` | Typed CFG edges comparable to Phase 2.6 | Ships a `sootup.codepropertygraph` module with `IfTrueCfgEdge`, `IfFalseCfgEdge`, `ExceptionalCfgEdge`, `CdgEdge`, `DdgEdge` 📄; most active project in the survey (1,022 commits/12 mo, v3.0.1 2026-08-07) 📄 | **Java source frontend dropped in 3.x** — bytecode / Jimple / APK only 📄; no Spring, no endpoints |
| **Doop / JackEE** | `plast-lab/doop-mirror` | Independent **reachability oracle** | UPL-1.0; best-in-class reflection and dynamic-proxy modelling; JackEE reports >4× completeness, ~6× speedup (PLDI 2020) 📄 | `framework-annotations.dl` enumerates 28 Spring annotations **as entry-point markers only** — Doop reads *that* an annotation is present, never its `value`/`path` 📄. Answers "which handlers are reachable", never "what URI does this serve" |
| **CodeQL** | `github/codeql` | SAST comparator | `SpringRequestMappingAnnotationType` **handles meta-annotations**, so `@GetMapping` resolves 📄 | Does **not** compose class-level with method-level paths; no constant or placeholder resolution 📄; **zero `@PreAuthorize` anywhere in the repo** ✅ |
| **Fraunhofer AISEC CPG** | `Fraunhofer-AISEC/cpg` | The vocabulary wadi implements | Apache-2.0, commits daily; declares an `HttpEndpoint` concept carrying `method`, `path`, `url`, `handler`, `userInput`, `rateLimiting`, `proxyTarget`, `transportEncryption`, **`authenticity` and `authorization`** 📄 — strikingly close to wadi's model, generated from an OWL cloud ontology | **Nothing fills it from Java.** Concept passes are config, file, logging + three C/C++ passes; **no HTTP concept pass for any language**, no Java concepts directory 📄 |
| **CloudPG** | (Fraunhofer-adjacent) | wadi's table of contents, unstaffed | Has `SpringBootPass.kt`, `JaxRsPass.kt`, `HttpClientPass.kt`, **`HttpStatusCodesPass.kt`**, `IngressInvocationPass.kt`, `KubernetesPass.kt`, plus Go/Python/JS/Ruby HTTP passes and DB passes 📄 | Sizes tell the story: `SpringBootPass.kt` **156 lines**, `HttpClientPass.kt` 112, `IngressInvocationPass.kt` 74, with the literal line `// for now, NoAuthentication` 📄 |
| **jQAssistant** | `jQAssistant/jqassistant` | Storage-layer comparator | Neo4j-backed code model — good comparator for wadi's Tier-2 graph | Spring plugin has **three** concepts (`RestController`, `ControllerAdvice`, `RestControllerAdvice`), pure Cypher label-painting 📄; **no `Statement`, `BasicBlock`, `ControlFlow`, `Instruction` or `CallSite` descriptor**; `INVOKES` is a declared-target bytecode edge, not a resolved call graph 📄. Non-starter as an analysis substrate. GPL-3.0 |
| **opalj/JCG** | `opalj/JCG` ✅ | **External soundness oracle** | Annotated call-graph soundness corpus with adapters for Soot, SootUp, WALA, OPAL, Doop **and a dynamic JVM-agent ground-truth oracle** 📄; active (2026-08-07) ✅ | ⛔ **No LICENSE file** ✅; neither Joern nor Tai-e has an adapter — writing one is the work |
| **Privado** | `Privado-Inc/privado` | Joern fork cautionary tale | 652★ adoption | Forks Joern and republishes under the **same `io.joern` group ID**, so `build.sbt` cannot reveal it is not stock 📄; `privado-core` **last pushed 2024-11-21** ✅ — 21 months stale; PII dataflow only; endpoints exist as regex-matched taint entry points with no verb, path template or contract 📄; **zero `PreAuthorize` / `SecurityConfig` hits** 📄; detection rules carry **LGPL-3.0 + Commons Clause** 📄; **no independent academic evaluation found** 📄 |
| **codebadger** | `Lekssays/codebadger` | The one prior example of wadi's posture | MCP server over **stock** Joern so an agent never writes CPGQL 📄; ICSE 2026 workshop (arXiv:2603.24837) | GPL-3.0 — **reference only, never vendor**; security queries only, no extracted model |
| **Jasmine** | `SpringJasmine/Jasmine` | Spring DI + AOP at Soot IR level | Established that off-the-shelf Soot/Doop/WALA silently miss Spring's dynamic wiring (ASE 2022) 📄 | MIT, 28★, **abandoned 2022-08-30** 📄. Cite the result, not the tool |

> **P5 vindicated.** Every serious attempt to productise Joern has forked it — Privado (fork,
> core 21 months stale) and AppThreat `chen` (full detachment). Upstream shipped a release the
> day this was written. wadi pinning 4.0.593 against a live 4.0.605 is exactly the position P5
> exists to preserve: an upgrade is a conformance-suite run, not a merge.

---

## 5. Datasets and ground truth

| Dataset | Size | Ground truth | Where |
|---|---|---|---|
| **microSecEnD** | 17 Java Spring apps, 604–14,527 LoC, 4–15 services each | **182 components + 385 connections + 160 endpoints = 727 items** ✅ | `tuhh-softsec/microSecEnD` · `zenodo.org/records/7574138` |
| **EMSE2025SAR** harness | Same 17 apps, pinned | Textual GT, per-tool run scripts, **all 9 tools' raw + processed results**, execution times | `M3SOulu/EMSE2025SAR-Replication` · `-Tools` · `-Benchmarks` |
| **WebFuzzing/EMB subset + GT+** | 7 Spring Boot projects, 1,962–28,099 LoC | 552 methods, **7,174 parameters**, 605 responses — the only public GT below endpoint granularity | GT+ `zenodo.org/records/13916835`; original in Respector's artifact |
| **TrainTicket v1.0.0 manual GT** | 42 Java Spring services | 146 REST calls, 261 endpoints, 142 pairs, 90 SDG links, full context map | Paper §5.3 below · `zenodo.org/record/7902018` |
| **cloudhubs endpoint-roles** | TrainTicket, different commit | **241 endpoints → required roles** ✅ — the only public per-endpoint authz GT in existence | `cloudhubs/authorization-consistency-solver` → `data/validation/` |

> ⚠️ **Do not cite "223 endpoints" for microSecEnD.** Table 1's endpoint column sums to exactly
> **160** ✅, and 182 + 385 + 160 = 727, which is the total the results table uses. The "63
> endpoints" figure in the text is the number *added to* that 160 during the 2025 study.

### 5.1 The scale gap, in the competitor's own words

microSecEnD's exclusion criterion **EC5** rules out systems too large to hand-model and names
the casualty 📄:

> *"An example for an application excluded because of EC5 is Train Ticket, an application that
> consists of more than 40 microservices plus databases and over 300,000 lines of code. The time
> needed to analyse this application with the level of detail we include in our DFDs is vastly
> disproportional to the added value of having it in the dataset."*

Its largest system is 14.5k LoC / 15 services. wadi runs TrainTicket (365 endpoints) and ICPC
(804 endpoints, 118 controllers) routinely. The one paper that *does* use TrainTicket for
evolution analysis hard-codes **41 of 44 services**, dropping one with the comment
`skipped, target URL reconstruction too complicated` 📄.

**Nobody has published a precision/recall architecture-recovery result on TrainTicket.** Frame
wadi's numbers as closing that gap, not as winning a comparison — there is nothing at that scale
to compare against.

### 5.2 microSecEnD app list

`anilallewar/microservices-basics-spring-boot` · `apssouza22/java-microservice` ·
`callistaenterprise/blog-microservices` · `ewolff/microservice` · `ewolff/microservice-kafka` ·
`fernandoabcampos/spring-netflix-oss-microservices` ·
`georgwittberger/apache-spring-boot-microservice-example` · `jferrater/tap-and-eat-microservices` ·
`koushikkothagal/spring-boot-microservices-workshop` · `mdeket/spring-cloud-movie-recommendation` ·
`mudigal-technologies/microservices-sample` · `piomin/sample-spring-oauth2-microservices` ·
`rohitghatol/spring-boot-microservices` · `shabbirdwd53/springboot-microservice` ·
`spring-petclinic/spring-petclinic-microservices` · `sqshq/piggymetrics` ·
`yidongnan/spring-cloud-netflix-example`

### 5.3 TrainTicket v1.0.0 published results

| Characteristic | Manual GT | MicroGraal | Prophet |
|---|---|---|---|
| REST calls | 146 | 146 | 146 |
| Endpoints | 261 | 261 | 261 |
| Call/endpoint pairs in SDG | 142 | 123 | 114 |
| Service-dependency links | 90 | 82 | 82 |
| Entities (bounded context) | 117 | 116 | 108 |
| Relations (bounded context) | 43 | 43 | 39 |
| Entities (merged context map) | 84 | 84 | 76 |
| Relations (merged context map) | 24 | 24 | 20 |

Both tools recovered every endpoint and every REST call, and both lost ~9% of the links.
**11 of MicroGraal's 19 missed pairs were URLs assigned inside an `if/else`** — the
multi-candidate over-approximation wadi does by construction. The remaining 8 were
body-parameter shapes it could not read.

---

## 6. The verified auth disagreement

`cloudhubs/authorization-consistency-solver` ships `data/validation/ground_truth_endpoint_roles.json`
— **241 endpoints**, distributed ✅:

| Roles | Count |
|---|---|
| `[UnauthenticatedRole, admin, user]` | 127 |
| `[admin, user]` | 61 |
| `[admin]` | 44 |
| `[user]` | 9 |

It marks `POST` and `PUT /api/v1/configservice/configs` as reachable by `UnauthenticatedRole`,
i.e. **public**. §5.2.11 records wadi correcting exactly those two routes from an evidenced
`false` to `true [ADMIN]`. Opened against the source ✅:

```yaml
# ts-security-service/src/main/resources/application.yml
security:
  authorization-rules:
    - paths: ["/api/v1/configservice/configs"]
      method: "POST"
      authorities: ["ROLE_ADMIN"]
    - paths: ["/api/v1/configservice/configs"]
      method: "PUT"
      authorities: ["ROLE_ADMIN"]
    - paths: ["/api/v1/configservice/**"]
      authorities: ["permitAll"]        # catch-all sits AFTER
```

```java
// ConfigController.java:21
@RequestMapping("api/v1/configservice")   // no leading slash
```

**wadi is right.** The rules are explicit and verb-scoped, the permissive catch-all follows them,
and the slash-less `@RequestMapping` is precisely the root-anchoring defect §5.2.11 records
fixing.

> **Caveat before publishing.** This was checked against `cloudhubs/train-ticket-aitest` — the
> fork wadi analysed. Their 241-endpoint GT is pinned to a different commit of upstream
> TrainTicket, so confirm the YAML is identical there first. The mechanism is the same either way.

**Related:** `cloudhubs/aiat-authorization-consistency-solver` (pushed 2026-03-20 ✅) runs on
`cloudhubs/train-ticket-aitest` and `cloudhubs/yas` — wadi's own corpora — and its README cites
`https://github.com/arfan-rfn/microservice-index` as its indexer ✅. Decide deliberately whether
that line is a baseline, a collaborator, or both; the answer changes how this disagreement should
be published.

---

## 7. Field C — LLM-based approaches

All numbers 📄 unless marked.

### 7.1 Where LLMs are measured on recovery, they collapse

| Finding | Number | Source |
|---|---|---|
| Cross-service structural facts (Shared Libraries, Cyclic Dependencies), 3 frontier models vs a static detector | **0% P / 0% R** vs 100% / 100% | ICSME'26, arXiv:2606.26927 |
| Infrastructure-pattern detection, 190 repos, GT annotated by the repos' own top contributors | 116 FP vs 114 TP; **F1 0.395** | ICSA'26, arXiv:2603.23073 |
| Detection quality correlates with **filename distinctiveness**, not architecture | r = **0.83** | ICSA'26, arXiv:2603.23073 |
| LLM decompositions preserving real source dependencies (PetClinic) | 68.0% | arXiv:2607.28331 |
| Service identification vs inter-service communication | F1 0.97 vs **0.61–0.82** | arXiv:2607.28307 |

An arXiv full-text search for `"architecture recovery" AND "large language model"` returns
**zero papers** 📄. The LLM community works on *generation* and *decomposition* — problems where
the model authors the answer.

### 7.2 The two real competitors — cite them yourself

| Tool | What it is | Numbers | Code | How to differentiate |
|---|---|---|---|---|
| **Neo** (IEEE S&P 2026, arXiv:2605.15569) | LLM agent generating analysis plans + classic program analysis, for **privilege escalation across microservices** | 25 apps, 7 languages, 6.2 M LoC, **P 81% / R 85%, 42 zero-days** | not stated | **Artifact vs findings.** Neo emits vulnerabilities; wadi emits a per-endpoint enforcement model with a contract-enforced withheld state. Do not compete on detection rate |
| **OOPS** (JSS 239, 2026) | LLM-based static analysis for OpenAPI generation, technology-agnostic, API dependency graph + self-refinement | 12 APIs, 5 languages, 8 frameworks; endpoints **F1 >98%**, params/responses 97%, constraints 92% | none | **Scope.** OOPS answers what one handler accepts and returns. Nothing about resolving a call to another service, which rule governs a route, or interprocedural control flow |

### 7.3 The hybrid consensus — wadi's position

SemRef (ICSE'26) has an LLM refine ten classical recovery tools' output. **RIG/SPADE** reports
**+12.2% agent accuracy, −53.9% time** when given a deterministic map, describing the effect as
shifting failures *"from structural misunderstandings toward reasoning mistakes."* **SAINT**
(IBM + Georgia Tech, ICSE 2026) has static analysis build an endpoint model and dependency graph
so LLM agents can generate integration tests — externally published validation of the exact
thesis wadi's MCP server bets on.

The field has already concluded LLMs need a symbolic substrate. wadi is that substrate.

---

## 8. Not baselines — and why

### 8.1 Spec consumers (potential evaluation vehicles, not rivals)

| Tool | Licence | Note |
|---|---|---|
| **EvoMaster** | LGPL-3.0 | White-box JVM bytecode instrumentation for coverage feedback — but the schema is an input |
| **Schemathesis** | MIT | Requires OpenAPI / GraphQL |
| **RESTler** | MIT | Requires OpenAPI |
| **RestTestGen** | Apache-2.0 | Derives an Operation Dependency Graph *from* the spec |

**Use these for Step 7:** feed wadi-derived specs to EvoMaster and measure coverage against
developer-written specs. That directly tests §5.2.16's claim that the extracted contract is
sufficient to generate from.

### 8.2 Dynamic tools — oracles with one shared failure mode

springdoc must boot the app · AppMap records only what the test suite exercises · traffic
inference is exercise-bound by construction. **All three dynamic categories share one limit, and
static extraction is the only category that does not.** Concretely: springdoc unrunnable on 3 of
7 projects; AppMap failed on 7 of 15 APIs in Respector's evaluation 📄. Note AppMap is
**Commons Clause + MIT**, not plain OSS 📄.

### 8.3 Traffic inference — a collapsed field

Akita's open CLI states verbatim that it *"does not include functionality for inferring types and
data formats"* 📄 — the OSS release is a packet sniffer, the engine was always cloud-side, and
Postman archived it. Optic, APIClarity/Speculator and Mizu/Kubeshark are archived or have moved
their generator private. **None recovers an authorization model**; Speculator's own docs concede
it cannot determine an OAuth2 flow type 📄.

### 8.4 Threat-model tooling — all authoring, none extraction

| Tool | Input | Extracts from source? |
|---|---|---|
| OWASP pytm | Python DSL | No |
| Threagile | Hand-authored YAML (a `terraform` code search returns 0 results) 📄 | No |
| OWASP Threat Dragon | GUI diagramming | No |
| MS Threat Modeling Tool | GUI + stencils | No |
| IriusRisk | Questionnaire + LLM-assisted diagramming from documents | No |
| **StartLeft** | CloudFormation, Terraform, Visio, Lucidchart, Drawio, MS TMT `.tm7` → **OTM** | **IaC/diagrams only** — its docs say it *"does not analyze Java, Python, or other programming languages directly"* 📄 |

**OTM (Open Threat Model)** is the interchange format to target if wadi ever wants to emit into
this ecosystem.

IriusRisk is the only one reaching for automation, and the direction it reached is *an LLM
summarising documents and code into a diagram* — precisely what §7.1 shows collapsing on
cross-service structural facts.

> A usable line: the threat-modelling ecosystem has spent fifteen years building excellent
> editors for a diagram nobody has time to draw.

### 8.5 Model-query, not source analysis

The Vienna (Zdun / Ntentos) conformance line annotates auth **per connector** with a three-valued
scope vocabulary — `None` / `Some Requests` / `All Requests` — with no endpoint, HTTP method, URI
or role anywhere in the metamodel 📄. Its detectors query a **hand-written model** and never open
a source file 📄. Its results are therefore **not commensurable** with Code2DFD's or wadi's; do
not put its numbers in the same table.

---

## 9. Defensible claims, with their evidence

| # | Claim | Evidence | Status |
|---|---|---|---|
| 1 | **Nobody reads Spring Security.** No mainstream SAST engine can answer "what guards `POST /api/v1/orders`?" | `github/codeql` code search for `PreAuthorize`: **0 results**. `semgrep/semgrep-rules`: 2 results, both `.java` **test fixtures**, zero rules | ✅ verified |
| 2 | **Granularity.** The field's best security-aware tool models auth as service-level stereotypes + a bag of path strings; the Vienna line models it per-connector, three-valued. Neither can say *which* requests | Code2DFD extractor source; Vienna metamodel | 📄 |
| 3 | **Honest unknowns are unprecedented.** Every surveyed system is presence-detection: an unreadable guard is silently absent. No prior system has a withheld state | Code2DFD, RAD, microCertiSec, the PHP/Rails AC literature | 📄 |
| 4 | **Scale.** The field's flagship security dataset explicitly excludes TrainTicket as unanalysable by hand. Best published endpoint F1 anywhere is 0.79 | microSecEnD EC5; EMSE 2025 Table 6c | 📄 / ✅ |
| 5 | **P5 vindicated.** Both products built on Joern hard-forked it; the earliest fork is 21 months stale; upstream shipped today | GitHub API on `joernio/joern`, `Privado-Inc/joern`, `privado-core`, `AppThreat/chen` | ✅ verified |
| 6 | **LLM failure has a shape.** Competent on local, semantically-rich, textually-evidenced facts; 0%/0% on cross-service structural facts where static scores 100% | ICSME'26, ICSA'26 | 📄 |
| 7 | ~~Nobody else builds ICFGs~~ | **Retracted.** Tai-e's `ICFGBuilder` predates wadi; SootUp ships typed CFG edges | ✅ verified false |

---

## 10. Action plan

1. **Read "Bridge the Islands" (ISSTA 2025).** Highest-value single item. Decides whether the slicer + phone book are still differentiated.
2. **Publish the auth disagreement** (§6) once the upstream commit's YAML is confirmed. Validation against a third-party artifact beats any self-reported number.
3. **Reconcile TrainTicket** against the §5.3 manual GT line by line. Beating 82/90 links would be the best published result on that benchmark. **Pin `v1.0.0`** — wadi has analysed both upstream (262 endpoints) and the `aitest` fork (365).
4. **Build the scorer nobody has.** Both microservice papers counted TP/FP/FN *by hand*; that bottleneck is why the comparison stopped at nine tools. Map wadi's artifacts onto the microSecEnD DFD vocabulary, validate by reproducing published numbers from the replication package, then run wadi. Closes the `TODOS.md` reproducibility item and turns the benchmark into a CI target.
5. **Close two cheap gaps first:** promote compose topology (databases, brokers, registries, gateways) to graph nodes — wadi already parses compose and discards it, and this is what separates a 0.98 component score from a 0; and handle **`@RepositoryRestResource`**, which is explicitly in the endpoint ground truth and currently unsupported.
6. **Run the baselines** in the §1 order.
7. **Prove the generation thesis** with EvoMaster (§8.1).
8. **Generalisation test before publishing anything.** MicroGraal matched TrainTicket ground truth almost perfectly and returned **empty output on all 17 benchmark apps**. Respector's score swung 3× across corpora. This literature does not catch corpus overfitting on its own — run the 17-app set first.

---

## 11. Open items

- Locate the "Bridge the Islands" artifact (or confirm none exists).
- Confirm the `configservice` YAML on the exact commit the cloudhubs GT pins.
- Verify Tai-e's handling of path variables, `produces`/`consumes` and WebFlux.
- Decide the relationship with the cloudhubs / Cerny line given the shared corpora and indexer.
- Re-verify anything marked 📄 before it appears in a publication.
