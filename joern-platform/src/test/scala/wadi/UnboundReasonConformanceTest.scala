package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** §5.4.2 T5 — every call that binds to no method must say WHY.
  *
  * The audit that produced this tranche started from a slice that named 7
  * files while the handler called into more, and it read as data loss. It was
  * not: 92.9% of the unbound calls were Lombok accessors that have no source
  * at all. The defect was that nothing said so. These goldens pin the reason
  * vocabulary so a dead-end node can never silently look like a hole again.
  */
class UnboundReasonConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value =
    exportFixture("unbound-reasons-mini", "unbound-reasons-export")

  /** (callee_full_name, unbound_reason) for every call node in the export. */
  private lazy val calls: List[(String, Option[String])] =
    exportJson("cfgs").arr.toList.flatMap { cfg =>
      cfg("nodes").arr.toList.flatMap { node =>
        node.obj.get("call").map { call =>
          val reason = call("unbound_reason") match {
            case ujson.Null => None
            case other      => Some(other.str)
          }
          (call("callee_full_name").str, reason)
        }
      }
    }

  private def reasonFor(fragment: String): Option[String] =
    calls.find(_._1.contains(fragment)).map(_._2).getOrElse(
      fail(s"no call node whose callee contains '$fragment'; saw: ${calls.map(_._1).mkString(", ")}")
    )

  test("the endpoint is found and its call nodes survive classification") {
    val endpoints = exportJson("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}")
    endpoints should contain("GET /orders/{id}")
    // P10 + the CFG contract: an unbindable call is still a node. Losing the
    // node is what would make the map lie.
    calls should not be empty
  }

  test("a Lombok-generated accessor is labelled, not dropped") {
    reasonFor("Order.setId") shouldBe Some("lombok-generated")
    reasonFor("Order.getId") shouldBe Some("lombok-generated")
  }

  test("a method inherited from an external supertype is labelled") {
    // `save` is CrudRepository's, not OrderRepository's — a first-party NAME
    // with no first-party body.
    reasonFor("OrderRepository.save") shouldBe Some("inherited-external")
  }

  test("an enum's compiler-synthesized values() is labelled") {
    reasonFor("OrderStatus.values") shouldBe Some("compiler-generated")
  }

  test("a type absent from the CPG is labelled third-party") {
    reasonFor("RestTemplate.getForObject") shouldBe Some("third-party")
  }

  test("a call that binds normally carries NO reason") {
    // The control case: classification must not label healthy edges.
    reasonFor("OrderSummary.describe") shouldBe None
  }

  test("a static import attributed to the importing class is unresolved-receiver") {
    // `unresolved-receiver` is also the classifier's fall-through, so without
    // pinning it to a specific input a regression that collapsed everything
    // into the default would still look covered by the blanket test below.
    reasonFor("OrderController.ok") shouldBe Some("unresolved-receiver")
  }

  test("a setter asked for per FIELD is still lombok-generated") {
    // `OrderFormatter` carries @Getter at class level and @Setter on the
    // field. Reading only class-level annotations, a direction-aware check
    // concludes "@Getter generates no setters" and mislabels this — trading
    // one wrong answer for another. Both levels have to be read.
    reasonFor("OrderFormatter.setPrefix") shouldBe Some("lombok-generated")
  }

  test("a hand-written method that merely starts with 'set' is never generated") {
    // `settle` binds to a real body, so the honest answer is no reason at all.
    // Testing the prefix without a boundary check was what let names like
    // settle/island/getaway read as generated accessors.
    reasonFor("OrderFormatter.settle") shouldBe None
  }

  test("every unbound call has a reason and every bound call has none") {
    val bound   = calls.filter(_._2.isEmpty).map(_._1)
    val unbound = calls.filter(_._2.nonEmpty)
    // No call may be left unexplained: an empty reason on an unbindable call
    // is exactly the silent hole this tranche exists to remove.
    unbound.foreach { case (name, reason) => withClue(s"$name: ")(reason.get should not be empty) }
    bound should contain("com.acme.orders.OrderSummary.describe:java.lang.String(java.lang.String,int)")
  }
}
