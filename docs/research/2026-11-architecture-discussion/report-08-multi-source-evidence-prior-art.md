# Report 08: How other systems hold facts from several sources

Research report 08 of the architecture discussion of 2026-11-16 and 2026-11-17. A research
agent wrote it for that discussion. The text below is the report as delivered, unedited.
The report's own markers say how each source was checked. The plan document that uses it is
`target-architecture-plan.md` and `bundle-import-and-hub-plan.md` in `docs/`. See `README.md` in this folder.

---

## How existing systems represent facts from several independent sources

## Short answer

Three shapes recur, and the entity identity key is the fixed part in every system I read.

- **Separate records per source, combined at read time.** SARIF runs, in-toto attestations, DataHub aspects, Backstage provider buckets, Otterize and Glean stacks work this way.
- **One statement per claim, all kept, with a rank.** Wikidata is the example.
- **One value per field, plus a record of who owns the field.** Kubernetes server-side apply is the example.

A single merged graph with no source tags was enough where sources state facts that do not overlap (Kythe, Cartography). The systems that store one value and rank sources at write time (ServiceNow, DataHub lineage) are the ones whose own docs describe overwrites.

**Marking.** A bracketed number means I opened that page in this session and the claim comes from it. "Recalled" means memory only. Most pages came through a fetch tool that returns extracts, so quotes are as it returned them. I read SARIF, the CycloneDX schema and `scip.proto` directly from the downloaded text.

## Comparison table

| System | Model shape | Conflict rule | Scoping (version, environment, time) | Adding a source, and what stays fixed |
|---|---|---|---|---|
| Kythe | One graph of entries, each a source, edge kind, target, fact name and value. Stores combine by set union. The entry has no field naming the tool that wrote it [1]. | None. A write replaces an entry with the same key, and tools "should avoid producing entries with conflicting data" [1]. | No version or time. The doc only says a "Branch or Client label" could be added later [1]. | A new indexer emits entries in the shared schema [2]. The node name and entry shape stay fixed [1]. |
| Glean | Typed facts in per-language schemas, with derived predicates "similar to SQL views" as the common layer [3]. Incremental indexes are stacked immutable databases, where a layer can add or hide facts below it [3]. | The pages read define none. A stack decides visibility by per-fact ownership sets [4]. | One database per name and hash, where the hash "can be the revision of the repository" [5]. | A new schema and indexer. The derived-predicate step for the common view is recalled. |
| SCIP, LSIF, Sourcegraph | One index file per indexer run. Symbols are strings made of scheme, package manager, package name, version and descriptors [7]. | Fixed precedence at read time. Precise results are used "whenever available" and search-based ones "as a fallback" [8]. | The package version is inside the symbol string [7]. Sourcegraph maps each commit to the uploads that can answer for it [9]. | A new indexer with its own scheme. The symbol grammar stays fixed [7]. |
| Backstage catalog | One stored entity per reference. Each provider owns "a private bucket", and "no two providers can try to output the same entity" [10]. | No field merge. A location key decides which writer may replace an entity, to prevent "rogue" takeovers [11]. | None in the identity. Orphaned entities are annotated and removed by default [10]. | A new entity provider with a stable name, or a processor that enriches [11]. Kind, namespace and name are the primary key [12]. |
| DataHub | Entity URN plus aspects. An aspect is "the smallest atomic unit of write" [13]. UI edits live in separate `editable*` aspects [14]. | A write replaces the whole aspect (recalled). The editable split exists "to avoid accidental overwrites" [14]. Lineage has no split and "may conflict" [15]. | Environment is part of the dataset URN [14]. Versioned aspects have a numeric version and timeseries aspects a timestamp [13]. | A new ingestion source emits existing aspects. A new aspect needs a schema and a registry entry [13]. |
| ServiceNow CMDB (vendor docs) | One record per item and one value per attribute. CMDB 360 adds a store of each source's proposed values [17]. | A rule engine. Static rules rank sources per class and attribute. Dynamic rules pick "the largest or most reported value" [17]. | Data refresh rules mark an item stale per source, so a lower-priority source may update it [17]. | Register the source and place it in the rule order. Identification rules define identity (recalled). |
| OpenLineage, Marquez | Events about runs, jobs and datasets, identified by namespace and name [21]. Metadata attaches as named facets [18]. | A new facet with the same name "replaces the previous facet instance for that entity entirely" [18]. | Static facets "apply to an entity until a new version of the same facet is produced" [19]. Marquez versions datasets and jobs (recalled). | A custom facet with a project prefix and an immutable schema URL [18]. |
| Wikidata | One statement per claimed value, with qualifiers, references and a rank [23]. | Keep all values. The default read takes preferred rank, else normal. Deprecated is never used unless requested [22]. | Qualifiers for start time, end time and point in time [22][23]. | Add a reference or another statement. No schema change. |
| W3C PROV | A vocabulary for interchange "in heterogeneous environments" [25]. | The overview does not address conflicting accounts [25]. | Bundles let provenance describe provenance (recalled beyond the mention in [25]). | "Extensibility points" [25]. |
| SARIF, GitHub code scanning | A log holds runs, and "a run object describes a single run of an analysis tool" [26]. Nothing merges across tools. | Keep separate. "Each configuration of code scanning generates a unique set of alerts", and an alert "may display different statuses from different configurations" [27]. | Run category and id, plus first and last detection times [26]. | A new tool is a new run. Property bags hold extras [26]. |
| CycloneDX, SPDX | One component with evidence attached. Each identity field has a confidence, a concluded value, methods with technique and confidence, and tools [29]. SPDX keeps declared, concluded and found-in-files licenses as three fields [30]. | The producer concludes one value and keeps the evidence. SPDX asks for a written explanation when concluded differs from declared [30]. | Per document (recalled). | A new tool or method entry. The technique list is a fixed enum that includes "other" [29]. |
| OpenVEX | A document of statements with product, vulnerability, status, author and timestamp [31]. | Within one author, "a sequence of statements, each overriding, but also enriching the previous ones". The spec does not address authors who disagree [31]. | Product identifiers and timestamps [31]. | Another document from another author. |
| in-toto, SLSA | A signed envelope around a statement that binds subject digests to a predicate type URI [32][49]. Each attestation stands alone. | None in the format. The consumer's policy engine decides. Processing several attestations is a TODO in the validation doc [33]. | "Subject artifacts are matched purely by digest" [32]. | A new predicate type URI. Envelope and statement stay fixed [49]. |
| Dynatrace Smartscape on Grail (vendor docs) | Nodes with typed ids, updated by partial upserts. Static edges are "mostly based on configuration". Dynamic edges are "based on monitoring signals" [36]. | Not documented. Partial upserts suggest the last writer per field wins (my inference). | `lifetime.start` and `lifetime.end` on nodes, with 35-day retention. Dynamic edges are recorded per point in time [36]. | A custom node type with id components, sent through the ingest pipeline [36]. |
| Datadog Software Catalog (vendor docs) | Rows come from telemetry discovery and from YAML definitions, joined on name [38]. Inferred services come from callers' span attributes [39]. | Definitions "are the canonical source of truth" [38]. The pages read do not document merge rules. | Not stated on the pages read. | Imports from Backstage or ServiceNow [38], custom kinds and an `extensions` block [40]. |
| Kiali | An observed graph built from Istio telemetry, decorated with Istio configuration [41][42]. | None. Config validation errors are a separate list [42]. | A query time window. Idle edges "previously had traffic, but not during the requested time period" [42]. | Not examined. |
| Otterize (vendor docs) | Two record kinds side by side. Discovered intents come from the network mapper, and declared ones are `ClientIntents` [43]. | No merge. The comparison shows which calls "would be blocked or allowed" [43]. | A cluster map with history in the hosted product [44]. | Not examined. |
| Kubernetes server-side apply | One object and one value per field. `managedFields` lists each manager's fields, operation, API version and time [45]. | A conflict is an error unless the writer forces. Writers that set the same value share the field [45]. | Per-manager time and API version [45]. `spec` and `status` split desired from observed, linked by `observedGeneration` [47]. | Any new manager name. The schema's merge markers stay fixed [45]. |
| Cartography (added) | One graph. Modules `MERGE` on a shared id, and it is "encouraged" for more than one module to modify the same node type [48]. | Last writer per property (my inference from `MERGE`). | Every node and relationship gets `lastupdated` and `firstseen` [48]. | A new module with its own schema objects [48]. |

## Lessons

1. **Identity fails before the fact model does.**
   - OpenLineage warns that the legacy Snowflake name format "forces dataset IDs that won't match", and that after a switch "existing lineage nodes won't connect to new ones" [21].
   - Datadog requires that a definition's name "must exactly match the primary identifier from the telemetry data" [38].
   - A Backstage maintainer called the entity key "an unavoidable limitation". Of two identity systems he said "there's no existing edge between them" [12].
   - SCIP replaced LSIF's "opaque ID numbers" with string symbols, because global ids made it hard to update part of an index [6].

2. **Ranking sources at write time discards the losing value.**
   - ServiceNow states that "without reconciliation rules, discovery sources can overwrite each other's updates" [17].
   - Its CMDB 360 feature stores each source's proposed values, so an administrator can revert one source and recompute [17].
   - DataHub warns that manual and programmatic lineage can cause "unwanted overwrites" [15].
   - The figure that 75% of CMDB projects fail on data quality reached me only through vendor blogs. I could not verify it.

3. **One write domain per kind of source was enough for several systems.**
   - DataHub keeps UI edits in `editable*` aspects so ingestion cannot erase them [14].
   - Kubernetes gives users `spec` and controllers `status` [47].
   - Backstage gives each provider a bucket [10].
   - The cost is that two sources cannot contribute to one Backstage entity. The maintainer's answer was "you really would have to do that merging 'outside' anyway" [12], and stitching "cannot be modified or extended" [10].

4. **Per-field ownership depends on the schema declaring merge granularity (Kubernetes).**
   - Custom resources default to atomic lists [45].
   - After a list changes from atomic to keyed, the server "is unable to infer the new ownership" [45].
   - Ownership is not tracked correctly on some sub-resources [45].
   - Dropping `replicas` before the autoscaler claims it resets the value to 1 [45].
   - Controllers are told to "always force conflicts" [45], so conflict detection mainly serves people and CI systems [46].

5. **A rich store can still have a simple default read (Wikidata).**
   - The RDF export has a "truthy" form with only best-rank values and no qualifiers or references. It says "for many queries simple values will be enough" [24].
   - The maintainers also wrote rules against misuse. Deprecated rank "does not apply to correct historical information", which takes time qualifiers. Ranks "are not a way of asserting your view for a disputed value" [22].

6. **Systems that show declared beside observed keep two record kinds and present a difference.**
   - Otterize compares discovered with declared intents to show what "would be blocked", and calls discovered calls only "presumably" intended [43].
   - SPDX holds declared, concluded and found-in-files licenses as separate fields [30]. CycloneDX adds observed licenses as evidence [29].
   - Smartscape gives static and dynamic edges different time semantics [36].
   - DataHub marks manual lineage edges with the editor's avatar [16].
   - OpenLineage's experimental proposal uses precedence instead. A lineage facet, when present, "is the authoritative picture" [20].
   - Observed data is bounded by a window. Smartscape Classic shows 72 hours [37], and Kiali omits edges with no traffic in the period [42].

7. **Evidence formats avoid reconciliation and leave it to the reader.**
   - SARIF keeps one run per tool [26], and GitHub lets one alert hold different statuses per configuration [27].
   - in-toto validates one attestation at a time [33].
   - SLSA says "provenance doesn't do anything unless somebody inspects it" [34]. That page is marked retired in favour of v1.2.
   - GUAC says conflicting reports "should be flagged as something to be analyzed further" [35].
   - Matching across runs still needs a stable key. Without fingerprints "users may see duplicate alerts" [28].

8. **Retracting a fact needs per-source bookkeeping.**
   - Cartography stamps each node and relationship with the run's update tag. It deletes what the run did not touch, scoped to the sub-resource being synced [48].
   - DataHub's `incremental_lineage` avoids overwrites, but then "lineage edges that used to exist will not be removed" [15].
   - Smartscape notes that "removing a field from the Smartscape event does not remove it from the node" [36].
   - Glean's fact ownership "requires O(facts) time" and space, and incremental derivation on stacks was not implemented when the page was written [4].
   - OpenLineage listed facet deletion as open work [19].

## What I could not verify

- The Marquez data model page returned 404, so its versioning is recalled.
- The ServiceNow CMDB 360 page did not render. Its claims come from the reconciliation rules page [17].
- Kiali's "Idle Nodes" option appeared only in search snippets.
- I could not open the results of the paper comparing RDF reification options for Wikidata.
- The Datadog pages I read do not say which source wins on a field conflict.

## Sources

1. https://kythe.io/docs/kythe-storage.html
2. https://kythe.io/docs/kythe-overview.html
3. https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/
4. https://glean.software/docs/implementation/incrementality/
5. https://glean.software/docs/databases/
6. https://sourcegraph.com/blog/announcing-scip (vendor)
7. https://github.com/sourcegraph/scip/blob/main/scip.proto
8. https://sourcegraph.com/docs/code-navigation/precise-code-navigation (vendor)
9. https://sourcegraph.com/docs/code-navigation/explanations/uploads (vendor)
10. https://backstage.io/docs/features/software-catalog/life-of-an-entity
11. https://backstage.io/docs/features/software-catalog/external-integrations/entity-providers
12. https://github.com/backstage/backstage/issues/11406
13. https://docs.datahub.com/docs/metadata-modeling/metadata-model
14. https://docs.datahub.com/docs/generated/metamodel/entities/dataset
15. https://docs.datahub.com/docs/features/feature-guides/lineage
16. https://docs.datahub.com/docs/features/feature-guides/ui-lineage
17. https://www.servicenow.com/docs/r/xanadu/servicenow-platform/configuration-management-database-cmdb/r_ReconciliationRulesPrinciples.html (vendor)
18. https://openlineage.io/docs/spec/facets/
19. https://openlineage.io/blog/static-lineage/
20. https://openlineage.io/blog/explicit-lineage
21. https://openlineage.io/docs/spec/naming
22. https://www.wikidata.org/wiki/Help:Ranking
23. https://www.wikidata.org/wiki/Help:Statements
24. https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format
25. https://www.w3.org/TR/prov-overview/
26. https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html
27. https://docs.github.com/en/code-security/code-scanning/managing-code-scanning-alerts/about-code-scanning-alerts
28. https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning
29. https://github.com/CycloneDX/specification/blob/master/schema/bom-1.6.schema.json
30. https://spdx.github.io/spdx-spec/v2.3.1/package-information/
31. https://github.com/openvex/spec/blob/main/OPENVEX-SPEC.md
32. https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md
33. https://github.com/in-toto/attestation/blob/main/docs/validation.md
34. https://slsa.dev/spec/v1.0/verifying-artifacts
35. https://docs.guac.sh/guac/guac-ontology/
36. https://docs.dynatrace.com/docs/platform/grail/smartscape-on-grail (vendor)
37. https://docs.dynatrace.com/docs/discover-dynatrace/platform/smartscape (vendor)
38. https://docs.datadoghq.com/internal_developer_portal/software_catalog/set_up/ (vendor)
39. https://docs.datadoghq.com/tracing/services/inferred_services/ (vendor)
40. https://docs.datadoghq.com/internal_developer_portal/software_catalog/entity_model/ (vendor)
41. https://kiali.io/docs/features/topology/
42. https://kiali.io/docs/faq/graph/
43. https://docs.otterize.com/reference/shadow-vs-active-enforcement (vendor)
44. https://docs.otterize.com/features/network-mapping-network-policies (vendor)
45. https://kubernetes.io/docs/reference/using-api/server-side-apply/
46. https://kubernetes.io/blog/2022/10/20/advanced-server-side-apply/
47. https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md
48. https://docs.cartography.dev/dev/writing-intel-modules.html
49. https://github.com/in-toto/attestation/blob/main/spec/README.md
