package wadi

import org.objectweb.asm.{ClassReader, Opcodes}
import org.objectweb.asm.tree.{
  AbstractInsnNode,
  ClassNode,
  JumpInsnNode,
  LookupSwitchInsnNode,
  MethodNode,
  TableSwitchInsnNode
}
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

import java.nio.file.{Files, Path, Paths}
import scala.jdk.CollectionConverters.*

/** §5.2.8 M3: the independent bytecode oracle — the first check that is not
  * wadi-checking-wadi. javac compiles the SAME matrix source the CPG parses;
  * ASM derives per-method decision-point and loop counts from the bytecode and
  * diffs them against the exported coarse graph. Every divergence must be a
  * whitelisted javac desugaring (recorded in §5.2.8), or the test fails:
  * an unexplained divergence is a bug on one side or the other.
  *
  * Requires `mvn -q -f fixtures/control-flow-matrix/pom.xml compile`
  * (CI runs it before sbt test); the suite cancels with instructions when
  * `target/classes` is absent.
  *
  * Counts are also pinned in `expected/cfg/bytecode-oracle.json`
  * (WADI_REGEN_CFG_GOLDENS=1 regenerates) so drift on EITHER side — a javac
  * upgrade or a coarsening change — is loud.
  */
class BytecodeOracleTest extends AnyFunSuite with Matchers with FixtureCpg {

  private val classesDir =
    Paths.get("fixtures", "control-flow-matrix", "target", "classes").toAbsolutePath
  private val goldenPath = Paths
    .get("fixtures", "control-flow-matrix", "expected", "cfg", "bytecode-oracle.json")
    .toAbsolutePath
  private val regen = sys.env.get("WADI_REGEN_CFG_GOLDENS").contains("1")

  /** Divergence whitelist (§5.2.8): javac desugarings where bytecode counts
    * legitimately differ from the source-level coarse graph. A method absent
    * from this map must match EXACTLY.
    */
  private val whitelist: Map[String, List[String]] = Map(
    "ConditionalController.ternary"          -> List("ternary"),
    "ConditionalController.shortCircuit"     -> List("short-circuit"),
    // Same short-circuit class, reached with an ALLOCATION in the
    // short-circuited operand (§5.2.8, 2026-08-05). The allocation's lowering
    // block used to be admitted as a statement, putting a node in neither arm
    // on the branch's successor list; it is now condition interior and
    // collapses into the branch. What remains is the ordinary `&&`/`||`
    // divergence — 2 bytecode conditional jumps against 1 source branch — in
    // the safe direction: the graph never claims MORE decision points than
    // the bytecode.
    "ConditionalController.allocInCondition"       -> List("short-circuit"),
    "ConditionalController.allocInConditionNoElse" -> List("short-circuit"),
    "ConditionalController.allocInOrCondition"     -> List("short-circuit"),
    "SwitchController.onString"              -> List("switch-on-string"),
    "SwitchController.yieldForm"             -> List("switch-lowering", "ternary"),
    // javac folds a constant-true loop test away entirely: `while (true)` and
    // `for (;;)` emit an unconditional GOTO and zero conditional jumps, while
    // the source graph still has a loop node. Source-level truth and bytecode
    // truth genuinely differ here.
    "DegenerateController.infiniteLoop"      -> List("constant-true-condition"),
    "DegenerateController.infiniteFor"       -> List("constant-true-condition"),
    // try-with-resources desugars into null-checks plus a synthetic finally,
    // so the bytecode carries conditionals the source never wrote.
    "DegenerateController.tryWithResources"  -> List("try-with-resources")
  )

  private case class Counts(condJumps: Int, switches: Int, backJumps: Int)

  private def bytecodeCounts(method: MethodNode): Counts = {
    val insns = method.instructions.toArray.toList
    val index = insns.zipWithIndex.toMap
    var cond, switches, back = 0
    insns.foreach {
      case jump: JumpInsnNode =>
        if (jump.getOpcode != Opcodes.GOTO && jump.getOpcode != Opcodes.JSR) cond += 1
        if (index(jump.label.asInstanceOf[AbstractInsnNode]) < index(jump)) back += 1
      case table: TableSwitchInsnNode =>
        switches += 1
        if ((table.dflt :: table.labels.asScala.toList)
            .exists(l => index(l.asInstanceOf[AbstractInsnNode]) < index(table))) back += 1
      case lookup: LookupSwitchInsnNode =>
        switches += 1
        if ((lookup.dflt :: lookup.labels.asScala.toList)
            .exists(l => index(l.asInstanceOf[AbstractInsnNode]) < index(lookup))) back += 1
      case _ => ()
    }
    Counts(cond, switches, back)
  }

  private lazy val bytecode: Map[String, Counts] = {
    val classFiles = Files
      .walk(classesDir)
      .iterator()
      .asScala
      .filter(p => p.toString.endsWith("Controller.class"))
      .toList
    classFiles.flatMap { path =>
      val node   = new ClassNode()
      new ClassReader(Files.readAllBytes(path)).accept(node, ClassReader.SKIP_DEBUG)
      val cls = node.name.split('/').last
      node.methods.asScala
        .filter(m =>
          (m.access & (Opcodes.ACC_SYNTHETIC | Opcodes.ACC_BRIDGE)) == 0 &&
            !m.name.startsWith("<") && !m.name.startsWith("lambda$")
        )
        .map(m => s"$cls.${m.name}" -> bytecodeCounts(m))
    }.toMap
  }

  private lazy val exportJson: ujson.Value =
    exportFixture("control-flow-matrix", "control-flow-matrix-oracle-export")

  /** Per-method coarse-graph decision counts: if nodes, switch nodes
    * (incl. expression-position switch-arrow carriers), loop nodes.
    */
  private lazy val cpg: Map[String, Counts] = {
    val methodName = exportJson("methods").arr.flatMap { m =>
      val beforeSig = m("full_name").str.split(':').head
      val parts     = beforeSig.split('.')
      if (parts.length < 2) None
      else {
        val cls  = parts(parts.length - 2)
        val name = parts.last
        if (cls.endsWith("Controller") && !name.startsWith("<"))
          Some(m("id").num.toLong -> s"$cls.$name")
        else None
      }
    }.toMap
    exportJson("cfgs").arr.flatMap { cfg =>
      methodName.get(cfg("method_id").num.toLong).map { name =>
        val nodes      = cfg("nodes").arr
        def constructs = nodes.flatMap(_.obj.get("construct_kind").map(_.str))
        val ifs        = constructs.count(_ == "if")
        val switchLike = constructs.count(c => c == "switch" || c == "switch-arrow")
        val loops      = nodes.count(_("kind").str == "loop")
        name -> Counts(ifs, switchLike, loops)
      }
    }.toMap
  }

  private def compiledFixtureAvailable: Boolean = Files.isDirectory(classesDir)

  private val sourceDir =
    Paths.get("fixtures", "control-flow-matrix", "src", "main", "java").toAbsolutePath

  /** Newest mtime under a tree, or None when the tree is absent. */
  private def newestMtime(root: Path): Option[Long] =
    if (!Files.isDirectory(root)) None
    else {
      val stream = Files.walk(root)
      try
        stream.iterator().asScala.filter(Files.isRegularFile(_)).map { p =>
          Files.getLastModifiedTime(p).toMillis
        }.maxOption
      finally stream.close()
    }

  /** Are the compiled classes older than the fixture source?
    *
    * Found on 2026-08-05 while adding handlers for the condition-lowering fix:
    * three new methods were invisible to this oracle because `target/classes`
    * predated them, and the suite reported "0 unexplained divergences" over the
    * OLD method set — a check that passes while covering nothing, which is the
    * same failure class as the incident that prompted the work. Availability is
    * not freshness, so staleness fails loudly rather than being assumed away.
    */
  private def compiledFixtureIsStale: Boolean =
    (for {
      classes <- newestMtime(classesDir)
      sources <- newestMtime(sourceDir)
    } yield sources > classes).getOrElse(false)

  test("every divergence between bytecode and graph is whitelisted (§5.2.8)") {
    assume(
      compiledFixtureAvailable,
      s"compile the fixture first: mvn -q -f fixtures/control-flow-matrix/pom.xml compile"
    )
    withClue(
      "fixture source is newer than target/classes — this oracle would compare " +
        "STALE bytecode and report green over the old method set. Recompile: " +
        "mvn -q -f fixtures/control-flow-matrix/pom.xml compile : "
    ) {
      compiledFixtureIsStale shouldBe false
    }

    val rows = bytecode.toList.sortBy(_._1).map { case (name, bc) =>
      val graph = cpg.getOrElse(name, Counts(0, 0, 0))
      val exact =
        bc.condJumps == graph.condJumps + graph.backJumps &&
          bc.switches == graph.switches &&
          bc.backJumps == graph.backJumps
      (name, bc, graph, exact)
    }

    val unexplained = rows.collect {
      case (name, bc, graph, false) if !whitelist.contains(name) =>
        s"$name: bytecode(cond=${bc.condJumps}, switch=${bc.switches}, back=${bc.backJumps})" +
          s" vs graph(if=${graph.condJumps}, switch=${graph.switches}, loop=${graph.backJumps})"
    }
    withClue("unexplained bytecode/graph divergences — a bug on one side or a missing §5.2.8 whitelist entry:\n") {
      unexplained shouldBe empty
    }

    // The FP direction is never whitelisted: the graph must not claim MORE
    // decision points than the bytecode has (phantom branches).
    //
    // Back-jumps count toward the budget because a loop node corresponds to
    // one whether or not javac made its test conditional: `while (true)` folds
    // to an unconditional GOTO, so a budget of cond+switch alone would call a
    // correct loop node a phantom branch.
    rows.foreach { case (name, bc, graph, _) =>
      withClue(s"$name claims more decision points than the bytecode: ") {
        (graph.condJumps + graph.switches + graph.backJumps) should be <=
          (bc.condJumps + bc.switches + bc.backJumps)
      }
    }

    // Loop soundness (FN direction): bytecode loops imply graph loops.
    rows.foreach { case (name, bc, graph, _) =>
      if (bc.backJumps > 0)
        withClue(s"$name has bytecode loops the graph misses entirely: ") {
          graph.backJumps should be > 0
        }
    }

    val whitelistedExact = whitelist.keys.filter(name => rows.exists {
      case (n, _, _, exact) => n == name && exact
    })
    info(
      s"oracle: ${rows.size} methods compared, ${rows.count(_._4)} exact, " +
        s"${rows.count(r => !r._4 && whitelist.contains(r._1))} whitelisted divergences, " +
        s"0 unexplained" +
        (if (whitelistedExact.nonEmpty)
           s" (whitelist entries now exact, prunable: ${whitelistedExact.mkString(", ")})"
         else "")
    )

    // Pin the numbers so drift on either side is loud.
    val golden = ujson.Obj.from(rows.map { case (name, bc, graph, exact) =>
      name -> ujson.Obj(
        "bytecode" -> ujson.Obj(
          "cond_jumps" -> bc.condJumps,
          "switches"   -> bc.switches,
          "back_jumps" -> bc.backJumps
        ),
        "graph" -> ujson.Obj(
          "if_nodes"     -> graph.condJumps,
          "switch_nodes" -> graph.switches,
          "loop_nodes"   -> graph.backJumps
        ),
        "exact"   -> exact,
        "reasons" -> whitelist.getOrElse(name, Nil)
      )
    })
    val rendered = ujson.write(golden, indent = 2) + "\n"
    if (regen || !Files.exists(goldenPath)) {
      Files.createDirectories(goldenPath.getParent)
      Files.writeString(goldenPath, rendered)
      info(s"oracle golden written: $goldenPath")
    } else {
      ujson.read(Files.readString(goldenPath)) shouldBe golden
    }
  }
}
