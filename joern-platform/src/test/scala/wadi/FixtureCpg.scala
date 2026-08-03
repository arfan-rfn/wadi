package wadi

import org.scalatest.Informing

import java.nio.file.{Files, Paths}

/** Shared conformance-test harness: run the full pipeline on a fixture tree
  * and read back the export document.
  *
  * Export dirs are fixed (gitignored) paths under `target/` so slicing
  * behavior stays inspectable locally and the Python cross-language goldens
  * read the exact same files.
  */
trait FixtureCpg { self: Informing =>

  /** Build the CPG for `fixtures/<fixture>`, export to `target/<exportName>`,
    * and return the parsed export document. `fixture` may be a nested path
    * (e.g. "petstore-system/petstore") for per-module runs.
    */
  def exportFixture(fixture: String, exportName: String): ujson.Value = {
    val fixtureDir = Paths.get("fixtures").resolve(fixture).toAbsolutePath
    val exportDir  = Paths.get("target").resolve(exportName).toAbsolutePath
    val summary    = WadiPipeline.runFromSource(fixtureDir.toString, exportDir.toString)
    info(s"$fixture: $summary")
    ujson.read(Files.readString(exportDir.resolve("export.json")))
  }
}
