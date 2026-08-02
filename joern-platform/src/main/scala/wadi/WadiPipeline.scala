package wadi

import io.joern.javasrc2cpg.{Config, JavaSrc2Cpg}
import io.joern.x2cpg.X2Cpg
import io.shiftleft.codepropertygraph.generated.Cpg

import java.nio.file.Files
import scala.util.Using

import wadi.`export`.WadiExport
import wadi.packs.SpringPacks
import wadi.passes.SpringDIPass

/** The in-graph pipeline entrypoint (§5.1).
  *
  * The worker sends ONE control query per (service x language):
  * {{{
  *   wadi.WadiPipeline.runFromSource("/workspace/<snap>/<svc>", "/workspace/exports/<snap>/<svc>")
  * }}}
  * which builds the CPG (delombok types-only: type info from delombok, but
  * analysis on the ORIGINAL source so every anchor aligns with the committed
  * text — the §5.3 source-on-demand guarantee), runs the DI pass, applies
  * the framework packs, writes the bulk export to the shared volume, and
  * disposes the CPG (P5). Returns a one-line summary — the query channel is
  * for control, never bulk data.
  */
object WadiPipeline {

  /** §5.2.6 discovery hygiene — mirrors `wadi_joern_client.client.EXCLUDE_REGEX`
    * (the production path passes it over the CPGQL channel; this constant keeps
    * the conformance test path identical). Character classes avoid backslashes
    * so the same string survives both channels.
    */
  val ExcludeRegex = ".*/src/test/.*|.*/old-docs/.*|.*/[.][^/]+/.*"

  def run(cpg: Cpg, exportDir: String): String = {
    new SpringDIPass(cpg).createAndApply()
    SpringPacks.applyAll(cpg)
    WadiExport.run(cpg, exportDir)
  }

  def runFromSource(sourceDir: String, exportDir: String): String = {
    val cpgFile = Files.createTempFile("wadi", ".cpg")
    val config = Config()
      .withDelombokMode("types-only")
      .withInputPath(sourceDir)
      .withOutputPath(cpgFile.toString)
      .withIgnoredFilesRegex(ExcludeRegex)
    Using.resource(new JavaSrc2Cpg().createCpg(config).get) { cpg =>
      X2Cpg.applyDefaultOverlays(cpg)
      val summary = run(cpg, exportDir)
      summary
    }
  }
}
