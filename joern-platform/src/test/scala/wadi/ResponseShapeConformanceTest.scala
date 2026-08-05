package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** §5.2.7 (amended) — a raw wrapper's payload comes from the return expression.
  *
  * The measurement that produced this tranche: 274 of 365 `train-ticket-aitest`
  * response shapes resolved to `unresolved`, and every one of them was
  * `HttpEntity` — the corpus declares it raw 376 times against 9 generic ones.
  * The signature genuinely names no payload; the return statement does.
  *
  * Per the P8 amendment (§5.2.10), most of these goldens assert what must NOT
  * be inferred. A recovery that guesses is worse than one that abstains, so the
  * honest-unknown cases outnumber the recoveries here by design.
  */
class ResponseShapeConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value =
    exportFixture("response-shape-mini", "response-shape-export")

  private def endpoint(httpMethod: String, uri: String): ujson.Value =
    exportJson("endpoints").arr
      .find(e => e("http_method").str == httpMethod && e("uri").str == uri)
      .getOrElse(
        fail(
          s"no endpoint $httpMethod $uri; saw: " +
            exportJson("endpoints").arr
              .map(e => s"${e("http_method").str} ${e("uri").str}")
              .mkString(", ")
        )
      )

  private def shape(httpMethod: String, uri: String): ujson.Value =
    endpoint(httpMethod, uri).obj.getOrElse(
      "response_schema",
      fail(s"$httpMethod $uri carries no response_schema")
    )

  private def kindOf(httpMethod: String, uri: String): String   = shape(httpMethod, uri)("kind").str
  private def originOf(httpMethod: String, uri: String): String = shape(httpMethod, uri)("origin").str

  // ---- T0: the route is published root-anchored -------------------------

  test("a class-level mapping written without its leading slash is still root-anchored") {
    // `@RequestMapping("shapes")` routes exactly as `/shapes` in Spring, and
    // two real controllers in the corpus are written this way (§5.2.11).
    val uris = exportJson("endpoints").arr.map(_("uri").str).toSet
    uris should contain("/shapes/one")
    all(uris.toList) should startWith("/")
  }

  // ---- recoveries --------------------------------------------------------

  test("ok(expr) recovers the payload the callee declares") {
    kindOf("GET", "/shapes/one") shouldBe "object"
    originOf("GET", "/shapes/one") shouldBe "return-expression"
    val fieldNames = shape("GET", "/shapes/one")("fields").arr.map(_("name").str).toSet
    // @JsonProperty still applies — recovery changes where the TYPE comes
    // from, not how the shape is walked.
    fieldNames should contain("display_name")
    fieldNames should contain("id")
  }

  test("generics survive the extra hop, read from the callee's declaration text") {
    // `List<Item>` would erase to a bare `List` via typeFullName; the payload
    // element is the whole point of the recovery.
    kindOf("GET", "/shapes/list") shouldBe "array"
    originOf("GET", "/shapes/list") shouldBe "return-expression"
    shape("GET", "/shapes/list")("element")("kind").str shouldBe "object"
  }

  test("the constructor form recovers from argument 1, not the wrapper") {
    kindOf("POST", "/shapes/created") shouldBe "object"
    originOf("POST", "/shapes/created") shouldBe "return-expression"
  }

  // ---- honest unknowns ---------------------------------------------------

  test("returns that disagree elect no winner") {
    // One path returns Item, the other String. Publishing either would make a
    // shape up; the claim is withheld and the origin stays `declared` so the
    // absence of inference is visible, not just the absence of an answer.
    kindOf("GET", "/shapes/disagree") shouldBe "unresolved"
    originOf("GET", "/shapes/disagree") shouldBe "declared"
  }

  test("a builder chain with no body yields no shape") {
    kindOf("GET", "/shapes/empty") shouldBe "unresolved"
  }

  test("a payload whose type is off-CPG stays unresolved, never fabricated") {
    // P10: name only, never invented fields.
    kindOf("GET", "/shapes/offcpg") shouldBe "unresolved"
    shape("GET", "/shapes/offcpg").obj.get("fields") shouldBe None
  }

  // ---- the regression guard ---------------------------------------------

  test("a declared generic is never overridden by recovery") {
    // The fallback must not fire where the signature already answered.
    kindOf("GET", "/declared/list") shouldBe "array"
    originOf("GET", "/declared/list") shouldBe "declared"
    kindOf("GET", "/declared/one") shouldBe "object"
    originOf("GET", "/declared/one") shouldBe "declared"
  }
}
