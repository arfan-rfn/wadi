package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** Conformance test (P8) for the Phase 2 two-service fixture: one
  * `runFromSource` per Maven module, exactly as production analyzes each
  * discovered build root. Exercises the §5.2.4 URL slicer's scenario set:
  * config-key resolution, multi-path candidates, and the DB-row NONE trap.
  *
  * Exports land on fixed (gitignored) paths — the Python cross-language
  * golden test reads them.
  */
class PetstoreSystemConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private def moduleExport(module: String): ujson.Value =
    exportFixture(s"petstore-system/$module", s"petstore-system-export/$module")

  private lazy val petstore: ujson.Value  = moduleExport("petstore")
  private lazy val inventory: ujson.Value = moduleExport("inventory")

  private def endpoints(doc: ujson.Value): Set[String] =
    doc("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}").toSet

  private def httpSinks(doc: ujson.Value): Seq[ujson.Value] =
    doc("sinks").arr.toSeq.filter(_("kind").str == "http-client")

  // --- endpoint sets per module ----------------------------------------------------

  test("petstore serves exactly its seventeen controller endpoints") {
    endpoints(petstore) shouldBe Set(
      "GET /pets/{id}",
      "GET /pets",
      // §5.4.2 prefix-expression resolution (2026-08-05). A chained constant
      // is fully determined and must resolve; an ambiguous bare name and a
      // constant declared outside the analyzed source must HOLE. Truncating
      // to the tail — `/pets/list` — is what collapsed two controllers onto
      // one id and destroyed an endpoint.
      "GET /base/chained/pets/list",
      "GET {?}/pets/list",
      "PUT /pets/{id}/reserve/{count}",
      "POST /pets/{id}/alert",
      "GET /pets/summary/{id}",
      // §5.2.7 shape probes (M5).
      "GET /catalog/pets/{id}",
      "GET /catalog/pets",
      "POST /catalog/pets",
      "GET /catalog/tree",
      "GET /catalog/query-shape",
      "GET /catalog/vendor",
      // §5.4.2 endpoint idioms: constant class prefix + one endpoint per
      // multi-path array entry (the yas ApiConstant / storefront+backoffice
      // idioms — CIMET emits raw constant text here; wadi resolves it).
      "GET /admin/pets/summary",
      "GET /admin/pets/report",
      // Nested constant holder (yas Constants.ApiConstant shape).
      "GET /vet/pets/checkups"
    )
  }

  test("feign mappings never count as served endpoints (TrainTicket trap)") {
    endpoints(petstore).exists(_.contains("/api/v1/inventory")) shouldBe false
  }

  test("inventory serves its six endpoints incl. the role-protected one") {
    endpoints(inventory) shouldBe Set(
      "GET /stock/{id}",
      "GET /api/v1/inventory/stock/{id}",
      "GET /api/v1/inventory/reserved/{id}",
      "GET /api/v1/inventory/audit/{id}",
      "POST /admin/restock",
      "PUT /stock/reserve/{id}/{count}"
    )
  }

  test("endpoint params come from mapping annotations (§7 Endpoint.params)") {
    val byUri = petstore("endpoints").arr.map(e => e("uri").str -> e).toMap
    val pathParams = byUri("/pets/{id}")("params").arr
    pathParams.map(p => (p("name").str, p("location").str, p("required").bool)) shouldBe
      Seq(("id", "path", true))
    val queryParams = byUri("/pets")("params").arr
    queryParams.map(p => (p("name").str, p("location").str, p("required").bool)) shouldBe
      Seq(("owner", "query", false))
    val bodyParams = inventory("endpoints").arr
      .find(_("uri").str == "/admin/restock")
      .get("params")
      .arr
    bodyParams.map(p => (p("name").str, p("location").str)) shouldBe Seq(("payload", "body"))
  }

  test("analysis coverage counts production vs reachable methods (§5.4.3, T4-widened)") {
    val petstoreCoverage = petstore("analysis_coverage")
    // T4: the only unreached methods left are genuinely dead code —
    // AuditNotifier.target, OrphanedAuditNotifier.notifyAudit, and
    // LegacyPingProbe.ping (unwired classes). The formerly-unreached
    // framework-invoked pair (AuthForwardingInterceptor.apply +
    // CurrentRequest.bearerToken) is now rooted (`framework-callback`).
    // The denominator grew by the T4 fixture methods AND the lambda body
    // (`NightlySweepJob.<lambda>0` counts — real source; §5.4.3 refinement).
    petstoreCoverage("production_methods").num.toInt shouldBe 56
    petstoreCoverage("reachable_production_methods").num.toInt shouldBe 53

    val inventoryCoverage = inventory("analysis_coverage")
    // SecurityConfig.filterChain is now rooted as a `bean` — inventory walks
    // fully. The empty-bodied StockRepository.restock still counts on both
    // sides: empty concrete methods are production code, only abstract stubs
    // are excluded.
    inventoryCoverage("production_methods").num.toInt shouldBe 10
    inventoryCoverage("reachable_production_methods").num.toInt shouldBe 10
  }

  // --- provider-side wire shapes (§5.2.7, M5) ---------------------------------------

  private def endpointByUri(doc: ujson.Value, verb: String, uri: String): ujson.Value =
    doc("endpoints").arr
      .find(e => e("uri").str == uri && e("http_method").str == verb)
      .get

  test("response shape walks nested DTOs with Jackson wire semantics (M5)") {
    val shape = endpointByUri(petstore, "GET", "/catalog/pets/{id}")("response_schema")
    shape("kind").str shouldBe "object"
    shape("type_name").str shouldBe "PetDetails"
    val fields = shape("fields").arr.map(f => f("name").str)
    // @JsonProperty renames; @JsonIgnore omits (wire contract, not layout).
    fields should contain("display_name")
    fields should not contain "internalNote"
    val renamed = shape("fields").arr.find(_("name").str == "display_name").get
    renamed("java_name").str shouldBe "name"
    val stock = shape("fields").arr.find(_("name").str == "stock").get("shape")
    stock("kind").str shouldBe "object"
    stock("fields").arr.map(_("name").str).toSet shouldBe Set("available", "price")
    val tags = shape("fields").arr.find(_("name").str == "tags").get("shape")
    tags("kind").str shouldBe "array"
    tags("element")("kind").str shouldBe "scalar"
  }

  test("generic wrappers unwrap: ResponseEntity<List<PetDetails>> (M5)") {
    val shape = endpointByUri(petstore, "GET", "/catalog/pets")("response_schema")
    shape("kind").str shouldBe "array"
    shape("element")("kind").str shouldBe "object"
    shape("element")("type_name").str shouldBe "PetDetails"
  }

  test("request body carries its own shape (M5)") {
    val shape = endpointByUri(petstore, "POST", "/catalog/pets")("request_schema")
    shape("kind").str shouldBe "object"
    shape("type_name").str shouldBe "NewPetRequest"
    shape("fields").arr.map(_("name").str).toSet shouldBe Set("name", "breed")
  }

  test("self-referencing DTOs terminate in an explicit cycle node (M5)") {
    val shape = endpointByUri(petstore, "GET", "/catalog/tree")("response_schema")
    val children = shape("fields").arr.find(_("name").str == "children").get("shape")
    children("kind").str shouldBe "array"
    children("element")("kind").str shouldBe "cycle"
    children("element")("type_name").str shouldBe "Category"
  }

  test("off-CPG types are an honest unresolved name, never fabricated fields (M5)") {
    val vendor = endpointByUri(petstore, "GET", "/catalog/vendor")("response_schema")
    vendor("kind").str shouldBe "unresolved"
    vendor("type_name").str shouldBe "VendorInfo"
    vendor.obj.contains("fields") shouldBe false
    // Without the staged union (module-only build) the shared-library DTO is
    // ALSO honestly unresolved here — the e2e proves the union resolves it.
    val query = endpointByUri(petstore, "GET", "/catalog/query-shape")("response_schema")
    query("kind").str shouldBe "unresolved"
  }

  // --- URL slicing scenarios -------------------------------------------------------

  test("RestClient fluent chain is a sink: verb from the root, URL from .uri (T2)") {
    // The yas idiom (§5.4.2): 34 real call sites used to export as a clean
    // zero because no pass modelled the type. Same shape as WebClient.
    val restClientSinks = httpSinks(petstore).filter(s =>
      s.obj.get("mechanism").exists(_.strOpt.contains("restclient"))
    )
    restClientSinks should have size 2 // absolute-template probe + base-bound probe
    val sink = restClientSinks
      .find(_("value").strOpt.contains("${inventory.api.url}/api/v1/inventory/stock/{?}"))
      .get
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
  }

  test("fluent-client base recovery: RestClient.create(base) + relative .uri (T2)") {
    val sink = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("client base <-")))
      .get
    sink("value").str shouldBe "${inventory.api.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("mechanism").str shouldBe "restclient"
  }

  test("unrecoverable client base reports base-undetermined, never a fabricated absolute (T2)") {
    val sink = httpSinks(petstore)
      .find(s => s("value").strOpt.exists(_.startsWith("{?}/mystery")))
      .get
    sink("value").str shouldBe "{?}/mystery/{?}"
    sink("value_confidence").str shouldBe "heuristic"
    sink("evidence").str should include("[base-undetermined]")
  }

  test("declarative @HttpExchange interface is a sink with its declared URL (T2)") {
    val sink = httpSinks(petstore)
      .find(_.obj.get("mechanism").exists(_.strOpt.contains("http-interface")))
      .get
    sink("value").str shouldBe "https://audit.example.com/feed/{id}"
    sink("http_verb").str shouldBe "GET"
    sink("value_confidence").str shouldBe "high"
  }

  test("ternary branches both become candidates (T2, §5.2 over-approximation)") {
    val rows = httpSinks(petstore).filter(s =>
      s("evidence").strOpt.exists(_.contains("ternary "))
    )
    rows.map(_("value").str).toSet shouldBe Set(
      "http://backup-inventory:9091/api/v1/inventory/reserved/{?}",
      "${inventory.api.url}/api/v1/inventory/reserved/{?}"
    )
    rows.foreach(_("value_confidence").str shouldBe "heuristic") // unprovable branch
  }

  test("statement-form StringBuilder joins in statement order (T2)") {
    val sink = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("StringBuilder join")))
      .get
    sink("value").str shouldBe "${inventory.api.url}/api/v1/inventory/reserved/{?}"
    sink("value_confidence").str shouldBe "high"
  }

  test("String.join and MessageFormat resolve through varargs lowering (T2)") {
    val joined = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("String.join")))
      .get
    joined("value").str shouldBe "${inventory.api.url}/api/v1/inventory/audit/{?}"
    val formatted = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("MessageFormat.format")))
      .get
    formatted("value").str shouldBe "${inventory.api.url}/api/v1/inventory/audit/{?}"
  }

  test("member-held Map.of constant map resolves (T2)") {
    val sink = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("HOSTS.get")))
      .get
    sink("value").str shouldBe "http://inventory:8081/api/v1/inventory/stock/{?}"
  }

  test("@Value on a constructor parameter carries its config key (T2)") {
    val sink = httpSinks(petstore)
      .find(s => s("evidence").strOpt.exists(_.contains("@Value(\"${inventory.api.url}\") parameter")))
      .get
    sink("value").str shouldBe "${inventory.api.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
  }

  test("UriComponentsBuilder chain slices base + path steps (T2)") {
    // The top real-world URL idiom after `+` (predecessor-study regression).
    // queryParam is identity-neutral: skipped with a trace note, never a hole.
    val candidates = httpSinks(petstore).filter(s =>
      s("evidence").strOpt.exists(_.contains("UriComponentsBuilder chain"))
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value").str shouldBe "${inventory.api.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("evidence").str should include("queryParam")
  }

  test("RequestEntity-form exchange recovers verb and URI.create URL (T2)") {
    // Verb + URL live on the entity's builder chain, off the call site; the
    // trailing "/1" literal is a concrete segment the endpoint template absorbs.
    val candidates = httpSinks(petstore).filter(s =>
      s("value").strOpt.contains("${inventory.api.url}/stock/reserve/{?}/1")
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "PUT"
    sink("evidence").str should include("RequestEntity.put")
    sink("evidence").str should include("URI.create")
  }

  test("config-key URL slices to a ${key} template at HIGH confidence") {
    val candidates = httpSinks(petstore).filter(s =>
      s("value").strOpt.contains("${inventory.url}/stock/{?}") &&
        s("mechanism").strOpt.contains("resttemplate")
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value").str shouldBe "${inventory.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("evidence").str should include("@Value")
  }

  test("feign completeness: base, inherited, RequestMapping(method=), constant-name, url=${key} (T2)") {
    val feignSinks = httpSinks(petstore).filter(_("mechanism").strOpt.contains("feign"))
    feignSinks.map(s => (s("value").str, s("http_verb").str)).toSet shouldBe Set(
      ("http://inventory/api/v1/inventory/stock/{id}", "GET"),      // base case
      ("http://inventory/api/v1/inventory/reserved/{id}", "GET"),   // inherited contract
      ("http://inventory/stock/{id}", "GET"),                       // RequestMapping(method=)
      ("http://inventory/api/v1/inventory/audit/{id}", "GET"),      // constant name + contextId
      ("${inventory.url}/stock/{id}", "GET")                        // url=${key}
    )
    // The RequestInterceptor in the module marks every feign call token-forwarding.
    feignSinks.foreach(_("auth_propagation").str shouldBe "feign-interceptor")
  }

  test("inventory auth evidence arrives: annotation tags + filter-chain rules") {
    val restock = inventory("endpoints").arr.find(_("uri").str == "/admin/restock").get
    val authTags = restock("auth_tags").arr.map(_.str)
    authTags should have size 1
    authTags.head should startWith("auth=annotation:@PreAuthorize")
    authTags.head should include("hasRole('ADMIN')")

    val rules = inventory("security_rules").arr
    rules.map(r => (r("pattern").str, r("access").str)) shouldBe Seq(
      ("/admin/**", "hasRole(\"ADMIN\")"),
      ("/stock/**", "permitAll()"),
      ("/**", "authenticated()")
    )
    rules.head("anchor")("file").str should include("SecurityConfig.java")
  }

  test("service-registry idiom resolves through DI + constant map (TrainTicket)") {
    val resolved = httpSinks(petstore).filter(s =>
      s("value").strOpt.contains("http://inventory/stock/{?}")
    )
    resolved should have size 1
    val sink = resolved.head
    sink("value").str shouldBe "http://inventory/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("evidence").str should include("return of getServiceUrl")
    sink("evidence").str should include("serviceMap.get(\"inventory-api\") = \"inventory\"")
  }

  test("branch-dependent URL yields one candidate row per path (§5.2)") {
    val eventCandidates = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.endsWith("/events"))
    )
    eventCandidates.map(_("value").str).toSet shouldBe Set(
      "http://inventory:8081/events",
      "https://audit.example.com/events"
    )
    // Rows for one site share the call id (per-candidate rows, export 2.0.0).
    eventCandidates.map(_("call_id").num).toSet should have size 1
  }

  test("a runtime-only URL from a registry lookup stays an honest NONE (P10)") {
    val undetermined = httpSinks(petstore).filter(_("value").isNull)
    undetermined should have size 1
    undetermined.head("value_confidence").str shouldBe "none"
  }

  test("config_refs carries @Value keys AND the feign url=${key} attribute (T2)") {
    val refs = petstore("config_refs").arr
    refs.map(_("key").str).toSet shouldBe Set(
      "inventory.url",
      "inventory.api.url",
      "petstore.services.inventory", // T3: compose-env-only key
      "inventory.profile.url"        // T3: profile-file-only key
    )
    // The feign url attribute is a visible config reference now, anchored at
    // the interface (previously resolved by accident, invisible to coverage).
    refs.exists(r =>
      r("key").str == "inventory.url" &&
        r("anchor")("file").str.contains("InventoryReadClient.java")
    ) shouldBe true
  }

  test("inventory module has no outbound http sinks") {
    httpSinks(inventory) shouldBe empty
  }

  // --- Tranche 1 (§5.2.5): budget model, verbs, WebClient, honesty ----------------

  test("long-concat exchange() resolves through the map AND recovers the verb (T1)") {
    val reserve = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.startsWith("http://inventory/stock/reserve/"))
    )
    reserve should have size 1
    val sink = reserve.head
    // Five operands + DI hop + constant map: the old per-AST-level depth charge
    // starved this exact shape (the TrainTicket 21-false-unknowns bug).
    sink("value").str shouldBe "http://inventory/stock/reserve/{?}/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("evidence").str should include("serviceMap.get(\"inventory-api\") = \"inventory\"")
    sink("evidence").str should not include "truncated"
    // The verb lives in the HttpMethod.PUT argument, not the method name.
    sink("http_verb").str shouldBe "PUT"
  }

  test("WebClient fluent chain: .uri() is the sink, verb from the chain root (T1)") {
    val sink = httpSinks(petstore)
      .find(s =>
        s("mechanism").strOpt.contains("webclient") &&
          s("value").strOpt.contains("http://inventory:8081/admin/restock")
      )
      .get
    sink("value_confidence").str shouldBe "exact"
    sink("http_verb").str shouldBe "POST"
  }


  test("same-named field in another class does not bleed into the slice (T1)") {
    val billing = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.contains("/billing-events"))
    )
    // One candidate only — the AuditNotifier decoy's baseUrl must not appear.
    billing should have size 1
    billing.head("value").str shouldBe "http://billing:9082/billing-events"
    billing.head("value_confidence").str shouldBe "high"
  }

  test("unresolvable receiver surfaces as a suspected sink, never vanishes (T1)") {
    val suspected = petstore("sinks").arr.toSeq.filter(_("kind").str == "http-client-suspected")
    suspected should have size 1
    val sink = suspected.head
    sink("mechanism").str shouldBe "unknown"
    // The URL argument still slices even though the receiver is unknown.
    sink("value").str shouldBe "http://billing:9999/charge/{?}"
  }

  test("sinks in unwired classes land in the unreachable inventory (T1)") {
    val rows = petstore("unreachable_sinks").arr
    rows.map(_("value").strOpt.getOrElse("")).toSet shouldBe
      Set("https://audit.example.com/orphaned/{?}")
    rows.head("method_full_name").str should include("OrphanedAuditNotifier")
    rows.head("file").str should include("OrphanedAuditNotifier.java")
    inventory("unreachable_sinks").arr shouldBe empty
  }

  // --- analysis-unit resilience (§5.2.6): this suite parses the petstore module
  // WITHOUT the staged source union, so com.acme.common.* is deliberately
  // unresolvable here — exactly the ts-common condition. The e2e suite proves
  // the union path; these prove the fallbacks.

  test("shared-module DTO in the DI signature no longer drops the closure (§5.2.6)") {
    // stockSummary(StockQuery) — the exact shape that lost 29 TrainTicket
    // calls. Exact-value match: the T4 probes add literal /stock/N siblings.
    val summary = httpSinks(petstore).filter(s =>
      s("value").strOpt.contains("http://inventory:8081/stock/{?}")
    )
    summary should have size 1
    summary.head("http_verb").str shouldBe "GET"
  }

  test("interface -> abstract base -> impl chain reaches the leaf sink (§5.2.6)") {
    val reports = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.contains("/reports/"))
    )
    reports should have size 1
    reports.head("value").str shouldBe "https://audit.example.com/reports/{?}"
    reports.head("http_verb").str shouldBe "POST"
  }

  // --- T4 reachability roots (§5.4.2, M7) -------------------------------------------

  private lazy val sweeper: ujson.Value = moduleExport("sweeper")

  private def asyncRoots(doc: ujson.Value): Set[(String, String)] = {
    val methods = doc("methods").arr.map(m => m("id").num -> m("full_name").str).toMap
    doc("async_roots").arr.map(r => (r("kind").str, methods(r("method_id").num))).toSet
  }

  test("async roots are tagged per kind (T4)") {
    val roots = asyncRoots(petstore)
    roots should contain(("scheduled", "com.acme.petstore.NightlySweepJob.sweep:void()"))
    roots.map(_._1) should contain allOf (
      "scheduled", "event-listener", "kafka-listener", "application-runner", "framework-callback"
    )
    // The DI-registered Feign interceptor — framework-invoked through an
    // external interface, the M1 coverage fixture's anticipated case.
    roots.exists { case (kind, m) =>
      kind == "framework-callback" && m.contains("AuthForwardingInterceptor.apply")
    } shouldBe true
    // @Bean factory methods root at startup (inventory's filterChain).
    asyncRoots(inventory).exists { case (kind, m) =>
      kind == "bean" && m.contains("SecurityConfig.filterChain")
    } shouldBe true
  }

  test("each T4 traversal edge reaches its sink (T4)") {
    val values = httpSinks(petstore).flatMap(_("value").strOpt).toSet
    // One URL per construct (NightlySweepJob doc lists the mapping).
    values should contain allOf (
      "http://inventory:8081/stock/8", // DI-bean constructor body
      "http://inventory:8081/stock/9", // the scheduled root itself
      "http://inventory:8081/stock/10", // lambda body (METHOD_REF)
      "http://inventory:8081/api/v1/inventory/reserved/3", // method reference
      "http://inventory:8081/api/v1/inventory/audit/7", // anonymous class body
      "http://inventory:8081/stock/11", // helper one hop below an event listener
      "http://inventory:8081/stock/12", // kafka listener root
      "http://inventory:8081/stock/13", // application runner root
      "http://inventory:8081/stock/14" // named class behind external Thread
    )
  }

  test("dead code stays dead: the orphaned sink remains inventoried (T4)") {
    // T4 roots frameworks, not wishes — a class nothing invokes is still
    // dead, and its sink stays in the unreachable inventory (§5.2.5).
    val rows = petstore("unreachable_sinks").arr
    rows.map(_("method_full_name").str).toSet shouldBe
      Set("com.acme.petstore.OrphanedAuditNotifier.notifyAudit:void(java.lang.String)")
  }

  test("a controller-less service is non-empty through its async root (T4)") {
    sweeper("endpoints").arr shouldBe empty
    asyncRoots(sweeper) should contain(
      ("scheduled", "com.acme.sweeper.ExpiredReservationSweeper.sweepExpired:void()")
    )
    httpSinks(sweeper).flatMap(_("value").strOpt) should contain(
      "http://inventory:8081/api/v1/inventory/reserved/0"
    )
    sweeper("unreachable_sinks").arr shouldBe empty
    val cov = sweeper("analysis_coverage")
    cov("reachable_production_methods").num.toInt should be > 0
  }

  test("test sources never enter the CPG (§5.2.6 discovery hygiene)") {
    val everywhere =
      petstore("sinks").arr.toSeq ++ petstore("unreachable_sinks").arr.toSeq
    everywhere.flatMap(_("value").strOpt) should not contain
      "http://test-only-host:1/smoke"
    petstore("methods").arr.map(_("full_name").str).exists(_.contains("SmokeTest")) shouldBe false
  }
}
