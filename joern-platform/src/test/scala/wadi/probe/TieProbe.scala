package wadi.probe

import io.joern.javasrc2cpg.{Config, JavaSrc2Cpg}
import io.joern.x2cpg.X2Cpg
import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.*
import io.shiftleft.semanticcpg.language.*

import java.nio.file.{Files, Path, Paths}
import scala.collection.mutable
import scala.util.Using

import wadi.WadiPipeline

/** Release 1b P3 probe. Throwaway: lives on `probe/p3-tie-break`, never merged.
  *
  * For each service in a manifest it builds the CPG exactly as
  * `WadiPipeline.runFromSource` does, runs the real export, and then writes
  * `nodes.json` beside `export.json`: for every node id the export names, the
  * node's label, its kind and sequence number (the two halves of a Joern id),
  * its file, line, column, `order`, and its AST path (the `order` values from
  * the root down). The Python side compares two runs.
  *
  * Usage: TieProbe <manifest.json> <out-dir>
  * manifest: [{"name": "...", "parse_root": "..."}]
  */
object TieProbe {

  private val IdKeys = Set("id", "method_id", "callee_id", "node_id", "call_id")

  def main(args: Array[String]): Unit = {
    val manifest = ujson.read(Files.readString(Paths.get(args(0)))).arr
    val outBase  = Paths.get(args(1)).toAbsolutePath
    Files.createDirectories(outBase)
    val started = System.currentTimeMillis()
    val summary = ujson.Arr()
    for (entry <- manifest) {
      val name      = entry("name").str
      val parseRoot = entry("parse_root").str
      val outDir    = outBase.resolve(name)
      Files.createDirectories(outDir)
      val t0 = System.currentTimeMillis()
      val result =
        try {
          probeOne(parseRoot, outDir)
          ujson.Obj("name" -> name, "ok" -> true)
        } catch {
          case e: Throwable =>
            ujson.Obj("name" -> name, "ok" -> false, "error" -> s"${e.getClass.getName}: ${e.getMessage}")
        }
      result("seconds") = (System.currentTimeMillis() - t0) / 1000.0
      summary.arr += result
      println(s"[probe] $name ${result.render()}")
    }
    val meta = ujson.Obj(
      "jvm"         -> System.getProperty("java.vm.name"),
      "jvm_version" -> System.getProperty("java.version"),
      "os"          -> s"${System.getProperty("os.name")} ${System.getProperty("os.arch")}",
      "processors"  -> Runtime.getRuntime.availableProcessors(),
      "max_heap_mb" -> Runtime.getRuntime.maxMemory() / (1024 * 1024),
      "pid"         -> ProcessHandle.current().pid(),
      "seconds"     -> (System.currentTimeMillis() - started) / 1000.0,
      "services"    -> summary
    )
    Files.writeString(outBase.resolve("run.json"), meta.render(indent = 1))
  }

  private def probeOne(parseRoot: String, outDir: Path): Unit = {
    val cpgFile = Files.createTempFile("wadi-probe", ".cpg")
    val config = Config()
      .withDelombokMode("types-only")
      .withInputPath(parseRoot)
      .withOutputPath(cpgFile.toString)
      .withIgnoredFilesRegex(WadiPipeline.ExcludeRegex)
    Using.resource(new JavaSrc2Cpg().createCpg(config).get) { cpg =>
      X2Cpg.applyDefaultOverlays(cpg)
      WadiPipeline.run(cpg, outDir.toString)
      val exportDoc = ujson.read(Files.readString(outDir.resolve("export.json")))
      val ids    = mutable.LinkedHashSet.empty[Long]
      collectIds(exportDoc, ids)
      Files.writeString(outDir.resolve("nodes.json"), describe(cpg, ids).render())
    }
    Files.deleteIfExists(cpgFile)
  }

  private def collectIds(value: ujson.Value, into: mutable.Set[Long]): Unit = value match {
    case obj: ujson.Obj =>
      obj.value.foreach { case (key, v) =>
        v match {
          case ujson.Num(n) if IdKeys.contains(key) && n == math.floor(n) => into += n.toLong
          case other                                                    => collectIds(other, into)
        }
      }
    case arr: ujson.Arr => arr.value.foreach(collectIds(_, into))
    case _              => ()
  }

  private def describe(cpg: Cpg, ids: collection.Set[Long]): ujson.Obj = {
    val byId = mutable.HashMap.empty[Long, StoredNode]
    cpg.all.foreach { n =>
      if (ids.contains(n.id())) byId(n.id()) = n
    }
    val nodes = ujson.Obj()
    for (id <- ids) {
      byId.get(id) match {
        case None => nodes(id.toString) = ujson.Obj("missing" -> true)
        case Some(n) =>
          val (path, rooted) = astPath(n)
          val record = ujson.Obj(
            "label"  -> n.label,
            "kind"   -> (id >>> 32),
            "seq"    -> (id & 0xffffffffL),
            "file"   -> fileOf(n).getOrElse("<unknown>"),
            "path"   -> ujson.Arr.from(path.map(ujson.Num(_))),
            "parent" -> rooted
          )
          n match {
            case a: AstNode =>
              a.lineNumber.foreach(l => record("line") = l.intValue)
              a.columnNumber.foreach(c => record("column") = c.intValue)
              record("order") = a.order
            case _ => ()
          }
          nodes(id.toString) = record
      }
    }
    ujson.Obj("node_count" -> cpg.all.size, "nodes" -> nodes)
  }

  /** `order` values from the AST root down to `n`, and whether `n` has an AST parent. */
  private def astPath(n: StoredNode): (List[Int], Boolean) = {
    var path    = List.empty[Int]
    var current = n
    var guard   = 0
    var hasParent = false
    while (guard < 10000) {
      current match {
        case a: AstNode => path = a.order :: path
        case _          => ()
      }
      val parents = current._astIn.l
      if (parents.isEmpty) return (path, hasParent)
      if (current eq n) hasParent = true
      current = parents.head
      guard += 1
    }
    (path, hasParent)
  }

  private def fileOf(n: StoredNode): Option[String] = {
    var current: StoredNode = n
    var guard               = 0
    while (guard < 10000) {
      current match {
        case m: Method         => return Some(m.filename)
        case t: TypeDecl       => return Some(t.filename)
        case b: NamespaceBlock => return Some(b.filename)
        case _                 => ()
      }
      val parents = current._astIn.l
      if (parents.isEmpty) return None
      current = parents.head
      guard += 1
    }
    None
  }
}
