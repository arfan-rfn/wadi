package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{AstNode, Call, ControlStructure, Method}
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
  * Statement coarsening: statements are the AST nodes whose parent is a
  * BLOCK (assignments and standalone calls are CALL nodes, control structures
  * and returns their own kinds); the expression-level CFG is projected onto
  * them (an edge between statements exists iff some expression-level CFG edge
  * crosses them). IF-statement edges are relabeled true/false from the AST.
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
    */
  val ExportSchemaVersion = "2.1.0"

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
    val closure         = reachableClosure(endpointMethods)
    val methodIds       = closure.map(_.id).toSet

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
            Some(
              ujson.Obj(
                "method_id"   -> num(method.id),
                "http_method" -> httpMethod,
                "uri"         -> uri,
                "auth_tags"   -> method.tag.nameExact("auth").value.l.map(v => s"auth=$v"),
                "params"      -> endpointParamObjs(method)
              )
            )
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

    val document = ujson.Obj(
      "export_schema_version" -> ExportSchemaVersion,
      "language"              -> "java",
      "methods"               -> methodObjs,
      "cfgs"                  -> cfgObjs,
      "endpoints"             -> endpointObjs,
      "sinks"                 -> sinkRows.toList,
      "unreachable_sinks"     -> unreachableObjs,
      "data_models"           -> modelObjs,
      "security_rules"        -> securityRuleObjs(cpg),
      "config_refs"           -> configRefObjs(cpg)
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
      s"${sinkRows.size} sinks, ${unreachableObjs.size} unreachable sinks -> $outDir/export.json"
  }

  /** BFS over resolved calls (incl. DI-added edges), internal methods only. */
  private def reachableClosure(roots: List[Method]): List[Method] = {
    val ordered = mutable.LinkedHashMap.empty[Long, Method]
    val queue   = mutable.Queue.from(roots)
    while (queue.nonEmpty) {
      val current = queue.dequeue()
      if (!ordered.contains(current.id)) {
        ordered.put(current.id, current)
        current.call.callee.filterNot(_.isExternal).filterNot(_.name.startsWith("<")).l.foreach { callee =>
          if (!ordered.contains(callee.id)) queue.enqueue(callee)
        }
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
    */
  private val ContainerStructureTypes = Set("IF", "FOR", "WHILE", "DO", "SWITCH", "TRY", "ELSE")

  private def isLeafStatement(node: AstNode): Boolean = node match {
    case cs: ControlStructure => !ContainerStructureTypes.contains(cs.controlStructureType)
    case _                    => true
  }

  /** Statement nodes of a method: AST children of blocks, in line order,
    * excluding lowering artifacts nested inside leaf statements.
    */
  private def statementsOf(method: Method): List[AstNode] = {
    val candidates = method.ast
      .filter(node => StatementLabels.contains(node.label))
      .filter(node => node.astParent.isBlock)
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
      val (kind, callInfo) = classify(statement, exportedMethodIds)
      callInfo.flatMap(_.sinkTag).foreach { case (sinkKind, sinkCall) =>
        sinkRows ++= sinkRowsFor(cpg, statement.id, method.id, sinkKind, sinkCall)
      }
      val obj = ujson.Obj(
        "id"       -> num(statement.id),
        "kind"     -> kind,
        "code"     -> firstLine(statement.code),
        "line"     -> lineOf(statement.lineNumber),
        "line_end" -> lineOf(statement.lineNumber)
      )
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
        case _ => ()
      }
      obj
    }

    // Project the expression-level CFG onto statements.
    val projected = mutable.LinkedHashSet.empty[(Long, Long)]
    method.cfgNode.l.foreach { cfgNode =>
      enclosing.get(cfgNode.id).foreach { sourceStatement =>
        cfgNode._cfgOut.foreach { successor =>
          enclosing.get(successor.id).foreach { targetStatement =>
            if (sourceStatement != targetStatement)
              projected.add((sourceStatement, targetStatement))
          }
        }
      }
    }

    // Relabel IF edges as true/false from the AST.
    val labels = mutable.Map.empty[(Long, Long), String]
    statements.collect { case cs: ControlStructure if cs.controlStructureType == "IF" => cs }.foreach { ifStatement =>
      firstStatementIn(ifStatement.whenTrue.l, statementIds, enclosing, ifStatement.id).foreach {
        target => labels((ifStatement.id, target)) = "true"
      }
      firstStatementIn(ifStatement.whenFalse.l, statementIds, enclosing, ifStatement.id).foreach {
        target => labels((ifStatement.id, target)) = "false"
      }
    }

    ujson.Obj(
      "method_id" -> num(method.id),
      "nodes"     -> nodeObjs,
      "edges" -> projected.toList.map { case (source, target) =>
        ujson.Obj(
          "source" -> num(source),
          "target" -> num(target),
          "label"  -> labels.getOrElse((source, target), "flow")
        )
      }
    )
  }

  /** The first statement inside a branch arm's subtree (for true/false labels).
    *
    * The arm's Block itself maps up to the surrounding IF — exclude it, or a
    * branch label would degenerate to a self-loop.
    */
  private def firstStatementIn(
    roots: List[AstNode],
    statementIds: Set[Long],
    enclosing: mutable.Map[Long, Long],
    excludeStatementId: Long
  ): Option[Long] =
    roots.iterator
      .flatMap(_.ast.l)
      .flatMap(node => enclosing.get(node.id))
      .find(id => statementIds.contains(id) && id != excludeStatementId)

  private case class CallInfo(
    calleeFullName: String,
    calleeId: Option[Long],
    resolved: Boolean,
    viaDi: Boolean,
    sinkTag: Option[(String, Call)]
  )

  private def classify(statement: AstNode, exportedMethodIds: Set[Long]): (String, Option[CallInfo]) =
    statement match {
      case cs: ControlStructure =>
        cs.controlStructureType match {
          case "IF"                        => ("branch", None)
          case "FOR" | "WHILE" | "DO"      => ("loop", None)
          case _                           => ("statement", None)
        }
      case _ if statement.label == "RETURN" =>
        ("return", primaryCallOf(statement, exportedMethodIds))
      case _ =>
        primaryCallOf(statement, exportedMethodIds) match {
          case some @ Some(_) => ("call", some)
          case None           => ("statement", None)
        }
    }

  /** The most interesting real (non-operator) call inside a statement subtree. */
  private def primaryCallOf(statement: AstNode, exportedMethodIds: Set[Long]): Option[CallInfo] = {
    val realCalls = statement.ast.isCall
      .filterNot(_.name.startsWith(OperatorPrefix))
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
    val verb = feignEncoded
      .map(_.split('|').head)
      // WebClient chains carry the verb on the chain root; the sink pass
      // stores it as a tag on the tagged .uri(...) call (§5.2.5).
      .orElse(call.tag.nameExact("wadi-verb").value.headOption)
      .orElse(httpVerbOf(call))
    val clientTag = call.tag.nameExact("wadi-client").value.headOption
    val isHttpKind = kind == "http-client" || kind == "http-client-suspected"
    val mechanism =
      if (feignEncoded.isDefined) Some("feign")
      else if (kind == "http-client-suspected") Some("unknown")
      else if (kind == "http-client") Some(clientTag.getOrElse("resttemplate"))
      else None
    val candidates: List[(Option[String], String, Option[String])] = feignEncoded match {
      case Some(encoded) =>
        val url = encoded.split('|').last
        List(
          (
            Some(url),
            "high",
            Some(s"feign client: declared mapping composes $url (discovery-name authority)")
          )
        )
      case None if !isHttpKind => List((None, "none", None))
      case None =>
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

  /** Every `@Value("${key}")` reference on a field, CPG-wide (§5.2.4). */
  private def configRefObjs(cpg: Cpg): List[ujson.Obj] = {
    val keyPattern = "\\$\\{([^}:]+)(?::([^}]*))?\\}".r
    cpg.member.l.flatMap { member =>
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
    }.sortBy(obj => (obj("key").str, obj("anchor")("file").str))
  }

  private def stripQuotes(literal: String): String =
    literal.stripPrefix("\"").stripSuffix("\"")

  private def firstLine(code: String): String =
    code.linesIterator.nextOption().getOrElse("").take(500)
}
