package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}

/** Week-one validation (§11, §12 risk): Lombok must not dead-end extraction.
  *
  * `GreetingController` uses `@RequiredArgsConstructor` — the constructor that
  * injects the service does not exist in source. javasrc2cpg's bundled
  * delombok handles the rewrite; the DI pass must still resolve the
  * interface call into the implementation.
  */
class LombokConformanceTest extends AnyFunSuite with Matchers {

  private val fixtureDir = Paths.get("fixtures", "lombok-mini").toAbsolutePath
  // Fixed output path (gitignored) so slicing behavior is inspectable locally.
  private val exportDir = Paths.get("target", "lombok-export").toAbsolutePath

  private lazy val exportJson: ujson.Value = {
    val summary = WadiPipeline.runFromSource(fixtureDir.toString, exportDir.toString)
    info(summary)
    ujson.read(Files.readString(exportDir.resolve("export.json")))
  }

  test("endpoint on the lombok controller is found") {
    val endpoints =
      exportJson("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}").toSet
    endpoints should contain("GET /greet/{name}")
  }

  test("DI resolution crosses into the impl despite the lombok constructor") {
    val methodNames = exportJson("methods").arr.map(_("full_name").str)
    methodNames.exists(_.contains("GreetingServiceImpl.greet")) shouldBe true
  }

  test("URL through a lombok getter resolves via the backing-field bridge") {
    // getBaseUrl() has no source body (Lombok generates it); the slicer must
    // bridge to the field initializer instead of dead-ending (recorded
    // decision: exact anchors + getter bridge over run-delombok).
    val httpSinks = exportJson("sinks").arr.filter(_("kind").str == "http-client")
    httpSinks should not be empty
    val sink = httpSinks.head
    sink("value").str shouldBe "http://upstream:9000/greet/{?}"
    sink("value_confidence").str shouldBe "high"
    sink("evidence").str should include("lombok getter bridged")
  }

  test("anchors point at real source lines (not delombok misalignment)") {
    val controllerHandler = exportJson("methods").arr
      .find(_("full_name").str.contains("GreetingController.greet"))
      .get
    // The @GetMapping method starts at line 17 in the committed source.
    controllerHandler("line").num.toInt should be >= 15
    controllerHandler("filename").str should include("GreetingController.java")
  }
}
