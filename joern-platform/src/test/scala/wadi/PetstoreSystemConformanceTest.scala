package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}

/** Conformance test (P8) for the Phase 2 two-service fixture: one
  * `runFromSource` per Maven module, exactly as production analyzes each
  * discovered build root. Exercises the §5.2.4 URL slicer's scenario set:
  * config-key resolution, multi-path candidates, and the DB-row NONE trap.
  *
  * Exports land on fixed (gitignored) paths — the Python cross-language
  * golden test reads them.
  */
class PetstoreSystemConformanceTest extends AnyFunSuite with Matchers {

  private val fixtureDir = Paths.get("fixtures", "petstore-system").toAbsolutePath
  private val exportRoot = Paths.get("target", "petstore-system-export").toAbsolutePath

  private def moduleExport(module: String): ujson.Value = {
    val exportDir = exportRoot.resolve(module)
    val summary = WadiPipeline.runFromSource(
      fixtureDir.resolve(module).toString,
      exportDir.toString
    )
    info(s"$module: $summary")
    ujson.read(Files.readString(exportDir.resolve("export.json")))
  }

  private lazy val petstore: ujson.Value  = moduleExport("petstore")
  private lazy val inventory: ujson.Value = moduleExport("inventory")

  private def endpoints(doc: ujson.Value): Set[String] =
    doc("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}").toSet

  private def httpSinks(doc: ujson.Value): Seq[ujson.Value] =
    doc("sinks").arr.toSeq.filter(_("kind").str == "http-client")

  // --- endpoint sets per module ----------------------------------------------------

  test("petstore serves exactly its eight controller endpoints") {
    endpoints(petstore) shouldBe Set(
      "GET /pets/{id}",
      "GET /pets",
      "PUT /pets/{id}/reserve/{count}",
      "POST /pets/{id}/alert",
      "GET /pets/summary/{id}",
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

  test("inventory serves its four endpoints incl. the role-protected one") {
    endpoints(inventory) shouldBe Set(
      "GET /stock/{id}",
      "GET /api/v1/inventory/stock/{id}",
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

  test("analysis coverage counts production vs reachable methods (§5.4.3)") {
    val petstoreCoverage = petstore("analysis_coverage")
    // The 5 unreached petstore methods are exactly the T1 unreachable-inventory
    // fixture surface: AuditNotifier.target, OrphanedAuditNotifier.notifyAudit,
    // LegacyPingProbe.ping (unwired classes), AuthForwardingInterceptor.apply
    // and CurrentRequest.bearerToken (framework-invoked, a recorded T4 root
    // class). Bodiless interface stubs count on neither side.
    petstoreCoverage("production_methods").num.toInt shouldBe 27
    petstoreCoverage("reachable_production_methods").num.toInt shouldBe 22

    val inventoryCoverage = inventory("analysis_coverage")
    // Inventory's one unreached method is SecurityConfig.filterChain — a @Bean
    // framework-invoked at startup (a recorded T4 root class). The empty-bodied
    // StockRepository.restock still counts on both sides: empty concrete
    // methods are production code, only abstract stubs are excluded.
    inventoryCoverage("production_methods").num.toInt shouldBe 7
    inventoryCoverage("reachable_production_methods").num.toInt shouldBe 6
  }

  // --- URL slicing scenarios -------------------------------------------------------

  test("RestClient fluent chain is a sink: verb from the root, URL from .uri (T2)") {
    // The yas idiom (§5.4.2): 34 real call sites used to export as a clean
    // zero because no pass modelled the type. Same shape as WebClient.
    val restClientSinks = httpSinks(petstore).filter(s =>
      s.obj.get("mechanism").exists(_.strOpt.contains("restclient"))
    )
    restClientSinks should have size 1
    val sink = restClientSinks.head
    sink("value").str shouldBe "${inventory.api.url}/api/v1/inventory/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
  }

  test("UriComponentsBuilder chain slices base + path steps (T2)") {
    // The top real-world URL idiom after `+` (predecessor-study regression).
    // queryParam is identity-neutral: skipped with a trace note, never a hole.
    val candidates = httpSinks(petstore).filter(s =>
      s("value").strOpt.contains("${inventory.api.url}/stock/{?}")
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("evidence").str should include("UriComponentsBuilder chain")
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
      s("value").strOpt.exists(_.startsWith("${inventory.url}"))
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value").str shouldBe "${inventory.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("evidence").str should include("@Value")
  }

  test("feign call becomes an http-client sink with the discovery-name URL") {
    val feignSinks = httpSinks(petstore).filter(_("mechanism").strOpt.contains("feign"))
    feignSinks should have size 1
    val sink = feignSinks.head
    sink("value").str shouldBe "http://inventory/api/v1/inventory/stock/{id}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    // The RequestInterceptor in the module marks the call as token-forwarding.
    sink("auth_propagation").str shouldBe "feign-interceptor"
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

  test("config_refs section carries the @Value keys with their anchors") {
    val refs = petstore("config_refs").arr
    refs.map(_("key").str).toSet shouldBe Set("inventory.url", "inventory.api.url")
    val byKey = refs.map(r => r("key").str -> r).toMap
    byKey("inventory.url")("anchor")("file").str should include("PetServiceImpl.java")
    byKey("inventory.api.url")("anchor")("file").str should include("StockHistoryClient.java")
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
    val webclient = httpSinks(petstore).filter(_("mechanism").strOpt.contains("webclient"))
    webclient should have size 1
    val sink = webclient.head
    sink("value").str shouldBe "http://inventory:8081/admin/restock"
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
    // stockSummary(StockQuery) — the exact shape that lost 29 TrainTicket calls.
    val summary = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.startsWith("http://inventory:8081/stock/"))
    )
    summary should have size 1
    summary.head("value").str shouldBe "http://inventory:8081/stock/{?}"
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

  test("test sources never enter the CPG (§5.2.6 discovery hygiene)") {
    val everywhere =
      petstore("sinks").arr.toSeq ++ petstore("unreachable_sinks").arr.toSeq
    everywhere.flatMap(_("value").strOpt) should not contain
      "http://test-only-host:1/smoke"
    petstore("methods").arr.map(_("full_name").str).exists(_.contains("SmokeTest")) shouldBe false
  }
}
