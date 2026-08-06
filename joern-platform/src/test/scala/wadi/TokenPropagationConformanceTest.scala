package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** §5.2.11 T4 — whether the caller's credentials cross an outbound call.
  *
  * `auth_propagation` read null on 382 of 382 train-ticket-aitest calls. The
  * detector was not broken so much as aimed wrong: it looked for a literal
  * `"Authorization"` anywhere in the enclosing method, which on that corpus
  * appears only inside `JWTUtil` — where inbound tokens are READ and no
  * outbound sink exists. The idiom that actually forwards a bearer token is
  * `new HttpEntity(body, headers)` (5 sites), and the far commoner shape is
  * `new HttpEntity(null)` (98 sites) — a provable negative a nullable field
  * could not express apart from "we did not look".
  */
class TokenPropagationConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value =
    exportFixture("token-propagation-mini", "token-propagation-export")

  /** (url, propagation state, mechanism) for every http sink. */
  private lazy val sinks: List[(String, String, String)] =
    exportJson("sinks").arr.toList
      .filter(_("kind").str.startsWith("http-client"))
      .map { sink =>
        val url = sink("value") match {
          case ujson.Null => "<undetermined>"
          case other      => other.str
        }
        val mechanism = sink("auth_propagation") match {
          case ujson.Null => "<none>"
          case other      => other.str
        }
        (url, sink("auth_propagation_state").str, mechanism)
      }

  private def stateOf(fragment: String): String =
    sinks.find(_._1.contains(fragment)).map(_._2).getOrElse(
      fail(s"no sink whose url contains '$fragment'; saw: ${sinks.map(_._1).mkString(", ")}")
    )

  private def mechanismOf(fragment: String): String =
    sinks.find(_._1.contains(fragment)).map(_._3).getOrElse(fail(s"no sink for '$fragment'"))

  test("inbound headers on the outbound entity read as forwarded") {
    stateOf("/stock/1") shouldBe "forwarded"
    mechanismOf("/stock/1") shouldBe "authorization-header"
  }

  test("an entity built with no headers argument is a PROVABLE negative") {
    // The distinction the nullable field could not carry: this is not "we
    // could not tell", it is "there is no vehicle for a token here".
    stateOf("/reserved/1") shouldBe "not-forwarded"
    mechanismOf("/reserved/1") shouldBe "<none>"
  }

  test("two sites in one method answer for themselves, not for the method") {
    // The defect a method-level answer would reintroduce: `ConsignServiceImpl`
    // builds both shapes a few lines apart, so a method-wide verdict would
    // mark the bare call as forwarding a token it never sends.
    stateOf("/audit/1") shouldBe "forwarded"
    stateOf("/public/1") shouldBe "not-forwarded"
  }

  test("a null in the headers position is a stated negative, not a forwarding") {
    // The shape that broke the first cut. Treating "an argument occupies the
    // headers slot" as forwarding reported 299 of 382 corpus calls as carrying
    // credentials, when `new HttpEntity(info, null)` — which sends none — is
    // the commonest two-argument form there (81+ sites). Publishing that would
    // tell a reader auth propagates across calls that demonstrably send none:
    // the exact over-approximation the three-state model exists to prevent.
    stateOf("/nulled/1") shouldBe "not-forwarded"
  }

  test("the headers-ONLY constructor forwards, despite its single argument") {
    // `new HttpEntity(headers)` and `new HttpEntity(body)` are the same shape
    // in every respect but the argument's TYPE, and they mean opposite things.
    // Reading position instead of type published "provably does not forward"
    // about a call that forwards every inbound header — caught by checking a
    // claim against its source rather than trusting the aggregate.
    stateOf("/headers-only/1") shouldBe "forwarded"
    // ...and the body-only form must not drift into forwarding with it.
    stateOf("/reserved/1") shouldBe "not-forwarded"
  }

  test("headers reaching the entity through a helper still count as forwarded") {
    // `HeadersUtils.prepareForSent(headers)` — 22 sites on the corpus. The
    // argument is a call, so its RETURN type is what says whether headers ride.
    stateOf("/helper/1") shouldBe "forwarded"
  }

  test("every http sink carries a state — silence is not one of the answers") {
    sinks should not be empty
    all(sinks.map(_._2)) should (be("forwarded") or be("not-forwarded") or be("undetermined"))
  }

  test("a named mechanism only ever accompanies forwarded") {
    // The contract enforces this too; asserting it at the source keeps the
    // pack from emitting a contradiction the worker would then have to reject.
    sinks.filter(_._3 != "<none>").map(_._2).distinct shouldBe List("forwarded")
  }
}
