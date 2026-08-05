package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Call,
  CfgNode,
  ControlStructure,
  JumpTarget,
  Literal,
  Method,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import java.nio.file.{Files, Path, Paths, StandardOpenOption}
import scala.collection.mutable

import wadi.packs.{SpringPacks, SpringSecurityPack}
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
    *
    * 2.6.0: (additive, §5.4.2 T5) a call binding to no method in the export
    * carries `unbound_reason`, so a consumer can tell a Lombok-generated
    * accessor (no source exists) from a hole in the map; and (§5.2.8 T3, a
    * semantics change within the existing label vocabulary) an `if` whose arm
    * holds no statements labels its join edge for that arm instead of
    * dropping to `flow`, a TRY enters through its BODY's first statement
    * rather than the lowest-numbered statement anywhere in its subtree, and
    * an empty try body routes its handlers (`exception`) and its normal
    * completion explicitly.
    */
  val ExportSchemaVersion = "2.10.0"

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
              // §5.2.7: field-level wire shapes, honest terminals. The response
              // shape falls back to the return expression when the signature
              // declares a raw wrapper (§5.2.7 amendment) and marks which it read.
              TypeShapes
                .responseShapeOf(cpg, method)
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

    val securityRules = securityRuleObjs(cpg)

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
      "security_rules"        -> securityRules,
      "auth_enforcements"     -> authEnforcementObjs(cpg),
      "method_security"       -> methodSecurityObj(cpg),
      "auth_mechanisms"       -> authMechanismObjs(cpg),
      "config_refs"           -> configRefObjs(cpg),
      "analysis_coverage"     -> coverageObj,
      "auth_extraction"       -> authExtractionObj(cpg, securityRules),
      "auth_policies"         -> authPolicyObjs(cpg),
      "auth_authorities"      -> authAuthorityObjs(cpg)
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
  /** Constructs a bare `break` can bind to besides a loop (JLS §14.15). */
  private val SwitchStructureTypes  = Set("SWITCH", "MATCH")

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
    * excluding lowering artifacts nested inside leaf statements or inside a
    * control structure's condition.
    */
  private def statementsOf(method: Method): List[AstNode] = {
    val candidates = method.ast
      .filter(node => StatementLabels.contains(node.label))
      .filter(isStatementPosition)
      .filterNot {
        case call: Call => call.name == "<operator>.fieldAccess" // bare field reads aren't statements
        case _          => false
      }
      .filterNot(isConditionInterior)
      .l
    val candidateIds = candidates.map(_.id).toSet
    candidates
      .filterNot(node => hasLeafStatementAncestor(node, candidateIds, candidates))
      .sortBy(n => (lineOf(n.lineNumber), n.id))
  }

  /** Is this candidate part of a control structure's CONDITION rather than of
    * its body (§5.2.8, recorded 2026-08-05)?
    *
    * A condition is an expression, so nothing inside one is a statement — but
    * javasrc2cpg lowers an allocation into a BLOCK holding `$obj = new X()`,
    * and that block's children sit in "statement position" by the only test
    * `isStatementPosition` can make locally (their AST parent is a BLOCK).
    * Admitting them put a node in NEITHER arm on the branch's successor list,
    * which `labelIfEdges` labels by arm-interior membership: with an `else`
    * the edge stayed `flow` and surfaced as an `unlabeled-arm` anomaly; with
    * no `else` the empty-arm heuristic stamped it `false`, so the graph grew a
    * second `false` successor that does not exist and the invariants reported
    * clean. Silently wrong is the worse half, and it is the common one —
    * `if (x != null && x.f(new Y()))` is an idiomatic guard clause.
    *
    * Excluding them collapses the lowering into the enclosing control
    * structure, whose own self-edge is dropped as a recorded
    * non-representable — the condition's cost stops being drawn as control
    * flow, which is what the source says.
    *
    * MATCH shields its interior for the same reason it does in
    * `hasLeafStatementAncestor`: an expression-position switch used inside a
    * condition still holds real yield-arm statements.
    */
  private def isConditionInterior(node: AstNode): Boolean = {
    var current: AstNode = node
    var steps            = 0
    while (current != null && !current.isInstanceOf[Method] && steps < 10_000) {
      current.astParent match {
        case cs: ControlStructure if cs.controlStructureType == "MATCH" => return false
        case cs: ControlStructure if cs.condition.id.l.contains(current.id) => return true
        case _                                                             => ()
      }
      current = current.astParent
      steps += 1
    }
    false
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
      val (kind, construct, callInfo) = classify(cpg, statement, exportedMethodIds, enclosing)
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
          "via_di"           -> info.viaDi,
          "unbound_reason"   -> info.unboundReason.map(ujson.Str.apply).getOrElse(ujson.Null)
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
    semantics.labelExpressionMatchEdges()
    semantics.wireOrphanHandlers()
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

    /** IF successors labeled by the set of arms that REACH each target, not by
      * statement containment alone (§5.2.8 T3). A target inside one arm takes
      * that arm's label. The residual (join) edge takes the label of whichever
      * arm is empty — an arm written only to say nothing happens (`//do
      * nothing`) still carries control, and claiming edges by an empty arm's
      * statement ids claims none of them. When BOTH arms are empty-or-absent
      * the residual is genuinely both paths and stays `flow`: one
      * statement-level edge cannot carry two labels (a recorded
      * non-representable, alongside empty-body loop self-edges).
      */
    def labelIfEdges(): Unit =
      controlStructures(Set("IF")).foreach { ifS =>
        val trueIds    = interiorIn(ifS.whenTrue.l)
        val falseIds   = interiorIn(ifS.whenFalse.l)
        val trueEmpty  = trueIds.isEmpty
        val falseEmpty = ifS.whenFalse.isEmpty || falseIds.isEmpty
        edges.filter(_._1 == ifS.id).foreach { edge =>
          if (trueIds.contains(edge._2)) labels(edge) = "true"
          else if (falseIds.contains(edge._2)) labels(edge) = "false"
          else if (trueEmpty && falseEmpty) () // convergent — leave `flow`
          else if (falseEmpty) labels(edge) = "false"
          else if (trueEmpty) labels(edge) = "true"
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
        // A TRY's normal entry is its BODY block's first statement, never a
        // handler. Taking the whole subtree's minimum line worked only
        // because a non-empty body holds the lowest number; a body that is
        // entirely commented out made the container wire itself straight to
        // its own CATCH and present the handler as normal flow (§5.2.8 T3).
        val entryScope =
          if (container.controlStructureType == "TRY") bodyInteriorOf(container) else interior
        // Prefer the body statement control actually ARRIVES at from outside.
        // Ranking the whole body by (line, id) breaks when two statements share
        // a line, because the tiebreak is node id — arbitrary with respect to
        // source order. `Runnable r = new Runnable() { ... };` opening a try
        // puts the allocation call and the declaration on one line, javasrc2cpg
        // numbered the call lower, and the container was wired to the call
        // while the enclosing `if` arm still pointed at the declaration: the
        // reroute matched nothing and the TRY was left with no incoming edge,
        // reported as `disconnected-node`. (Third instance of this shape in one
        // pass — the CFG invariant's own entry pick had it too.) Falling back
        // to positional order keeps a container that opens its method working,
        // where nothing outside points in.
        val arrivesFromOutside = entryScope.filter { id =>
          edges.exists(e => e._2 == id && e._1 != container.id && !interior.contains(e._1))
        }
        val entry = (if (arrivesFromOutside.nonEmpty) arrivesFromOutside else entryScope)
          .minByOption { id =>
            val s = statementById(id)
            (lineOf(s.lineNumber), id)
          }
        entry.foreach { entryId =>
          rerouteThroughContainer(container, interior, entryId)
          // Always connect container→entry — a try that opens the method has
          // no incoming edge to reroute, and an unconnected container would be
          // entry-patched straight to exit downstream.
          val toEntry = (container.id, entryId)
          edges += toEntry
          labels.getOrElseUpdate(toEntry, "flow")
        }
        if (entry.isEmpty && container.controlStructureType == "TRY")
          routeEmptyTryBody(container, interior)
      }
    }

    /** Reroute every edge entering `target` from outside `container` so it
      * enters the container node instead.
      */
    private def rerouteThroughContainer(
      container: ControlStructure,
      interior: Set[Long],
      target: Long,
      keepSources: Set[Long] = Set.empty
    ): Unit = {
      val isCatch = container.controlStructureType == "CATCH"
      val incoming = edges.toList.filter { case (s, t) =>
        t == target && s != container.id && !interior.contains(s) && !keepSources.contains(s)
      }
      incoming.foreach { edge =>
        val viaContainer = (edge._1, container.id)
        edges -= edge
        edges += viaContainer
        labels(viaContainer) =
          if (isCatch) "exception" else labels.getOrElse(edge, "flow")
        labels.remove(edge)
      }
    }

    /** Every handler is reachable from its try, and an empty handler still
      * continues (§5.2.8, recorded 2026-08-05).
      *
      * The normal path leans on javasrc2cpg's try-tail→handler approximation,
      * which `routeContainers` relabels `exception`. Two ordinary shapes leave
      * that approximation with nothing to say, and both projected a CATCH with
      * no incoming edge — an unreachable handler, which on the map reads as
      * "this error path cannot happen":
      *
      *   - an EMPTY catch body (`catch (Exception e) { }`, a swallow) has no
      *     interior, so the container router finds no entry and wires neither
      *     side; the CATCH is fully isolated;
      *   - a try body whose TAIL leaves the method (`throw` / `return` as the
      *     last statement) has no normal tail for the edge to start from, even
      *     though that very throw is what the handler catches.
      *
      * Rather than teach the approximation two more cases, the gap is closed by
      * its invariant: a handler that ended up with no incoming edge gets one
      * from its try, and a handler with no outgoing edge continues where the
      * try does. Runs AFTER the routers, so it only ever fills a hole — a
      * handler they wired correctly is left untouched.
      */
    def wireOrphanHandlers(): Unit =
      controlStructures(Set("TRY")).foreach { tryS =>
        val handlers = tryS.astChildren.l.collect {
          case cs: ControlStructure
              if HandlerStructureTypes.contains(cs.controlStructureType) &&
                statementIds.contains(cs.id) =>
            cs
        }
        handlers.filter(_.controlStructureType == "CATCH").foreach { handler =>
          if (!edges.exists(_._2 == handler.id)) {
            val edge = (tryS.id, handler.id)
            edges += edge
            labels(edge) = "exception"
          }
        }
        handlers.foreach { handler =>
          if (!edges.exists(_._1 == handler.id)) {
            normalCompletionTarget(tryS).foreach { case (target, isBack) =>
              val edge = (handler.id, target)
              edges += edge
              labels.getOrElseUpdate(edge, "flow")
              if (isBack) backEdges += edge
            }
          }
        }
      }

    /** An empty try body has no tail for javasrc2cpg's try-tail→handler
      * approximation to start from and no interior to enter, so the whole
      * construct projects edge-less: the handler is unreachable and the
      * statement AFTER the try is orphaned into a false second entry point.
      * Wire both paths explicitly (§5.2.8 T3) — handlers exceptionally,
      * normal completion into the finally when there is one and otherwise
      * into the try's next sibling statement.
      */
    private def routeEmptyTryBody(tryS: ControlStructure, interior: Set[Long]): Unit = {
      val handlers = tryS.astChildren.l.collect {
        case cs: ControlStructure
            if HandlerStructureTypes.contains(cs.controlStructureType) &&
              statementIds.contains(cs.id) =>
          cs
      }
      val normal = handlers
        .find(_.controlStructureType == "FINALLY")
        .map(id => (id.id, false))
        .orElse(normalCompletionTarget(tryS))
      // An empty body projects to nothing, so a preceding statement wired
      // itself straight to wherever the construct completes, skipping the try.
      // Reroute it, exactly as the non-empty path does — left alone, the try
      // has no incoming edge, gets entry-patched, and the method reads as
      // having two entry points.
      //
      // An ENCLOSING branch or loop is excluded from that reroute: the edge it
      // left behind belongs to the arm that SKIPS the try, so consuming it
      // would stamp that arm's label on the path INTO the try and delete the
      // skip path entirely. Such a container is owed its own arm-labeled edge
      // instead (`armEdgeInto`).
      val enclosing = enclosingChain(tryS).map(_.id).toSet
      normal.foreach { case (target, _) =>
        rerouteThroughContainer(tryS, interior, target, keepSources = enclosing)
      }
      armEdgeInto(tryS).foreach { case (source, label) =>
        val edge = (source, tryS.id)
        edges += edge
        labels(edge) = label
      }
      handlers.filter(_.controlStructureType == "CATCH").foreach { handler =>
        val edge = (tryS.id, handler.id)
        edges += edge
        labels(edge) = "exception"
      }
      normal.foreach { case (target, isBack) =>
        val edge = (tryS.id, target)
        edges += edge
        labels.getOrElseUpdate(edge, "flow")
        if (isBack) backEdges += edge
      }
    }

    /** The arm-labeled edge an enclosing branch or loop owes a construct that
      * OPENS one of its arms but projects to nothing.
      *
      * A non-empty arm gets its entry edge from the raw projection, which
      * `labelIfEdges` then labels. An arm whose first statement is an empty
      * try has no such edge to label — the projection wired the arm straight
      * past it — so the edge has to be created, or the arm reads as absent.
      */
    private def armEdgeInto(node: ControlStructure): Option[(Long, String)] =
      enclosingChain(node).find(cs => statementIds.contains(cs.id)).flatMap { owner =>
        owner.controlStructureType match {
          case "IF" =>
            if (interiorIn(owner.whenTrue.l).contains(node.id)) Some((owner.id, "true"))
            else if (interiorIn(owner.whenFalse.l).contains(node.id)) Some((owner.id, "false"))
            else None
          case t if LoopStructureTypes.contains(t) =>
            Option.when(loopBodyOf(owner).contains(node.id))((owner.id, "true"))
          case _ => None
        }
      }

    /** Statement ids in a container's BODY block — its FIRST block child.
      *
      * Measured, not assumed: a TRY's handlers are CATCH/FINALLY
      * ControlStructures, not blocks, and javasrc2cpg hoists a
      * try-with-resources resource declaration OUT of the TRY to a preceding
      * sibling statement. So the body is the only block child there. Contrast
      * `loopBodyOf`, which takes the LAST block child because a `for`
      * header's clauses precede the body. Pinned by
      * `DegenerateController.tryWithResources`.
      */
    private def bodyInteriorOf(container: ControlStructure): Set[Long] =
      container.astChildren.isBlock.headOption.map(interiorOf).getOrElse(Set.empty)

    /** Where control goes when `node` completes normally, and whether that
      * edge closes a cycle.
      *
      * Searched OUTWARD through the AST, not just in the immediate parent
      * block. A construct at the tail of an if-arm has no next sibling there,
      * but control has not left the method — it continues after the `if`.
      * Reading only the parent returned None, and downstream a node whose
      * every successor is a handler is taken to have left the method, so the
      * graph asserted "on normal completion this returns" for code that
      * plainly does not (§5.2.8 T3).
      *
      * The walk stops at the nearest enclosing LOOP, whose header is where a
      * construct at the tail of the body actually completes to — a
      * cycle-closing edge, flagged as such. None means the walk reached the
      * method boundary: normal completion genuinely leaves the method, which
      * is the one case the exit patch may complete.
      */
    private def normalCompletionTarget(node: AstNode): Option[(Long, Boolean)] = {
      val own     = interiorOf(node) + node.id
      var current = node
      var steps   = 0
      while (current != null && !current.isInstanceOf[Method] && steps < 10_000) {
        steps += 1
        val parent = current.astParent
        if (parent == null) return None
        parent match {
          case cs: ControlStructure
              if LoopStructureTypes.contains(cs.controlStructureType) &&
                statementIds.contains(cs.id) =>
            return Some((cs.id, true))
          case _ => ()
        }
        followingStatementIn(parent, current, own) match {
          case Some(id) => return Some((id, false))
          case None     => ()
        }
        current = parent
      }
      None
    }

    /** The first admitted statement among `child`'s later siblings under
      * `parent`, skipping anything inside `exclude` (the completing
      * construct's own subtree).
      */
    private def followingStatementIn(
      parent: AstNode,
      child: AstNode,
      exclude: Set[Long]
    ): Option[Long] =
      parent.astChildren.l
        .filter(_.order > child.order)
        .sortBy(_.order)
        .iterator
        .flatMap(sibling => sibling.ast.l)
        .flatMap(n => enclosing.get(n.id))
        .find(id => statementIds.contains(id) && !exclude.contains(id))

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
        val chain = enclosingChain(jump)
        val enclosingLoops = chain.collect {
          case cs: ControlStructure
              if LoopStructureTypes.contains(cs.controlStructureType) &&
                statementIds.contains(cs.id) =>
            cs
        }
        // `break` binds to the nearest enclosing BREAKABLE construct, and a
        // switch is one (JLS §14.15). Collecting only loops meant a break
        // inside a switch inside a loop matched the LOOP — its raw target, the
        // switch join, lies within the loop's interior — and was redirected to
        // the loop's exit. The map then claimed those arms leave the loop
        // entirely, and the statement after the switch was left with no
        // incoming edge at all (measured: every `disconnected-node` still
        // standing on the benchmark). `continue` is unaffected: a switch does
        // not capture it, so its nearest binder is still the loop.
        val nearestBreakable = chain.collectFirst {
          case cs: ControlStructure
              if (LoopStructureTypes.contains(cs.controlStructureType) ||
                SwitchStructureTypes.contains(cs.controlStructureType)) &&
                statementIds.contains(cs.id) =>
            cs
        }
        val breakBindsToSwitch =
          isBreak && nearestBreakable.exists(cs => SwitchStructureTypes.contains(cs.controlStructureType))
        edges.toList.filter(_._1 == jump.id).foreach { edge =>
          val target = edge._2
          enclosingLoops.find(l => l.id == target || interiorOf(l).contains(target)) match {
            case Some(_) if breakBindsToSwitch =>
              // The break leaves the SWITCH, not the loop; its raw target — the
              // statement after the switch — is already right.
              ()
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
    /** An arrow switch in EXPRESSION position wires its arms (§5.2.8, 2026-08-05).
      *
      * `Set<Long> x = switch (role) { case "a" -> ...; }` puts the MATCH inside
      * an expression, so the control structure is not itself a statement — its
      * CARRIER is (`x = switch(role) {`, already marked `switch-arrow`).
      * `labelSwitchEdges` filters edges by the control structure's own id and
      * therefore found none, leaving every arm with no incoming edge: reported
      * as `disconnected-node`, and read as unreachable code on the map.
      *
      * What javasrc2cpg emits is arm→carrier — the arm's VALUE flowing into the
      * assignment — with no carrier→arm to match. Statement position gets the
      * shape right, so the fix is to give expression position the same one:
      * carrier→arm labeled `case`/`default`, and each arm continuing to
      * whatever follows the carrier instead of pointing back at it. Fallthrough
      * is deliberately not synthesised — arrow arms do not fall through.
      */
    def labelExpressionMatchEdges(): Unit =
      // Driven from the STATEMENTS, not from `controlStructures`: that helper
      // collects control structures that ARE statements, and the whole point
      // of an expression-position MATCH is that it is not one. Filtering its
      // result for non-statements searched an already-empty list.
      statements.foreach { statement =>
        statement.ast
          .collectAll[ControlStructure]
          .find(m =>
            m.controlStructureType == "MATCH" && enclosing.get(m.id).contains(statement.id)
          )
          .foreach { matchS =>
            val carrier = statement.id
            val groups   = caseGroupsOf(matchS)
            val interior = interiorOf(matchS)
            // NOT `firstStatementId`: it walks outward to the nearest enclosing
            // STATEMENT, and an arrow arm's nearest enclosing statement is the
            // carrier itself — which produced a `case` self-edge on the carrier
            // and left the arm as unreachable as before. The arm's own entry is
            // the lowest-positioned statement the arm and the match interior
            // share, with the carrier excluded by construction.
            val armEntry = groups.flatMap { group =>
              group.statementIds
                .intersect(interior)
                .filter(_ != carrier)
                .toList
                .sortBy(id => (lineOf(statementById(id).lineNumber), id))
                .headOption
                .map(group -> _)
            }
            val armIds = armEntry.map(_._2).toSet
            // Read BEFORE adding arm edges: what the carrier already reaches
            // that is not an arm is where control resumes after the switch.
            val continuations =
              edges.filter(e => e._1 == carrier && !armIds.contains(e._2)).map(_._2).toSet

            armEntry.foreach { case (group, entry) =>
              val edge = (carrier, entry)
              edges += edge
              if (group.isDefault) labels(edge) = "default"
              else {
                labels(edge) = "case"
                caseValues(edge) = group.values
              }
            }

            edges.toList.filter(e => e._2 == carrier && interior.contains(e._1)).foreach { edge =>
              edges -= edge
              labels.remove(edge)
              continuations.foreach { target =>
                if (target != edge._1) edges += ((edge._1, target))
              }
            }
          }
      }

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
    sinkTag: Option[(String, Call)],
    unboundReason: Option[String]
  )

  /** Why a call binds to no method in this export (§5.4.2 T5, export 2.6.0).
    *
    * P10: an unresolved call is a legitimate, common outcome — 92.9% of them
    * on the train-ticket benchmark are Lombok accessors that HAVE no source —
    * but a consumer that is only told "unresolved" cannot tell a generated
    * accessor from a hole in the map. The reason travels with the call so a
    * dead-end node can say why it dead-ends.
    */
  private object UnboundReason {
    /** Accessor/constructor synthesized by Lombok. Analysis runs on ORIGINAL
      * source (`--delombok-mode types-only`, §5.3) so anchors stay on
      * committed text — which means these bodies do not exist to show. */
    val LombokGenerated = "lombok-generated"

    /** Declared by an external supertype (Spring Data `CrudRepository.save`,
      * etc.); the first-party interface only inherits it. */
    val InheritedExternal = "inherited-external"

    /** `values`/`valueOf` on an enum — emitted by javac, absent from source. */
    val CompilerGenerated = "compiler-generated"

    /** The declaring type is not in this CPG at all (JDK, framework, or a
      * type no staged source root provides). */
    val ThirdParty = "third-party"

    /** The declaring type IS first-party and declares this name, but the
      * receiver type could not be bound to one overload — never guessed. */
    val AmbiguousOverload = "ambiguous-overload"

    /** The receiver's TYPE is a javasrc2cpg sentinel — it could not be bound at
      * all, so nothing downstream can name the callee. */
    val UnresolvedReceiver = "unresolved-receiver"

    /** The first-party type declares exactly this method, and the call still
      * did not bind. The ACTIONABLE bucket (§5.2.11 T5): every other code here
      * describes something analysis cannot see, this one describes something
      * it saw and failed to connect. */
    val DeclaredNotBound = "declared-not-bound"

    /** A first-party type in the CPG that declares no such method — a static
      * import attributed to the importing class (`ok(…)` from
      * `ResponseEntity.ok` is the common one). Not a hole in the map: the
      * callee is real and elsewhere. */
    val NotDeclared = "not-declared"

    /** The callee name carries no type qualifier to split on. */
    val UnparseableCallee = "unparseable-callee"
  }

  /** Lombok annotations, grouped by what each ACTUALLY generates.
    *
    * Split by accessor direction on purpose: `@Getter` generates no setters,
    * and `@Value` generates none either (it is immutable). One combined set
    * let a `setX()` call on such a class be reported `lombok-generated`, which
    * the UI renders as "Lombok generates this accessor … there is nothing
    * hidden here" — a positive claim that no source exists, about a method
    * Lombok never wrote.
    *
    * Both are read at CLASS and FIELD level, because `@Getter` on the class
    * with `@Setter` on one field is an ordinary idiom and the setter it
    * generates is just as sourceless as a class-level one.
    */
  private val LombokGetterAnnotations =
    Set("Data", "Getter", "Value")
  private val LombokSetterAnnotations =
    Set("Data", "Setter")
  private val LombokConstructorAnnotations =
    Set("Data", "Value", "Builder", "AllArgsConstructor", "NoArgsConstructor", "RequiredArgsConstructor")
  private val LombokObjectMethodAnnotations =
    Set("Data", "Value", "EqualsAndHashCode", "ToString")
  private val ObjectMethodNames = Set("toString", "equals", "hashCode", "canEqual")

  /** javasrc2cpg's sentinels for "this could not be bound" (the same ones
    * SpringDIPass and SpringPacks already screen for). A callee rendered
    * `&lt;unresolvedNamespace&gt;.foo` matches no TypeDecl, so without this it fell
    * through to `third-party` — telling the reader "declared outside every
    * analyzed source root, the JDK or a library" about code that may well be
    * theirs. `unresolved-receiver` exists for exactly this.
    */
  private def isUnresolvedTypeName(typeName: String): Boolean =
    typeName.startsWith("<unresolved") || typeName.startsWith("<empty") ||
      typeName == "ANY" || typeName.startsWith("ANY.")

  /** Does `methodName` start with `prefix` AS a Java accessor prefix?
    *
    * `startsWith` alone matches `settle`, `island` and `getaway`. A generated
    * accessor always capitalizes the property, so the next character has to be
    * uppercase (or `_`, which Lombok keeps for `_field`).
    */
  private def hasAccessorPrefix(methodName: String, prefix: String): Boolean =
    methodName.startsWith(prefix) && methodName.length > prefix.length && {
      val next = methodName.charAt(prefix.length)
      next.isUpper || next == '_'
    }

  /** Split `com.foo.Bar.baz:java.lang.Object()` into its declaring type and
    * method name. javasrc2cpg renders unresolved callees the same way, with
    * `<unresolvedSignature>` in place of the parameter list.
    */
  private def splitCalleeName(fullName: String): Option[(String, String)] = {
    val beforeSignature = fullName.indexOf(':') match {
      case -1 => fullName
      case i  => fullName.substring(0, i)
    }
    beforeSignature.lastIndexOf('.') match {
      case -1 => None
      case i  => Some((beforeSignature.substring(0, i), beforeSignature.substring(i + 1)))
    }
  }

  private def classLevelAnnotations(td: TypeDecl): Set[String] =
    td.ast.isAnnotation.filter(_.astParent == td).name.toSet

  /** Annotations on the type's FIELDS. `@Getter` on the class with `@Setter`
    * on one field generates a setter every bit as sourceless as a class-level
    * one, so a direction-aware check has to see both levels or it trades one
    * mislabel for another. */
  private def fieldLevelAnnotations(td: TypeDecl): Set[String] =
    td.member.flatMap(_.ast.isAnnotation).name.toSet

  /** A Java enum is a TypeDecl inheriting `java.lang.Enum` — javasrc2cpg
    * exposes no `isEnum` flag, and `values`/`valueOf` exist only in bytecode.
    */
  private def isEnumTypeDecl(td: TypeDecl): Boolean =
    td.inheritsFromTypeFullName.exists(_.startsWith("java.lang.Enum"))

  /** Would Lombok have generated `methodName` for this type, given its
    * class-level annotations? Deliberately conservative: a name that does not
    * match a generated shape falls through to the other reasons.
    */
  private def isLombokGenerated(td: TypeDecl, methodName: String): Boolean = {
    val onClass = classLevelAnnotations(td)
    // Accessors can be asked for per field; the class-scoped generators
    // (constructors, equals/hashCode/toString, the builder) cannot.
    lazy val accessorScope = onClass ++ fieldLevelAnnotations(td)
    def hasOnClass(group: Set[String])  = onClass.exists(group.contains)
    def hasAnywhere(group: Set[String]) = accessorScope.exists(group.contains)
    val isGetter = hasAccessorPrefix(methodName, "get") || hasAccessorPrefix(methodName, "is")
    val isSetter = hasAccessorPrefix(methodName, "set")
    if (isGetter && hasAnywhere(LombokGetterAnnotations)) true
    else if (isSetter && hasAnywhere(LombokSetterAnnotations)) true
    else if (methodName == "<init>" && hasOnClass(LombokConstructorAnnotations)) true
    else if (ObjectMethodNames.contains(methodName) && hasOnClass(LombokObjectMethodAnnotations)) true
    else if ((methodName == "builder" || methodName == "build") && onClass.contains("Builder")) true
    else false
  }

  /** Does an EXTERNAL supertype of `td` declare `methodName`?
    *
    * Asking only "does this type have any external supertype" was enough for a
    * class that merely `implements Serializable` to be reported
    * `inherited-external`, which states "declared by a framework supertype,
    * not by the type in your repo" about a method the repo does define. The
    * question the reason answers is about the METHOD, so ask it about the
    * method.
    */
  private def inheritsMethodFromExternal(td: TypeDecl, methodName: String): Boolean = {
    val seen    = mutable.Set.empty[Long]
    val pending = mutable.Queue(td)
    var found   = false
    while (pending.nonEmpty && !found) {
      val current = pending.dequeue()
      if (seen.add(current.id)) {
        val supertypes = current.inheritsFromOut.l
          .flatMap(_._refOut.collectAll[TypeDecl])
          .filterNot(_.fullName == "java.lang.Object")
        supertypes.foreach { parent =>
          // An external supertype has no method bodies in the CPG, so a name
          // match is the strongest evidence available; when it declares
          // nothing at all (a stub TypeDecl) fall back to the name being
          // absent from every first-party ancestor.
          if (parent.isExternal && (parent.method.isEmpty || parent.method.nameExact(methodName).nonEmpty))
            found = true
          else if (!parent.isExternal) pending.enqueue(parent)
        }
      }
    }
    found
  }

  /** Classify a call that resolved to no internal method (§5.4.2 T5).
    *
    * TOTAL by contract: the reader contract says a null reason means the call
    * BOUND. Returning None for a callee name this cannot parse would give
    * null a second meaning — "unbindable and unclassifiable" — which a
    * consumer has no way to tell apart from a healthy call, and which is the
    * silent dead end the whole tranche exists to remove (P10). A name with no
    * type qualifier is an unbound receiver, so say that.
    */
  private def unboundReasonOf(cpg: Cpg, call: Call): String =
    splitCalleeName(call.methodFullName).fold(UnboundReason.UnparseableCallee) {
      case (typeName, methodName) =>
        // The answer is a property of the (type, method) pair, not of the call
        // site, and the same pair recurs hundreds of times per service: the
        // benchmark has 1,881 unbound sites over 617 distinct callees, and
        // 92.9% take the Lombok path, which walks the declaring type's whole
        // AST looking for annotations.
        reasonCacheFor(cpg).getOrElseUpdate(
          (typeName, methodName),
          classifyUnbound(cpg, typeName, methodName)
        )
    }

  /** Per-CPG memo for :func:`classifyUnbound`.
    *
    * Weak-keyed on the CPG so a build that goes out of scope — every
    * conformance test builds its own — is not pinned in memory by this cache.
    * Synchronized because nothing here promises the export is single-threaded.
    */
  private val reasonCaches =
    new java.util.WeakHashMap[Cpg, mutable.Map[(String, String), String]]()

  private def reasonCacheFor(cpg: Cpg): mutable.Map[(String, String), String] =
    reasonCaches.synchronized {
      reasonCaches.computeIfAbsent(cpg, _ => mutable.Map.empty)
    }

  private def classifyUnbound(cpg: Cpg, typeName: String, methodName: String): String =
    // A sentinel type name means javasrc2cpg could not bind the receiver at
    // all. It matches no TypeDecl, so without this it fell through to
    // `third-party` — an affirmative claim that the callee lives outside
    // every analyzed source root, which is not something the analysis knows.
    if (isUnresolvedTypeName(typeName)) UnboundReason.UnresolvedReceiver
    else
      cpg.typeDecl.fullNameExact(typeName).filterNot(_.isExternal).headOption match {
        case None => UnboundReason.ThirdParty
        case Some(td) =>
          val declared = td.method.nameExact(methodName).l
          if (declared.sizeIs > 1) UnboundReason.AmbiguousOverload
          else if (declared.nonEmpty) UnboundReason.DeclaredNotBound
          else if (isLombokGenerated(td, methodName)) UnboundReason.LombokGenerated
          else if (isEnumTypeDecl(td) && (methodName == "values" || methodName == "valueOf"))
            UnboundReason.CompilerGenerated
          else if (inheritsMethodFromExternal(td, methodName)) UnboundReason.InheritedExternal
          else UnboundReason.NotDeclared
      }

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
    cpg: Cpg,
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
        (kind, Some(constructOf(cs)), primaryCallOf(cpg, statement, exportedMethodIds, enclosing))
      case _ if statement.label == "RETURN" =>
        ("return", None, primaryCallOf(cpg, statement, exportedMethodIds, enclosing))
      case _ =>
        primaryCallOf(cpg, statement, exportedMethodIds, enclosing) match {
          case some @ Some(_) => ("call", None, some)
          case None           => ("statement", None, None)
        }
    }

  /** The most interesting real (non-operator) call the statement itself owns
    * (nearest enclosing statement is this one — container bodies never
    * double-claim their statements' calls).
    */
  private def primaryCallOf(
    cpg: Cpg,
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
      val calleeId = concrete.map(_.id).filter(exportedMethodIds.contains)
      CallInfo(
        calleeFullName = concrete.map(_.fullName).getOrElse(call.methodFullName),
        calleeId = calleeId,
        resolved = internalCallees.nonEmpty,
        viaDi = viaDi,
        sinkTag = sink,
        // Classify only what actually dead-ends for a consumer: an internal
        // callee the export still carries needs no excuse (§5.4.2 T5).
        unboundReason = Option.when(calleeId.isEmpty)(unboundReasonOf(cpg, call))
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
    // §5.2.11 T4: the mechanism answers HOW auth crosses; the state answers
    // WHETHER, including the case where we can prove it does not.
    val propagationState =
      call.tag.nameExact("token-propagation-state").value.headOption.getOrElse("undetermined")
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
        "auth_propagation"       -> authPropagation.map(ujson.Str(_)).getOrElse(ujson.Null),
        "auth_propagation_state" -> propagationState
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
          // Limit to 3: an `access("a || b")` SpEL expression legitimately
          // contains the separator, and an unlimited split would throw.
          val Array(verb, pattern, access) = encoded.split('|').take(2) :+
            encoded.split('|').drop(2).mkString("|")
          // 2.8.0 (§5.2.10): the scope is a nullable field with a confidence,
          // not a sentinel smuggled into a required string. A sentinel can only
          // be written by a code path that already resolved a matcher, which is
          // precisely why an unreadable chain SHAPE erased its site instead of
          // degrading it.
          val (patternValue, confidence) =
            if (pattern == SpringSecurityPack.Unresolvable) (ujson.Null, "none")
            else if (pattern.startsWith(SpringSecurityPack.ConfigPrefix))
              (ujson.Str(pattern), "config")
            else (ujson.Str(pattern), "exact")
          ujson.Obj(
            // The SITE identity: rows sharing it are one access call with
            // several patterns, exactly as sink rows share `node_id`.
            "call_id"            -> num(call.id),
            "pattern"            -> patternValue,
            "pattern_confidence" -> confidence,
            "http_method" -> (if (verb == "*") ujson.Null else ujson.Str(verb)),
            "access"      -> access,
            "kind"        -> "filter-chain",
            // Chain scope (§5.2.9): rules belong to the bean/override that
            // declared them. A service with several chains must not have its
            // rules pooled into one flat first-match-wins list.
            "chain_id"      -> chainIdOf(call),
            "chain_pattern" -> chainPatternOf(cpg, call),
            "anchor" -> ujson.Obj(
              "file" -> call.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(call.lineNumber)
            ),
            "evidence" -> firstLine(call.code)
          )
        }
      }

  /** What the auth vocabulary SAW versus what it turned into rules (§5.2.10).
    *
    * The in-graph half of the no-drop invariant. `access_calls_seen` counts
    * every call bearing an access-vocabulary name anywhere in the CPG — no
    * scope test, no filtering — so it cannot be talked down by the same
    * predicate that decides emission. `rule_sites_emitted` counts the distinct
    * sites that produced rules.
    *
    * The two are NOT expected to be equal: `access`, `authenticated` and
    * `anonymous` are ordinary words, and a business method named `access()`
    * legitimately raises the first number without belonging in the second. The
    * gap is the point — the worker reconciles it against an independent
    * source-text oracle, and a gap that grows without a matching business
    * explanation is how the next unreadable chain shape announces itself
    * instead of publishing a confident wrong claim.
    */
  private def authExtractionObj(cpg: Cpg, securityRules: List[ujson.Obj]): ujson.Obj = {
    val emittedSites = securityRules.map(_("call_id").num).distinct.size
    ujson.Obj(
      "access_calls_seen" -> cpg.call
        .nameExact(SpringSecurityPack.AccessCallNames.toSeq*)
        .size,
      "rule_sites_emitted" -> emittedSites
    )
  }

  /** Request-level policy from `auth-policy=` tags (§5.2.10 T6).
    *
    * CORS, CSRF and rejection handling: service-level facts that shape who can
    * reach an endpoint without deciding which principal may. Published so the
    * question is answerable, never merged into the endpoint's auth claim.
    */
  private def authPolicyObjs(cpg: Cpg): List[ujson.Obj] =
    cpg.call
      .where(_.tag.nameExact("auth-policy"))
      .l
      .sortBy(call => (lineOf(call.lineNumber), call.id))
      .flatMap { call =>
        call.tag.nameExact("auth-policy").value.l.sorted.map { encoded =>
          val Array(kind, scope, detail) = encoded.split('|').take(2) :+
            encoded.split('|').drop(2).mkString("|")
          ujson.Obj(
            "kind"   -> kind,
            "scope"  -> scope,
            "detail" -> detail,
            "anchor" -> ujson.Obj(
              "file" -> call.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(call.lineNumber)
            )
          )
        }
      }

  /** Authority-model facts from `auth-authority=` tags (§5.2.10 T7).
    *
    * What a grant MEANS and where it is minted. Never an input to the claim —
    * these gate nothing — but a `RoleHierarchy` makes every role list on the
    * service incomplete, which the worker marks rather than hides.
    */
  private def authAuthorityObjs(cpg: Cpg): List[ujson.Obj] =
    (cpg.call.where(_.tag.nameExact("auth-authority")).l ++
      cpg.method.where(_.tag.nameExact("auth-authority")).l)
      .sortBy(node => (lineOf(node.lineNumber), node.id))
      .flatMap { node =>
        node.tag.nameExact("auth-authority").value.l.sorted.map { encoded =>
          val Array(kind, detail) =
            encoded.split('|').take(1) :+ encoded.split('|').drop(1).mkString("|")
          ujson.Obj(
            "kind"   -> kind,
            "detail" -> detail,
            "anchor" -> ujson.Obj(
              "file" -> node.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(node.lineNumber)
            )
          )
        }
      }

  /** The chain a rule belongs to: its enclosing `SecurityFilterChain` bean or
    * `configure(HttpSecurity)` override, identified by method full name.
    */
  private def chainIdOf(call: Call): ujson.Value = ujson.Str(call.method.fullName)

  /** A chain-level `securityMatcher(...)`/`antMatcher(...)` scope, when the
    * chain declares one — rules inside it only apply to requests it matches.
    */
  private def chainPatternOf(cpg: Cpg, call: Call): ujson.Value = {
    // The modern DSL puts rules inside `authorizeHttpRequests(auth -> …)`, and
    // javasrc2cpg lowers that lambda into its OWN method — so the chain's
    // `securityMatcher`, which sits in the enclosing bean method, is not in the
    // same method at all.
    //
    // The predecessor fell back to the declaring TYPE, which pools every scope
    // on that type (§5.2.10). Reproduced: three chains in one class gave an
    // UNSCOPED chain its siblings' `"/fluent/**,/literal/**"`. That is a
    // restriction invented where none exists, and it withdraws every endpoint
    // outside the borrowed scope — the same over-approximation error the
    // rule-scoping fix corrected in 0.6.0, one level up.
    //
    // A lambda is now attributed to the method that PASSED it, which
    // javasrc2cpg makes recoverable: the argument's code is the lambda's own
    // full name.
    val home = chainHomeOf(cpg, call.method)
    // Non-literal scopes resolve through the shared reader too. Reading only
    // literals made `securityMatcher(PREFIX + "/api/**")` look like NO scope,
    // which does not degrade to "unknown": an unscoped chain governs every
    // request, so it joins the candidates for endpoints it has nothing to do
    // with and makes them ambiguous between chains.
    val scopes = cpg.call
      .nameExact("securityMatcher", "antMatcher")
      .filter(scope => chainHomeOf(cpg, scope.method) == home)
      .argument
      .argumentIndexGt(0)
      .l
      .flatMap { argument =>
        val owner = argument.method.typeDecl.headOption
        argument match {
          case literal: Literal => Some(literal.code.stripPrefix("\"").stripSuffix("\""))
          case _ =>
            SpringPacks
              .constantString(cpg, argument.code, owner)
              .orElse(SpringPacks.stringExpression(cpg, argument.code, owner))
        }
      }
      .filter(_.startsWith("/"))
      .distinct
    scopes match {
      case single :: Nil => ujson.Str(single)
      case Nil           => ujson.Null
      // Several scopes on one chain: the union is what governs, and picking
      // one would be a guess. The worker treats it as chain-wide.
      case many => ujson.Str(many.mkString(","))
    }
  }

  /** The bean method a chain lives in, following a lambda to its caller. */
  private def chainHomeOf(cpg: Cpg, method: Method): String = {
    val name = method.fullName
    if (!method.name.startsWith("<lambda>")) name
    else
      cpg.call
        .filter(_.argument.argumentIndexGt(0).code.exists(_ == name))
        .method
        .fullName
        .headOption
        .getOrElse(name)
  }

  /** How the service authenticates, from `auth-mechanism=` tags (§5.2.9 D4).
    *
    * A trailing `!<reason>` on the tag marks a mechanism that is present in
    * source but switched off — it is exported as inactive rather than dropped,
    * because "basic auth is explicitly disabled here" is a fact a reader wants.
    */
  private def authMechanismObjs(cpg: Cpg): List[ujson.Obj] =
    cpg.call
      .where(_.tag.nameExact("auth-mechanism"))
      .l
      .sortBy(call => (lineOf(call.lineNumber), -call.id))
      .flatMap { call =>
        call.tag.nameExact("auth-mechanism").value.l.map { encoded =>
          val (kind, rest)      = encoded.span(_ != ':')
          val payload           = rest.stripPrefix(":")
          val (detail, disabled) = payload.span(_ != '!')
          ujson.Obj(
            "kind"   -> kind,
            "detail" -> detail,
            "active" -> disabled.isEmpty,
            "inactive_reason" ->
              (if (disabled.isEmpty) ujson.Null else ujson.Str(disabled.stripPrefix("!"))),
            "anchor" -> ujson.Obj(
              "file" -> call.file.name.headOption.getOrElse("<unknown>"),
              "line" -> lineOf(call.lineNumber)
            )
          )
        }
      }
      .distinctBy(obj => (obj("kind").str, obj("detail").str, obj("active").bool))

  /** Whether method-security annotations are actually ENFORCED (§5.2.9 D6).
    *
    * `@PreAuthorize` on a handler means nothing unless the corresponding family
    * is enabled, and the defaults differ by Spring generation:
    * `@EnableGlobalMethodSecurity` (Spring Security 5) defaults every family
    * OFF, while `@EnableMethodSecurity` (6+) defaults prePostEnabled ON and
    * securedEnabled/jsr250Enabled OFF. Believing an inert annotation would
    * publish enforcement that does not exist; dropping it would hide a policy
    * the author clearly intended. The worker does neither — it marks it.
    *
    * `present=false` means no enabling annotation was found at all, which is
    * NOT the same as "disabled": a service may enable it via XML or a parent
    * config outside this CPG, so the worker treats it as unresolved.
    */
  private def methodSecurityObj(cpg: Cpg): ujson.Obj = {
    val enabling = cpg.annotation
      .nameExact("EnableMethodSecurity", "EnableGlobalMethodSecurity")
      .l
    enabling.headOption match {
      case None => ujson.Obj("present" -> false)
      case Some(annotation) =>
        val modern = annotation.name == "EnableMethodSecurity"
        def flag(name: String, default: Boolean): Boolean =
          s"$name\\s*=\\s*(true|false)".r
            .findFirstMatchIn(annotation.code)
            .map(_.group(1) == "true")
            .getOrElse(default)
        ujson.Obj(
          "present"        -> true,
          "style"          -> annotation.name,
          "pre_post"       -> flag("prePostEnabled", default = modern),
          "secured"        -> flag("securedEnabled", default = false),
          "jsr250"         -> flag("jsr250Enabled", default = false),
          "evidence"       -> firstLine(annotation.code),
          "anchor" -> ujson.Obj(
            "file" -> annotation.file.name.headOption.getOrElse("<unknown>"),
            "line" -> lineOf(annotation.lineNumber)
          )
        )
    }
  }

  /** Gating constructs that carry no security-framework rule (§5.2.9):
    * chain bypasses now, interceptors/filters/aspects as those passes land.
    */
  private def authEnforcementObjs(cpg: Cpg): List[ujson.Obj] = {
    // Enforcement is tagged on a CALL when a registration site names it
    // (addInterceptor, addUrlPatterns) and on a METHOD when the construct IS
    // the code (an in-handler check, an aspect's advice).
    val tagged: List[(String, String, Int, Long)] =
      cpg.call
        .where(_.tag.nameExact("auth-enforcement"))
        .l
        .flatMap(call =>
          call.tag
            .nameExact("auth-enforcement")
            .value
            .l
            .map(v =>
              (
                v,
                call.file.name.headOption.getOrElse("<unknown>"),
                lineOf(call.lineNumber),
                call.id
              )
            )
        ) ++
        cpg.method
          .where(_.tag.nameExact("auth-enforcement"))
          .l
          .flatMap(method =>
            method.tag
              .nameExact("auth-enforcement")
              .value
              .l
              .map(v => (v, method.filename, lineOf(method.lineNumber), method.id))
          )

    tagged
      .sortBy { case (_, _, line, id) => (line, -id) }
      .map { case (encoded, file, line, _) =>
        val Array(kind, pattern, detail) = encoded.split('|').take(2) :+
          encoded.split('|').drop(2).mkString("|")
        ujson.Obj(
          "kind"    -> kind,
          "pattern" -> pattern,
          "detail"  -> detail,
          "anchor"  -> ujson.Obj("file" -> file, "line" -> line)
        )
      }
      .distinctBy(obj => (obj("kind").str, obj("pattern").str, obj("detail").str))
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
