package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Call,
  CfgNode,
  ControlStructure,
  JumpTarget,
  Method,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import java.nio.file.{Files, Path, Paths, StandardOpenOption}
import scala.collection.mutable

import wadi.slicing.UrlSlicer

/** Bulk subgraph export (§5.1): the endpoint-reachable closure as JSON.
  *
  * Writes `export.json` (the Scala↔Python contract; see
  * `wadi_joern_client/export.py`, version below must track its major) to the
  * shared workspace volume. The CPGQL channel never carries bulk data.
  *
  * Statement coarsening (§5.2.8): statements are the AST nodes whose parent
  * is a BLOCK (assignments and standalone calls are CALL nodes, control
  * structures and returns their own kinds), plus CATCH/FINALLY handlers
  * (children of their TRY, not of a block). The expression-level CFG is
  * projected onto them, walking transitively THROUGH nodes with no enclosing
  * statement (BLOCKs, JUMP_TARGETs — the synchronized/labeled-jump routing).
  * Edges are then given construct semantics: IF and loop successors labeled
  * true/false (+ a `back` flag on cycle-closing loop edges), switch selectors
  * emit one labeled case/default edge per arm with fallthrough made explicit,
  * try/catch/finally containers route their interiors (catch entry =
  * `exception` edge), and an explicit throw links to its handler on exact
  * catch-type match.
  */
object WadiExport {

  // Follow existing CALL edges only (which include the DI pass's added edges).
  private given ICallResolver = NoResolve

  /** 2.0.0: one sink row PER CANDIDATE value (node_id no longer unique across
    * rows), rows carry call_id / evidence / auth_propagation, endpoints carry
    * auth_tags + params, new top-level security_rules + config_refs sections.
    * 2.1.0 (additive, §5.2.5): new top-level `unreachable_sinks` inventory
    * (http-client sinks outside the endpoint closure, with inline anchors);
    * sinks may carry kind `http-client-suspected` (unresolved receiver) and
    * mechanism `webclient`.
    * 2.2.0 (additive, §5.4.3): new top-level `analysis_coverage` counts —
    * production methods in the CPG vs. the endpoint-reachable subset.
    * 2.3.0 (additive, §5.2.7): endpoints carry `request_schema` /
    * `response_schema` — field-level wire shapes with honest terminals.
    * 2.4.0 (additive, §5.4.2 T4): new top-level `async_roots` (non-endpoint
    * reachability roots, method_id + kind); the closure is rooted at
    * endpoints ∪ async roots and traverses METHOD_REFs (lambdas, method
    * refs), anonymous-class bodies, constructor/`<clinit>` bodies; the
    * coverage denominator counts lambda bodies.
    * 2.5.0 (additive, §5.2.8): CFG nodes carry `construct` (if/switch/
    * switch-arrow/for/foreach/while/do-while/try/catch/finally/throw/break/
    * continue/goto) and real `line_end` extents; SWITCH becomes a `branch`
    * node keeping its selector condition; edges gain labels `case` (with
    * `case_values`), `default`, `fallthrough`, `exception`, and a `back`
    * flag on cycle-closing loop edges; if-without-else emits an explicit
    * `false` join edge; catch/finally handlers are graph nodes; sinks inside
    * conditions/throws/for-headers attach to their statement.
    */
  val ExportSchemaVersion = "2.5.0"

  /** Node ids as JSON numbers (upickle would render Long as String). Graph ids
    * stay far below 2^53, so double precision is exact. */
  private def num(id: Long): ujson.Num = ujson.Num(id.toDouble)

  /** lineNumber is `Option[Int | Integer]` in flatgraph — normalize via string. */
  private def lineOf(value: Option[Int | Integer]): Int =
    value.map(_.toString.toInt).getOrElse(0)

  private val StatementLabels = Set("CALL", "CONTROL_STRUCTURE", "RETURN")
  private val OperatorPrefix  = "<operator"

  def run(cpg: Cpg, outDir: String): String = {
    val endpointMethods = cpg.method.where(_.tag.nameExact("endpoint")).l
    // T4 (§5.4.2): async roots from the service's OWN sources only — a
    // staged-library `@Scheduled` method would root (and duplicate its call
    // sites) into every dependent (§5.2.6 rationale).
    val asyncRootMethods = cpg.method
      .where(_.tag.nameExact("async-root"))
      .filterNot(_.filename.startsWith("wadi-libs/"))
      .l
    val closure   = reachableClosure(endpointMethods ++ asyncRootMethods)
    val methodIds = closure.map(_.id).toSet

    val sinkRows = mutable.ListBuffer.empty[ujson.Obj]

    val methodObjs = closure.map(methodJson)
    val cfgObjs = closure.flatMap { method =>
      val statements = statementsOf(method)
      if (statements.isEmpty && method.cfgNode.isEmpty) None
      else Some(cfgJson(cpg, method, statements, methodIds, sinkRows))
    }
    val endpointObjs = endpointMethods.flatMap { method =>
      method.tag.nameExact("endpoint").value.l.flatMap { value =>
        value.split(" ", 2) match {
          case Array(httpMethod, uri) =>
            Some {
              val obj = ujson.Obj(
                "method_id"   -> num(method.id),
                "http_method" -> httpMethod,
                "uri"         -> uri,
                "auth_tags"   -> method.tag.nameExact("auth").value.l.map(v => s"auth=$v"),
                "params"      -> endpointParamObjs(method)
              )
              // §5.2.7: field-level wire shapes, honest terminals.
              TypeShapes
                .returnTypeTextOf(method)
                .flatMap(TypeShapes.shapeOf(cpg, _))
                .foreach(shape => obj("response_schema") = shape)
              requestBodyTypeText(method)
                .flatMap(TypeShapes.shapeOf(cpg, _))
                .foreach(shape => obj("request_schema") = shape)
              obj
            }
          case _ => None
        }
      }
    }
    val modelObjs = cpg.typeDecl.where(_.tag.nameExact("model")).l.map { typeDecl =>
      ujson.Obj(
        "entity" -> typeDecl.name,
        "fields" -> typeDecl.member.l.map(m =>
          ujson.Obj("name" -> m.name, "type_name" -> m.typeFullName)
        ),
        "persistence_framework" -> "spring-data",
        "storage_name"          -> ujson.Null
      )
    }

    val unreachableObjs = unreachableSinkObjs(cpg, methodIds)
    val coverageObj     = analysisCoverageObj(cpg, methodIds)
    // T4 (§5.4.2): one row per (method, kind); a method may carry several.
    val asyncRootObjs = asyncRootMethods.flatMap { method =>
      method.tag.nameExact("async-root").value.l.distinct.sorted.map { kind =>
        ujson.Obj("method_id" -> num(method.id), "kind" -> kind)
      }
    }

    val document = ujson.Obj(
      "export_schema_version" -> ExportSchemaVersion,
      "language"              -> "java",
      "methods"               -> methodObjs,
      "cfgs"                  -> cfgObjs,
      "endpoints"             -> endpointObjs,
      "async_roots"           -> asyncRootObjs,
      "sinks"                 -> sinkRows.toList,
      "unreachable_sinks"     -> unreachableObjs,
      "data_models"           -> modelObjs,
      "security_rules"        -> securityRuleObjs(cpg),
      "config_refs"           -> configRefObjs(cpg),
      "analysis_coverage"     -> coverageObj
    )

    val target: Path = Paths.get(outDir)
    Files.createDirectories(target)
    Files.write(
      target.resolve("export.json"),
      ujson.write(document, indent = 2).getBytes("UTF-8"),
      StandardOpenOption.CREATE,
      StandardOpenOption.TRUNCATE_EXISTING
    )
    s"wadi export: ${closure.size} methods, ${endpointObjs.size} endpoints, " +
      s"${asyncRootObjs.size} async roots, " +
      s"${sinkRows.size} sinks, ${unreachableObjs.size} unreachable sinks, " +
      s"coverage ${coverageObj("reachable_production_methods").num.toInt}/" +
      s"${coverageObj("production_methods").num.toInt} -> $outDir/export.json"
  }

  /** Analysis-coverage counts (§5.4.3): how much of the service's own
    * production code the endpoint-reachable closure walks.
    *
    * Denominator filters mirror the closure BFS (internal, name not starting
    * with `<`) plus concrete (an abstract/interface stub has nothing to walk —
    * its implementation counts separately; an *empty* concrete method is still
    * production code) and the service's own sources (`wadi-libs/` staged
    * library code would duplicate into every dependent's denominator, §5.2.6).
    * The numerator intersects the closure with the same set, so T4's
    * root/lambda widening moves both counts together.
    */
  private def analysisCoverageObj(cpg: Cpg, reachableMethodIds: Set[Long]): ujson.Obj = {
    val productionIds = cpg.method
      .filterNot(_.isExternal)
      // T4 refinement (§5.4.3): lambda bodies are real source and count;
      // the remaining `<` exclusions are operators and `<init>`/`<clinit>`
      // (javasrc2cpg synthesizes a default constructor per class with a line
      // number — counting them would add one no-op entry per class; their
      // bodies still enter the closure via the T4 traversal).
      .filter(m => !m.name.startsWith("<") || m.modifier.modifierType.l.contains("LAMBDA"))
      .filterNot(_.modifier.modifierType.l.contains("ABSTRACT"))
      .filterNot(_.filename.startsWith("wadi-libs/"))
      .id
      .toSet
    ujson.Obj(
      "production_methods"           -> productionIds.size,
      "reachable_production_methods" -> productionIds.count(reachableMethodIds.contains)
    )
  }

  /** Anonymous classes are named `Outer$1`-style with a trailing numeric
    * suffix (survey fact, §5.4.2 T4); named nested classes (`Outer$Inner`)
    * do not match.
    */
  private val AnonymousClassName = ".*\\$\\d+$".r

  /** `_refOut`, not `.referencedTypeDecl` — the strict accessor throws on a
    * TYPE missing its mandatory REF edge (the unresolvable-method-ref
    * failure class, benchmark-proven).
    */
  private def inheritsExternalSupertype(td: TypeDecl): Boolean =
    td.inheritsFromOut.l
      .flatMap(_._refOut.collectAll[TypeDecl])
      .filterNot(_.fullName == "java.lang.Object")
      .exists(_.isExternal)

  /** BFS over the T4 reachability edges (§5.4.2), internal methods only:
    *
    *   1. resolved CALL callees (incl. DI-added edges) — operators excluded,
    *      `<init>`/`<clinit>`/`<lambda>N` pass (constructor bodies used to be
    *      filtered out wholesale by `name.startsWith("<")`);
    *   2. METHOD_REF targets — javasrc2cpg binds lambdas and method
    *      references (`this::x`) via METHOD_REF, not CALL;
    *   3. an anonymous class's other methods once its `<init>` is reached —
    *      its overrides dispatch through the external interface
    *      (`java.lang.Runnable.run`) and are invisible to call-edge BFS;
    *      instantiated-where-defined makes this the honest over-approximation;
    *   4. the visited method's class `<clinit>` and `<init>` constructors —
    *      if any method of a class runs, the class was loaded (static init
    *      ran) and an instance was constructed; the constructor half makes
    *      DI-bean constructors reachable (Spring beans are never `new`ed in
    *      user code).
    */
  private def reachableClosure(roots: List[Method]): List[Method] = {
    val ordered = mutable.LinkedHashMap.empty[Long, Method]
    val queue   = mutable.Queue.from(roots)
    def enqueue(m: Method): Unit = if (!ordered.contains(m.id)) queue.enqueue(m)
    while (queue.nonEmpty) {
      val current = queue.dequeue()
      if (!ordered.contains(current.id)) {
        ordered.put(current.id, current)
        current.call.callee
          .filterNot(_.isExternal)
          .filterNot(_.name.startsWith(OperatorPrefix))
          .l
          .foreach { callee =>
            enqueue(callee)
            if (callee.name == "<init>") {
              callee.typeDecl.l.foreach { td =>
                if (AnonymousClassName.matches(td.name)) {
                  // Anonymous: all methods (instantiated-where-defined).
                  td.method.filterNot(_.isExternal).l.foreach(enqueue)
                } else if (inheritsExternalSupertype(td)) {
                  // Named class behind an external supertype (`PollThread
                  // extends Thread`): the override surface runs through the
                  // external parent, invisible to call-edge BFS.
                  td.method
                    .filterNot(_.isExternal)
                    .filterNot(_.name.startsWith("<"))
                    .filterNot(_.modifier.modifierType.l.contains("STATIC"))
                    .filterNot(_.modifier.modifierType.l.contains("PRIVATE"))
                    .l
                    .foreach(enqueue)
                }
              }
            }
          }
        // NOT `.referencedMethod` — that accessor treats the REF edge as
        // mandatory and THROWS on unresolvable method refs (`Unknown::x`),
        // which real repos are full of; `_refOut` is the tolerant spelling.
        current.ast.isMethodRef.l
          .flatMap(_._refOut.collectAll[Method])
          .filterNot(_.isExternal)
          .foreach(enqueue)
        current.typeDecl.method
          .nameExact("<clinit>", "<init>")
          .filterNot(_.isExternal)
          .l
          .foreach(enqueue)
      }
    }
    ordered.values.toList
  }

  /** Declared endpoint params from parameter annotations (§7 `Endpoint.params`).
    *
    * Unannotated parameters are omitted — injected framework arguments
    * (HttpServletRequest, Principal, …) are not API surface, and guessing
    * would violate P10.
    */
  private val ParamAnnotationLocations = Map(
    "PathVariable"  -> "path",
    "RequestParam"  -> "query",
    "RequestBody"   -> "body",
    "RequestHeader" -> "header"
  )

  /** The declared type text of the @RequestBody parameter, when present. */
  private def requestBodyTypeText(method: Method): Option[String] =
    method.parameter.indexGt(0).l
      .find(_.ast.isAnnotation.exists(_.name == "RequestBody"))
      .flatMap { parameter =>
        val code    = parameter.code
        val nameIdx = code.lastIndexOf(parameter.name)
        if (nameIdx <= 0) None
        else {
          val before = code.substring(0, nameIdx).trim
          // Trailing token, <>-aware — annotations are earlier tokens.
          var depth = 0
          var idx   = before.length - 1
          var cut   = -1
          while (idx >= 0 && cut < 0) {
            val c = before(idx)
            if (c == '>') depth += 1
            else if (c == '<') depth -= 1
            else if (c.isWhitespace && depth == 0) cut = idx
            idx -= 1
          }
          Some(if (cut < 0) before else before.substring(cut + 1)).filter(_.nonEmpty)
        }
      }

  private def endpointParamObjs(method: Method): ujson.Arr = {
    val rows = method.parameter.indexGt(0).sortBy(_.index).flatMap { parameter =>
      parameter.ast.isAnnotation.flatMap { annotation =>
        ParamAnnotationLocations.get(annotation.name).map { location =>
          val explicitName = "\"([^\"]*)\"".r.findFirstMatchIn(annotation.code).map(_.group(1))
          val required     = !annotation.code.contains("required = false") &&
            !annotation.code.contains("required=false")
          ujson.Obj(
            "name"      -> explicitName.filter(_.nonEmpty).getOrElse(parameter.name),
            "location"  -> location,
            "type_name" -> parameter.typeFullName,
            "required"  -> required
          )
        }
      }.headOption
    }
    ujson.Arr(rows.toSeq*)
  }

  private def methodJson(method: Method): ujson.Obj =
    ujson.Obj(
      "id"          -> num(method.id),
      "full_name"   -> method.fullName,
      "signature"   -> method.signature,
      "filename"    -> method.filename,
      "line"        -> lineOf(method.lineNumber),
      "line_end"    -> lineOf(method.lineNumberEnd),
      "code"        -> firstLine(method.code),
      "doc_comment" -> ujson.Null,
      "return_type" -> method.methodReturn.typeFullName,
      "params" -> method.parameter.indexGt(0).l.map(p =>
        ujson.Obj("name" -> p.name, "type_name" -> p.typeFullName)
      ),
      "tags" -> method.tag.l.map(t => s"${t.name}=${t.value}")
    )

  /** Container control structures may legitimately hold nested statements;
    * everything else (calls, returns, throws) is a leaf — frontend lowering
    * artifacts inside them (e.g. `throw new X()` desugaring) are not statements.
    * MATCH (arrow switch) is a container so block-bodied `yield` arm interiors
    * survive; CATCH/FINALLY are containers so handler bodies stay legible.
    */
  private val ContainerStructureTypes =
    Set("IF", "FOR", "WHILE", "DO", "SWITCH", "MATCH", "TRY", "CATCH", "FINALLY", "ELSE")

  private val HandlerStructureTypes = Set("CATCH", "FINALLY")
  private val LoopStructureTypes    = Set("FOR", "WHILE", "DO")

  private def isLeafStatement(node: AstNode): Boolean = node match {
    case cs: ControlStructure => !ContainerStructureTypes.contains(cs.controlStructureType)
    case _                    => true
  }

  /** Statement admission (§5.2.8): block children, plus CATCH/FINALLY handlers
    * whose AST parent is their TRY control structure, never a block.
    */
  private def isStatementPosition(node: AstNode): Boolean =
    node.astParent.isBlock || (node match {
      case cs: ControlStructure if HandlerStructureTypes.contains(cs.controlStructureType) =>
        cs.astParent match {
          case parent: ControlStructure => parent.controlStructureType == "TRY"
          case _                        => false
        }
      case _ => false
    })

  /** Statement nodes of a method: AST children of blocks, in line order,
    * excluding lowering artifacts nested inside leaf statements.
    */
  private def statementsOf(method: Method): List[AstNode] = {
    val candidates = method.ast
      .filter(node => StatementLabels.contains(node.label))
      .filter(isStatementPosition)
      .filterNot {
        case call: Call => call.name == "<operator>.fieldAccess" // bare field reads aren't statements
        case _          => false
      }
      .l
    val candidateIds = candidates.map(_.id).toSet
    candidates
      .filterNot(node => hasLeafStatementAncestor(node, candidateIds, candidates))
      .sortBy(n => (lineOf(n.lineNumber), n.id))
  }

  private def hasLeafStatementAncestor(
    node: AstNode,
    candidateIds: Set[Long],
    candidates: List[AstNode]
  ): Boolean = {
    val leafIds = candidates.filter(isLeafStatement).map(_.id).toSet
    var current = node.astParent
    while (current != null && !current.isInstanceOf[Method]) {
      current match {
        // An expression-position MATCH shields its interior: `int b = switch(n)
        // {...}` is a leaf CALL, but the yield-arm statements inside the MATCH
        // are real statements, not lowering artifacts.
        case cs: ControlStructure if cs.controlStructureType == "MATCH" => return false
        case _                                                          => ()
      }
      if (leafIds.contains(current.id) && candidateIds.contains(current.id)) return true
      current = current.astParent
    }
    false
  }

  /** Nearest enclosing statement for every node in the method (walk up the AST). */
  private def nearestEnclosingStatement(
    method: Method,
    statementIds: Set[Long]
  ): mutable.Map[Long, Long] = {
    val enclosing = mutable.Map.empty[Long, Long]
    method.ast.l.foreach { node =>
      var current: AstNode = node
      var done             = false
      var steps            = 0
      while (!done && steps < 10_000) {
        if (statementIds.contains(current.id)) {
          enclosing(node.id) = current.id
          done = true
        } else if (current.isInstanceOf[Method]) {
          done = true // reached the method root: node sits outside any statement
        } else {
          current = current.astParent
        }
        steps += 1
      }
    }
    enclosing
  }

  private def cfgJson(
    cpg: Cpg,
    method: Method,
    statements: List[AstNode],
    exportedMethodIds: Set[Long],
    sinkRows: mutable.ListBuffer[ujson.Obj]
  ): ujson.Obj = {
    val statementIds = statements.map(_.id).toSet

    // Nearest-enclosing mapping: a node inside an if-body maps to its own
    // statement, not to the outer if (a first-claimant map would mislabel
    // branch targets as self-loops).
    val enclosing = nearestEnclosingStatement(method, statementIds)

    val nodeObjs = statements.map { statement =>
      val (kind, construct, callInfo) = classify(statement, exportedMethodIds, enclosing)
      callInfo.flatMap(_.sinkTag).foreach { case (sinkKind, sinkCall) =>
        sinkRows ++= sinkRowsFor(cpg, statement.id, method.id, sinkKind, sinkCall)
      }
      val obj = ujson.Obj(
        "id"       -> num(statement.id),
        "kind"     -> kind,
        "code"     -> firstLine(statement.code),
        "line"     -> lineOf(statement.lineNumber),
        "line_end" -> lineEndOf(statement)
      )
      construct.foreach(c => obj("construct_kind") = c)
      callInfo.foreach { info =>
        obj("call") = ujson.Obj(
          "callee_full_name" -> info.calleeFullName,
          "callee_id"        -> info.calleeId.map(id => ujson.Num(id.toDouble)).getOrElse(ujson.Null),
          "resolved"         -> info.resolved,
          "via_di"           -> info.viaDi
        )
      }
      statement match {
        case cs: ControlStructure =>
          cs.condition.headOption.foreach(condition => obj("condition_code") = condition.code)
        case _ =>
          // An expression-position arrow switch marks its carrier statement
          // (`return switch(n){…}` / `int b = switch(n){…}`) — §5.2.8.
          expressionMatchOf(statement, enclosing).foreach { m =>
            obj("construct_kind") = "switch-arrow"
            m.condition.headOption.foreach(c => obj("condition_code") = c.code)
          }
      }
      obj
    }

    val projected = projectEdges(method, enclosing)
    val semantics = new EdgeSemantics(projected, statements, statementIds, enclosing)
    semantics.labelIfEdges()
    semantics.labelLoopEdges()
    semantics.routeContainers()
    semantics.labelSwitchEdges()
    semantics.fixJumpEdges()

    ujson.Obj(
      "method_id" -> num(method.id),
      "nodes"     -> nodeObjs,
      "edges"     -> semantics.edgeObjs
    )
  }

  /** Project the expression-level CFG onto statements, walking transitively
    * THROUGH nodes with no enclosing statement (BLOCK wrappers, JUMP_TARGETs —
    * the synchronized/labeled-jump routing, §5.2.8). Self-edges are dropped:
    * every statement's internal expression chain projects onto itself, so a
    * self-edge carries no signal (statement-level self-loops are a recorded
    * non-representable, §5.2.8).
    */
  private def projectEdges(
    method: Method,
    enclosing: mutable.Map[Long, Long]
  ): mutable.LinkedHashSet[(Long, Long)] = {
    val projected = mutable.LinkedHashSet.empty[(Long, Long)]
    method.cfgNode.l.foreach { cfgNode =>
      enclosing.get(cfgNode.id).foreach { sourceStatement =>
        val seen  = mutable.Set.empty[Long]
        val queue = mutable.Queue.empty[CfgNode]
        cfgNode._cfgOut.foreach {
          case c: CfgNode => queue.enqueue(c)
          case _          => ()
        }
        while (queue.nonEmpty) {
          val successor = queue.dequeue()
          if (seen.add(successor.id)) {
            enclosing.get(successor.id) match {
              case Some(targetStatement) =>
                if (sourceStatement != targetStatement)
                  projected.add((sourceStatement, targetStatement))
              case None =>
                successor._cfgOut.foreach {
                  case c: CfgNode => queue.enqueue(c)
                  case _          => ()
                }
            }
          }
        }
      }
    }
    projected
  }

  /** §5.2.8 construct semantics over the projected statement edges: labeling,
    * container routing, switch case structure, throw→handler linkage.
    */
  private final class EdgeSemantics(
    projected: mutable.LinkedHashSet[(Long, Long)],
    statements: List[AstNode],
    statementIds: Set[Long],
    enclosing: mutable.Map[Long, Long]
  ) {
    private val edges      = mutable.LinkedHashSet.from(projected)
    private val labels     = mutable.Map.empty[(Long, Long), String]
    private val caseValues = mutable.Map.empty[(Long, Long), List[String]]
    private val backEdges  = mutable.Set.empty[(Long, Long)]

    private val statementById = statements.map(s => s.id -> s).toMap

    private def controlStructures(types: Set[String]): List[ControlStructure] =
      statements.collect {
        case cs: ControlStructure if types.contains(cs.controlStructureType) => cs
      }

    /** Statement ids AST-contained in `root` (excluding `root` itself). */
    private def interiorOf(root: AstNode): Set[Long] =
      root.ast.filter(n => n.id != root.id && statementIds.contains(n.id)).map(_.id).toSet

    /** A loop's BODY statements: the last block child (a `for`'s init/update
      * live in the FOR's AST but outside the body — an init→loop edge is the
      * loop ENTRY, never a back edge).
      */
    private def loopBodyOf(loop: ControlStructure): Set[Long] =
      loop.astChildren.isBlock.lastOption.map(interiorOf).getOrElse(Set.empty)

    private def interiorIn(roots: List[AstNode]): Set[Long] =
      roots.flatMap(r => r.ast.filter(n => statementIds.contains(n.id)).map(_.id)).toSet

    /** IF successors: arm-entry edges labeled per arm; without an `else`, the
      * join edge IS where control goes on false — labeled `false` (§5.2.8).
      */
    def labelIfEdges(): Unit =
      controlStructures(Set("IF")).foreach { ifS =>
        val trueIds  = interiorIn(ifS.whenTrue.l)
        val falseIds = interiorIn(ifS.whenFalse.l)
        val hasElse  = ifS.whenFalse.nonEmpty
        edges.filter(_._1 == ifS.id).foreach { edge =>
          if (trueIds.contains(edge._2)) labels(edge) = "true"
          else if (falseIds.contains(edge._2)) labels(edge) = "false"
          else if (!hasElse) labels(edge) = "false"
        }
      }

    /** Loop successors labeled like IF (`true` = body, `false` = exit) plus a
      * `back` flag on cycle-closing edges: interior→loop for for/while/foreach,
      * loop→interior re-entry for do-while (the condition runs after the body).
      * A nested loop's exit edge (inner→outer) is both the inner's `false`
      * successor and the outer's back edge — both marks apply.
      */
    def labelLoopEdges(): Unit =
      controlStructures(LoopStructureTypes).foreach { loop =>
        val body = loopBodyOf(loop)
        val isDo = loop.controlStructureType == "DO"
        edges.foreach { edge =>
          if (edge._1 == loop.id) {
            if (body.contains(edge._2)) {
              labels(edge) = "true"
              // do-while runs its condition AFTER the body: loop→body is the
              // re-entry that closes the cycle. body→loop is forward flow.
              if (isDo) backEdges += edge
            } else labels(edge) = "false"
          } else if (edge._2 == loop.id && body.contains(edge._1) && !isDo) {
            backEdges += edge
          }
        }
      }

    /** TRY/CATCH/FINALLY become routing nodes: every edge entering a
      * container's first interior statement from outside is rerouted through
      * the container node — catch entries as `exception` edges (javasrc2cpg's
      * try-tail→handler approximation made explicit), try/finally entries keep
      * the incoming label. Innermost containers route first so nesting holds.
      */
    def routeContainers(): Unit = {
      val containers = controlStructures(Set("TRY") ++ HandlerStructureTypes)
        .sortBy(cs => -astDepth(cs))
      containers.foreach { container =>
        val interior = interiorOf(container)
        if (interior.nonEmpty) {
          val entry = interior.minBy { id =>
            val s = statementById(id)
            (lineOf(s.lineNumber), id)
          }
          val isCatch = container.controlStructureType == "CATCH"
          val incoming = edges.toList.filter { case (s, t) =>
            t == entry && s != container.id && !interior.contains(s)
          }
          incoming.foreach { edge =>
            val viaContainer = (edge._1, container.id)
            edges -= edge
            edges += viaContainer
            labels(viaContainer) =
              if (isCatch) "exception" else labels.getOrElse(edge, "flow")
            labels.remove(edge)
          }
          // Always connect container→entry — a try that opens the method has
          // no incoming edge to reroute, and an unconnected container would be
          // entry-patched straight to exit downstream.
          val toEntry = (container.id, entry)
          edges += toEntry
          labels.getOrElseUpdate(toEntry, "flow")
        }
      }
    }

    /** Labeled jumps inherit javasrc2cpg's approximation: the label's
      * JUMP_TARGET re-enters at the labeled statement's start — for
      * `continue outer` an acceptable statement-level shape, for `break outer`
      * a false cycle (a break EXITS the loop). Redirect: a break edge landing
      * inside an enclosing loop's subtree goes to that loop's `false` (exit)
      * successors instead; a continue edge landing inside goes to the loop
      * node itself. Every continue→loop edge is cycle-closing → `back`.
      */
    def fixJumpEdges(): Unit = {
      val jumps = controlStructures(Set("BREAK", "CONTINUE"))
      jumps.foreach { jump =>
        val isBreak = jump.controlStructureType == "BREAK"
        val enclosingLoops = enclosingChain(jump).collect {
          case cs: ControlStructure
              if LoopStructureTypes.contains(cs.controlStructureType) &&
                statementIds.contains(cs.id) =>
            cs
        }
        edges.toList.filter(_._1 == jump.id).foreach { edge =>
          val target = edge._2
          enclosingLoops.find(l => l.id == target || interiorOf(l).contains(target)) match {
            case Some(loop) if isBreak =>
              edges -= edge
              labels.remove(edge)
              edges.toList.filter(e => e._1 == loop.id && labels.get(e).contains("false")).foreach {
                exitEdge =>
                  val redirected = (jump.id, exitEdge._2)
                  edges += redirected
                  labels.getOrElseUpdate(redirected, "flow")
              }
            case Some(loop) if !isBreak && target != loop.id =>
              edges -= edge
              labels.remove(edge)
              val toLoop = (jump.id, loop.id)
              edges += toLoop
              labels.getOrElseUpdate(toLoop, "flow")
              backEdges += toLoop
            case Some(loop) => // continue already targeting its loop node
              backEdges += edge
            case None => ()
          }
        }
      }
    }

    /** Switch selectors (classic SWITCH and statement-position MATCH): label
      * each selector→arm edge `case`/`default` with the arm's stacked case
      * values; rewrite the projection's fallthrough artifact (body→switch,
      * a fabricated cycle) into an explicit body→next-arm `fallthrough` edge;
      * drop the phantom selector→join edge when a `default` arm exists.
      */
    def labelSwitchEdges(): Unit =
      controlStructures(Set("SWITCH", "MATCH")).foreach { switch =>
        val interior = interiorOf(switch)
        val groups   = caseGroupsOf(switch)
        val groupOfStatement: Map[Long, Int] = groups.zipWithIndex.flatMap {
          case (group, idx) => group.statementIds.map(_ -> idx)
        }.toMap
        val entryEdgeTarget = mutable.Map.empty[Int, Long]

        edges.filter(_._1 == switch.id).toList.foreach { edge =>
          groupOfStatement.get(edge._2) match {
            case Some(idx) =>
              val group = groups(idx)
              entryEdgeTarget(idx) = edge._2
              if (group.isDefault) labels(edge) = "default"
              else {
                labels(edge) = "case"
                caseValues(edge) = group.values
              }
            case None =>
              // Selector→join: infeasible when a default arm exists (§5.2.8).
              if (groups.exists(_.isDefault)) {
                edges -= edge
                labels.remove(edge)
              }
          }
        }

        // Fallthrough artifacts: an interior statement's edge BACK to the
        // switch is the projection of body-end→next-JUMP_TARGET.
        edges.toList.filter(e => e._2 == switch.id && interior.contains(e._1)).foreach { edge =>
          edges -= edge
          labels.remove(edge)
          groupOfStatement.get(edge._1).foreach { idx =>
            groups.zipWithIndex.drop(idx + 1).collectFirst {
              case (g, i) if g.statementIds.nonEmpty => i
            }.foreach { nextIdx =>
              val target = entryEdgeTarget
                .get(nextIdx)
                .orElse(groups(nextIdx).firstStatementId(statementById, enclosing))
              target.foreach { t =>
                val fallthrough = (edge._1, t)
                edges += fallthrough
                labels(fallthrough) = "fallthrough"
              }
            }
          }
        }
      }

    // Throw→handler linkage is deliberately absent: javasrc2cpg drops the
    // catch parameter (no Local, no type — §5.2.8), so typed matching is
    // impossible and an untyped guess would mislead the map (P10).

    def edgeObjs: List[ujson.Obj] =
      edges.toList.map { case edge @ (source, target) =>
        val obj = ujson.Obj(
          "source" -> num(source),
          "target" -> num(target),
          "label"  -> labels.getOrElse(edge, "flow")
        )
        caseValues.get(edge).foreach(values => obj("case_values") = values)
        if (backEdges.contains(edge)) obj("back") = true
        obj
      }

    // --- switch case structure -------------------------------------------------

    private case class CaseGroup(
      values: List[String],
      isDefault: Boolean,
      bodyRoots: List[AstNode]
    ) {
      lazy val statementIds: Set[Long] =
        bodyRoots.flatMap(r => r.ast.filter(n => n.label != "JUMP_TARGET").map(_.id)).toSet

      def firstStatementId(
        statementById: Map[Long, AstNode],
        enclosing: mutable.Map[Long, Long]
      ): Option[Long] =
        bodyRoots.iterator
          .flatMap(_.ast.l)
          .flatMap(n => enclosing.get(n.id))
          .find(statementById.contains)
    }

    /** Partition a switch body's children into (case labels, arm body) groups
      * in source order; stacked labels (`case 1: case 2:` / `case 1, 2 ->`)
      * share one group.
      */
    private def caseGroupsOf(switch: ControlStructure): List[CaseGroup] = {
      val children = switch.astChildren.isBlock.headOption
        .map(_.astChildren.l)
        .getOrElse(Nil)
        .sortBy(n => n.order)
      val groups        = mutable.ListBuffer.empty[CaseGroup]
      var currentBodies = mutable.ListBuffer.empty[AstNode]
      var currentLabels = List.empty[JumpTarget]
      def flush(): Unit = {
        if (currentLabels.nonEmpty) {
          groups += CaseGroup(
            values = currentLabels.filterNot(_.name == "default").map(_.code),
            isDefault = currentLabels.exists(_.name == "default"),
            bodyRoots = currentBodies.toList
          )
        }
        currentLabels = Nil
        currentBodies = mutable.ListBuffer.empty[AstNode]
      }
      children.foreach {
        case jt: JumpTarget =>
          if (currentBodies.nonEmpty) flush()
          currentLabels = currentLabels ++ List(jt)
        case other =>
          currentBodies += other
      }
      flush()
      groups.toList
    }

    // --- throw→handler matching ------------------------------------------------

    private def astDepth(node: AstNode): Int = {
      var depth   = 0
      var current = node.astParent
      while (current != null && !current.isInstanceOf[Method] && depth < 10_000) {
        depth += 1
        current = current.astParent
      }
      depth
    }

    /** All AST-ancestor control structures of a node, nearest first. */
    private def enclosingChain(node: AstNode): List[ControlStructure] = {
      val chain   = mutable.ListBuffer.empty[ControlStructure]
      var current = node.astParent
      var steps   = 0
      while (current != null && !current.isInstanceOf[Method] && steps < 10_000) {
        current match {
          case cs: ControlStructure => chain += cs
          case _                    => ()
        }
        current = current.astParent
        steps += 1
      }
      chain.toList
    }
  }

  private def lineEndOf(statement: AstNode): Int = {
    val own = lineOf(statement.lineNumber)
    val max = statement.ast.flatMap(n => n.lineNumber.map(_.toString.toInt)).maxOption.getOrElse(own)
    math.max(own, max)
  }

  /** The MATCH control structure carried in expression position by this
    * statement (its own enclosing statement is this one), if any.
    */
  private def expressionMatchOf(
    statement: AstNode,
    enclosing: mutable.Map[Long, Long]
  ): Option[ControlStructure] =
    statement.ast
      .collectAll[ControlStructure]
      .find(m => m.controlStructureType == "MATCH" && enclosing.get(m.id).contains(statement.id))

  private case class CallInfo(
    calleeFullName: String,
    calleeId: Option[Long],
    resolved: Boolean,
    viaDi: Boolean,
    sinkTag: Option[(String, Call)]
  )

  private def constructOf(cs: ControlStructure): String = cs.controlStructureType match {
    case "IF"       => "if"
    case "SWITCH"   => "switch"
    case "MATCH"    => "switch-arrow"
    case "FOR"      => "for"
    case "WHILE"    => if (cs.code == "FOR") "foreach" else "while"
    case "DO"       => "do-while"
    case "TRY"      => "try"
    case "CATCH"    => "catch"
    case "FINALLY"  => "finally"
    case "THROW"    => "throw"
    case "BREAK"    => "break"
    case "CONTINUE" => "continue"
    case "GOTO"     => "goto"
    case other      => other.toLowerCase
  }

  private def classify(
    statement: AstNode,
    exportedMethodIds: Set[Long],
    enclosing: mutable.Map[Long, Long]
  ): (String, Option[String], Option[CallInfo]) =
    statement match {
      case cs: ControlStructure =>
        val kind = cs.controlStructureType match {
          case "IF" | "SWITCH" | "MATCH" => "branch"
          case "FOR" | "WHILE" | "DO"    => "loop"
          case _                         => "statement"
        }
        // Calls the node itself owns (condition, for-header, throw argument —
        // never body statements, which claim their own): sinks inside
        // conditions and throws finally produce sink rows (§5.2.8).
        (kind, Some(constructOf(cs)), primaryCallOf(statement, exportedMethodIds, enclosing))
      case _ if statement.label == "RETURN" =>
        ("return", None, primaryCallOf(statement, exportedMethodIds, enclosing))
      case _ =>
        primaryCallOf(statement, exportedMethodIds, enclosing) match {
          case some @ Some(_) => ("call", None, some)
          case None           => ("statement", None, None)
        }
    }

  /** The most interesting real (non-operator) call the statement itself owns
    * (nearest enclosing statement is this one — container bodies never
    * double-claim their statements' calls).
    */
  private def primaryCallOf(
    statement: AstNode,
    exportedMethodIds: Set[Long],
    enclosing: mutable.Map[Long, Long]
  ): Option[CallInfo] = {
    val realCalls = statement.ast.isCall
      .filterNot(_.name.startsWith(OperatorPrefix))
      .filter(call => enclosing.get(call.id).contains(statement.id))
      .l
      .sortBy(_.id)
    // Prefer a tagged sink call, then one that resolves into the export, then the first.
    val chosen = realCalls
      .find(c => c.tag.nameExact("sink").nonEmpty)
      .orElse(realCalls.find(c => c.callee.filterNot(_.isExternal).nonEmpty))
      .orElse(realCalls.headOption)
    chosen.map { call =>
      val internalCallees = call.callee.filterNot(_.isExternal).l
      // An interface method and its DI-resolved implementation can both be
      // internal; prefer the one with a body — that is where the flow goes.
      val concrete = internalCallees
        .find(_.body.astChildren.nonEmpty)
        .orElse(internalCallees.headOption)
      val viaDi = call.tag.nameExact("wadi-di").nonEmpty
      val sink  = call.tag.nameExact("sink").value.headOption.map(kind => (kind, call))
      CallInfo(
        calleeFullName = concrete.map(_.fullName).getOrElse(call.methodFullName),
        calleeId = concrete.map(_.id).filter(exportedMethodIds.contains),
        resolved = internalCallees.nonEmpty,
        viaDi = viaDi,
        sinkTag = sink
      )
    }
  }

  /** One sink row PER CANDIDATE value (export 2.0.0, §5.2 over-approximation).
    *
    * http-client sinks go through the backward slicer; the legacy
    * literal/concat recovery stays as the floor — if slicing recovers nothing
    * but the old syntactic template does, the template wins (results are
    * never worse than Phase 1).
    */
  private def sinkRowsFor(
    cpg: Cpg,
    statementId: Long,
    methodId: Long,
    kind: String,
    call: Call
  ): List[ujson.Obj] = {
    val feignEncoded = call.tag.nameExact("wadi-feign").value.headOption
    // Declared-contract sinks beyond feign (T2): `verb|url|mechanism`.
    val declaredEncoded = call.tag.nameExact("wadi-declared").value.headOption.map(_.split('|'))
    val verb = feignEncoded
      .map(_.split('|').head)
      .orElse(declaredEncoded.map(_.head))
      // WebClient chains carry the verb on the chain root; the sink pass
      // stores it as a tag on the tagged .uri(...) call (§5.2.5).
      .orElse(call.tag.nameExact("wadi-verb").value.headOption)
      .orElse(httpVerbOf(call))
    val clientTag = call.tag.nameExact("wadi-client").value.headOption
    val isHttpKind = kind == "http-client" || kind == "http-client-suspected"
    val mechanism =
      if (feignEncoded.isDefined) Some("feign")
      else if (declaredEncoded.isDefined) Some(declaredEncoded.get.last)
      else if (kind == "http-client-suspected") Some("unknown")
      else if (kind == "http-client") Some(clientTag.getOrElse("resttemplate"))
      else None
    val candidates: List[(Option[String], String, Option[String])] = (feignEncoded, declaredEncoded) match {
      case (Some(encoded), _) =>
        val url = encoded.split('|').last
        List(
          (
            Some(url),
            "high",
            Some(s"feign client: declared mapping composes $url (discovery-name authority)")
          )
        )
      case (None, Some(parts)) =>
        val url = parts(1)
        // A {?} authority is honest: the proxy factory holds the base — the
        // path is declared truth, the base is not (§5.4.2 recorded limit).
        val confidence = if (url.startsWith("{?}")) "heuristic" else "high"
        List(
          (
            Some(url),
            confidence,
            Some(s"declared ${parts.last} contract composes $url")
          )
        )
      case (None, None) if !isHttpKind => List((None, "none", None))
      case _ =>
        val sliced = UrlSlicer.slice(cpg, call)
        val usable = sliced.filter(_.url.isDefined)
        if (usable.nonEmpty) usable.map(c => (c.url, c.confidence, Some(c.evidence)))
        else {
          val (legacyValue, legacyConfidence) = legacyRecoverUrl(call)
          if (legacyValue.isDefined)
            List((legacyValue, legacyConfidence, Some("legacy literal/concat recovery (slice floor)")))
          else
            sliced.take(1).map(c => (None, "none", Some(c.evidence)))
        }
    }
    val authPropagation = call.tag.nameExact("token-propagation").value.headOption
    candidates.map { case (value, confidence, evidence) =>
      ujson.Obj(
        "node_id"          -> num(statementId),
        "call_id"          -> num(call.id),
        "method_id"        -> num(methodId),
        "kind"             -> kind,
        "value"            -> value.map(ujson.Str(_)).getOrElse(ujson.Null),
        "value_confidence" -> (if (value.isDefined) confidence else "none"),
        "http_verb"        -> verb.map(ujson.Str(_)).getOrElse(ujson.Null),
        "mechanism"        -> mechanism.map(ujson.Str(_)).getOrElse(ujson.Null),
        "evidence"         -> evidence.map(ujson.Str(_)).getOrElse(ujson.Null),
        "auth_propagation" -> authPropagation.map(ujson.Str(_)).getOrElse(ujson.Null)
      )
    }
  }

  /** http-client sinks outside the endpoint-reachable closure (§5.2.5).
    *
    * Dead/unwired code is excluded from the architecture map by design, but
    * the exclusion itself is a queryable fact — dropped-silently was a P10
    * violation, and cross-tool comparisons need the inventory to reconcile
    * counts. Anchors are inline because the enclosing methods are not in the
    * export.
    */
  private def unreachableSinkObjs(cpg: Cpg, reachableMethodIds: Set[Long]): List[ujson.Obj] =
    cpg.call
      .where(_.tag.nameExact("sink"))
      .l
      .filterNot(call => reachableMethodIds.contains(call.method.id))
      // Staged library sources (§5.2.6): a library's own unwired code belongs
      // to whichever service reaches it — inventorying it here would duplicate
      // the same rows into every dependent service's export.
      .filterNot(call => call.method.filename.startsWith("wadi-libs/"))
      .sortBy(_.id)
      .flatMap { call =>
        call.tag.nameExact("sink").value.headOption.toList
          .filter(_.startsWith("http-client"))
          .flatMap { kind =>
            sinkRowsFor(cpg, call.id, call.method.id, kind, call).map { row =>
              row("method_full_name") = call.method.fullName
              row("file") = call.method.filename
              row("line") = lineOf(call.lineNumber)
              row
            }
          }
      }

  /** SecurityFilterChain DSL rules from `auth-rule=` tags, CPG-wide — the
    * chain beans live outside the endpoint-reachable closure (§5.1). Order is
    * declaration order (line, then id): the worker applies first-match-wins.
    */
  private def securityRuleObjs(cpg: Cpg): List[ujson.Obj] =
    cpg.call
      .where(_.tag.nameExact("auth-rule"))
      .l
      // Declaration order: chains are outermost-call-first in the AST (the
      // last declared rule wraps the others), so within one line the inner
      // (earlier-declared) rule has the LARGER id — sort id-descending.
      .sortBy(call => (lineOf(call.lineNumber), -call.id))
      .flatMap { call =>
        call.tag.nameExact("auth-rule").value.l.map { encoded =>
          val Array(verb, pattern, access) = encoded.split('|')
          ujson.Obj(
            "pattern"     -> pattern,
            "http_method" -> (if (verb == "*") ujson.Null else ujson.Str(verb)),
            "access"      -> access,
            "kind"        -> "filter-chain",
            "anchor" -> ujson.Obj(
              "file" -> call.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(call.lineNumber)
            ),
            "evidence" -> firstLine(call.code)
          )
        }
      }

  private val HttpVerbs = Set("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE")
  private val HttpMethodArgument = """(?:org\.springframework\.http\.)?HttpMethod\.([A-Z]+)""".r

  private def httpVerbOf(call: Call): Option[String] =
    call.name.toLowerCase match {
      case n if n.startsWith("get")     => Some("GET")
      case n if n.startsWith("post")    => Some("POST")
      case n if n.startsWith("put")     => Some("PUT")
      case n if n.startsWith("delete")  => Some("DELETE")
      case n if n.startsWith("patch")   => Some("PATCH")
      case n if n.startsWith("head")    => Some("HEAD")
      case n if n.startsWith("options") => Some("OPTIONS")
      // exchange/execute carry the verb as an argument (§5.2.5); WebClient's
      // .method(HttpMethod.X) is the same shape.
      case "exchange" | "execute" | "method" => verbArgumentOf(call)
      case _                                 => None
    }

  /** `exchange(url, HttpMethod.PUT, …)`: only a literal enum reference counts —
    * `HttpMethod.valueOf(expr)` and other dynamic verbs stay an honest null
    * (P10), never a guess.
    */
  private def verbArgumentOf(call: Call): Option[String] =
    call.argument
      .argumentIndexGt(0)
      .l
      .sortBy(_.argumentIndex)
      .iterator
      .map(_.code.trim)
      .collectFirst { case HttpMethodArgument(verb) if HttpVerbs.contains(verb) => verb }

  /** Phase-1 literal/concat recovery, kept as the slice floor. */
  private def legacyRecoverUrl(call: Call): (Option[String], String) =
    call.argument.argumentIndex(1).headOption match {
      case Some(argument) if argument.label == "LITERAL" =>
        (Some(stripQuotes(argument.code)), "exact")
      case Some(argument) if argument.label == "CALL" && argument.code.contains("\"") =>
        (Some(concatToTemplate(argument.code)), "heuristic")
      case _ =>
        (None, "none")
    }

  /** `invUrl + "/stock/" + id` -> `{?}/stock/{?}`. */
  private def concatToTemplate(code: String): String = {
    val parts = code.split('+').map(_.trim)
    parts.map { part =>
      if (part.startsWith("\"") && part.endsWith("\"")) stripQuotes(part) else "{?}"
    }.mkString
  }

  /** Every `${key}` config reference in code, CPG-wide (§5.2.4): `@Value`
    * fields and `@FeignClient(url = "${key}")` attributes (T2 — the latter
    * resolved by template expansion all along but was invisible to coverage).
    */
  private def configRefObjs(cpg: Cpg): List[ujson.Obj] = {
    val keyPattern = "\\$\\{([^}:]+)(?::([^}]*))?\\}".r
    val memberRefs = cpg.member.l.flatMap { member =>
      member.ast.isAnnotation.filter(_.name == "Value").headOption.flatMap { annotation =>
        keyPattern.findFirstMatchIn(annotation.code).map { matched =>
          ujson.Obj(
            "key"     -> matched.group(1).trim,
            "default" -> Option(matched.group(2)).map(ujson.Str(_)).getOrElse(ujson.Null),
            "anchor" -> ujson.Obj(
              "file" -> member.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(member.lineNumber)
            ),
            "context" -> firstLine(annotation.code)
          )
        }
      }
    }
    val feignRefs = cpg.typeDecl.filterNot(_.isExternal).l.flatMap { td =>
      td.ast.isAnnotation
        .filter(_.astParent == td)
        .filter(_.name == "FeignClient")
        .headOption
        .flatMap { annotation =>
          keyPattern.findFirstMatchIn(annotation.code).map { matched =>
            ujson.Obj(
              "key"     -> matched.group(1).trim,
              "default" -> Option(matched.group(2)).map(ujson.Str(_)).getOrElse(ujson.Null),
              "anchor" -> ujson.Obj(
                "file" -> td.file.name.headOption.getOrElse("<unknown>"),
                "line" -> lineOf(td.lineNumber)
              ),
              "context" -> firstLine(annotation.code)
            )
          }
        }
    }
    (memberRefs ++ feignRefs).sortBy(obj => (obj("key").str, obj("anchor")("file").str))
  }

  private def stripQuotes(literal: String): String =
    literal.stripPrefix("\"").stripSuffix("\"")

  private def firstLine(code: String): String =
    code.linesIterator.nextOption().getOrElse("").take(500)
}
