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

  // ---- the envelope: one field deeper than the wrapper -------------------

  test("a raw generic envelope resolves T from the producer's return statement") {
    // What 291 of 365 train-ticket-aitest endpoints published before this:
    // `{status, msg, data}` where `data` was an unbound `T`. The shape named
    // the wrapper and withheld the only field a reader wants. No signature
    // anywhere carries the argument — the service declares a RAW `Envelope`
    // and only its return statement says what went in.
    kindOf("GET", "/shapes/envelope") shouldBe "object"
    val fields = shape("GET", "/shapes/envelope")("fields").arr
    val data = fields.find(_("name").str == "data").getOrElse(fail("no data field"))
    data("shape")("kind").str shouldBe "array"
    data("shape")("element")("kind").str shouldBe "object"
    // ...and it is the real payload entity, walked like any other type.
    data("shape")("element")("fields").arr.map(_("name").str) should contain("display_name")
  }

  test("a null payload is an absence, not a disagreement") {
    // The failure branch is `new Envelope<>(0, "empty", null)`. Treating that
    // as a competing claim would withhold the type the success branch states
    // plainly — every TrainTicket service writes exactly this pair.
    val fields = shape("GET", "/shapes/envelope")("fields").arr
    fields.find(_("name").str == "data").get("shape")("kind").str should not be "unresolved"
  }

  test("a DECLARED generic wrapping a raw envelope binds too") {
    // `ResponseEntity<Envelope>` has a type argument, so it never took the
    // recovery path — while the `Envelope` inside is as raw as any recovered
    // one. Binding only on recovery left this showing `data: T` while a
    // handler one line different resolved fully.
    val fields = shape("GET", "/declared/wrapped-envelope")("fields").arr
    val data = fields.find(_("name").str == "data").getOrElse(fail("no data field"))
    data("shape")("kind").str shouldBe "array"
  }

  test("a declared type ARGUMENT answers without touching the producer") {
    // `Envelope<Item>` says T=Item outright. Preferring it over the return
    // expression keeps the strongest evidence first, as the rest of §5.2.7 does.
    val fields = shape("GET", "/declared/declared-argument")("fields").arr
    val data = fields.find(_("name").str == "data").getOrElse(fail("no data field"))
    data("shape")("kind").str shouldBe "object"
    data("shape")("fields").arr.map(_("name").str) should contain("display_name")
  }

  test("a payload every path sets to null is EMPTY, not unknown") {
    // The distinction a reader acts on: `unresolved` says analysis could not
    // determine the type, `always-null` says the code determined it sends
    // nothing. Both of the endpoints that prompted this were the second.
    val fields = shape("GET", "/shapes/envelope-empty")("fields").arr
    val data = fields.find(_("name").str == "data").getOrElse(fail("no data field"))
    data("shape")("kind").str shouldBe "always-null"
  }

  test("two constructions that genuinely disagree leave T unresolved") {
    // The guard: `Item` on one path and `String` on the other is a real
    // conflict, and recovery must not pick. This is the case the null rule
    // above must NOT swallow.
    val fields = shape("GET", "/shapes/envelope-conflict")("fields").arr
    fields.find(_("name").str == "data").get("shape")("kind").str shouldBe "unresolved"
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

  // ---- declared status codes (T9) ----------------------------------------

  private def statusesOf(httpMethod: String, uri: String): List[(Int, String)] =
    endpoint(httpMethod, uri)("status_codes").arr.toList
      .map(s => (s("code").num.toInt, s("origin").str))

  test("a builder's NAME fixes the status") {
    statusesOf("GET", "/shapes/status-builder") shouldBe List((204, "builder"))
  }

  test("an explicit constant is read from the construction") {
    statusesOf("POST", "/shapes/status-explicit") shouldBe List((201, "explicit"))
  }

  test("status(X).body(y) takes X, not the body's implied 200") {
    // The chain nests, so a walk that kept descending would find `body` and
    // report nothing, or find a builder further in and report the wrong code.
    statusesOf("POST", "/shapes/status-chain") shouldBe List((202, "explicit"))
  }

  test("two paths declare two statuses and neither is elected") {
    // Unlike a response SHAPE, where disagreement means we cannot know, an
    // endpoint genuinely answers with several statuses — the honest answer is
    // the set, not a refusal.
    statusesOf("GET", "/shapes/status-branching").map(_._1) shouldBe List(200, 404)
  }

  test("@ResponseStatus replaces the builder's status rather than joining it") {
    // The framework sends 202. Publishing the co-located `ok(...)` 200 beside
    // it would name a status this endpoint never answers with.
    statusesOf("GET", "/shapes/status-annotated") shouldBe List((202, "annotation"))
  }

  test("every endpoint carries the field, and a plain ok() reads 200") {
    statusesOf("GET", "/shapes/one") shouldBe List((200, "builder"))
  }

  test("a handler that names nothing gets the framework's answer, marked as such") {
    // `/declared/welcome` returns a bare String: Spring serializes it with 200
    // and the code never says so. Leaving it empty beside endpoints showing
    // `200` made an identical outcome look like an unknown — but the origin
    // has to stay `default`, because the handler did not declare it.
    statusesOf("GET", "/declared/welcome") shouldBe List((200, "default"))
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
