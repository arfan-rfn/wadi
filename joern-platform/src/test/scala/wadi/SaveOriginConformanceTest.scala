package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** Conformance test (P8) for the `save` raw facts beyond the plan's goldens
  * (§5.2.17 M1b; Q22, Q23, R1-27).
  *
  * `SpringDataCrudMatrixConformanceTest` pins the plan's numbered save
  * goldens. `fixtures/save-origin-mini` pins the shapes those goldens leave
  * open, so that a fact is narrow where it should be: each guard form the
  * rule reads (null check, `isPresent()`, `isEmpty()`, an `exists*` boolean),
  * the shapes that must stay `none` or `other` (a conjunction, a loop in the
  * arm, another repository's check, a `toBuilder()` of a read entity, a new
  * list), and the edges of the caller hop (a DI-linked caller, a caller
  * outside the export, a lambda's parameter, which no call site passes).
  *
  * Each shape is keyed by the method that holds its save; every save site in
  * the export belongs to exactly one shape.
  */
class SaveOriginConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value = exportFixture("save-origin-mini", "save-origin-mini-export")

  private lazy val methodNames: Map[Long, String] =
    exportJson("methods").arr.map(m => m("id").num.toLong -> m("full_name").str).toMap

  private lazy val saveRows: Seq[ujson.Value] =
    exportJson("sinks").arr.toSeq
      .filter(row => row("kind").str == "db" && row("db")("save") != ujson.Null)
      .distinctBy(_("call_id").num.toLong)

  private def savesIn(owner: String): Seq[ujson.Value] =
    saveRows.filter(row => methodNames(row("method_id").num.toLong).startsWith(s"com.acme.saves.$owner:"))

  /** A `save` object as the export writes it (A1). */
  private case class Save(origin: String, lookup: Boolean, arm: String = "none", callers: List[String] = Nil) {
    def json: ujson.Value = ujson.Obj(
      "argument_origin"        -> origin,
      "lookup_same_repository" -> lookup,
      "guard_arm"              -> arm,
      "caller_origins"         -> ujson.Arr.from(callers.map(ujson.Str(_)))
    )
  }

  private val Guard  = "web.GuardShapesController."
  private val Origin = "web.OriginShapesController."

  /** Owner method → the save facts of its one save site. */
  private val shapes: List[(String, Save)] = List(
    // Q23: each guard form the rule reads, in each arm.
    Guard + "nullCheckNotFound"  -> Save("constructed", lookup = true, "not-found"),
    Guard + "notNullFound"       -> Save("constructed", lookup = true, "found"),
    Guard + "nullCheckElseArm"   -> Save("constructed", lookup = true, "found"),
    Guard + "isPresentLocal"     -> Save("constructed", lookup = true, "found"),
    Guard + "isEmptyChain"       -> Save("constructed", lookup = true, "not-found"),
    Guard + "existsBooleanLocal" -> Save("constructed", lookup = true, "not-found"),
    Guard + "noBracesArm"        -> Save("constructed", lookup = true, "not-found"),
    // Not DIRECTLY in an arm of an exact existence test: no arm.
    Guard + "conjunctionNone" -> Save("constructed", lookup = true),
    Guard + "nestedLoopNone"  -> Save("constructed", lookup = true),
    // Another repository's check is neither a guard nor a lookup.
    Guard + "otherRepositoryNone" -> Save("constructed", lookup = false),
    // Q22: origin by def-use in the saving method.
    Origin + "orElseConstructed"   -> Save("mixed", lookup = true),
    Origin + "orElseNull"          -> Save("read", lookup = true),
    Origin + "toBuilder"           -> Save("other", lookup = true),
    Origin + "reassignedAfterSave" -> Save("read", lookup = true),
    Origin + "parameterReassigned" -> Save("read", lookup = true),
    Origin + "ternary"             -> Save("mixed", lookup = true),
    Origin + "field"               -> Save("other", lookup = false),
    Origin + "cast"                -> Save("other", lookup = false),
    Origin + "listAllocSaveAll"    -> Save("other", lookup = false),
    Origin + "subtypeConstructed"  -> Save("constructed", lookup = false),
    // R1-27: one hop, only over call sites the export holds.
    Origin + "<lambda>0"                      -> Save("parameter", lookup = false),
    "service.WidgetWriter.storeFromTwoPlaces" -> Save("parameter", lookup = false, callers = List("read")),
    "service.WidgetServiceImpl.store"         -> Save("parameter", lookup = false, callers = List("read"))
  )

  shapes.foreach { case (owner, expected) =>
    test(s"$owner: ${expected.origin}, lookup=${expected.lookup}, arm=${expected.arm}, callers=${expected.callers}") {
      savesIn(owner).map(_("db")("save").render()) shouldBe List(expected.json.render())
    }
  }

  test("every save site in the export belongs to exactly one shape") {
    saveRows should have size shapes.size
    shapes.map(_._1).distinct should have size shapes.size
  }

  test("the caller hop's excluded call site is really outside the export") {
    methodNames.values.exists(_.startsWith("com.acme.saves.service.UnreachableJob.run:")) shouldBe false
  }
}
