# Report 07: Runtime evidence and join keys

Research report 07 of the architecture discussion of 2026-11-16 and 2026-11-17. A research
agent wrote it for that discussion. The text below is the report as delivered, unedited.
The report's own markers say how each source was checked. The plan document that uses it is
`target-architecture-plan.md` in `docs/`. See `README.md` in this folder.

---

Markers: **(O)** opened and read in this session; **(R)** recalled, not opened; **(S)** seen only in a search summary; **(V)** vendor's own claim. Semantic conventions were read at v1.45.0, released 2 November 2026 (O). Six sources were read as full text (the Java agent's instrumentation list and five papers); the rest came through a fetch tool that returns an extract, so quoted phrases are from that extract.

## 1. Runtime evidence sources

| Source | Granularity | Join key | Format | Cost |
|---|---|---|---|---|
| Distributed traces (OpenTelemetry, Jaeger, Zipkin) | Service edge and endpoint per sampled request; method only where a span exists; no line | `service.name` + `http.request.method` + `http.route`; `db.collection.name`; `messaging.destination.name` (O) | OTLP protobuf or JSON over gRPC 4317 / HTTP 4318 (O); Jaeger and Zipkin JSON (R) | Agent or SDK in every process. OTel SDK default sampler is `parentbased_always_on`; Jaeger's remote-sampling fallback is 0.1% (O) |
| eBPF auto-instrumentation (OBI, formerly Beyla; Pixie; Hubble; Odigos) | Service edge; endpoint by raw path, with the route inferred heuristically by default (O) | Process or workload name; method + path | OBI exports OTLP spans, RED and service-graph metrics (O); Hubble flow JSON, Pixie in-cluster tables (R) | No code change. Kernel 5.8+ with BTF, root or capabilities (O). Trace context breaks at L7 proxies and encrypted HTTP/2 (O). Pixie captures "full-body messages" (O). Hubble needs an L7 network policy (O). Odigos is (R); its docs were behind a sign-in |
| Service mesh (Envoy access log, Istio metrics, Kiali) | Service edge from metrics; raw path per request from access logs | Kubernetes workload and service names; raw path. Istio standard metrics have no path, route or method label (O) | Prometheus metrics; text or JSON access logs (O) | Needs a mesh. Kiali shows per-operation nodes only after Istio request classification is configured (O) |
| Gateway and web server access logs | Externally exposed endpoint by raw path | Method + raw path; nginx `combined` logs `"$request" $status` and has no route variable (O) | Text or JSON lines | Usually already collected. Sees only traffic that crosses the gateway |
| Traffic capture and API discovery (APIClarity and similar) | Endpoint plus parameter and payload shape | Inferred path template + method + host | Reconstructed OpenAPI, diffed against a supplied spec to flag "shadow" and "zombie" APIs (O) | Captures payloads, so the highest privacy exposure. APIClarity was archived in May 2026 (O) |
| Runtime coverage (JaCoCo, coverage.py, V8, Go `-cover`) | Line and branch, per process, not per request | Class + method + line of the identical build; file path | JaCoCo `.exec` or TCP dump from a live JVM; coverage.py SQLite; V8 JSON; Go `GOCOVERDIR` files (O) | Instrumented run. JaCoCo calls its overhead "small" (O). Go loses the data on a panic (O) |
| Continuous profilers | Function and line, statistical, so hot code only | Function name + file + line (R); samples can carry a trace ID (O) | pprof, JFR (R); OTLP profiles, Alpha (O) | Designed for low overhead (O); cold paths are rarely sampled (R) |
| Database query logs | Table and statement per database user, not per endpoint | Table name; database user. `pg_stat_statements` has no client or application column (O) | SQL view or log lines | Needs a preload and restart; keeps 5,000 statements by default and evicts the least executed (O) |
| Broker metadata (consumer groups) | Consumer service to topic edge; producers are not listed (R) | Topic name, group ID, client ID (R) | Admin API output (R) | Read-only admin access; no payloads (R) |
| Kubernetes API state | Deployed instance, version and environment; no traffic | OTel guidance derives `service.name` from `app.kubernetes.io/instance`, then `/name`, then the deployment name, and `service.version` from the image `&lt;tag&gt;@&lt;digest&gt;` (O) | JSON | Read-only RBAC |

## 2. What a static model must record now so runtime evidence can join later

1. **Method and route template per endpoint, including the application root, kept matchable against a raw path.**
   - `http.route` and `http.request.method` are Stable. The route "SHOULD include the application root", and the URI path must never stand in for it (O).
   - The Java agent lists route support in 53 of its 257 modules, including Spring WebMVC, WebFlux and Cloud Gateway (O).
   - Flask sets it from the URL rule (O).
   - Express sets it, but catch-all, 404 and nested-router values were wrong until late 2025, and the reporter says the fix is incomplete (O).
   - Go's `otelhttp` sets it only since contrib v1.36.0, and only when `Request.Pattern` is set (O).
   - Mesh, gateway and default eBPF sources supply raw paths only (O).

2. **Every name a service runs under.** `service.name` and `service.namespace` are Stable (O). The Java agent takes the name from `spring.application.name` (O), Kubernetes-derived names come from labels or the deployment (O), and Istio identifies workloads and service hosts (O).

3. **Commit, repository URL, build identity and environment per snapshot.**
   - `vcs.ref.head.revision` and `vcs.repository.url.full` are Release Candidate (O). I found no auto-instrumentation that sets them; Datadog's documentation asks OpenTelemetry users to set those two (O, V).
   - `service.version` is Stable but its format is undefined (O).
   - `deployment.environment.name` has been Stable since v1.41.0 and explicitly does not change service identity (O).

4. **Runtime-native method name, repo-relative file and line range for each node.**
   - `code.function.name`, `code.file.path` and `code.line.number` are Stable (O).
   - The Java agent emits only `code.function.name`, in 33 modules. Spring Data repository calls get such a span by default; Spring controller spans are off by default (O).
   - File and line appear only on log records, behind an opt-in flag (O).
   - I found no `code.*` span attributes from Python, Node or Go auto-instrumentation (R).
   - Line evidence therefore comes from coverage and profilers.

5. **The declaring method behind lambdas, anonymous classes and proxies.** The convention's own lambda example is `com.mycompany.Main$$Lambda/0x0000748ae4149c00.myMethod` (O). A CGLIB proxy is "a runtime-generated subclass of the target type" (O).

6. **The configured target of each outbound call: host, discovery name and path template.**
   - `peer.service` is deprecated. Its successor `service.peer.name` was deprecated in v1.45.0 for `server.service.name`, which is Development (O).
   - The Java agent fills it only from an operator-supplied mapping that is empty by default (O).
   - Client-side `url.template` is Development, opt-in and "not usually available on HTTP clients" (O).
   - A client span therefore reliably carries only `server.address`, port and `url.full`.

7. **Topic names and consumer group IDs.** Every `messaging.*` attribute is still Development, and `messaging.system` became `messaging.system.name` in v1.45.0 (O). The Java agent already emits `messaging.destination.name` and `messaging.consumer.group.name` (O).

8. **Physical table or collection name and database name per entity.** `db.collection.name`, `db.namespace`, `db.system.name` and `db.query.summary` are Stable, and the collection name is not to be parsed from query text (O).

9. **The gateway route table: external path to service and rewritten path.** In the TrainTicket study, 52 of 171 observed endpoints were gateway calls absent from the static endpoint list (O).

## 3. Joining problems, ranked by severity

The ordering is my judgement from the evidence.

1. **Sampling and unexercised behaviour.**
   - Jaeger's fallback is 0.1%, and one Meta profile samples 0.01% (O).
   - An 11-test E2E suite reached 119 of 262 TrainTicket endpoints, 45.4% (O).
   - Public corpora plus manual inputs plus fuzzing covered 12–65% of branches in four Java programs (O).
   - Five minutes of random input covered a mean 8% of methods across 1,000 Android apps (O).
   - Helm et al. prove that precision measured against a dynamic baseline is only a lower bound (O), so runtime silence cannot refute a static fact.

2. **Version skew.**
   - JaCoCo matches only byte-identical class files and reports a mismatched class as 0% covered (O).
   - Different compilers, compiler settings, AspectJ and runtime-modifying frameworks all change the class ID (O).
   - Meta saw 180,000 new service IDs in 22 months, 89.7% of them later deprecated (O).
   - Severity is highest for line joins and lower for endpoints and edges; that part is my inference.

3. **Raw path versus route template.** Envoy, nginx and Istio carry no template (O). The TrainTicket authors needed signature matching because traces hold argument values where static analysis holds parameters (O).

4. **Gateway rewrites.** The 52-of-171 result applies here too. Envoy logs `X-ENVOY-ORIGINAL-PATH` and falls back to `:PATH` (O), so gateway and service can log different paths for one request.

5. **Lost context across async boundaries.**
   - Messaging conventions link producer and consumer spans by default; parent-child is optional and limited to single-message cases (O).
   - The Java agent's design note admits executor propagation can join unrelated requests into one trace lasting hours (O).
   - At Meta, 80% of ranking-service call paths that reach depth 3 end in inferred nodes (O).
   - This damages attribution of an edge to an endpoint more than the edge itself.

6. **Proxy and generated classes.** Self-invocation bypasses proxy advice (O), so a statically drawn advice edge may never run. JaCoCo excludes classes with no source location by default (O).

7. **High-cardinality paths.** OBI calls its heuristic "best effort" that "may still lead to cardinality explosion" (O). Its `low-cardinality` mode wildcards a segment after a cap, which could merge distinct routes (my inference). A static template set removes most of this (my inference).

## Prior art, 2020–2026

- **Call graph recall.**
  - Sui et al. (ICSE 2020) measured median static recall of 0.884 against test-derived oracles, and 0.935 with dynamic-feature support (O).
  - Helm et al. (ISSTA 2024) found 0-CFA edge recall of 30–58% on Batik, and an empty graph for Xerces from one reflective call (O).
  - Samhi et al. (ISSTA 2024) found 13 Android tools missed 61% of executed methods on average (O).
  - PyCG reports 99.2% precision and 69.9% recall (O).
- **Designs that worked.**
  - Feeding dynamic facts into static analysis raised JavaScript call-graph recall from 75.9% to 88.1% with negligible precision loss (O).
  - Meta's dead-code system adds runtime endpoint usage to a static dependency graph. It has deleted over 100 million lines, though wrong deletions have reached production (O, self-reported).
- **Microservices.**
  - Nine static recovery tools on 17 applications: the best reached F1 0.86, connection recall 0.83 and endpoint recall 0.68; a four-tool combination reached 0.91 (O).
  - Cerny and Taibi state that dynamic artefacts "can only be as complete as the underlying systems tests", while "only dynamic analysis can recognize inter-service communication with perfect precision" (O).
  - I did not find a study that measures static edges against trace-derived edges on one system.
- **Industry.** Sysdig reports that 15% of fixable critical and high vulnerabilities sit in packages loaded at runtime (O, V).

## Ingestion

- **Live versus file.** OTLP is Stable for traces, metrics and logs, and Development for profiles (O). The OTLP file format is JSON Lines with one signal per file, and its specification is still Development (O).
- **Collector.** The `spanmetrics` and `servicegraph` connectors turn spans into aggregates; both are alpha (O). The service graph needs every span of a request on one collector instance, holds an unpaired span for 2 seconds by default, and still reads `peer.service` (O).
- **Aggregates versus raw spans.** Aggregates drop the per-request path, so they cannot later attribute an edge to an endpoint; raw spans can (my inference).
- **Privacy.** Header capture needs explicit configuration, `db.query.parameter.*` is opt-in, and unparameterised query text should be sanitised (O). Hubble does not redact by default (O). OpenTelemetry warns that hashing a small input space is reversible (O).

## 4. Sources

All opened unless marked.

**OpenTelemetry specifications**
- https://opentelemetry.io/docs/specs/semconv/http/http-spans/
- https://opentelemetry.io/docs/specs/semconv/registry/attributes/http/ (also `/url/`, `/code/`, `/service/`, `/server/`, `/peer/`, `/deployment/`, `/vcs/`, `/messaging/` under the same path)
- https://opentelemetry.io/docs/specs/semconv/registry/entities/vcs/
- https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/
- https://opentelemetry.io/docs/specs/semconv/db/database-spans/
- https://opentelemetry.io/docs/specs/semconv/non-normative/k8s-attributes/
- https://github.com/open-telemetry/semantic-conventions/releases
- https://opentelemetry.io/docs/specs/otlp/
- https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/
- https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/
- https://opentelemetry.io/docs/concepts/signals/profiles/
- https://opentelemetry.io/docs/security/handling-sensitive-data/

**Instrumentation and collectors**
- https://raw.githubusercontent.com/open-telemetry/opentelemetry-java-instrumentation/main/docs/instrumentation-list.yaml (full text)
- https://opentelemetry.io/docs/zero-code/java/agent/disable/
- https://raw.githubusercontent.com/open-telemetry/opentelemetry-java-instrumentation/main/docs/misc/inter-thread-context-propagation.md
- https://github.com/open-telemetry/opentelemetry-js-contrib/issues/1947
- https://app.unpkg.com/@opentelemetry/instrumentation-express@0.68.0/files/README.md
- https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/flask/flask.html
- https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
- https://github.com/open-telemetry/opentelemetry-go-contrib/releases/tag/v1.36.0
- https://opentelemetry.io/docs/zero-code/obi/ (also `/configure/routes-decorator/` and `/distributed-traces/`)
- https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/servicegraphconnector/README.md
- https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/spanmetricsconnector/README.md
- https://www.jaegertracing.io/docs/latest/architecture/sampling/

**Other runtime sources**
- https://docs.px.dev/about-pixie/data-sources/
- https://docs.cilium.io/en/stable/observability/visibility/
- https://istio.io/latest/docs/reference/config/metrics/
- https://www.envoyproxy.io/docs/envoy/latest/configuration/observability/access_log/usage
- https://kiali.io/docs/features/topology/
- https://nginx.org/en/docs/http/ngx_http_log_module.html
- https://github.com/openclarity/apiclarity
- https://www.jacoco.org/jacoco/trunk/doc/classids.html (also `agent.html`, `faq.html`)
- https://coverage.readthedocs.io/en/latest/contexts.html
- https://nodejs.org/api/cli.html
- https://go.dev/doc/build-cover
- https://www.postgresql.org/docs/current/pgstatstatements.html
- https://docs.spring.io/spring-framework/reference/core/aop/proxying.html
- https://docs.datadoghq.com/source_code/service-mapping/ (V)
- https://sysdig.com/press-releases/sysdig-2023-usage-report (V)

**Papers and engineering reports**
- Helm et al., ISSTA 2024 (full text): https://sse.cs.tu-dortmund.de/storages/sse-cs/r/Publications/Preprints/dyncg-issta-2024.pdf
- Samhi et al., ISSTA 2024 (full text): https://homes.cs.washington.edu/~mernst/pubs/callgraph-soundness-issta2024.pdf
- Huye et al., USENIX ATC 2023 (full text): https://www.usenix.org/system/files/atc23-huye.pdf
- Abdelfattah et al., ESOCC 2023 (full text): https://arxiv.org/pdf/2308.09257
- Cerny and Taibi, Dagstuhl OASIcs (full text): https://drops.dagstuhl.de/storage/01oasics/oasics-vol111-microservices2020-2022/OASIcs.Microservices.2020-2022.2/OASIcs.Microservices.2020-2022.2.pdf
- Schneider et al. (first 100,000 characters): https://arxiv.org/html/2412.08352v1
- Sui et al., ICSE 2020 (abstract only): https://2020.icse-conferences.org/details/icse-2020-papers/47/On-the-Recall-of-Static-Call-Graph-Construction-in-Practice
- Laursen et al., PLDI 2024 (abstract only): https://pldi24.sigplan.org/details/pldi-2024-papers/48/Reducing-Static-Analysis-Unsoundness-with-Approximate-Interpretation
- PyCG (abstract only): https://arxiv.org/abs/2103.00587
- Meta dead-code cleanup (self-reported): https://engineering.fb.com/2023/10/24/data-infrastructure/automating-dead-code-cleanup/

**Not opened**
- The extended TrainTicket paper returned 403; its 91.98% API-test endpoint coverage figure is (S) and is not used above: https://www.mdpi.com/2079-9292/13/10/1913
- Odigos documentation was behind a sign-in.
- The Kafka consumer-group documentation redirected, so that table row is (R).
