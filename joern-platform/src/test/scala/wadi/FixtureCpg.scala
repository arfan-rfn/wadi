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

  /** An endpoint's shape with its type refs resolved back into a tree.
    *
    * Shapes are emitted as a graph since §5.2.16 — each type defined once in
    * the endpoint's `type_defs` and referenced wherever it occurs. Conformance
    * assertions are about the CONTRACT (which fields exist, what they are,
    * which terminals were reached), not about how the wire carries it, so they
    * resolve first. That those assertions still hold unchanged across the
    * change is the evidence that the shared form is lossless.
    *
    * A ref already on the resolution path is left alone: that is a real cycle
    * in the type, and inlining it would not terminate.
    */
  def resolveRefs(value: ujson.Value, defs: ujson.Obj, path: Set[String] = Set.empty): ujson.Value =
    value match {
      case o: ujson.Obj if o.obj.get("kind").exists(_.str == "ref") =>
        val name = o("type_name").str
        if (path.contains(name)) o
        else
          defs.obj.get(name) match {
            case Some(definition) => resolveRefs(definition, defs, path + name)
            case None             => o
          }
      case o: ujson.Obj =>
        val out = ujson.Obj.from(o.obj.view.filterKeys(k => k != "fields" && k != "element").toSeq)
        o.obj.get("fields").foreach { fs =>
          out("fields") = ujson.Arr.from(fs.arr.map { f =>
            val fo = ujson.Obj.from(f.obj.view.filterKeys(_ != "shape").toSeq)
            fo("shape") = resolveRefs(f("shape"), defs, path)
            fo
          })
        }
        o.obj.get("element").foreach(e => out("element") = resolveRefs(e, defs, path))
        out
      case other => other
    }

  /** `endpoint("response_schema")` with that endpoint's refs resolved. */
  def resolvedShape(endpoint: ujson.Value, key: String = "response_schema"): ujson.Value = {
    val defs = endpoint.obj.get("type_defs").map(v => ujson.Obj.from(v.obj.toSeq)).getOrElse(ujson.Obj())
    resolveRefs(endpoint(key), defs)
  }
}
