package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}

/** Conformance (P8) for the exact yas outbound idiom: RestClient +
  * UriComponentsBuilder base from a @ConfigurationProperties record accessor,
  * through a URI-typed local into `.uri(url)`.
  */
class RestClientYasConformanceTest extends AnyFunSuite with Matchers {

  private val fixtureDir = Paths.get("fixtures", "restclient-yas-mini").toAbsolutePath
  private val exportDir  = Paths.get("target", "restclient-yas-export").toAbsolutePath

  private lazy val exportJson: ujson.Value = {
    val summary = WadiPipeline.runFromSource(fixtureDir.toString, exportDir.toString)
    info(summary)
    ujson.read(Files.readString(exportDir.resolve("export.json")))
  }

  test("the yas idiom resolves to a config-key template (T2)") {
    val sinks = exportJson("sinks").arr.filter(_("kind").str == "http-client")
    sinks should have size 1
    val sink = sinks.head
    sink("mechanism").str shouldBe "restclient"
    sink("http_verb").str shouldBe "GET"
    // The @ConfigurationProperties accessor binds to its config key — the
    // base is a ${key} template, not an unknowable hole.
    sink("value").str shouldBe "${yas.services.customer}/storefront/customer/profile"
    sink("value_confidence").str shouldBe "high"
    sink("evidence").str should include("@ConfigurationProperties")
  }
}
