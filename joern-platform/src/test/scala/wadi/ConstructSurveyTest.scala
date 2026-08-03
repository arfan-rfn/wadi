package wadi

import io.joern.javasrc2cpg.{Config, JavaSrc2Cpg}
import io.joern.x2cpg.X2Cpg
import io.shiftleft.semanticcpg.language.*
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}
import scala.util.Using

import wadi.`export`.WadiExport
import wadi.packs.SpringPacks
import wadi.passes.SpringDIPass

/** The §5.2.8 survey instrument (Phase 2.6 M1): dump, per matrix-fixture
  * handler, the raw javasrc2cpg picture (control structures, jump targets,
  * expression-level CFG) next to what the current coarsening exports.
  *
  * This is an instrument, not a conformance gate: its output
  * (`target/construct-survey/survey.md`) is the empirical record that §5.2.8
  * transcribes BEFORE any coarsening fix lands. The only assertion is that
  * the survey ran over the whole fixture.
  */
class ConstructSurveyTest extends AnyFunSuite with Matchers {

  private val fixtureDir = Paths.get("fixtures", "control-flow-matrix").toAbsolutePath
  private val exportDir  = Paths.get("target", "construct-survey", "export").toAbsolutePath
  private val surveyPath = Paths.get("target", "construct-survey", "survey.md").toAbsolutePath

  private def short(code: String, max: Int = 90): String = {
    val firstLine = code.linesIterator.nextOption().getOrElse("")
    if (firstLine.length <= max) firstLine else firstLine.take(max) + "…"
  }

  test("survey every matrix handler and write the empirical record") {
    val cpgFile = Files.createTempFile("wadi-survey", ".cpg")
    val config = Config()
      .withDelombokMode("types-only")
      .withInputPath(fixtureDir.toString)
      .withOutputPath(cpgFile.toString)
      .withIgnoredFilesRegex(WadiPipeline.ExcludeRegex)

    Using.resource(new JavaSrc2Cpg().createCpg(config).get) { cpg =>
      X2Cpg.applyDefaultOverlays(cpg)
      new SpringDIPass(cpg).createAndApply()
      SpringPacks.applyAll(cpg)
      WadiExport.run(cpg, exportDir.toString)

      val exported = ujson.read(Files.readString(exportDir.resolve("export.json")))
      val cfgsByMethodId: Map[Long, ujson.Value] =
        exported("cfgs").arr.map(c => c("method_id").num.toLong -> c).toMap

      val sb = new StringBuilder
      sb ++= "# control-flow-matrix construct survey (empirical, pre-fix)\n\n"
      sb ++= s"javasrc2cpg + current WadiExport coarsening, export schema ${exported("export_schema_version").str}\n"

      val handlers = cpg.typeDecl
        .name(".*Controller")
        .method
        .filterNot(_.astParentType == "TYPE_DECL" && false)
        .filter(m => m.lineNumber.isDefined)
        .sortBy(m => (m.filename, m.lineNumber.map(_.intValue()).getOrElse(0)))
        .l

      handlers.foreach { m =>
        sb ++= s"\n## ${m.typeDecl.map(_.name).headOption.getOrElse("?")}.${m.name} (${m.filename.split('/').last}:${m.lineNumber.getOrElse(-1)})\n"

        val structures = m.ast.isControlStructure.sortBy(_.lineNumber.map(_.intValue()).getOrElse(0)).l
        sb ++= "\n### raw CONTROL_STRUCTURE nodes\n"
        if (structures.isEmpty) sb ++= "- (none)\n"
        structures.foreach { cs =>
          sb ++= s"- ${cs.controlStructureType} @${cs.lineNumber.getOrElse(-1)} `${short(cs.code)}`\n"
        }

        val jumps = m.ast
          .collectAll[io.shiftleft.codepropertygraph.generated.nodes.JumpTarget]
          .sortBy(_.lineNumber.map(_.intValue()).getOrElse(0))
          .l
        if (jumps.nonEmpty) {
          sb ++= "\n### raw JUMP_TARGET nodes\n"
          jumps.foreach { jt =>
            sb ++= s"- ${jt.name} @${jt.lineNumber.getOrElse(-1)} `${short(jt.code)}`\n"
          }
        }

        val cfgNodes = m.cfgNode.l
        sb ++= s"\n### raw expression-level CFG (${cfgNodes.size} nodes)\n"
        cfgNodes.sortBy(_.id).foreach { n =>
          val succs = n._cfgOut.collectAll[io.shiftleft.codepropertygraph.generated.nodes.CfgNode].l
          if (succs.nonEmpty) {
            val succStr = succs
              .map(s => s"${s.label}#${s.id}@${s.lineNumber.getOrElse(-1)}")
              .mkString(", ")
            sb ++= s"- ${n.label}#${n.id}@${n.lineNumber.getOrElse(-1)} `${short(n.code, 60)}` -> $succStr\n"
          }
        }

        sb ++= "\n### exported (coarsened) CFG\n"
        cfgsByMethodId.get(m.id) match {
          case None => sb ++= "- (method has no exported CFG)\n"
          case Some(cfg) =>
            val nodesById = cfg("nodes").arr.map(n => n("id").num.toLong -> n).toMap
            cfg("nodes").arr.foreach { n =>
              val cond = n.obj.get("condition_code").map(c => s" cond=`${short(c.str, 50)}`").getOrElse("")
              val call = n.obj.get("call").map(c => s" call=${c("callee_full_name").str}").getOrElse("")
              sb ++= s"- [${n("kind").str}] #${n("id").num.toLong}@${n("line").num.toInt} `${short(n("code").str, 60)}`$cond$call\n"
            }
            if (cfg("edges").arr.isEmpty) sb ++= "- edges: (none)\n"
            cfg("edges").arr.foreach { e =>
              val src = e("source").num.toLong
              val tgt = e("target").num.toLong
              def tag(id: Long) =
                nodesById.get(id).map(n => s"${n("kind").str}@${n("line").num.toInt}").getOrElse(s"?#$id")
              sb ++= s"- edge ${tag(src)} -> ${tag(tgt)} [${e("label").str}]\n"
            }
        }
      }

      Files.createDirectories(surveyPath.getParent)
      Files.writeString(surveyPath, sb.toString)
      info(s"survey written to $surveyPath (${handlers.size} handlers)")

      // The instrument's only gate: every controller handler was surveyed.
      handlers.size should be >= 24
    }
  }
}
