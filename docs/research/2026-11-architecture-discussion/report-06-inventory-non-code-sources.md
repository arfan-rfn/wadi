# Report 06: Inventory of non-code sources of truth

Research report 06 of the architecture discussion of 2026-11-16 and 2026-11-17. A research
agent wrote it for that discussion. The text below is the report as delivered, unedited.
The report's own markers say how each source was checked. The plan document that uses it is
`target-architecture-plan.md` in `docs/`. See `README.md` in this folder.

---

## Non-code artifacts for a whole-system map: ranked inventory and evidence

**Provenance key.** O: I read the document text or chart myself (PDF extracted locally). F: I opened the page through a fetch tool that returns a model-written extract, so its quotes are second-hand. S: search snippet only, not opened. R: recalled, not opened. V: vendor source.

## Ranked table

| # | Family | Facts | Adoption evidence | Readable from files alone | Priority |
|---|---|---|---|---|---|
| 1 | Kubernetes manifests, Helm, Kustomize, ConfigMaps | a b c d e g h | Kubernetes is in production at 82% of container users (CNCF 2025, n=628, O), but only 28.5% of all developers use it (Stack Overflow 2025, F). Helm is in production at 81% (CNCF 2025, O) and is the preferred packaging for 75%, against 14% for Kustomize (CNCF 2024, O). | Plain YAML reads directly. Helm needs rendering with values that may sit in another repo or in CI. | 1 |
| 2 | Dockerfiles and build config | a c e | 71.1% of developers use Docker (Stack Overflow 2025, F). | High. It joins a code module to the image name a manifest runs. | 1 |
| 3 | Ingress, Gateway API, nginx, other gateways | b c d g | ingress-nginx served "about half of cloud native environments" and was retired in March 2026 (Kubernetes Steering Committee, F, no source given). Envoy is at 33% (CNCF 2025, O). A 95% API gateway figure attributed to F5 is S, V and unverified. | Ingress and HTTPRoute read directly, but ingress-nginx behaviour sits in controller-specific annotations. nginx.conf is a separate grammar. Kong and APISIX often hold routes in a database (R). | 1 for Ingress and Gateway API, 2 for nginx, 4 for the rest |
| 4 | Flyway and Liquibase migrations, schema files | e | I found no survey figure. PostgreSQL is at 55.6% (Stack Overflow 2025, F). | High, and they live in the service repo. They give physical table names that ORM code leaves implicit. | 2 |
| 5 | GitOps (Argo CD, Flux) | a h | Argo is in production at 52% and Flux at 23% (CNCF 2025, O). | High. An Application names the repo path, chart, values files and target namespace, which tells you which Helm values to render with (R). | 2 |
| 6 | Terraform and CloudFormation, including ECS, Lambda, Cloud Run, queues, API gateways, IAM | a c d e f g h | 17.8% of developers use Terraform (Stack Overflow 2025, F). 71% of AWS and 55% of Google Cloud organisations use some IaC (Datadog 2024, F, V telemetry). Lambda is used by 65% of AWS customers and Cloud Run by 70% of Google Cloud customers (Datadog 2025, F, V). | Medium. It needs module and variable resolution, and often lives in a separate infrastructure repo (R). | 2 |
| 7 | Git-backed config repos (Spring Cloud Config) and server-held config (Nacos, Apollo, Consul KV, Vault) | b e g | No survey figure found. | A git-backed repo reads like the Spring config already supported. The others hold values in a server (R). | 2 for git-backed, 4 for server-held |
| 8 | Istio | b d g | Service mesh in production fell from 50% to 42% (CNCF 2023 to 2024, O). Istio is at 36% (CNCF 2025, O). | High. AuthorizationPolicy and VirtualService are declarative. | 3 |
| 9 | Messaging definitions (Kafka topics, schema registries, RabbitMQ definitions) | e f | Kafka is at 9.4% and RabbitMQ at 10.9% of developers (Stack Overflow 2024, F). Strimzi is at 14% (CNCF 2025, O). | Low. Kafka creates topics on first use by default (Confluent docs, F), so many topics exist only in the broker. | 3 |
| 10 | Policy and identity config (OPA, Kyverno, Keycloak), added | d | OPA 25%, Kyverno 23%, Keycloak 42% (CNCF 2025, O). | Rego is a language. Keycloak realms usually live in its database (R). | 3 |
| 11 | Ownership files (CODEOWNERS, Backstage) | h, plus declared a b e | Backstage is in production at 14% (CNCF 2025 chart, O; the report text says single digit). | High. Backstage requires `owner`, while `dependsOn` and `consumesApis` are optional and hand-written (F). | 3 |
| 12 | CI/CD pipelines | a h | CI/CD in production ranges from 42% to 91% by maturity tier (CNCF 2025, O). | Medium. Shell steps hide the deploy target. | 3 |
| 13 | Observability config (alert rules, SLOs, dashboards) | g h | Prometheus is at 77% (CNCF 2025, O). | Rule files read directly. Dashboards usually live in the tool (R). | 4 |
| 14 | CDK, Pulumi, Nomad, Linkerd, Consul mesh | varies | Pulumi is at 0.9% (Stack Overflow 2024, F) and Linkerd at 11% (CNCF 2025, O). I found no Nomad figure. | CDK and Pulumi are programs, so only their synthesised output is readable. | 4 |
| 15 | Feature flags | conditional b d | OpenFeature is at 2% (CNCF 2025, O). | Flag state lives in the vendor service. | Do not build |

Families the brief missed (R):
- Scheduled jobs and workflow definitions (CronJob, EventBridge, Step Functions) are non-HTTP entry points.
- IAM policies show which service may touch which resource.
- DNS, CDN and WAF rules carry edge enforcement.
- Runtime traces are not files but are the main alternative source for (b). OpenTelemetry is in production at 49% (CNCF 2025, O).

CNCF surveys its own community and Stack Overflow surveys all developers, so the real share lies between the two figures. I could not get tool-level numbers from JetBrains 2025.

## Question 3: prior art

No study I found measures code plus deployment artifacts against code alone. The closest evidence compares tools.

- **Schneider et al. (arXiv 2412.08352, F).** They ran 9 of 13 tools on 17 Java and Spring applications, with 182 components and 385 connections in the ground truth.
  - Attack Graph Generator reads only Docker Compose, MicroDepGraph reads Compose plus Java, and microMiner reads Kubernetes manifests.
  - ContextMap reads pom.xml, RAD reads bytecode, and Prophet and RAD-source read source.
  - Code2DFD reads source and configuration files, and its own paper adds build files and Compose (O).
  - MicroDepGraph and microMiner scored overall precision 0.99 and 0.97, but component recall of 0.76 and 0.56, against 0.98 for Code2DFD.
  - The paper states that 65 components appear in no deployment file.
  - Adding MicroDepGraph to Code2DFD moved connection F1 from 0.87 to 0.89 and added nothing for components.
  - The Kubernetes manifests microMiner ran on were created for the study and added to the dataset.
- **Code2DFD (O).** It takes its service list from build and Docker files and reads names, ports and some flows from bootstrap.yml. It reports precision 0.93 and recall 0.85. MicroDepGraph reached 0.99 and 0.58, and ran on only 10 of the 17 applications because 7 had no Compose file.
- **MiSAR (2018, O).** This was a manual study of 8 systems. The authors write that static recovery was "mainly possible due to the presence of" docker-compose.yml. Without it they would have needed runtime analysis for non-JVM components and external backing services.
- **microMiner (README, F) and MicroART (R).** microMiner takes components from manifests but gets connections by deploying the application and sniffing traffic. MicroART uses Docker runtime data and tcpdump logs.
- **Bakhtin et al. (2023, O).** Of 37 catalogued tools, 19 are static, 13 take source directly, 3 take only deployment files, and 21 target Java. Only 4 had commits in the first half of 2023.
- **2024 to 2026.**
  - ModARO (arXiv 2602.08181, F) reads Compose, Kubernetes, Maven, Gradle and package.json through pluggable extractors. It needed 27 project-specific extractors out of 71 across 10 projects and measured no accuracy.
  - Duarte (arXiv 2502.04188, F) feeds only IaC files to an LLM. One researcher verified 83% of reported patterns, with no recall figure.
  - Liljas et al. (ESEM 2026, F) scored F1 0.604 with a GPT-4o agent reading source on 17 Java applications.
  - IBM's cluster-topology-analyzer (F) infers workload connections from env vars, args and ConfigMaps that name a Service. It requires plain YAML with "no helm-style templating".

## Question 4: what is usually not in git

- **Console-made cloud resources.** At least 38% of AWS organisations made manual console changes in every account within 14 days (Datadog 2024, F, V telemetry). Only 6% of surveyed IaC users report complete coverage (Firefly 2025, F, V).
- **Live replica counts.** 64% of Kubernetes organisations use the Horizontal Pod Autoscaler (Datadog 2025, F, V).
- **Auto-created Kafka topics** (F), and schema registry subjects that producers register at run time (R).
- **Server-held state (R).** This covers gateway routes behind an admin API, config server and Vault values, secret values, feature flag state, and identity provider clients and roles.
- **Deploy-time changes (R).** These are Helm values passed by CI, mutating admission webhooks such as sidecar injection, and operator-generated resources.
- **Other runtime state (R).** Service registry contents, DNS, and dashboards or alert routes edited in a UI.

## Question 5: drift and contradiction

I found no peer-reviewed measurement of how often committed config differs from deployed state.

The available numbers are vendor claims:
- Accurics said over 90% of code-provisioned deployments drift (2020, via CSO Online, F, V, method undefined).
- Firefly said fewer than a third of organisations monitor drift continuously (2025, F, V).
- The Datadog 38% figure is the best-grounded, because it comes from CloudTrail logs.

Evidence on config contradicting behaviour is stronger:
- **Bufalino et al. (arXiv 2506.21134, F).** They installed 287 Helm-packaged open-source applications and compared declarations with runtime.
  - 259 (90%) had at least one of 634 misconfigurations.
  - 188 were container ports open but undeclared, and 67 were ports declared but not open.
  - 32 were Services targeting an unopened or undeclared port.
  - 241 were flagged for lacking network policies, so fact (d) is usually absent from manifests.
- **cDep (FSE 2020 abstract, F).** It found 448 undocumented configuration dependencies across eight systems.
- I found no study that measures how often application config contradicts code in microservice repos.

## What the ranking rests on

Priority 1 families combine high adoption, declarative files, and facts code cannot supply.

The case against over-investing in manifests is also on record. Manifests alone gave low recall and no connections in the Schneider comparison, and their declared ports are often wrong. Every fact read from these files should be published as declared, not as verified live.

Mesh, catalog and feature-flag support have falling or low adoption, or their state is not in files.

The two CNCF text extractions are at a temporary session folder (not stored) and a temporary session folder (not stored).

## Sources

- CNCF Annual Survey 2025 (Jan 2026): https://www.linuxfoundation.org/hubfs/Research%20Reports/CNCF_Annual_Survey_Report_1.15.26.pdf
- CNCF Annual Survey 2024 (Mar 2025): https://www.linuxfoundation.org/hubfs/Research%20Reports/cncf_annual_survey24_031225a.pdf
- Stack Overflow 2025: https://survey.stackoverflow.co/2025/technology
- Stack Overflow 2024: https://survey.stackoverflow.co/2024/technology
- Datadog State of Containers and Serverless 2025: https://www.datadoghq.com/state-of-containers-and-serverless/
- Datadog State of DevSecOps 2024: https://www.datadoghq.com/state-of-devsecops-2024/
- Kubernetes ingress-nginx statement: https://kubernetes.io/blog/2026/01/29/ingress-nginx-statement/
- Schneider et al.: https://arxiv.org/html/2412.08352v1
- Code2DFD: https://arxiv.org/abs/2304.12769
- Bakhtin et al.: https://par.nsf.gov/servlets/purl/10572053
- MiSAR: https://bura.brunel.ac.uk/bitstream/2438/16033/1/Fulltext.pdf
- microMiner: https://github.com/di-unipi-socc/microMiner
- ModARO: https://arxiv.org/html/2602.08181v1
- Duarte: https://arxiv.org/html/2502.04188v1
- Liljas et al.: https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ESEM.2026.62
- Bufalino et al.: https://arxiv.org/abs/2506.21134
- cluster-topology-analyzer: https://github.com/np-guard/cluster-topology-analyzer
- Backstage descriptor format: https://backstage.io/docs/features/software-catalog/descriptor-format
- Confluent broker configs: https://docs.confluent.io/platform/current/installation/configuration/broker-configs.html
- Firefly State of IaC 2025 (vendor): https://firefly.ai/state-of-iac-2025
- Accurics via CSO Online (vendor): https://www.csoonline.com/article/3543878/most-cloud-resources-drift-from-secure-configuration-baseline-after-deployment.html
- cDep: https://2020.esec-fse.org/details/fse-2020-papers/154/Understanding-and-Discovering-Software-Configuration-Dependencies-in-Cloud-and-Datace
