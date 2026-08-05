package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Paths}
import scala.jdk.CollectionConverters.*

/** §5.2.8 conformance (P8, Phase 2.6 M1): every construct's coarsened CFG
  * shape is pinned as a golden file — full node/edge structure, not
  * set-membership.
  *
  * Goldens live in `fixtures/control-flow-matrix/expected/cfg/<Class>.<method>.json`
  * in a normalized, id-free form (node keys are `kind@line[#n]`, stable across
  * CPG builds). Regenerate deliberately with
  * `WADI_REGEN_CFG_GOLDENS=1 sbt "testOnly wadi.ControlFlowMatrixConformanceTest"`
  * and review the git diff — a golden change IS a coarsening-behavior change.
  */
class ControlFlowMatrixConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private val goldenDir =
    Paths.get("fixtures", "control-flow-matrix", "expected", "cfg").toAbsolutePath
  private val regen = sys.env.get("WADI_REGEN_CFG_GOLDENS").contains("1")

  private lazy val exportJson: ujson.Value =
    exportFixture("control-flow-matrix", "control-flow-matrix-export")

  /** method-id → (Class.method, cfg) for every controller handler. */
  private lazy val handlerCfgs: Map[String, ujson.Value] = {
    val methodName = exportJson("methods").arr.flatMap { m =>
      val fullName = m("full_name").str
      val beforeSig = fullName.split(':').head
      val parts     = beforeSig.split('.')
      if (parts.length < 2) None
      else {
        val cls    = parts(parts.length - 2)
        val method = parts.last
        if (cls.endsWith("Controller") && !method.startsWith("<")) {
          Some(m("id").num.toLong -> s"$cls.$method")
        } else None
      }
    }.toMap
    exportJson("cfgs").arr.flatMap { cfg =>
      methodName.get(cfg("method_id").num.toLong).map(name => name -> cfg)
    }.toMap
  }

  /** Normalize a cfg to an id-free shape: node keys `kind@line`, `#n`-suffixed
    * on collision in (line, id) order.
    */
  private def normalize(cfg: ujson.Value): ujson.Obj = {
    val nodes = cfg("nodes").arr.toList
    val keyOf = scala.collection.mutable.Map.empty[Long, String]
    val used  = scala.collection.mutable.Map.empty[String, Int]
    nodes.foreach { n =>
      val base  = s"${n("kind").str}@${n("line").num.toInt}"
      val count = used.getOrElse(base, 0)
      used(base) = count + 1
      keyOf(n("id").num.toLong) = if (count == 0) base else s"$base#$count"
    }
    val nodeObjs = nodes.map { n =>
      val obj = ujson.Obj(
        "key"      -> keyOf(n("id").num.toLong),
        "kind"     -> n("kind").str,
        "code"     -> n("code").str,
        "line"     -> n("line").num.toInt,
        "line_end" -> n("line_end").num.toInt
      )
      n.obj.get("construct_kind").foreach(c => obj("construct_kind") = c.str)
      n.obj.get("condition_code").foreach(c => obj("condition_code") = c.str)
      n.obj.get("call").foreach { call =>
        obj("call") = ujson.Obj(
          "callee"   -> call("callee_full_name").str.split(':').head,
          "resolved" -> call("resolved").bool
        )
      }
      obj
    }
    val edgeObjs = cfg("edges").arr.toList
      .map { e =>
        val obj = ujson.Obj(
          "source" -> keyOf(e("source").num.toLong),
          "target" -> keyOf(e("target").num.toLong),
          "label"  -> e("label").str
        )
        e.obj.get("case_values").foreach(v => obj("case_values") = v)
        e.obj.get("back").foreach(b => obj("back") = b)
        obj
      }
      .sortBy(e => (e("source").str, e("target").str, e("label").str))
    ujson.Obj("nodes" -> nodeObjs, "edges" -> edgeObjs)
  }

  test("every controller handler has a pinned golden CFG shape") {
    handlerCfgs.size should be >= 24
    Files.createDirectories(goldenDir)

    val failures = scala.collection.mutable.ListBuffer.empty[String]
    handlerCfgs.toList.sortBy(_._1).foreach { case (name, cfg) =>
      val golden     = goldenDir.resolve(s"$name.json")
      val normalized = normalize(cfg)
      val rendered   = ujson.write(normalized, indent = 2) + "\n"
      if (regen || !Files.exists(golden)) {
        Files.writeString(golden, rendered)
        info(s"golden written: $name")
      } else {
        val expected = ujson.read(Files.readString(golden))
        if (expected != normalized) {
          failures += s"$name:\n--- expected\n${ujson.write(expected, indent = 2)}\n--- actual\n${ujson
              .write(normalized, indent = 2)}"
        }
      }
    }
    if (failures.nonEmpty)
      fail(
        s"${failures.size} golden CFG mismatches (WADI_REGEN_CFG_GOLDENS=1 to regenerate deliberately):\n" +
          failures.mkString("\n\n")
      )

    // No stale goldens: every golden file corresponds to a live handler.
    val liveNames = handlerCfgs.keySet.map(_ + ".json")
    val stale = Files
      .list(goldenDir)
      .iterator()
      .asScala
      .map(_.getFileName.toString)
      // bytecode-oracle.json is the M3 oracle's pinned counts, not a handler golden.
      .filter(f => f.endsWith(".json") && f != "bytecode-oracle.json" && !liveNames.contains(f))
      .toList
    stale shouldBe empty
  }

  test("the export declares schema 2.8.0") {
    exportJson("export_schema_version").str shouldBe "2.10.0"
  }

  test("§5.2.8 cross-cutting: enriched vocabulary is present in the fixture") {
    val allEdges = handlerCfgs.values.flatMap(_("edges").arr).toList
    val labels   = allEdges.map(_("label").str).toSet
    labels should contain allOf ("flow", "true", "false", "case", "default", "fallthrough", "exception")
    allEdges.exists(e => e.obj.get("back").exists(_.bool)) shouldBe true
    allEdges.filter(_("label").str == "case").foreach { e =>
      e.obj.get("case_values").map(_.arr).getOrElse(Nil) should not be empty
    }
    val constructs = handlerCfgs.values
      .flatMap(_("nodes").arr)
      .flatMap(_.obj.get("construct_kind").map(_.str))
      .toSet
    constructs should contain allOf ("if", "switch", "switch-arrow", "for", "foreach", "while",
      "do-while", "try", "catch", "finally", "throw", "break", "continue")
  }

  /** Out-edge labels of every node of `kind` in a handler's CFG. */
  private def armLabels(handler: String, kind: String): Set[String] = {
    val cfg = handlerCfgs(handler)
    val ids = cfg("nodes").arr.filter(_("kind").str == kind).map(_("id").num.toLong).toSet
    cfg("edges").arr.filter(e => ids.contains(e("source").num.toLong)).map(_("label").str).toSet
  }

  test("§5.2.8 T3: an if arm holding no statements still labels its edge") {
    // An arm written only to say nothing happens (`//do nothing`) claims no
    // statement ids, so labeling by containment alone dropped its edge to
    // `flow` — the graph then could not say which way control went.
    armLabels("DegenerateController.emptyThenArm", "branch") shouldBe Set("true", "false")
    armLabels("DegenerateController.emptyElseArm", "branch") shouldBe Set("true", "false")
    // Recorded non-representable: with the only arm empty and no `else`, both
    // outcomes reach the SAME statement and one edge cannot carry two labels.
    armLabels("DegenerateController.emptyThenNoElse", "branch") shouldBe Set("flow")
  }

  test("§5.2.8 T3: a construct that ends its method leaves its exit arm to the assembler") {
    // The export is deliberately exit-free, so the untaken arm has no target
    // here. What must NOT happen is a fabricated successor.
    armLabels("DegenerateController.trailingIf", "branch") shouldBe Set("true")
    armLabels("DegenerateController.trailingLoop", "loop") shouldBe Set("true")
    armLabels("DegenerateController.trailingSwitch", "branch") shouldBe Set("case")
  }

  test("§5.2.8 T3: an empty try body still reaches its handler and its successor") {
    val cfg   = handlerCfgs("DegenerateController.emptyTryBody")
    val nodes = cfg("nodes").arr.map(n => n("id").num.toLong -> n).toMap
    def construct(id: Long): Option[String] = nodes(id).obj.get("construct_kind").map(_.str)

    val fromTry = cfg("edges").arr.filter(e => construct(e("source").num.toLong).contains("try"))
    // The handler is an EXCEPTION path, never normal flow — presenting a catch
    // as `flow` is what made the commented-out body read as the happy path.
    val handlerEdges = fromTry.filter(e => construct(e("target").num.toLong).contains("catch"))
    handlerEdges.map(_("label").str).toSet shouldBe Set("exception")
    // ...and normal completion reaches the statement after the try, which was
    // otherwise orphaned into a false second entry point.
    val normal = fromTry.filter(e => e("label").str == "flow")
    normal.map(e => nodes(e("target").num.toLong)("code").str).toSet shouldBe
      Set("return \"done:\" + hits;")

    val targets = cfg("edges").arr.map(_("target").num.toLong).toSet
    val entries = cfg("nodes").arr.map(_("id").num.toLong).filterNot(targets.contains)
    entries.size shouldBe 1
  }

  /** Edges of `method` as `(sourceCode, label, targetCode)`, with `back`
    * folded into the label so a cycle-closing edge cannot be mistaken for a
    * forward one. */
  private def edgeTriples(method: String): Set[(String, String, String)] = {
    val cfg   = handlerCfgs(method)
    val nodes = cfg("nodes").arr.map(n => n("id").num.toLong -> n("code").str).toMap
    cfg("edges").arr.map { e =>
      val label = e("label").str + (if (e.obj.get("back").exists(_.bool)) "/back" else "")
      (nodes(e("source").num.toLong), label, nodes(e("target").num.toLong))
    }.toSet
  }

  private def entryCount(method: String): Int = {
    val cfg     = handlerCfgs(method)
    val targets = cfg("edges").arr.map(_("target").num.toLong).toSet
    cfg("nodes").arr.map(_("id").num.toLong).count(id => !targets.contains(id))
  }

  test("§5.2.8 T3: an empty try with a predecessor is entered, not skipped") {
    // The empty body projects to nothing, so the preceding statement wired
    // itself straight to the statement AFTER the try. Left alone that gives
    // the try no incoming edge at all — it gets entry-patched downstream and
    // the method reads as having two entry points.
    edgeTriples("DegenerateController.emptyTryAfterWork") shouldBe Set(
      ("this.hits += n", "flow", "try"),
      ("try", "flow", "return \"done:\" + hits;"),
      ("try", "exception", "catch"),
      ("catch", "flow", "return \"caught:\" + n;")
    )
    entryCount("DegenerateController.emptyTryAfterWork") shouldBe 1
  }

  test("§5.2.8 T3: an empty try nested in an if-arm keeps BOTH arms") {
    // Two separate ways to get this wrong, and the fix has to avoid both.
    // Reading only the immediate parent block finds no next sibling, so
    // normal completion goes unwired and a construct whose every successor is
    // a handler is taken to have left the method — the graph would claim this
    // returns. And rerouting the branch's surviving edge through the try
    // would stamp `false` on the path INTO the true arm and delete the skip
    // path outright.
    edgeTriples("DegenerateController.emptyTryNested") shouldBe Set(
      ("if (n > 0)", "true", "try"),
      ("if (n > 0)", "false", "return \"done:\" + hits;"),
      ("try", "flow", "return \"done:\" + hits;"),
      ("try", "exception", "catch"),
      ("catch", "flow", "this.hits = -1")
    )
    entryCount("DegenerateController.emptyTryNested") shouldBe 1
  }

  test("§5.2.8 T3: an empty try completes into its finally, not past it") {
    edgeTriples("DegenerateController.emptyTryFinally") shouldBe Set(
      ("try", "flow", "finally"),
      ("finally", "flow", "this.hits += n"),
      ("this.hits += n", "flow", "return \"done:\" + hits;")
    )
  }

  test("§5.2.8 T3: a try-with-resources enters its BODY, never a handler") {
    // The resource declaration is hoisted to a sibling statement ahead of the
    // TRY, so the body is the container's first block child. Picking the wrong
    // block would make a NON-empty try look empty and route its handler as
    // normal flow — the failure this pins against.
    edgeTriples("DegenerateController.tryWithResources") shouldBe Set(
      ("AutoCloseable c = () -> hits++", "flow", "try"),
      ("try", "flow", "this.hits += n"),
      ("this.hits += n", "flow", "return \"done:\" + hits;"),
      ("this.hits += n", "exception", "catch"),
      ("catch", "flow", "return \"caught:\" + n;")
    )
  }

  test("§5.2.8 T3: a loop with no exit test states no exit arm") {
    // `while (true)` and `for (;;)` present the same label set as a trailing
    // loop — body arm plus a back edge, no exit arm — but there is no exit to
    // name. The condition is the only thing that tells them apart, so it has
    // to be exported: absent for `for (;;)`, literally "true" for the others.
    for (method <- List("infiniteLoop", "infiniteFor")) {
      val loops = handlerCfgs(s"DegenerateController.$method")("nodes").arr
        .filter(_("kind").str == "loop")
      loops.size shouldBe 1
      withClue(s"$method: ")(
        loops.head.obj.get("condition_code").map(_.str) shouldBe
          (if (method == "infiniteLoop") Some("true") else None)
      )
    }
    edgeTriples("DegenerateController.infiniteLoop") shouldBe Set(
      ("while (true)", "true", "this.hits += n"),
      ("this.hits += n", "flow/back", "while (true)")
    )
  }

  test("sinks inside conditions and throws produce sink rows (§5.2.8)") {
    val sinkValues = exportJson("sinks").arr
      .filter(_("kind").str == "http-client")
      .flatMap(s => s.obj.get("value").filter(_ != ujson.Null).map(_.str))
      .toSet
    sinkValues should contain("http://inventory:8080/ping")   // in an if-condition
    sinkValues should contain("http://inventory:8080/status") // inside a throw
  }
}
