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

  // --- URL slicing scenarios -------------------------------------------------------

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

  test("config_refs section carries the @Value key with its anchor") {
    val refs = petstore("config_refs").arr
    refs.map(_("key").str).toSet shouldBe Set("inventory.url")
    val ref = refs.head
    ref("anchor")("file").str should include("PetServiceImpl.java")
    ref("context").str should include("inventory.url")
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
