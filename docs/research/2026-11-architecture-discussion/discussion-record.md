# Record of the architecture discussion

The questions the owner asked on 2026-11-16 and 2026-11-17 and the answers given, in order. The
plan documents in `docs/` cite entries here as "item NNN". The numbers have gaps, because entries
that held no content of the discussion are left out.

This is a record, not a statement of the design. Later answers replace earlier ones. The plan
documents are the consolidated statement, and `README.md` in this folder lists the corrections
that apply to this record.

---

## Item 000. Owner

Can you take a look into the new architecture plan and give me the summary of that

## Item 001. Answer

I took "the new architecture plan" to mean `docs/rule-packs-and-learned-rules-plan.md`, the newest of the three plan docs (compiled 2026-11-13) and the only one with a target architecture. I read it in full; here is the summary.

#### What it is

[rule-packs-and-learned-rules-plan.md](../../../docs/rule-packs-and-learned-rules-plan.md) is a proposal for how wadi could support many languages and frameworks, and how each analyzed system could extend the rules for its own conventions. Nothing in it is built, and it changes nothing in `architecture.md` until a stage is accepted. Neither `TODOS.md` nor `architecture.md` references it yet.

#### The problem it measured

The starting worry was that more frameworks would bloat the Joern container. The measurements say the container is not the constraint: stock Joern already ships 14 language frontends in 1.7 GB, and all of wadi's Spring and Java support is an 11 MB jar.

What does block growth:

- **Cost per framework:** Spring took about 7,200 lines of Scala, 1,700+ lines of Python and six rounds of fidelity fixes, where §5.1 assumed "tens of declarative lines".
- **Hard-wiring:** the pipeline applies Spring passes to every graph, the client hard-codes `importCode.java`, and discovery reads Maven only.
- **Release coupling:** a one-line fix to a pass ships as a new Joern image.
- **Per-codebase conventions:** ICPC's eight home-made auth annotations needed a Scala change and a release.

#### The target architecture

There are two modes that never mix:

- **Analyze** replays stored rules and runs no model, so the same commit with the same rules gives the same output.
- **Learn** runs a model only on command, and its only output is new rules.

The work splits into three layers:

| Layer | Form | How many | Holds |
|---|---|---|---|
| Language profile | Scala in the jar | Five to eight | Frontend choice, call resolution, control-flow and type-shape export |
| Framework rules | Data files loaded at run time | Many | What marks an endpoint, which calls are sinks, which types are models, build roots and config |
| Semantic plugins | Code attached to a pack | Rare | Auth models and dependency injection; Spring Security stays here |

Rules come in three scopes with one format: base packs that ship with wadi, learned rules for one analyzed system, and hints for a single site.

- **Reproducibility:** every fact records the rule that produced it, and every snapshot records a rule-set hash plus the wadi, pack and Joern versions.
- **Learn loop:** coverage gaps and the idiom census feed a model that drafts rules; a validator dry-runs each draft inside an extraction and allows additions only; a person reviews.
- **Support levels:** a rules-only framework publishes routes and sinks and marks authorization as not read. Spring stays at full depth.
- **Joern only for now:** tree-sitter is ruled out as a backup because it gives no control flow, call resolution or types.

#### Stages

Each stage is usable without the ones after it.

0. **Evidence base:** W0 (ground truth and scorer) and G9 from the hardening plan.
1. **Two probes:** throwaway Quarkus/JAX-RS and FastAPI extractions, to learn what a rule format must express.
2. **Rule engine and base packs:** Spring routes, sinks and models become a pack; the exit check is that every existing fixture and golden is unchanged.
3. **Reproducibility stamps.**
4. **Learned rules written by hand:** the exit check is ICPC's eight annotations read through learned rules alone.
5. **Census, validator and review.**
6. **A model drafts the rules:** gated behind W8's three experiments.
7. **A second language end to end:** two services in different languages stitched with no language-specific code.

#### Decisions waiting on you

- **D1, where learned rules live:** the plan recommends both the database and a `.wadi/` file in the analyzed repo, with the committed file winning.
- **D2, whether a drafted rule applies before approval:** it recommends that non-auth rules apply at once, marked unreviewed, and auth rules only withhold until approved.
- **D3, how the model is driven:** one-turn evidence packets (W8's design), a coding agent through MCP, or both. No recommendation.
- **D4, timing against the paper:** stage 1 is small and would give the paper a cost-per-framework number; stages 2 to 5 are a large change to the layer the paper's numbers come from.
- **D5, the real target:** hundreds of frameworks, or three to five that serve the research.
- **D6, first probe targets:** Quarkus and FastAPI are proposed, with Express as the alternative.
- **D7, whether W8's one-off verified facts stay beside learned rules:** recommended yes.

#### Biggest stated risks

- Whether one rule format can express real frameworks is unknown, and everything after stage 1 depends on it.
- No non-Java Joern frontend has been run through wadi.
- How well a model drafts rules is untested; W8 predicts a small model fails the hardest ICPC case.

The plan was compiled against 0.8.2, before the 0.9.0 entity-access work landed, so its line counts and file references are slightly behind master.

If you meant one of the other two plans in `docs/` (`foundation-hardening-plan.md` or `contract-triangulation-plan.md`, both dated August), say so and I'll summarize that instead.

## Item 002. Owner

show me the viz

## Item 004. Answer

This is the plan's own section 3 diagram redrawn, with two things added from elsewhere in the plan:

- **Hints** are in the Rules box. The plan's diagram omits them, but section 4 names them as the third rule scope.
- **The learn loop reads bottom to top**, so it closes visibly into Learned rules.

Three of the small grey captions are my wording, not the plan's: "export to stored artifacts", "what the rules did not read" and "from the gaps and nearby source".

The source file is at rule-packs-architecture.html. It sits in the session scratchpad, so say if you want it kept under `docs/`.

## Item 005. Owner

Was this architecture in mind where different language frameworks can be swapped. And each codebase can be enrich with LLM so it understand that specific codebase really well. And the rules will be storeable per codebase.

## Item 006. Answer

Yes, all three are what the plan was written for, and its section 2 records the second and third as already decided by you. Each comes with a limit worth knowing.

**Swappable frameworks: yes for frameworks, partly for languages.**
- A framework becomes a data file loaded at run time, and discovery picks the packs per service, so adding one needs no new Joern image.
- A language is not swappable in the same way. Each needs a Scala language profile in the jar; the plan expects five to eight of them.
- A rules-only framework gets routes and sinks, with authorization marked as not read. Spring-level depth still needs plugin code.
- No non-Java Joern frontend has been run through wadi yet, so this is the least proven part.

**LLM enrichment per codebase: yes, but the model writes rules and does not read code on every analysis.**
- The model looks at what the base rules missed in that codebase and drafts rules for its conventions: its own auth annotations, HTTP client wrappers, response envelopes and config keys.
- Ordinary analysis then replays those rules with no model running, so reruns of the same commit match.
- The limit on "understands it really well" is what a rule can express. A pattern that needs more logic stays published as unknown.
- This is stage 6, the last one before the second language, and it is gated on W8's three experiments. No model has been chosen, and how well one drafts rules is untested.

**Rules stored per codebase: yes.**
- Learned rules belong to one analyzed system and sit on top of the base packs.
- Every fact records the rule that produced it, and every snapshot records a hash of the rule set it used.
- Where they are stored is still your call (D1). The plan recommends both wadi's database and a `.wadi/` file committed in the analyzed repo, with the committed file winning.

Stages 1 to 5 contain no model at all. If the model turns out to draft poor rules, you still end up with swappable packs and per-codebase rules written by hand.

## Item 007. Owner

what if we have a monorepo with multiple languages used on a single repo. can we handle it as well

## Item 008. Answer

Yes for the common case, and the plan treats a monorepo no differently from many repos, because the unit of analysis is the service, not the repo.

**Today (0.9.0)**
- A monorepo with several services already works: discovery treats every leaf `pom.xml` as its own service (`_find_maven_leaf_modules` in [boundary.py:350](../../../services/extraction-worker/src/wadi_worker/boundary.py:350)).
- It only finds Maven modules and stamps each one `languages=["java"]` ([boundary.py:122](../../../services/extraction-worker/src/wadi_worker/boundary.py:122)). A Python or Node service in the same repo has no `pom.xml`, so discovery never produces a service for it.

**Under the plan**
- Discovery becomes rule-driven and decides the language and frameworks per service directory, so a Java service and a Python service in one repo each get their own frontend and packs.
- Joern takes one service at a time, so a mixed repo needs no extra memory.
- The stitcher matches a caller's URL and verb to an endpoint from stored artifacts and never reads source, so a Python caller links to a Java endpoint the same way two Java services do.
- This is stage 7, whose exit check is exactly this: a fixture with services in two languages that call each other, stitched with no language-specific code.

**What it does not handle**
- **Two languages inside one service.** If a single deployable mixes, say, Java and Kotlin or Python and a native extension, calls across that boundary are not linked and are published as unknown.
- **A language with no Joern frontend.** That service stays a placeholder in the map, with no flow of its own.
- **Shared libraries in other ecosystems.** The library-versus-service classification from §5.2.14 reads Maven dependencies. The plan does not say how an npm workspace or a Python shared package would be classified; that is my reading of a gap, not something it lists.

## Item 009. Owner

So, how would be the workflow from beginning to end assuming we have build everything planned. Can you go through with the user journey with visualized version. so, I have a clear understanding about the complete dream usecase it will enable

## Item 011. Answer

The journey above assumes all eight stages are built. A few things in it are mine, not the plan's:

- **The example system is invented.** The plan names Quarkus and FastAPI as probe targets and uses ICPC's `@ContestManager` and an `ApiClient.call(service, path)` wrapper as examples; I put them together into one monorepo to make the story concrete.
- **The "after" column in step 9 is the intended outcome, not a measured one.** The plan only says what each kind of learned rule would tell wadi; nothing has been run.
- **"Flow" for FastAPI and Quarkus in step 2 is my inference.** The plan says a rules-only framework publishes routes and sinks with auth not read. I added flow because the language profile is what exports control flow, and no non-Java frontend has been tested.
- **No command names appear because none are designed.** The plan says review goes through the CLI first and then the UI, and stops there.

The three orange tags (D1, D2, D3) are the decisions the plan leaves to you, and they change steps 4, 6 and 7. The plan gives a recommendation for D1 and D2 and none for D3.

The source file is at rule-packs-journey.html in the session scratchpad.

## Item 012. Owner

Here we can see that, we are going to publish the first map, then go with the LLM to understand more to filling out the missing pieces. 

Here I need an expert, well researched, deeply thought opinion. Because this is one of the most critical architectural decisions. At one hand if we go with the publishing the first map and then enriching with the custom rules or LLM to teach the study analyzer that's a one way to move forward. In a simple language, it's a good it's going to be a static analysis analyzer with a steroid. On the other hand, we can driven by the LLM and then does the static analysis then at the custom rule but, I'm not sure what would be the best way. The reason I'm saying it is if we go with the static analyzer first and then enrich with LLM. There might be something that the static analyzer going to do that is wrong, but I'm not sure if we what would be the best way to move forward. So don't be biased. Give me a well researched plan. What would be the best way to analyze a source code. Here is our intention: we want to have a complete understanding of the source code, the more rigorous is better and if our analyzer is missing some part it is never going to be a complete View of the system, and those few points that it is missing is going to be the place it will shine or die, and we want to make sure that those things are done properly and handled properly. So I want to make sure that our analyzer represents the most accurate representation possible so that any analyzation on top of it is accurate because our analysis is just the middle part, and the extension will be analyzing the source code, generating test cases with AI, LLM, or maybe analyzing each of the endpoint data coverage, code coverage, or root cause analysis. There can be a lot of things that can be possible with that tool, and if we can make it happen really really well that would be the most beautiful thing that is possible. 

Additionally, the reason it should exist is in microservice, based on my understanding, is the gap is with the current LLM and everything each of the LLM they when they each of the team when they own a source code they own one piece they are not going to own Own the entire stack, entire service, and understanding what else is other services doing is really important for LLM to understand because the new way the way people write code have been changed people no longer need to AI is basically writing all the code nowadays and we want to build a tool that will empower LLM so that it is LLM writing code in steroid right now, but we it can give the LM a superpower if they can understand everything that's going it is going on on a service or on a software with all the understanding of all the microservices that is going on, and that's why we are planning of creating the hub where each of the hub is going to act as a brain of their product and service can be each of the service can push their their analysis, their part into the house, so that a central brain can orchestrate everything, understand everything, what is going on, and it would be a really good way to handle things so there's a lot of possibilities if we can do it right but if we do it wrong nobody's gonna use it at all

## Item 015. Answer

**Verdict.** Keep the static analyzer as the only writer of facts in the map, and do not move to an LLM-driven core. The plan as drawn still leaves your worry open, because its model only looks where the analyzer already admits a gap. Add a second, independent reading of the code by a model, and make every disagreement between the two readings the work queue.

#### What the evidence says

The split follows the kind of fact.

| Kind of fact | Stronger reader | Evidence |
|---|---|---|
| Local to one handler: what is an endpoint, what it accepts and returns, whether something is a guard | LLM | Agents recovering OpenAPI specs scored F1 98.8 on endpoints and 97.0 on responses, against 57.3 and 26.6 for static baselines ([Chen 2026](https://arxiv.org/abs/2601.12735)) |
| Global and exhaustive: call graph, interprocedural flow, cross-service connections | Static | An agent rebuilding 17 Java microservice systems reached F1 0.604 ([Liljas 2026](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ESEM.2026.62), GPT-4o); the best static tool in [Schneider's comparison](https://arxiv.org/abs/2412.08352) reached 0.86. Gemini 2.5 Pro listed all sources of a flow exactly right 50% of the time ([CoRe](https://arxiv.org/abs/2507.05269)) |
| Anything that must repeat | Static | Three identical agent runs returned 3, 6 and 11 findings ([Semgrep 2025](https://semgrep.dev/blog/2025/finding-vulnerabilities-in-modern-web-apps-using-claude-code-and-openai-codex)); accuracy varied up to 15% at temperature 0 ([Atil](https://arxiv.org/abs/2408.04667)) |

Static analysis has measured holes of its own, and it does not know where they are:

- Median Java call-graph recall is 0.884 ([Sui, ICSE 2020](https://2020.icse-conferences.org/details/icse-2020-papers/47/On-the-Recall-of-Static-Call-Graph-Construction-in-Practice)).
- Without framework modelling, a strong analyzer covered 14.48% of enterprise application code ([Antoniadis, PLDI 2020](https://janvitek.org/events/NEU/7575/pubs/elephant.pdf)).
- Modelling Spring injection and AOP multiplied call edges by 2.5 to 4, and up to 23.77% of the added edges were spurious ([Jasmine, ASE 2022](https://weihang-wang.github.io/papers/ASE2022-Jasmine.pdf)).

Three more findings decide the design:

- **Independent readers catch each other.** In Schneider's study, the facts two tools agreed on had precision 1.00, and the union of two tools had recall 0.97. Agreement is a usable confidence tier. Wadi already works this way by hand, with its oracles and the 40-endpoint blind check.
- **A wrong fact costs more than a missing one.** Models adopt incorrect supplied context over 60% of the time ([ClashEval](https://arxiv.org/abs/2404.10198)). Agents followed a stale instruction file in 90.1% of choices, even after flagging the conflict ([Xu and Wu 2026](https://arxiv.org/abs/2610.30571)).
- **The map helps most where the agent cannot read the code.** With the code on disk, graph context adds 2 to 8 points and the gain shrinks as models grow. Verified structure helps test generation: a static dependency graph added 17.1 line and 34.2 branch coverage points ([SAINT, ICSE 2026](https://arxiv.org/abs/2511.13305)). LLM-written overview files added cost and no success ([Gloaguen 2026](https://arxiv.org/abs/2602.11988)).

That last point is the argument against an LLM-written map. The consuming agent could have produced it itself, and it would then trust its errors.

#### Recommended design: one writer, two readers

1. **One writer.** Only the deterministic engine publishes facts. Reruns match, two commits can be diffed, and bundles from different teams stay comparable in the hub.
2. **The model as recognizer.** For local facts, the model proposes, the graph verifies, and a confirmed pattern becomes a rule. W8 and stage 6 already say this. The evidence says it is where the model is strongest, so it should be the main way a new framework is onboarded.
3. **The model as auditor.** This is new. A capable agent reads the source without seeing wadi's output and states what a sample of endpoints call, guard and touch. Wadi diffs that against the map. Each disagreement is opened and ends as an analyzer fix, a new rule, or a recorded model error. The auditor never writes a fact, and its second output is a measured error rate per kind of fact on the snapshot.
4. **Runtime traces as a third reader where they exist.** Injection, AOP and reflection are where static analysis is blind, and runtime evidence closes most of it. Traces can only confirm, because a test suite exercises part of the system (45% of TrainTicket's endpoints).
5. **The trust level travels with the fact.** Each fact says whether two readers confirmed it, one reader produced it, or it is contested. A contested fact carries its source anchor so the consuming agent reads the code there.

#### What this changes in the two plans

- The learn loop takes gaps and the idiom census as input. Audit disagreements become a third input, and the auditor is built before model-drafted rules.
- The validator lets a learned rule only add facts, so learning can never correct a wrong base fact. Keep that, and let an audit disagreement mark a base fact contested, the way `withheld` works for auth. The correction itself goes through the pack code and its fixture.
- W8 rules out a multi-turn agent on small-model figures. That holds for per-gap packets. Auditing and rule drafting are rare and need exploration, so they should use a capable agent (decision D3: both, behind one proposal contract).
- A fourth gate experiment joins E1 to E3, described next.

#### The case for LLM-first, and what would change my mind

The case is real. Execution-prediction accuracy went from 75% in 2024 to 96% in 2026. Frontier agents with ordinary tools found over 500 validated vulnerabilities, by the vendor's own report. On handler-level contracts they already beat static tools.

Those wins are on local facts, or on tasks where finding something counts and a miss costs nothing. Wadi claims completeness per endpoint, where the miss is the defect. Nobody has published a test of a 2026 frontier agent against a code property graph on interprocedural flow or cross-service extraction; the call-graph and microservice results use 2024 models.

You can settle it with your own ground truth. Have a frontier agent rebuild the map for about 40 sampled train-ticket and ICPC endpoints from source alone, five runs each, and score completeness and run-to-run agreement. If it matches the analyzer on both, LLM-first deserves a serious look. If it matches on local facts and fails on flow, which the literature predicts, this design stands. The same setup then becomes the auditor.

#### Caveats

- Research agents gathered the outside numbers and opened the sources; I did not re-open them. Some are abstract-only, and the vulnerability count is a vendor claim.
- I have not estimated what the auditor costs per snapshot.

I can write this up as a proposal in `docs/` beside the other plans.

## Item 016. Owner

How that will architect then. same plan as before or something changed

## Item 018. Answer

Mostly the same plan. The whole analyze path, the rule packs and the learn loop stay as written; the orange parts are additions. This revision is my proposal from this conversation, and nothing in `docs/` records it yet.

#### What changes in the build order

The auditor does not depend on the rule engine or on a second language. It needs only stored artifacts, source at a pinned commit, a model, and W0's scorer, so it can run against today's Spring-only wadi.

| Stage | Before | Now |
|---|---|---|
| 0 | W0 scorer, G9 | Same, plus the frontier-agent experiment on about 40 endpoints |
| New | (none) | The auditor, built from the experiment's setup, plus the trust level in the contracts |
| 1 to 4 | Probes, rule engine, stamps, hand-written learned rules | Unchanged |
| 5 | Census, validator, review | Same, plus disagreements as an input and the contested mark |
| 6 | A model drafts rules | Same, driven by a capable agent, not only one-turn packets |
| 7 | Second language | Unchanged |

If the experiment shows a frontier agent matching the analyzer on completeness and repeatability, stop and reconsider before building the rest.

#### How it fits the existing principles

- **P7 holds.** The auditor is optional. With no API key the core runs as it does today and every fact stays at "single reader".
- **P4 holds.** The auditor is its own service with its own collection, the same pattern as `llm-resolver`.
- **P2 is not in the way.** The validator has to run inside an extraction because it needs the code graph. The auditor reads source and stored artifacts, so it runs any time after.
- **Contracts change.** The trust level is a new field on facts, so it needs a contracts bump and `make schema`.

#### Decisions for you

1. **Where the trust level is computed.** I recommend the stitcher folds it into the coverage report, since it already writes that collection. The alternative is computing it at read time.
2. **Sample size per snapshot.** I have not costed this. The 40-endpoint blind check bounded the error rate at 7.2%, which gives a starting size.
3. **Timing against the paper.** The auditor produces a measured error rate the paper could cite, but it is new work in front of W1 to W7.
4. **How the model is driven (D3).** This revision assumes a capable agent for auditing and rule drafting, and keeps W8's one-turn packets for per-gap resolution.

The source file is at two-readers-architecture.html in the session scratchpad.

## Item 019. Owner

Now I would like to add one more important part to the architecture the thing is that currently the whole system assumes that there knows nothing exists, only the source code exists and it tries to make sense out of it, but the reality is it is not the real case. Most of the microservice applications are well matured and they already have a lot of things to do the work they are doing for example there exist a Swagger API documentation or OpenAI API spec or maybe the contract repository between services and those are things may already exist and maybe some other documentation that is available and And the fact of ignoring them would be a really a big mistake rather I believe the value is going to be if the existing work can empower the system more. This way we would be able to have a keep utilizing all the resources that we have and giving the user developer the entire team the complete view way easier so if we want to incorporate that part. I believe there are a few things, few places we need to make changes into our architecture because this is going to be another data source to read in to make sense. So, how exactly that will fit into our whole solution?

## Item 022. Answer

Your idea fits as a third reader beside the analyzer and the auditor. Part of it is already planned: `contract-triangulation-plan.md` package C5 ingests a provider's OpenAPI document under a new `provider-declared` provenance. Your version is wider in two ways: it covers more than OpenAPI, and it uses the documents to strengthen the analysis, where C5 only compares them against it.

#### What the documents buy

1. **A check on the analyzer that needs no model.** A spec is an independent list of endpoints, shapes and statuses. An endpoint in the spec and absent from the map is exactly the kind of miss the gap list cannot see.
2. **An inside for services wadi cannot read.** A service in a language with no Joern frontend, an external API, or another team's service is a placeholder today. With a spec it has endpoints that callers can be stitched to.
3. **Labeled targets for the learn loop.** "The spec lists 14 endpoints here and the analyzer found none" tells the model what to look for, and the spec then scores the rule it drafts.
4. **Intent for the consuming agent.** The code says what an endpoint does, and the spec says what it should do. A test generator needs the second, or it writes tests that confirm bugs.

#### The six places that change

1. **Intake.** Wadi looks for these files in the repos it already checks out, so they sit at a pinned commit and the snapshot rule holds. A contract repository is added as one more repo. A spec fetched from a URL has no commit, so it needs a content hash and a fetch time (the plan's M3).
2. **A declared reader in the worker.** It is Python, with one parser per format, and it writes its own artifact. It never merges into the extracted `Endpoint`.
3. **Binding and identity.** Each document must be tied to a service, and each declared endpoint joined to an extracted one by verb and normalized path. Joins that fail are counted and reported (the plan's M5).
4. **One comparer.** The triangulation plan's contract-checker and my auditor comparison become the same service.
5. **The learn loop** gains declared-only items as an input and the documents as a test set.
6. **Contracts and readers.** New provenance terms, both views side by side in REST, MCP and the UI, and the document hashes added to the snapshot stamp.

#### Rules that keep it honest

- **A document never overrides the code.** Where they disagree, the fact is contested and the difference is reported as spec drift.
- **A document fills in only where the code was not read,** and the fact stays labeled as declared.
- **Declared security can only withhold a claim.** A spec saying "secured" never makes an endpoint read as protected when no enforcement was found.
- **Record how each document was made.** One generated by another tool from the same code is still a useful check, because it is a different implementation. One generated from wadi's own output is circular and counts for nothing.
- **Prose docs produce questions, never facts.** In the study I cited earlier, agents followed a stale instruction file in 90.1% of choices.

#### What I measured on train-ticket

- It has no committed spec files, no proto files and no Pact contracts.
- 20 of its 22 modules carry springfox, so its spec exists only while the services run.

For this corpus, "use the existing spec" means the user exports it or points wadi at a URL. The design cannot assume a file in the repo. It is the only corpus on this machine, so ICPC and yas are unchecked.

#### Limit

Specs and contracts describe the interface: endpoints, shapes, statuses, declared security. They say nothing about the flow inside an endpoint, its downstream calls or the entities it touches. The auditor is still needed for that.

#### Build order

The declared reader needs no model and no rule engine, so it can come right after stage 0 and before the auditor. It also gives the W0 scorer ground truth for each system without hand labeling.

#### Decisions for you

1. **Runtime-served specs.** I recommend wadi accepts a file or URL and never boots the application itself.
2. **Scope of the first version.** I recommend OpenAPI and Pact-style contracts first, and prose docs last.
3. **External services with a spec.** The plan's open question M4: treat one as an analyzed service marked `provider-declared`, or add a new target kind.
4. **Identity for a service known only from a spec.** The plan's M5; it cannot be changed later.

The source file is at declared-reader-architecture.html in the session scratchpad.

## Item 023. Owner

Now my one of the biggest question is if we have the third reader which which will include the spec contract or other Other things that exist, how exactly it will understand it. Are you going to write a another code to parse those data or they are going to some other way because sometimes the contract on the microservice it might be possible that they they have written differently so I just wanna double check how exactly we got we're going to handle it and read them.

## Item 025. Answer

Short answer: for standard formats there is almost no new parsing code to write, and no model reads them. Mature parser libraries exist for these formats. Wadi adds a thin adapter per format that translates the parsed result into its own contract vocabulary. A model on that route would add error where an exact parser has none.

#### "Written differently" has three levels

- **Variation inside a standard.** Examples are OpenAPI 2 against 3.1, schemas split across files, `allOf` and `oneOf`, and vendor `x-` keys. The adapter handles these. Anything it cannot express is counted and reported as unread.
- **House conventions on top of a standard.** Your team might put the required role in `x-required-role`, or encode consumer and provider in a folder name. That needs a mapping rule stored for your system, the same mechanism as learned rules for code. A model drafts it from the list of unread keys, the validator runs it, and a person approves it. After that it replays with no model.
- **A format of your own.** If the files have a consistent structure, a mapping rule covers them the same way. If they do not, they go down the prose route and can only raise questions.

#### Why this is safer than it sounds

A document is a finite tree, so wadi can say exactly which share of it was read. Code cannot give you that number. A misread convention shows up as a named unread key or a failed join.

#### Where the real difficulty is

Parsing is the easy part. Three things after it are harder:

- **Knowing which service a document describes.** One file may cover several services, or one service may have several files.
- **Joining paths.** The spec may say `/api/v1/orders/{orderId}` behind a gateway while the code says `/orders/{id}`. Wadi's matcher has had defects in this area before (§5.2.11 and §5.2.13), and finding H3 says there are currently two matchers. They should be unified first.
- **Comparing types on the wire.** A Java `Long` has to be compared with `integer / int64`. Enums and inherited fields are not yet represented on the code side (findings G6 and G5). Until those are fixed, the comparison should answer "not comparable" there and not report a false drift.

#### Limits

- **Contracts written as code.** Spring Cloud Contract's Groovy form fits neither route, and Groovy is not among the Joern frontends the plan measured. Only its YAML form would be read; the Groovy files would be listed as found and unread.
- **Shared API modules are not documents.** A jar of Feign interfaces and DTOs is code, so the static analyzer reads it.
- **I have not chosen or tested the parser libraries.** That is a build-time decision, and each adapter needs its own fixture plus a run over a large set of real public specs before its output is trusted.

I also re-checked train-ticket by file content, since my earlier count went by filename. The result is the same: no OpenAPI, Swagger or Pact documents.

#### Decisions for you

1. **Which formats come first.** I recommend OpenAPI 2 and 3, then Pact.
2. **Whether document mapping rules share storage and review with code rules.** I recommend yes, with a separate schema.
3. **Whether the prose route is in the first version.** I recommend leaving it out.

## Item 028. Owner

Into real world project.  There are a lot of source of truth, are living in different country pile, for example, in Cubanite's helm chart, or the Indian X, or other services.  So, Are we also considering those as a source of data point?  What we can analyze it, so to, so that we have a greater understanding of what a service does.  Or we are basically uh, only taking care of the opening aspect of those kind of data point only and leaving everything else behind.

## Item 031. Answer

I read your message as asking about Kubernetes Helm charts, nginx and similar systems, and whether we only handle OpenAPI.

No, it is not OpenAPI only. Deployment and routing config is in scope, and for one class of facts it is a better source than any spec.

#### Why it is different from a spec

A spec is a claim about what a service promises, and it can be stale. Deployment config is what actually runs. The code also asks for it directly. Train-ticket's Java uses `${station-service.url}` six times, and no amount of source reading can say where that points. Only the environment can. So config answers a question the code leaves open, and it does not compete with the code the way a spec does.

#### What wadi reads today

Part of this already exists in the worker and the stitcher:

- **Read today:** docker-compose (service names, environment, aliases, ports), Spring config with profile merge, Spring Cloud Gateway and Zuul routes, Eureka and Consul names, and Kubernetes DNS spellings inside URLs.
- **Not read:** Kubernetes manifests, Helm charts, Kustomize, nginx, ingress, service mesh config and Terraform. A code search found no reader for any of them.
- **Doc mismatch:** `architecture.md` line 112 says the boundary analyzer scans Kubernetes manifests. The code reads compose only.

#### What to read, chosen by the question it answers

The list of tools is endless, so the scope should follow the question, not the tool.

| Question | Where the answer lives | What wadi gains |
|---|---|---|
| Which running thing is which service | Kubernetes Deployment and Service, Helm values | Binds an image and DNS name to a code module |
| Where a call goes | Env vars, ConfigMaps, service registry, config server | An unresolved target becomes an edge |
| How a request gets in from outside | Ingress, nginx, API gateway, mesh routes | Explains path rewrites, marks endpoints as public or internal |
| What can block a request outside the code | Gateway auth, mesh policy, NetworkPolicy | Auth enforcement the code never shows |
| What it depends on that is not a service | Database URLs, topics and queues | Two services sharing one database, async wiring |
| How it behaves under failure | Timeouts, retries, replicas | Stored for root-cause work, not modelled at first |

Everything else in a chart (resource limits, probes, node placement) stays unread and is counted as unread.

#### What makes it harder than a spec

- **Helm charts are templates, not YAML.** Wadi should render them with a pinned `helm template` and a named values file, then read the plain output. No model is involved.
- **The answer depends on the environment.** Production and staging values differ, so every config fact must carry its environment.
- **Git is not the cluster.** Some truth lives only in running systems such as Consul or a cloud console. I recommend the first version reads files and exported snapshots only, and holds no cluster credentials.
- **Config never creates a call.** A policy that allows A to reach B does not mean A calls B. It can resolve, confirm or forbid an edge the code already has.
- **Edge auth covers only traffic through that edge.** Internal calls bypass the ingress. Config can add a restriction but can never make a protected endpoint public.

#### Where it fits

This is mostly new inputs to a component that exists. The stitcher's phonebook already resolves hosts from compose and gateway routes, and Kubernetes and nginx become more sources for it. The third reader then has two kinds of input with different rules. Wadi compares interface documents against the code, and uses wiring config to fill what the code leaves open.

Train-ticket cannot test this. It has no Kubernetes or Helm files, and one nginx file with a single routing rule that wadi does not read.

#### Decisions for you

1. **Which source comes first.** I recommend Kubernetes manifests with Helm rendering, then ingress and nginx, with mesh later.
2. **Which environment the default map shows.** I recommend production, with other environments shown as differences.
3. **A test system that has these files.** We need one before building, since no corpus on this machine does.

## Item 032. Owner

Okay, then, I wanted to fire off a multiple, parallel agent, or figure out what are the things?  The body need to also consider, because only understanding the contra, the open AI spat, or high level contract, is not going to cut the job here, the reason is we need to have if you're understanding, and for stitching, or any other purpose, having a clear understanding of those conflict files, those  Indian X server and all those data points is really, really important to have a clear understanding.  Without that, all the understanding we're going to have are going to have home, and it's not going to give the user proper picture.  What is going on into the server or in the service or into the entire system.  So, I believe it is really important to have those meats and pieces and integrate with the application, so that we have a higher confidence that it represents the actual system, what it does.

## Item 033. Owner

Additionally, you also need to figure out how we, right now everything's static, I believe.  And maybe we do not have any plan to do the runtime analysis as well, the dynamic analysis.  But in future, this is going to be also a part of it.  So, make sure we are architecting our entire solution in a way so that we have, we can support the dynamic analysis and future on top of body.  Very, very easy.

## Item 035. Owner

### Wadi: design gaps and what agents actually need

Nov 16, 2026 · @Md Arfan Uddin

#### Verdict

The goal is right, but the plan optimizes the wrong artifact. A full cross-service CFG is a human or analyzer artifact; an agent needs a small, queryable, evidence-backed summary of what an endpoint does, touches and breaks. Your overfitting is not a tuning problem: rules written against Train-Ticket's code instead of against Spring's semantics will always drop on the next system. Fix the layering (framework models, then resolution, then summaries), validate against runtime traces, and evaluate on more than one system, or the paper will not survive review.

#### Gaps, ranked by impact on agent productivity

Ranking is my judgment, not measured. Evaluation sits last for agent impact but first for publishability.

##### 1. Wrong granularity: a full cross-service CFG is not what an agent can use

- **Missing:** a compact behavior summary per endpoint: inputs, guards, downstream calls, data read and written, errors, side effects.
- **Why it hurts:** a loop-and-branch CFG across 5 services is thousands of nodes. It blows the context budget, and the agent must rebuild the meaning itself, which is the job you wanted to do for it.
- **Fix:** keep the CFG as an internal IR. Expose derived summaries (call tree with conditions, effect set, error paths), and let the agent drill into the raw graph only on request.
- **Related:** [RepoGraph](https://arxiv.org/html/2410.14684v2) returns a 1 or 2 hop ego-graph, not the whole graph, and lifted four agent frameworks by 32.8% on average on SWE-bench Lite.

##### 2. Overfitting: rules written per benchmark instead of per framework

- **Missing:** a framework-semantics layer. Rules like "this Train-Ticket class builds this URL" are memorized facts, not models.
- **Why it hurts:** every new system needs new rules, so coverage silently drops and the agent trusts a graph with holes.
- **Fix:** three layers. (a) Language frontend (Joern CPG). (b) Declarative framework models: Spring MVC mappings, `@FeignClient`, `RestTemplate`/`WebClient` call sites, `@Value` and `application.yml` binding, `@KafkaListener`, JPA repositories. (c) Optional per-project overrides as data, never code. Multi-language support then means a new frontend plus a new model pack, not a rewrite.
- **Related:** CodeQL [models-as-data](https://codeql.github.com/docs/codeql-language-guides/customizing-library-models-for-java-and-kotlin) (source, sink, summary, neutral models in YAML) is the exact pattern. [Code2DFD](https://arxiv.org/abs/2304.12769v1) uses evidence keywords that snowball through code and config, and reports 93% precision and 85% recall on 17 Java apps. [Cerny and Taibi](https://ar5iv.labs.arxiv.org/html/2205.08527) use a language-agnostic AST with pattern agents.

##### 3. Inter-service call resolution is where static graphs break

- **Missing:** a resolver that turns a call site into a target endpoint when the URL is built from config, env vars, service discovery (Eureka, Consul, k8s DNS), or a gateway rewrite.
- **Why it hurts:** one wrong or missing edge makes the agent's impact analysis wrong, with full confidence.
- **Fix:** constant-propagate URL strings through `@Value`, profiles and env; resolve logical service names against compose or k8s service names; model gateway routes (Spring Cloud Gateway, Nginx, Istio) as edges; match by HTTP method plus path template plus parameters. Emit unresolved calls as explicit `unknown` edges, never drop them.
- **Related:** [Cerny and Taibi](https://ar5iv.labs.arxiv.org/html/2205.08527) report their prototype fails when one endpoint maps to multiple possible URLs, and call static results a "best approximation".

##### 4. Data and state are invisible

- **Missing:** which entities and tables each endpoint reads or writes, shared databases across services, transaction boundaries, caches, and idempotency.
- **Why it hurts:** most real regressions in microservices are state bugs (a renamed column, a cross-service write, a retry that double-charges). A control flow view cannot show them. (Inferred from practice, not measured here.)
- **Fix:** extract JPA entities, repository methods and native queries into a read/write effect set per endpoint; flag tables touched by more than one service; mark `@Transactional` scope and calls that cross it.

##### 5. Config and deployment are a source of truth you are not reading

- **Missing:** docker-compose, Helm and k8s manifests, env files, and gateway config.
- **Why it hurts:** they define which services exist, their names, ports, replicas, and which DB or broker they use. Without them, gap 3 is unsolvable.
- **Fix:** parse deployment artifacts first and use them as the service inventory and name resolver for every later stage.
- **Related:** [Code2DFD](https://arxiv.org/abs/2304.12769v1) parses configuration files alongside code for exactly this reason.

##### 6. No runtime evidence to check the static graph

- **Missing:** a way to confirm or refute static edges with traces.
- **Why it hurts:** you cannot tell users or reviewers how wrong the graph is.
- **Fix:** run the benchmark under OpenTelemetry, derive the observed service graph, and label each static edge `confirmed`, `static-only`, or `runtime-only`. Runtime-only edges are your false negatives, for free.
- **Related:** the OpenTelemetry [service graph connector](https://pkg.go.dev/github.com/open-telemetry/opentelemetry-collector-contrib/connector/servicegraphconnector) already pairs client/server and producer/consumer spans into edges. Caveat: coverage is limited to paths your workload exercises.

##### 7. Async messaging is deferred, but it is half of many real systems

- **Missing:** producers, consumers, topics and payload schemas (Kafka, RabbitMQ, events via outbox).
- **Why it hurts:** an agent changing an event payload breaks consumers it cannot see; HTTP-only graphs hide this.
- **Fix:** model topics as nodes; match `send(topic)` to `@KafkaListener(topics)` through resolved config; extract the payload class as the schema. Do this before gRPC, not after.
- **Related:** [AsyncAPI 3.0](https://www.asyncapi.com/docs/reference/specification/v3.0.0) gives you a ready output format (channels, send and receive operations, messages).

##### 8. The MCP surface is not designed for agents yet

- **Missing:** task-shaped tools, token budgets, freshness, incremental re-analysis.
- **Why it hurts:** a tool that dumps a graph costs context and gets ignored; a stale graph is worse than none.
- **Fix:** few tools aligned to agent questions (see the 10x section), each with a concise and detailed mode, pagination, and a commit hash plus analysis time in every response. Re-analyze only changed services on each commit.
- **Related:** Anthropic's [tool-writing guide](https://anthropic.com/engineering/writing-tools-for-agents): consolidate tools, return meaningful context, offer a `response_format`, and note that Claude Code caps tool responses at 25,000 tokens by default.

##### 9. SLM or LLM placement can poison the graph

- **Missing:** a rule for where the model is allowed to decide.
- **Why it hurts:** a hallucinated edge looks identical to a real one. Agents act on it.
- **Fix:** the model proposes (unresolved URLs, endpoint purpose, auth intent); static checks or runtime traces confirm. Every fact carries `provenance` (static, runtime, llm) and `confidence`. Use the model for summaries and naming, never as the sole source of an edge.
- **Related:** [LLMDFA](https://arxiv.org/abs/2402.10754v2) gets 87.10% precision and 80.77% recall by decomposing tasks, having the LLM synthesize parser code, and verifying paths with a solver.

##### 10. Evaluation on one system proves nothing

- **Missing:** multiple systems, ground truth, and a downstream metric.
- **Why it hurts:** reviewers will reject Train-Ticket-only results, and you have already seen the drop on other systems.
- **Fix:** tune on Train-Ticket, then freeze rules and test on held-out systems (eShopOnContainers, Sock Shop, DeathStarBench, TeaStore, plus a sample from the [MSR 2024 dataset](https://2024.msrconf.org/details/msr-2024-data-and-tool-showcase-track/28/A-Dataset-of-Microservices-based-Open-Source-Projects) of 378 projects). Report edge precision and recall against traces plus manual labels, and agent task success with and without Wadi.
- **Related:** [Smith et al.](https://ar5iv.labs.arxiv.org/html/2306.05895) already pair Train-Ticket with eShopOnContainers as a test benchmark.

#### What would make agents 10x better

Change impact is the one to build first: it answers the question agents get wrong most in multi-service code, and it is your research area. The list below is my judgment, not measured; the agent A/B in step 3 is how you prove it.

| Artifact (MCP tool) | Question the agent asks | Why it multiplies output |
| --- | --- | --- |
| `impact(target)` | If I change this endpoint, DTO field, table or topic, what breaks? | Lists consumers, contracts and tests across services before the edit, not after CI fails |
| `endpoint_summary(id)` | What does this endpoint do end to end? | One card: guards, downstream calls, data effects, errors, auth, in a few hundred tokens |
| `check_diff(patch)` | Does my change break another service? | Turns contract drift into a pre-merge error the agent can fix itself |
| `invariants(entity)` | What rules must hold? | Validation, status state machines and guards extracted from code, so the agent does not violate business rules |
| `examples(endpoint)` | What does a valid request and response look like? | Real payloads from tests, fixtures or traces let the agent write working tests and calls first try |
| `failure_modes(call)` | What happens if this call fails? | Timeouts, retries, circuit breakers, fallbacks and error codes, needed for root cause analysis |
| `conventions(service)` | How does this service do auth, errors, logging? | Patterns to copy, so new code matches the codebase instead of the model's defaults |
| `tests_for(endpoint)` | Which tests cover this and how do I run them? | Closes the edit, run, fix loop without the agent guessing commands |

Every response should carry provenance, confidence and the commit it was computed at.

#### Next three steps

1. **Re-layer the pipeline.** Deployment inventory, then a Spring model pack as YAML data, then a call resolver that emits `unknown` edges. Freeze it, then test on Train-Ticket plus two held-out systems.
2. **Build ground truth.** Run three systems under OpenTelemetry, derive the observed service graph, and report edge precision and recall per layer.
3. **Ship three tools and run an agent A/B.** `endpoint_summary`, `impact` and `examples`, measured on about 20 cross-service tasks with and without Wadi. That result is your paper's headline.

#### Sources

- [Automatic Extraction of Security-Rich Dataflow Diagrams for Microservice Applications written in Java (Code2DFD)](https://arxiv.org/abs/2304.12769v1)
- [Static analysis tools in the era of cloud-native systems (Cerny, Taibi)](https://ar5iv.labs.arxiv.org/html/2205.08527)
- [CodeQL: customizing library models for Java and Kotlin](https://codeql.github.com/docs/codeql-language-guides/customizing-library-models-for-java-and-kotlin)
- [RepoGraph: Enhancing AI Software Engineering with Repository-level Code Graph](https://arxiv.org/html/2410.14684v2)
- [LLMDFA: Analyzing Dataflow in Code with Large Language Models](https://arxiv.org/abs/2402.10754v2)
- [OpenTelemetry service graph connector](https://pkg.go.dev/github.com/open-telemetry/opentelemetry-collector-contrib/connector/servicegraphconnector)
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0)
- [Anthropic: Writing effective tools for agents](https://anthropic.com/engineering/writing-tools-for-agents)
- [A Dataset of Microservices-based Open-Source Projects (MSR 2024)](https://2024.msrconf.org/details/msr-2024-data-and-tool-showcase-track/28/A-Dataset-of-Microservices-based-Open-Source-Projects)
- [Benchmarks for End-to-End Microservices Testing (Smith et al.)](https://ar5iv.labs.arxiv.org/html/2306.05895)

## Item 038. Answer

Yes to both. There are more sources than OpenAPI, and wadi can be made ready for runtime evidence without building any of it now.

The code audit found eight places where the model assumes code is the only source. The six changes cover six of them. The other two are Maven-only service discovery and graph node ids that change between runs. Once the six are in, adding runtime evidence is one import job, one collection and one adapter that maps a trace to the shared keys. The analyzer, the stitcher and the views do not change.

#### What each source cannot do

- **Config finds few services or calls by itself.** In a comparison on 17 Java systems, two tools that depend on deployment files for their service list found 76% and 56% of components. The best tool reading code and config found 98%, and 65 of 182 components appeared in no deployment file.
- **Config is often wrong about the running system.** A study that installed 287 Helm applications found a mismatch between declaration and runtime in 259. Config facts should read as declared, not verified.
- **Runtime evidence cannot refute a static fact.** An 11-test suite reached 119 of TrainTicket's 262 endpoints. Silence means "not exercised".
- **Runtime evidence needs the gateway routes first.** In one TrainTicket study, 52 of 171 observed endpoints were gateway calls missing from the static list.
- **Line-level joins need the identical build.** JaCoCo reports a class from a different build as 0% covered. Endpoint and call joins survive a version gap.
- **Some truth is in neither code nor git.** Console-made cloud resources, config servers and auto-created Kafka topics exist only in the running system, which is the case for runtime evidence later.

#### The review you pasted

I checked each gap against the code. It reads as written from a description of wadi, not from the repository.

| Gap | In the code today | Verdict |
|---|---|---|
| 1. Full CFG is wrong for agents | MCP returns a method-level summary by default and a contract card per endpoint | Partly built |
| 2. Rules written per benchmark | No rule names a benchmark, but all three measured systems are Spring and shaped the rules | Wrong as stated, right in substance |
| 3. No call resolver | A seven-step resolver exists and publishes unresolved calls with reasons | Exists, lacks Kubernetes and nginx |
| 4. Data is invisible | Entity access per endpoint shipped in 0.9.0 | Mostly shipped |
| 5. Config not read | Compose and Spring config are read | Half true |
| 6. No runtime evidence | The JaCoCo and bytecode checks run only in tests | True |
| 7. Async deferred | Listeners are detected, and the stitcher matches HTTP only | True |
| 8. MCP tools not agent-shaped | Eight tools built around entities, with no paging that I found | True |
| 9. Model can poison the graph | No model writes any fact today | Not a gap |
| 10. One system proves nothing | Three systems, all Spring, none held out | True in substance |

Three of its fixes need correcting:

- **Deployment files as the service inventory.** The 65-of-182 figure argues against it. Code should find services and config should name them.
- **Its held-out systems.** Most are not Java and Spring, which is all wadi reads today. From memory, eShopOnContainers is .NET and DeathStarBench is C++ and Go. The 17 systems in the tool comparison are Java and Spring and come with ground truth.
- **"Static only" as a false positive.** It must not be scored that way, for the coverage reason above.

It adds two things worth taking:

- **An `impact` tool.** `remote_edges` lists callers per service, but nothing answers "what breaks if I change this field or table".
- **An agent A/B test as the headline result.** The earlier research found graph context adds only 2 to 8 points when the agent has the code on disk. Run the test where the agent holds one service's code and not the others.

#### Decisions for you

1. **Record "one collection per source, joined at read time" in `architecture.md`** before any new reader is built. I recommend yes.
2. **Add environment as a scope now**, with one default environment. I recommend yes.
3. **First new source.** I recommend Kubernetes, Helm and the image link, because it also supplies the service names a runtime join needs.
4. **Held-out test set.** I recommend the 17 Java and Spring systems.

The agents opened their sources and marked what they only recalled. I did not re-open those sources or the review's. Nothing is written to the repository.

The page is at a temporary session folder (not stored).

## Item 039. Owner

Now with that change how exactly the full architecture gonna look like?

## Item 041. Answer

Everything that is built stays, and the rule packs plan becomes the inside of the static analyzer without changing.

#### What is different from the plan in `docs/`

- **Three more readers sit beside the static analyzer.** The plan had one source of facts.
- **Each reader keeps its own records, joined at read time.** Today one provenance value sits on each call edge, and the stitcher rewrites the whole set.
- **Environment becomes a scope.** Today a snapshot is one set of commits and config profiles collapse into one.
- **The learn loop gets more inputs.** The plan fed it only the gaps the analyzer knew about, so it could not see a fact that was wrong or silently missing.
- **Model output never becomes a call edge directly.** `architecture.md` §5.6 lets the stitcher use a model's guess as a low-trust edge. Here a model can only draft a rule, and the rule must pass the check. This is the plan's open decision D7, and it needs your call.

#### What stays the same

- Services still talk only through stored records.
- Each collection still has one writer.
- Joern stays stock.
- An ordinary analysis still runs with no model.
- Unknowns are still published.

#### Order I would build it in

1. The scorer and ground truth from the hardening plan, since every later step is measured against it.
2. The six model changes from my last message, together with the plan's stage 3, because both change the snapshot record.
3. The Kubernetes and Helm part of the config reader.
4. The rule engine and base packs.
5. The declared reader, then the auditor.
6. The runtime importer.

#### Still open

- **Where the new readers run.** I recommend jobs inside the extraction worker, because it already holds the repository checkouts. A separate service is the alternative.
- **Whether the fold is computed on every read or stored.** I recommend computing it first and storing it only if reads get slow.
- **How an environment is named and chosen** when a repository holds several values files.

None of this is recorded in `docs/` yet. The page is at a temporary session folder (not stored).

## Item 042. Owner

Where exactly we are going to store all those new framework data? Is it going to be like another hub or package manager to download it?

## Item 043. Answer

No. Neither the plan nor my recommendation has a second hub or a package manager. Framework data ships with wadi, and your own rules stay with your system.

#### Where each kind lives

| What | Form | Stored in | How it reaches you |
|---|---|---|---|
| Language profiles | Scala code | The wadi repository, compiled into the Joern image | A wadi release |
| Semantic plugins, such as Spring Security | Scala code | Same | A wadi release |
| Base packs, one folder per framework | Data files, each with a fixture and expected output | The wadi repository, loaded from a mounted directory at run time | A wadi release |
| Learned rules for your system | Data files | Wadi's database, plus a file under `.wadi/` in your repository | Learn mode writes them, git carries them |
| Hints | Data | Same as learned rules | Same |

Two things in that table are not settled:

- **How the mounted pack directory gets filled.** The plan says packs load from a mounted directory and stops there. I recommend filling it from the release, so a wadi version always means one exact set of packs.
- **Where learned rules live.** This is the plan's open decision D1. Its recommendation is both places, with the committed file winning, which matches what `architecture.md` already plans for hints. I agree with it.

#### One gap for your hub goal

The plan has no place for rules that belong to a whole company. If forty services across five teams use the same internal auth library, each team would have to learn the same rules separately.

I recommend a fourth scope for that. It would be a pack folder in a git repository your company owns, mounted beside the base packs. Git already gives versioning, review and pinning to a commit. The hub could hand that folder to each team later.

#### Why not a registry now

- **A pack decides what the map says, including whether an endpoint is protected.** A downloaded pack is something you have to trust.
- **Code must not be downloaded at run time.** The plan keeps plugins in the image for this reason.
- **Every pack needs a fixture checked in CI.** A registry would have to run that check for outside packs, or accept unchecked ones.
- **Nobody outside is writing packs yet.** Whether that changes depends on decision D5, hundreds of frameworks or three to five.

If D5 goes to hundreds, the first step is still not a registry. It is accepting packs by pull request into the wadi repository, which keeps them inside a release.

The door stays open if a pack is a self-contained folder with its own id, version and format version. The engine then does not care whether the folder came from a release, a git repository or a registry. From memory, CodeQL and Semgrep run registries and Nuclei syncs one git repository of templates. I did not check those in this session.

## Item 046. Owner

when and how those language profile will be downloded?

## Item 048. Answer

No separate download happens. A language profile is part of the wadi Joern image, so it arrives when the image does.

**When.** At install and at each upgrade. `wadi up` pulls `ghcr.io/wadi-sh/joern:<version>`, and `wadi upgrade` followed by `wadi up` pulls the next one. Wadi fetches nothing at analysis time, so pointing it at a Python repository downloads nothing.

**How.** One version covers the whole release. The CLI embeds a compose file whose image tags are pinned to its own version ([upgrade.py](../../../cli/src/wadi_cli/upgrade.py)), so upgrading the CLI package is what selects the new image.

#### What a language consists of

I checked both parts inside the local 0.9.0 image.

| Part | Written by | Size | State today |
|---|---|---|---|
| The parser for the language | Joern | 1.7 GB for 14 parsers | Already in the image: Java, Kotlin, Python, JavaScript, Go, C#, PHP, Ruby, Swift, Rust, C and others |
| The language profile | wadi | Inside one 11.5 MB jar | Java only, and not yet separated from the exporter (stage 2 of the plan) |

The parsers for most languages are already on your disk. What Python or Go lacks is wadi's own code that reads the parser's output. Adding a language means a wadi release with a larger jar. The plan expects five to eight profiles in total.

#### What an upgrade downloads

The jar is its own image layer, on top of a 1.94 GB Joern layer. The release workflow uses a build cache ([release.yml:122](../../../.github/workflows/release.yml:122)). When the cache holds the Joern layer, an upgrade should download only the jar layer. When the cache has expired, the build recreates the Joern layer and you download it again. I did not test an upgrade pull, so I can't say how often each case happens.

#### Why not fetch a profile on demand

- The jar is compiled against one exact Joern version, 4.0.593 ([Dockerfile](../../../joern-platform/Dockerfile)). A profile shipped separately could load against the wrong one.
- The plan lists loading compiled code at run time in Joern's server mode as unverified.
- Size gives no reason to. The parsers take up most of the image and are already there.

#### Two things I did not verify

- **Some parsers may need a runtime the image lacks.** The image has the PHP parser's files and no `php` binary. From memory, that parser runs under PHP. If so, adding PHP would grow the base image as well as the jar.
- **What wadi does today with a non-Java service.** P10 requires the map to show it as not analyzed, with a reason. I did not check the current behaviour.

## Item 049. Owner

I was concern about the current stack is required around 10gb storage/ram to run it. why is that then

## Item 050. Answer

I checked the compose file, the decision record and the local images. The 10 GB is memory, not storage, and it is a ceiling on one container. The stack does not use 10 GB at rest.

#### Where the memory goes

| Container | Limit in the compose file | Notes |
|---|---|---|
| `wadi-joern` | 10 GB | The JVM heap can use 75% of it, so 7.5 GB |
| Neo4j | 1 GB | Heap pinned at 512 MB |
| MongoDB | 512 MB | |
| Orchestrator, worker, stitcher, MCP | None | `architecture.md` estimates tens of MB each |

Docker does not reserve a limit. A container only takes what it uses.

#### Why the limit is 10

Joern builds a service's whole code graph inside one JVM. Since 0.8.1, wadi parses a service together with the library sources it compiles in, because the library declares the types the service returns. Memory follows the largest service plus its libraries.

One system set the number. ICPC has 563 service files and 840 library files, and the old 6 GB limit killed the parse. The limit went to 10 ([architecture.md:786](../../../docs/architecture.md:786)). I found no measurement of peak memory for any other system, so I can't say what a small one needs.

The limit does not grow with the number of services, languages or rule packs. The new readers we discussed are Python and add tens of MB each.

#### Three problems I found

- **Joern stays running.** `architecture.md` says it starts when extract jobs exist and stops when idle, with "steady-state cost: zero". The compose file starts it with `wadi up`, and I found no code that stops it. I could not measure its idle use because the stack is down.
- **The limit is hard-coded.** `mem_limit: 10g` has no setting behind it, so a small system gets the same ceiling as ICPC.
- **This Mac cannot reach the limit.** Its Docker VM has 5.78 GiB, below the 6 GB at which ICPC failed.

#### Disk is a separate number

The 0.9.0 images list at 9.4 GB in total. They share layers, so the real figure is lower. `docker system df` reports 9.9 GB for 0.8.2 and 0.9.0 together.

The Joern image is the largest at 4.49 GB as listed. Its Joern layer is 1.94 GB, and 1.7 GB of that is the 14 parsers. Wadi calls one of them today, the 89 MB Java parser ([WadiPipeline.scala:49](../../../joern-platform/src/main/scala/wadi/WadiPipeline.scala:49)).

#### What I would change

1. Record peak memory per service on each snapshot. That gives a real number to size against.
2. Start Joern only while extract jobs exist, as the decision record already says.
3. Make the limit a setting.

I would leave the unused parsers in the image. Removing them saves up to 1.6 GB of disk, and each new language would need its parser put back.

## Item 051. Owner

Quote of an earlier answer: "I would leave the unused parsers in the image. Removing them saves up to 1.6 GB of disk, and each new language would need its parser put back.&start=2284&end=2426&prefix=says. Make the limit a setting. &suffix=&comment=what you mean?"



## Item 052. Answer

I mean the Joern image carries 14 language parsers, and wadi uses only one of them today.

- **What is in the image.** Joern ships one parser per language: Java, Python, Go, JavaScript, Kotlin, C#, PHP, Ruby, Swift, Rust, C and a few more. Together they take 1.7 GB of disk.
- **What wadi uses.** Only the Java parser, which is 89 MB. The other 13 are files that wadi never runs.
- **The option.** We could delete those 13 from the image. The image would be up to 1.6 GB smaller to download and store.

I would not do it, for three reasons:

1. **It does not help the problem you raised.** Your concern was memory. A parser that never runs uses no memory, only disk.
2. **We would undo it language by language.** When wadi adds Python, the Python parser has to go back into the image, then the Go parser for Go, and so on. Each time is another build step that can go wrong, for example a parser from the wrong Joern version.
3. **The image stops being a plain Joern install.** Today the image is the official Joern release plus wadi's jar, which is what principle P5 asks for. Deleting files from it means maintaining our own list of what to keep.

There is a cheaper middle option if you want some of the saving. Two parsers are for things wadi has no plan to analyze: `ghidra2cpg` for compiled binaries (307 MB) and `abap2cpg` for SAP's ABAP language (111 MB). Removing only those two saves about 418 MB and costs nothing later.

## Item 053. Owner

in future we will find a way to optimized it. for now as we are doing a proof of concept. let's keep it as is and make sure it works properly

## Item 054. Answer

Agreed. The image, the parsers and the 10 GB limit stay as they are, and I will stop proposing footprint changes until you bring the topic back. I saved that as a note for future sessions.

I read "make sure it works properly" as the priority for the proof of concept, so I ran nothing and changed nothing in the repository.

One item from my earlier list affects whether wadi works, so it still matters. This Mac has 8 GB of RAM in total and gives Docker 5.78 GiB. The old 6 GB limit already killed the ICPC analysis, so ICPC will fail on this machine. No Docker setting can fix that here, because the Mac does not have 10 GB to give.

When that happens, the error does not mention memory. The next service fails with "CPGQL server unreachable", as the decision record notes.

For the proof of concept, that leaves two workable setups:

- **Demo on this Mac with smaller systems.** I have no measurement of what train-ticket needs, so I can't promise it fits. A run would show it.
- **Run large systems such as ICPC on a machine with 16 GB or more.**

## Item 055. Owner

my concern is, for each of the language there can be multiple framework. for i.e. python has django, fast api, js has nodejs, hono and other. Are we going to create one profiler per language or one per framework?

## Item 056. Answer

One profile per language. A framework never gets its own profile. Each framework is a pack, which is a data file of rules and not code.

#### How it splits

| Language profile (code, one per language) | Packs on top of it (data, one per library) |
|---|---|
| Java | Spring, Quarkus, Micronaut |
| Python | FastAPI, Django, Flask |
| JavaScript and TypeScript | Express, Hono, NestJS, Fastify |
| Go | Gin, Echo |

Node.js is the runtime, so the JavaScript profile covers it. The plan expects five to eight profiles in total and many packs.

- **The profile holds what is true for the whole language.** That covers which parser to use, how one function calls another, how control flow exports and how a URL string is built.
- **The pack holds which names mean what in one library.** That covers what marks an endpoint, where the verb and path are, and which calls reach a database, a queue or another service.

A pack is per library, not only per web framework. A Python service would use one profile and several packs at once, for example FastAPI, SQLAlchemy and an HTTP client. The worker picks the packs for each service.

A third layer exists for the rare framework that needs depth a data file cannot express, such as authorization. That layer is code, and Spring Security stays there. A framework with a pack only still publishes its routes and calls, and marks authorization as "not read".

#### What is not proven yet

- **The rule format does not exist.** The plan says "the format is not designed", and no framework other than Spring has been tried. Stage 1 runs two probes to measure the cost, with Quarkus and FastAPI proposed.
- **Frameworks declare routes in different shapes.** This is my own reading, from general knowledge of these frameworks, and the plan does not list the shapes. I count three:

  | Shape | Examples |
  |---|---|
  | A marker on the handler | Spring `@GetMapping`, FastAPI `@app.get("/x")`, NestJS `@Get()` |
  | A registration call | Express and Hono `app.get("/x", handler)`, Gin `r.GET(...)` |
  | A route table in another file | Django `urls.py` |

  Each shape needs engine code, written once and shared by every framework that uses it. The real count of code pieces is then languages plus route shapes plus the rare plugins. Frameworks stay data.
- **Python and JavaScript profiles will be harder than Java.** They have no static types, so resolving which function a call reaches is weaker. I expect more "unknown" answers there. Nobody has measured it.

#### One suggestion for the probes

Quarkus uses the same shape as Spring, so it measures the cost of a pack alone. FastAPI measures the cost of a new language. Neither tests the registration-call shape or the route-table shape. I would add Express or Django as a third probe before fixing the rule format, because those shapes decide whether "frameworks are data" holds.

## Item 057. Owner

So, are we going to put all the packs as a part of the profile as well inside the joern container?

## Item 058. Answer

No. Packs stay separate from the profile, and they are not compiled into the Joern image.

#### What sits where

| Piece | Form | Location |
|---|---|---|
| Language profile | Code | Inside wadi's jar, inside the Joern image |
| Rule engine, one for all packs | Code | Same jar |
| Rare plugins, such as Spring Security | Code | Same jar |
| Base packs | Data files | A directory mounted into the container at run time |
| Learned rules for your system | Data files | Wadi's database and `.wadi/`, handed to the engine for each run |

The Joern container reads the packs, but it does not own them. The plan words it as "loading packs from a mounted directory at run time".

Two reasons the plan keeps them out of the jar:

- **A rule fix should not need a new Joern image.** Today a one-line change to a pack ships as a new image, and the plan names that as a problem.
- **Joern is not the only reader.** A pack also says which files are build roots and config, and the Python worker reads that part. The files have to be visible to both containers.

#### What the plan leaves open

The plan does not say how the mounted directory gets filled. This is my recommendation, not something recorded.

1. Base packs ship as plain files in the worker image, which is 380 MB and quick to rebuild.
2. For each run, the worker copies the packs that service needs, plus your system's learned rules, into the volume it already shares with Joern.
3. The worker computes the rule-set hash over exactly those files and records it on the snapshot.

The worker already works this way for source code. It stages a service's sources, and its library sources, into that shared volume for Joern to parse. Packs would travel the same path.

This also gives an exact answer to "which rules produced this snapshot", because the hash covers the files Joern read for that run and nothing else.

## Item 059. Owner

they how exactly we will distribute those pack?

## Item 060. Answer

Through two channels that wadi already has: the wadi release and git. No new service is needed. The plan fixes only the first row below. The rest is my recommendation.

| Pack kind | Written by | Stored in | How it reaches a machine | Pinned by |
|---|---|---|---|---|
| Base packs | Wadi maintainers, and outside contributors by pull request | A `packs/` folder in the wadi repository | Inside the worker image, pulled by `wadi upgrade` then `wadi up` | The wadi version |
| Organization packs | Your company, for internal libraries many teams share | A git repository your company owns | The worker clones it, the same way it clones source repositories today | A commit named in the system's settings |
| Learned rules and hints | Learn mode, approved by a person | Wadi's database, and a `.wadi/` file in the analyzed repository | Git, once someone commits the file | The repository's commit |

#### How each one works

**Base packs.**
1. A pack is a folder with a rule file, a small sample project and the expected output.
2. CI runs the sample project on every change and fails if the output differs.
3. The release build copies the folder into the worker image.
4. Users get it with the next wadi version. Nothing extra to install.

**Organization packs.**
1. Your company keeps a repository of packs in the same folder layout.
2. A system's settings name that repository and a commit.
3. The worker fetches it before analysis and stages those packs beside the base packs.

The same channel covers an urgent fix. If a base pack is wrong today, you can put a corrected copy in that repository and not wait for a wadi release.

**Learned rules.**
1. Learn mode writes approved rules to the database, so they work at once on that install.
2. Wadi exports them to a `.wadi/` file. A person commits it, because wadi cannot write to analyzed repositories.
3. Teammates and CI get the rules through git. When both exist, the committed file wins.

#### Three properties this keeps

- **Nothing downloads during analysis** except repositories you named, so it works on a closed network.
- **Reruns match.** Every pack is fixed by a wadi version or a commit, and the snapshot records a hash of the rules it used.
- **Each pack is a self-contained folder** with its own id, version and format version. If hundreds of outside packs arrive later, a registry can be added as a third channel without changing the engine.

#### Two things to decide

- Whether you want the organization scope. The plan does not have it, and your hub goal needs something like it.
- Where a learned rule lives when a system spans several repositories. I would keep a rule in the repository whose code it describes, and keep system-wide rules in the database.

## Item 061. Owner

when a user install wadi, are they going to download all the profile and packs at the beginning. or they can download only whatever they need

## Item 062. Answer

They download all of them at install. Nothing is chosen at download time. Wadi picks what to use later, when it reads your repository.

#### Why downloading everything costs little

| Piece | Size |
|---|---|
| All of wadi's own Scala code today, which will hold every profile | 11.5 MB, measured |
| One pack's rule file | A few kilobytes, estimated, since no pack exists yet |
| Joern's 14 parsers | 1.7 GB, measured, and already in the image today |

The profiles and packs are small next to the parsers, and the parsers come with Joern whether wadi uses them or not. Even hundreds of packs would add a few megabytes. Each pack's sample project and expected output can stay in the wadi repository for CI, so users only receive the rule files.

#### What is selective

Use is selective, not download. For each service, the worker reads the build files, sees which language and libraries the service uses, and hands only those packs to the engine. A Java service with Spring never loads the Django pack.

Organization packs and learned rules are also selective already. Wadi fetches them only for a system whose settings name them.

#### Why I would not download on demand

- **Wadi cannot know what you need before it reads your code.** A monorepo can mix Java, Python and TypeScript, and a new service can add a library next week.
- **Analysis would need the network.** That breaks closed networks, and a download failing mid-analysis becomes a new way for a run to fail.
- **Reruns could differ.** Two machines on the same wadi version could hold different packs unless every download is locked to a version.
- **The saving is a few megabytes.**

One case could change this later. If a language needs a heavy runtime added to the image, splitting the image per language would be worth a look. That is an image-size question, and you have said to leave footprint alone for now.

## Item 063. Owner

now can you create the claude artifact of with the details architecture. make sure the architecture is easy to understand and how each of the component is connected together

## Item 068. Answer

The architecture page is published: https://claude.ai/artifact/AvjQASWRX8YVTHUH6QV6Kj

It is private to you until you share it from the page's Share menu.

The page has three diagrams and the tables behind them:

- **From evidence to the map.** Four kinds of evidence, each with its own reader and its own records, then the stitcher, the fold and the clients. Select any box to dim everything it does not connect to and see what it gets, what it gives and where it runs.
- **Which process talks to which.** Every service, the stores it uses and the channel on each connection.
- **Inside one analysis of one service.** The parser, language profile, rule engine, plugins and exporter in order, with the three kinds of rule files feeding the engine.

Below the diagrams are where code and rules are kept, the five fold statuses, the learn loop, the hub, a table of every piece, and a section that separates what is built, what is in the plan and what we only discussed.

Things to know:

- **Every part carries a state mark.** Built, partly built, planned or later, so the page does not present planned parts as existing.
- **The last section matters most for accuracy.** Much of the design, such as one collection per reader, the fold and organization packs, comes from this conversation and is in no document in the repository yet.
- **One correction.** I said earlier that the MCP server has eight tools. It has nine, and the page says nine.
- **What I checked.** I viewed the page once at desktop width in the light theme and widened one tight label column afterwards. I did not view the dark theme, the phone layout or the final published version.

## Item 069. Owner

can you make the artifact public

## Item 070. Answer

I can't change sharing from here. Only you can, from the page itself.

1. Open https://claude.ai/artifact/AvjQASWRX8YVTHUH6QV6Kj
2. Open the **Share** menu on the page.
3. Choose the public link option, then copy the link.

Before you do, one thing to weigh. The page holds no credentials, personal names or addresses, but it does describe unreleased plans, including the parts marked "proposed in discussion only".

## Item 071. Owner

Does our architecture supports exporting one analyzed date and import it later. is this the way wadi will talk with the wadi hub

## Item 072. Answer

Export is built. Import is not. And yes, the decision record says the exported bundle is exactly what a team's wadi will send to the hub.

#### What exists today

| Piece | State | Evidence |
|---|---|---|
| `wadi export <snapshot-id> --dir` | Built | [main.py:891](../../../cli/src/wadi_cli/main.py:891) |
| `GET /api/v1/snapshots/{id}/export`, a stream of records | Built | [app.py:350](../../../services/orchestrator/src/wadi_orchestrator/app.py:350) |
| Import of a bundle | Not built | No import or ingest code in the CLI or the orchestrator |
| A system whose source is a bundle | Not built | `RepoSource` accepts only a git URL or a local path |
| The `federated` label for imported facts | Reserved | The value exists in the contracts, and nothing writes it |

A bundle holds one snapshot: the system, the snapshot, service boundaries, endpoints, one flow graph per endpoint, outbound calls, queue interactions, data models, stitched edges and the coverage report. Three properties already suit the hub:

- **Every file validates against the published schemas.**
- **A manifest comes last, with a count per kind.** A reader that never sees it knows the bundle is cut short.
- **Exporting the same snapshot twice gives the same bytes**, apart from one timestamp.

#### How wadi will talk to the hub

This is Phase 11 in `architecture.md`, with export named as its prerequisite.

1. Each team runs wadi on the services it owns.
2. The team publishes a bundle. It can be full, or boundary-only, which carries endpoints and outbound calls without the flow graphs.
3. The hub's orchestrator accepts the bundle through an ingestion API and checks it against the schemas.
4. The hub runs the same stitcher across all bundles. It records each bundle's version and age, and shows stale ones in the coverage report.

The hub needs no source code for this, because the stitcher reads only stored records. I think this is the right design. It keeps teams and the hub joined by the file format alone, and it works across wadi versions and on closed networks.

#### What must change before import works

- **Service ids from local paths differ per machine.** A repository analyzed from a local folder gets an id built from that folder's path ([ids.py:78](../../../libs/wadi-contracts/src/wadi_contracts/ids.py:78)). The hub could then see one service as two. Git URLs do not have this problem.
- **Snapshot ids are random.** The hub needs the planned composite snapshot, which is a recorded set of bundles.
- **A bundle names its wadi version and nothing about its rules.** Two teams on different rule sets would look identical to the hub until the rule-set hash exists.
- **Pushing needs authentication.** The record places that in Phase 6, which is not built.
- **The new readers add collections.** Config records, declared contracts and observed records must join the bundle. The format is one file per collection, so this is an addition.

#### One suggestion

Build import as the exact reverse of export, and test it with a round trip: export, import into an empty install, export again, compare. The existing same-bytes rule makes that test cheap, and it would also give you backup and restore between machines.

## Item 073. Owner

okay first of all, we need a way to import service. make sure we add it as a part of the architecture. there should be 2 ways to analysis data. 1. directly from source, 2. importing from the export what wadi ran on other service and geenrate the export for that service. 

I know we haven't build that yet, however, what the plan for sending each service run to hub?

## Item 075. Answer

Import is now part of the architecture page, at the same link: https://claude.ai/artifact/AvjQASWRX8YVTHUH6QV6Kj

The page is shared as "anyone with the link" now, so this update is visible to everyone who has it.

#### What I added

- **A new section, "Two ways to get a service into the map".** Way 1 is from source, through the static analyzer. Way 2 is from a bundle, through an import job. Both fill the same collections, so the stitcher and every client work the same on either.
- **A "Service bundle" box in the main diagram**, feeding the code facts.
- **Import and export rows** in the table of pieces, and import moved up to step 3 of the build order.
- **The hub section now has the sending steps** and what a bundle carries.

I did not change `docs/architecture.md`. It already reserves this under Phase 11, and the repository rule is that a decision goes there before any code.

#### The plan for sending each service run to the hub

The decision record fixes the shape and not the mechanics. It says teams publish bundles, the hub has an ingestion API, a hub snapshot is a set of bundles with their ages, and teams own services. The steps below are my proposal.

1. A team's CI runs wadi on its services at one commit.
2. A publish command exports one bundle per service and sends each to the hub's REST API with the team's token.
3. The hub's orchestrator checks the manifest and whether that team owns the service, then creates an import job.
4. The hub's worker checks every record and replaces that service's earlier records as a whole. Each fact keeps the team, commit, wadi version and rule hash it came from.
5. The hub builds a new snapshot from the newest bundle of every service and runs the stitcher across all of them.
6. The coverage report shows the age of every bundle.

Two design choices in there:

- **One bundle per service, not per system.** Today export writes a whole snapshot. Per service means a change to one service resends only that service.
- **The worker writes imported records, not the orchestrator.** The worker is the only writer of those collections today, and this keeps that rule.

#### What blocks it today

- Export is whole-snapshot only, and there is no import.
- A system's source can only be a git URL or a local path.
- A service analyzed from a local folder gets an id that depends on that folder's path, so the hub could see one service as two.
- A snapshot must contain at least one commit, so it cannot be made of bundles alone.
- Team tokens belong to Phase 6, which is not built.

#### Decisions for you

- **Push or pull.** I recommend push from CI, with import from a folder as the fallback for closed networks.
- **Full or boundary-only by default.** Full bundles include every flow graph, which root-cause analysis across services needs. Boundary-only shares the interface alone.
- **Which branch the hub's map follows.** I recommend one named branch per system, with bundles from other branches stored and left out of the default map.

## Item 076. Owner

I have two question:
- I own a service, and the hub has all the services data. can I import the hub data and test out against mine? to run the analysis, to see if I have any breaking changes or else
- I have 2 services and they are dependent on each other. if I run the analyzer separately on both service and create the separate export. after importing them to a single instance, can the steacher be able to connect them all? if there any dependency call in between can it be able to detect properly?

## Item 077. Answer

Both are yes by design, and neither works today because import is not built. Here is what each one needs and where it would fall short.

#### 1. Testing your service against the hub's data

The decision record covers this in both directions. A team's wadi can import another team's bundle from the hub, and a planned contract checker compares two snapshots and reports breaks, with a CI gate named `--fail-on contract-break`.

The flow would be:

1. Pull the bundles of your neighbours from the hub. You only need the services that call yours and the ones yours calls, and a boundary-only bundle is enough.
2. Analyze your own service from source, at your branch.
3. Stitch them together and compare the result with the hub's current map.

What that comparison can catch depends on which facts wadi extracts today:

| Your change | Caught with today's facts? |
|---|---|
| You remove an endpoint, or change its verb or path, and another service calls it | Yes. That caller's call stops resolving. |
| You call an endpoint the other service does not have | Yes |
| You add a required role, and a caller does not forward a token | Partly. Wadi extracts both facts, but nothing compares them yet. |
| You remove or rename a response field | Half. Wadi sees your shape changed and who calls the endpoint. It does not know which fields each caller reads. |
| You change a queue topic or message | No. The stitcher links HTTP calls only. |
| Same contract, different behaviour | No. Static analysis of shapes cannot see it. |

The field-level row is the important gap. The record plans to close it by extracting what each caller sends and which response fields it reads.

#### 2. Two services analyzed separately, then imported together

Yes for HTTP calls. The stitcher reads four stored collections and never the source: service boundaries, endpoints, outbound calls and queue interactions ([pipeline.py:80](../../../services/stitcher/src/wadi_stitcher/pipeline.py:80)). Joern already analyzes each service separately today, so after import the stitcher gets the same inputs.

It connects them like this. Each service's record carries its own names and ports. When service A calls `http://service-b:8080/orders/1`, the stitcher looks up `service-b` among all the records, finds service B, and matches the verb and path to one of B's endpoints.

Separate analysis loses something in four cases:

- **B's network name is not in B's repository.** Wadi reads names from the compose file and config inside each repository. If the name exists only in a Helm chart or a shared deployment repository, B's bundle will not carry it. The stitcher then falls back to matching by port, or reports the call as unresolved with the reason.
- **The call goes through a gateway.** The routes live in the gateway's record, so you must import the gateway's bundle as well.
- **Both services use a shared library from a third repository.** Wadi pools the modules of all repositories in a system before it decides what is a library ([boundary.py:131](../../../services/extraction-worker/src/wadi_worker/boundary.py:131)). Analyzed alone, a service cannot see that library, and the types it declares stay unresolved. Each team would need to add the library's repository to its own system.
- **They talk over a queue.** Wadi extracts queue interactions, and the stitcher does not link them yet.

In every one of these cases the stitcher publishes an unknown. It does not invent a link.

Nobody has run this, so it is reasoning from the code. The test I would make the acceptance check for import: analyze a two-service fixture once as one system and once as two separate exports imported together. The stitched edges must be identical.

## Item 078. Owner

now with our architecture we are missing one of the most important part. which is auth/security. authorization and authentication works differently on different endpoints. Do we need a separate special service for that?

the current extractor does extract some of it. but hosnestly this is one of the biggest gap now we have as well. Research well and deeply how we can do it in best possible way

## Item 080. Answer

No separate service for extracting auth. Auth is not one more kind of evidence. Every reader holds part of the answer, so it belongs in the record model, with one checker on top that the roadmap already plans for Phase 3.

#### Where wadi stands today

From a code audit. I re-checked the first three points myself.

- **Nothing joins caller and callee.** Wadi has a claim per endpoint and a "token forwarded or not" fact per outbound call. The stitched edge has no auth field.
- **Object-level rules are unread.** "May this caller access this record" is never answered. `resource_binding` is always empty ([SpringSecurityPack.scala:1181](../../../joern-platform/src/main/scala/wadi/packs/SpringSecurityPack.scala:1181)).
- **Nothing outside the service's code is read.** A `gateway` evidence kind exists and nothing produces it.
- **It is all Spring, matched by name.** About 2,000 lines of Scala and 1,100 of Python.

#### What the research says

| Finding | Evidence |
|---|---|
| Access control is the top flaw class | First in [OWASP Top 10:2025](https://top10.owasp.org/2025/A01_2025-Broken_Access_Control). Object-level authorization is first in the OWASP API Top 10 2023. |
| Static analysis reads behaviour, not intent | Ote (OSDI 2026) calls complete extraction impossible in general |
| Object-level detection is 78 to 89% precise, recall unproven | [BolaRay](https://leehaofeng.github.io/papers/2024-BolaRay.pdf): 193 of 247. [MOCGuard](https://lfysec.github.io/paper/mocguard-oakland25.pdf): 161 of 180. Authors chose both corpora. |
| A quarter of real object-level bugs were fixed in the SQL | BolaRay's study of 101 bugs |
| Dynamic testing alone finds little | [EvoMaster](https://arxiv.org/html/2604.00702v1)'s missed-authorization check fired zero times on 44 real APIs (preprint) |
| A model alone does badly, and better with structure | A [Semgrep study](https://semgrep.dev/blog/2025/can-llms-detect-idors-understanding-the-boundaries-of-ai-reasoning) (vendor) measured 22% precision, and 0 of 37 where the check was cross-file or in middleware. Neo (preprint) reached 85% recall with CodeQL across services, on 20 cases. |
| No tool combines gateway, mesh and application rules | The tool survey looked and found none. None checks a forwarded identity against what the callee requires. |
| Every proxy layer can let requests through silently | Kong's anonymous consumer, Envoy's `failure_mode_allow`, Istio's permissive default |

The research points one way. Static analysis should pick the endpoint and the pair of identities, and a replayed test should prove the result.

#### The design I recommend

1. **One requirement record for every layer.** Extend the existing enforcement record with the layer (gateway, mesh, application, data), the environment, scopes, token audience, and whether the subject is the end user or the calling service.
2. **Every reader writes those records.**

   | Reader | Adds |
   |---|---|
   | Static analyzer | Today's rules, the framework's default (open or closed), token validation settings, object-level candidates |
   | Config reader | Gateway, ingress and mesh checks, recorded as "a check is configured" unless every let-through setting was read |
   | Declared reader | OpenAPI security per operation |
   | Runtime importer | Requests that succeeded without credentials, and proxy denials |

3. **Effective access is a function, like the fold.** It answers two questions per endpoint and environment: who can call it from outside, and who can call it from inside the cluster. Unknown stays unknown.
4. **One checker service writes findings.** It walks the stitched edges. Examples:
   - The caller forwards no token and the callee requires one.
   - The caller requires ADMIN, and the callee requires nothing and can be reached directly.
   - The callee trusts an identity header and can be reached around the gateway.

   The same service can hold the breaking-change check from your earlier question.
5. **Tests close the loop.** Where static analysis cannot decide, wadi generates the test: each endpoint against no identity, a user, another user and an admin. The result returns as runtime evidence.

#### What packs can and cannot cover

Frameworks declare auth in five shapes. Data rules can capture markers on a handler, literal rule tables and the framework default. Middleware chains, injected dependencies and expression languages need plugin code. Policy held in a database or an identity provider is invisible from a repository, so wadi must publish it as unknown.

#### Limits to accept

- "This endpoint cannot be reached without authentication" is almost never provable from files. One condition is that the deployed config equals the config read.
- Object-level results are candidates, not claims.
- Wadi reports what the code enforces, not what the team intended.

#### Order I would build it in

1. Join caller and callee on stitched edges, write findings, add a system-wide auth tool to MCP. This uses only facts wadi already has.
2. Close a known hole where an endpoint can be published as public beside a guard wadi did not detect. Make the auth measurements reproducible. Both are open in `TODOS.md`.
3. Generalize the record and add the framework default.
4. OpenAPI security through the declared reader.
5. Gateway and mesh checks through the config reader.
6. Object-level candidates, built on the entity access wadi already extracts.
7. Identity tests.

I have not added this to the architecture page.

## Item 081. Owner

The issue is, each application can handle the auth differently, sometimes they might have a custom role, oAuth, SSO, or others way. To test out the system, for i.e. when AI agent or other service need to create the test cases they need proper auth token or authorization and authentication properly. as different service handing it differently, combining all together can be a big issue. For i.e. in spring boot auth can be enforced in multiple layer, one can override other one. handling all these cases can be hard. 

don't get biased with how we are currently doing it at wadi. becuase we did it badly now. what would be the best possible way to do it

## Item 082. Answer

You're right to push on that. Before I answer, I want to check two things my recommendation would depend on, so it rests on evidence and not on how wadi works today: how automated tests can obtain valid credentials across OAuth, SSO and custom schemes, and whether a framework can be asked for its real decision instead of wadi re-implementing its layering.

## Item 083. Answer

The best way is to stop trying to compute the answer from each framework's rules. Split auth into three problems, because each has a different best solution.

#### Why the current approach cannot scale

Wadi re-implements each framework's decision logic. For Spring alone, a request can be allowed, denied or skipped in 12 places, and the defaults changed in versions 6.0 and 7.0. The last three places depend on values that only exist at run time. That is one precedence model per framework per major version, and a wrong one fails silently.

I compared the three ways to learn "is this caller allowed":

| | Read the rules statically | Ask the framework in a test process | Probe the running service |
|---|---|---|---|
| Needs | Source | An app that boots with mocked dependencies | A test environment and credentials |
| Covers | Declared rules | Layers that execute in that process | The whole path, gateway included |
| Cost | Per framework and version | Per framework. Only Spring, ASP.NET and Django REST expose a decision call. | Per system |
| Silent wrong answers | Likely where defaults changed | Spring's evaluator returns "allowed" when no rule applies | Likely if responses are read naively |

#### Problem 1: getting a credential

No tool can derive this from code. Test users, their roles and their secrets exist only with the system owner. A recent survey found "no standard way to provide authentication information to a fuzzer", and only 6 of 23 fuzzers support login at all ([preprint](https://arxiv.org/abs/2509.01612)).

The best answer is an **identity profile** per system and environment:

- **The mechanism**, which wadi can draft from OpenAPI security schemes, issuer settings and login endpoints.
- **Named test identities**, such as anonymous, customer, another customer, admin.
- **A recipe per identity**, in the [Web Fuzzing Commons](https://github.com/WebFuzzing/Commons) format, which four test tools already read. Secrets are references, never values.
- **A check.** Wadi runs each recipe and calls one protected endpoint to confirm it works.

A **credential broker** runs the recipes and attaches tokens to requests, so an agent never holds a secret.

OAuth, SSO and custom logins then differ only in the recipe:

| System uses | Recipe |
|---|---|
| Custom login returning a token or cookie | Call it, extract the token |
| OAuth with an identity provider | Client credentials for a service identity. For a user, a test user in a test tenant. |
| SSO with MFA | Cannot be fully automated. Use a test user excluded from MFA, or one human login whose session is reused. |
| One service tested alone | A mock token issuer. The service's real validation still runs. |

#### Problem 2: knowing what should happen

Measure it. For each endpoint and each identity, send the request and record the result. The running system has already combined every layer, so the "one layer overrides another" problem disappears. Nobody has to model it.

Naive probing is unreliable. One study measured 71% and 87% error rates when access was judged by response similarity ([BACScan](https://yuanxzhang.github.io/paper/bacscan-ccs25.pdf)). NestJS answers 403 where Spring answers 401, some APIs answer 404 to hide a resource, and a bad body can return 400 before the auth check runs.

Static analysis fixes exactly these problems, and this becomes its job:

- The list of endpoints and a valid request for each, so the call gets past validation.
- Which endpoints change data, so probing stays read-only by default.
- Each framework's response conventions, which is a small data table and fits a pack.
- Three calls per cell, compared: no credential, an identity expected to pass, one expected to fail.

#### Problem 3: explaining why

Keep reading the rules from code, but change what the result means. It becomes a prediction and an explanation. When prediction and measurement disagree, either the analyzer is wrong, which feeds learn mode, or the system is misconfigured, which is a security finding.

#### Combining services that differ

Join on the test identity, not on role names. One service says `ROLE_ADMIN`, another uses a scope, a third a group. The profile maps "admin" to each. The result is one table of endpoint by identity for the whole system, which is what a test generator needs.

#### So, a separate service?

Yes, two small ones, both outside the analyzer because the analyzer must run with no secrets:

- **The credential broker.**
- **An access prober**, which writes observed-access records. It fits the runtime evidence lane already in the design.

#### Limits

- A person supplies test identities and secrets once per system.
- A measurement holds for the identities tried, in that environment, at that time.
- Object-level checks need data set up first, so they come later.
- The measured result is what the system does. What it should do still comes from a person or a spec.

This reverses my last answer, where tests came seventh. I would now build the profile, broker and prober first.

## Item 086. Owner

One of the reason we need it, by utilizing the tool, if we want to create test cases, we need to impersonate different access control, roles, user to make sure everything works for everyone. and it doesn't break. For i.e. with request all it needed to do different auth token (in most cases) to verify all these. So, will that be supported with our system. 

It can work on multiple ways, 1. the auth can be generated separately or 2. each auth may need to produce the token on the fly in a situation like testing an endpoint for all the roles exist to verify a user only see what they are allowed to see

## Item 088. Answer

I reloaded the writing rules. Here is the answer.

Yes, the design supports both ways, and they are one mechanism run at different times. None of it is built. Today wadi cannot make or hand out a token.

#### The rule that makes both work

A test names an identity, such as "admin" or "customer B". It never contains a token. Each identity has a recipe that produces its credential, and the credential broker runs the recipe.

| Your two ways | When the recipe runs | Where it fits |
|---|---|---|
| Generated separately | Once before the run, per identity | Test suites in CI. SSO with MFA, where a person logs in once and the broker reuses the session. Logins that are slow or rate-limited. |
| On the fly | At the moment of the request, cached until the token expires | An agent trying one endpoint against every identity. Long runs where tokens expire. |

#### Testing every role that exists

How the broker makes a token depends on what the test runs against.

| Test runs against | How the identity is set | Any role without a test user | What the test proves |
|---|---|---|---|
| One service, inside its own test process | The framework's test support, such as Spring's `@WithMockUser`. No token. | Yes | The service's own rules |
| One service running alone | A mock issuer signs a token with the claims the test asks for | Yes | The service's token validation and its rules |
| The whole system in a test environment | Real login as a test user | No, one test user per identity | The whole path, gateway included |

The second row is your "on the fly for all roles" case. The analyzer supplies the list of roles each service checks, so the generator knows which ones to try.

#### Where a token is not enough

- **Roles stored in the application's database.** The token carries only a user id, so the recipe needs a setup step that creates the user with that role.
- **Sessions and opaque tokens.** A mock issuer cannot produce them. They need a real login.
- **"A user sees only their own data."** This needs two identities with the same role, and data that each one owns. The analyzer can mark which endpoints take a record id, so the generator knows where this test applies.

#### What an agent gets

- **For each endpoint.** The identities, the expected result for each, and whether wadi measured that result or read it from code.
- **A send-as call.** The agent says "send this request as admin" and the broker attaches the credential. The agent never holds a secret.
- **For tests saved in a repository.** A small helper that turns an identity name into a token at run time. The same test then runs locally with the mock issuer and in staging with real login.

#### Limits

- The system owner supplies test users and secrets once. Mock issuer mode needs only a test configuration in the service.
- A mock token can carry role combinations the real identity provider would never issue. To prevent that, I would record the claim layout of one real token per identity and have mock tokens copy it. That is my proposal, not an existing practice I found.
- A key that a service trusts can produce any identity. A production deployment must never trust the mock issuer.

#### Decision for you

Which level comes first. I recommend one service running alone with the mock issuer. It needs nothing from the system owner and gives every role on the fly. Whole-system login would follow.

The architecture page does not include any auth design yet.

## Item 089. Owner

with the auth module in mind, how the architecture will change?

## Item 092. Answer

The auth module adds two services and one data file to the architecture, and it changes what the existing readers are responsible for. I added it to the architecture page as a new "Identity and access" section: https://claude.ai/artifact/AvjQASWRX8YVTHUH6QV6Kj

The page is still public, so anyone with the link now sees this version.

#### What is new

| Piece | Kind | What it does |
|---|---|---|
| Identity profile | Data | Lists the test identities of a system, a recipe to log in as each, and the roles each has in each service. Wadi drafts it and a person confirms it. |
| Credential broker | Service | Turns an identity name into a credential and attaches it to a test request. It is the only part that reads secrets. |
| Access prober | Service | Calls each endpoint as each identity, through the broker, and stores what the system answered. |

#### What changes in existing parts

- **Access records.** Wadi stores one record per place a rule lives (code, gateway, mesh, spec). Today it stores one verdict per endpoint.
- **Static analyzer.** Its access result becomes a prediction with its reason. It also supplies the roles each service checks and a valid request for each endpoint.
- **Config reader and declared reader.** They also read access rules at the gateway and mesh, and the security part of each spec.
- **Shared keys.** Identity becomes a key, so services that name their roles differently still join.
- **Fold.** It builds the access table, one cell per endpoint and identity, with the answer as read and the answer as measured.
- **MCP server.** It gets two more read-only tools, for the identities and the access table.
- **Stitcher.** Each call edge also records whether the caller passes the user's identity on.
- **Bundles.** They carry the access rules and role mapping, and never a recipe or a secret.
- **Direct connections.** There was one, from the worker to Joern. The prober sending requests through the broker is a second.

#### What stays the same

Analysis still runs with no secret and no API key. Bundle export and import, the learn loop, Joern and the storage design do not change.

#### On the page

- A new diagram shows how the profile, broker, prober and access table connect.
- The process diagram has the two new services.
- The fourth evidence column is now "A running system", read by the prober first and the trace importer later.
- The build order has the profile and broker at step 3, the prober at step 4 and real login for a whole system at step 9.

Decision for you: I placed the auth steps before bundle import because test generation depends on them. If the hub matters more to you right now, they can move after step 5 without changing anything else.

## Item 093. Owner

where is the auth moddule?

(The owner attached a screenshot of the main figure.)

## Item 096. Answer

The auth module is now in the main figure, as the "Identity and access" panel on the right. Reload the page to see it: https://claude.ai/artifact/AvjQASWRX8YVTHUH6QV6Kj

(Image shown in the chat, not stored: Main figure with the identity and access panel)

In the figure you screenshotted, the module was hidden inside the "Runtime readers" box, and the rest of it sat in a separate section further down. That was the wrong place for it.

The panel holds five boxes:

- **A running system.** Your test environment, which is the evidence this module reads.
- **Access prober.** It calls each endpoint as each test identity.
- **Access as measured.** The prober's records, which go into the fold like every other reader's records.
- **Credential broker.** It logs in as a named identity for each test request, and nothing else reads secrets.
- **Identity profile.** The test identities and a login recipe for each.

Two arrows connect the panel to the rest:

- **Access as measured to the fold.** Measured access joins the rules wadi read from code.
- **Coding agents to the credential broker.** An agent sends a test request as an identity, and the broker adds the login.

To fit the panel I narrowed the other columns, and the trace importer no longer has its own column. It is still in the table of pieces and the build order as "later".

The "Identity and access" section lower on the page still has the detailed diagram, with the secret store, the identity provider and the system owner.
