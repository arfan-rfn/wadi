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

  test("petstore serves exactly its two controller endpoints") {
    endpoints(petstore) shouldBe Set("GET /pets/{id}", "GET /pets")
  }

  test("feign mappings never count as served endpoints (TrainTicket trap)") {
    endpoints(petstore).exists(_.contains("/api/v1/inventory")) shouldBe false
  }

  test("inventory serves its three endpoints incl. the role-protected one") {
    endpoints(inventory) shouldBe Set(
      "GET /stock/{id}",
      "GET /api/v1/inventory/stock/{id}",
      "POST /admin/restock"
    )
  }

  // --- URL slicing scenarios -------------------------------------------------------

  test("config-key URL slices to a ${key} template at HIGH confidence") {
    val candidates = httpSinks(petstore).filter(s =>
      s("value").strOpt.exists(_.contains("/stock/"))
    )
    candidates should have size 1
    val sink = candidates.head
    sink("value").str shouldBe "${inventory.url}/stock/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("http_verb").str shouldBe "GET"
    sink("evidence").str should include("@Value")
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
}
