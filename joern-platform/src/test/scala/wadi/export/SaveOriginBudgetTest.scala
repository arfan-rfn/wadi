package wadi.`export`

import io.joern.javasrc2cpg.{Config, JavaSrc2Cpg}
import io.joern.x2cpg.X2Cpg
import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.semanticcpg.language.*
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}
import scala.util.Using

import wadi.WadiPipeline
import wadi.packs.SpringPacks
import wadi.passes.SpringDIPass

/** A def-use walk that stops at its node budget reports `other` (§5.2.17,
  * review A5).
  *
  * No fixture method is large enough to reach the shipped budget of 20,000
  * CFG nodes, so the budget is a constructor parameter and this test lowers
  * it. Whatever a cut-short walk has already found, the origin it reports is
  * `other`: a read plus a walk that stopped is not `mixed`, which would claim
  * two origins on two paths. So at every budget, each save reports either
  * exactly what the unbounded walk reports or `other`.
  */
class SaveOriginBudgetTest extends AnyFunSuite with Matchers {

  private def withPipelineCpg[A](fixture: String)(body: Cpg => A): A = {
    val config = Config()
      .withDelombokMode("types-only")
      .withInputPath(Paths.get("fixtures").resolve(fixture).toAbsolutePath.toString)
      .withOutputPath(Files.createTempFile("wadi-budget", ".cpg").toString)
      .withIgnoredFilesRegex(WadiPipeline.ExcludeRegex)
    Using.resource(new JavaSrc2Cpg().createCpg(config).get) { cpg =>
      X2Cpg.applyDefaultOverlays(cpg)
      new SpringDIPass(cpg).createAndApply()
      SpringPacks.applyAll(cpg)
      body(cpg)
    }
  }

  test("at every node budget a save reports the unbounded origin or other, never a partial one") {
    withPipelineCpg("save-origin-mini") { cpg =>
      val saves = cpg.call
        .where(_.tag.nameExact("sink").valueExact("db"))
        .filter(call => SaveOrigin.SaveFamily.contains(call.name))
        .l
        .sortBy(_.id)
      val methodIds = cpg.method.id.toSet
      def origins(facts: EntityAccessFacts): List[String] =
        saves.map(call => facts.dbObj(call)("save")("argument_origin").str)

      val unbounded = origins(new EntityAccessFacts(cpg, methodIds))
      val byBudget  = (1 to 40).map(budget => budget -> origins(new EntityAccessFacts(cpg, methodIds, budget)))
      saves.size should be > 20
      byBudget.foreach { case (budget, cut) =>
        cut.zip(unbounded).zip(saves).foreach { case ((got, full), call) =>
          withClue(s"budget $budget, ${call.method.name}: ") {
            Set(full, "other") should contain(got)
          }
        }
      }
      // The budgets above really cut walks short: some save that is not
      // `other` unbounded is `other` under one of them.
      byBudget.exists { case (_, cut) => cut.zip(unbounded).exists { case (got, full) => got == "other" && full != "other" } } shouldBe true
    }
  }
}
