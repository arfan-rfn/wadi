package wadi.slicing

import io.shiftleft.codepropertygraph.generated.{Cpg, Operators}
import io.shiftleft.codepropertygraph.generated.nodes.*
import io.shiftleft.semanticcpg.language.*

import scala.collection.mutable

/** Backward URL slicing for http-client call arguments (§5.2.4).
  *
  * A bounded recursive evaluator over the AST plus structural member/local
  * assignment lookup. Deliberately NOT a dataflow-engine slice: `reachableBy`
  * yields flow paths, not reconstructed string values — value rebuilding is
  * structural work either way. Locals with several assignments yield one
  * candidate per assignment (over-approximation is the correct answer for an
  * architecture map, §5.2; each such candidate caps at HIGH because we cannot
  * prove which definition reaches). Reaching-def precision is a recorded
  * future refinement.
  *
  * Resolution rules: literals · string concatenation (candidate
  * cross-products) · String.format · locals · fields (constructor-lowered
  * initializers included) · `@Value("${key}")` config keys (rendered as
  * `${key}` templates for the stitcher) · the Lombok getter bridge ·
  * **interprocedural return resolution** (a call into an in-CPG body —
  * DI-resolved impls included — resolves its return expression with the
  * call-site arguments bound to the parameters; hop-budgeted, cycle-guarded)
  * · **constant-map lookups** (`map.get(k)` where every visible `put` on the
  * map is literal→literal and `k` resolves to one literal — the TrainTicket
  * service-resolver idiom).
  *
  * Confidence per candidate:
  *   - EXACT      everything literal, single path, no fields/config keys
  *   - HIGH       resolved through a `@Value("${key}")` config key, a
  *                single-assignment field/local, or an interprocedural hop;
  *                benign holes allowed
  *   - HEURISTIC  a non-benign hole remains, budget truncation, or
  *                multi-assignment fan-out
  *   - NONE       nothing recovered (url = null) — e.g. a URL from a DB row
  *
  * A `{?}` hole that occupies one complete path segment is BENIGN — it aligns
  * with the endpoint identity form and never lowers confidence. Every
  * candidate carries a human-readable evidence trace; Lombok-blocked
  * resolutions carry the exact marker the stitcher's coverage report counts.
  */
object UrlSlicer {

  /** Marker consumed verbatim by the stitcher (coverage reason code). */
  val LombokBlockedMarker = "lombok-generated interior"

  /** Marker consumed verbatim by the stitcher (`slice-budget-truncated`,
    * §5.2.5): a budget-starved resolution must say so — it never masquerades
    * as a semantic result.
    */
  val BudgetTruncatedMarker = "slice-budget-truncated"

  // Follow existing CALL edges only (incl. the DI pass's added edges).
  private given ICallResolver = NoResolve

  final case class UrlCandidate(url: Option[String], confidence: String, evidence: String)

  final case class SliceBudget(
    maxDepth: Int = 8,
    maxInterprocHops: Int = 2,
    maxCandidates: Int = 8,
    maxVisited: Int = 512,
    deadlineNanos: Long = 3_000_000_000L
  )

  // --- internal value domain ------------------------------------------------------

  private sealed trait Part
  private case class Lit(text: String)      extends Part
  private case class ConfigKey(key: String) extends Part
  private case object Hole                  extends Part

  /** One resolution path: parts + trace + flags that decide confidence. */
  private case class Candidate(
    parts: List[Part],
    trace: List[String],
    viaConfigKey: Boolean = false,
    viaField: Boolean = false,
    viaInterproc: Boolean = false,
    viaMultiAssignment: Boolean = false,
    truncated: Boolean = false
  ) {
    def ++(other: Candidate): Candidate = Candidate(
      parts ++ other.parts,
      trace ++ other.trace,
      viaConfigKey || other.viaConfigKey,
      viaField || other.viaField,
      viaInterproc || other.viaInterproc,
      viaMultiAssignment || other.viaMultiAssignment,
      truncated || other.truncated
    )
  }

  /** Interprocedural context: call-site argument values bound to parameter
    * names, remaining hop budget, and a cycle guard.
    */
  private case class Frame(
    bindings: Map[String, List[Candidate]] = Map.empty,
    hops: Int = 0,
    visited: Set[Long] = Set.empty
  )

  private class Budget(budget: SliceBudget) {
    private val start           = System.nanoTime()
    private var visitedCount    = 0
    def spend(): Boolean = {
      visitedCount += 1
      visitedCount <= budget.maxVisited && (System.nanoTime() - start) < budget.deadlineNanos
    }
    def capCandidates(candidates: List[Candidate]): List[Candidate] =
      if (candidates.length <= budget.maxCandidates) candidates
      else candidates.take(budget.maxCandidates).map(_.copy(truncated = true))
  }

  private val LombokTypeAnnotations = Set("Getter", "Data", "Value", "Builder")

  // --- public entrypoint ----------------------------------------------------------

  /** All candidate URLs for the URL argument (index 1) of an http-client call.
    * Never throws; never returns Nil (worst case: one NONE candidate).
    */
  def slice(cpg: Cpg, call: Call, budget: SliceBudget = SliceBudget()): List[UrlCandidate] =
    try {
      val tracker = new Budget(budget)
      call.argument.argumentIndexGt(0).sortBy(_.argumentIndex).headOption match {
        case None => List(noneCandidate(call, "call has no argument to slice"))
        case Some(argument) =>
          val frame = Frame(hops = budget.maxInterprocHops)
          val resolved = tracker.capCandidates(
            resolve(cpg, argument, budget.maxDepth, tracker, frame)
          )
          val rendered = resolved.map(render(call, _))
          if (rendered.isEmpty) List(noneCandidate(call, "no value could be recovered"))
          else dedupe(rendered)
      }
    } catch {
      case scala.util.control.NonFatal(exc) =>
        List(noneCandidate(call, s"slice aborted (${exc.getClass.getSimpleName}) — honest unknown"))
    }

  private def dedupe(candidates: List[UrlCandidate]): List[UrlCandidate] = {
    val seen = mutable.LinkedHashMap.empty[Option[String], UrlCandidate]
    candidates.foreach(c => if (!seen.contains(c.url)) seen(c.url) = c)
    seen.values.toList
  }

  private def noneCandidate(call: Call, reason: String): UrlCandidate =
    UrlCandidate(None, "none", s"${firstLine(call.code)} @ line ${lineOf(call)}: $reason")

  // --- the evaluator --------------------------------------------------------------

  private def resolve(
    cpg: Cpg,
    node: AstNode,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] = {
    if (depth <= 0 || !tracker.spend())
      return List(Candidate(List(Hole), List("<budget exhausted>"), truncated = true))
    node match {
      case literal: Literal =>
        List(Candidate(List(Lit(stripQuotes(literal.code))), Nil))
      case call: Call if call.name == Operators.addition =>
        // Depth measures indirection, not expression size (§5.2.5): Java's
        // left-associative `+` nests one addition per operand, so charging per
        // AST level starved the interproc + map stages on long URLs — the
        // TrainTicket 21-false-unknowns bug. Flatten the chain: one charge.
        val operands = flattenedConcatOperands(call)
        operands.foldLeft(List(Candidate(Nil, Nil))) { (acc, operand) =>
          val resolvedOperand = resolve(cpg, operand, depth - 1, tracker, frame)
          tracker.capCandidates(for {
            left  <- acc
            right <- resolvedOperand
          } yield left ++ right)
        }
      case call: Call if call.name == "format" && call.methodFullName.startsWith("java.lang.String") =>
        resolveStringFormat(cpg, call, depth, tracker, frame)
      case call: Call if call.name == Operators.fieldAccess =>
        resolveMember(cpg, call.method.typeDecl.headOption, fieldNameOf(call), depth, tracker, frame)
      case call: Call =>
        resolveCall(cpg, call, depth, tracker, frame)
      case identifier: Identifier =>
        resolveIdentifier(cpg, identifier, depth, tracker, frame)
      case _ =>
        List(Candidate(List(Hole), List(s"${firstLine(node.code)} -> unresolvable expression")))
    }
  }

  /** `a + b + c` parses as nested additions; flatten to the operand list so a
    * whole concat chain costs one depth level.
    */
  private def flattenedConcatOperands(call: Call): List[AstNode] =
    call.argument.l.sortBy(_.argumentIndex).flatMap {
      case nested: Call if nested.name == Operators.addition => flattenedConcatOperands(nested)
      case operand                                           => List(operand)
    }

  private def resolveStringFormat(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] = {
    val arguments = call.argument.l.sortBy(_.argumentIndex)
    arguments.headOption match {
      case Some(fmt: Literal) =>
        val template = stripQuotes(fmt.code)
        val slots    = "%[sd]".r.findAllIn(template).length
        val varargs  = arguments.drop(1)
        if (slots != varargs.length)
          List(Candidate(List(Hole), List(s"String.format arity mismatch @ line ${lineOf(call)}")))
        else {
          val segments = template.split("%[sd]", -1).toList
          varargs.foldLeft(List(Candidate(List(Lit(segments.head)), Nil)) -> segments.tail) {
            case ((acc, remaining), vararg) =>
              val resolvedArg = resolve(cpg, vararg, depth - 1, tracker, frame)
              val combined = tracker.capCandidates(for {
                left  <- acc
                right <- resolvedArg
              } yield left ++ right ++ Candidate(List(Lit(remaining.head)), Nil))
              combined -> remaining.tail
          }._1
        }
      case _ =>
        List(
          Candidate(
            List(Hole),
            List(s"String.format with non-literal template @ line ${lineOf(call)}")
          )
        )
    }
  }

  /** A non-operator call: constant-map lookup → interprocedural return
    * resolution → Lombok getter bridge → honest opaque hole.
    */
  private def resolveCall(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] =
    resolveConstantMapGet(cpg, call, depth, tracker, frame)
      .orElse(resolveInterprocReturn(cpg, call, depth, tracker, frame))
      .orElse(resolveGetterBridge(cpg, call, depth, tracker, frame))
      .getOrElse(
        List(Candidate(List(Hole), List(s"${firstLine(call.code)} -> opaque call result")))
      )

  /** `map.get(key)` on a local whose visible `put`s are all literal→literal —
    * the constant service registry idiom (TrainTicket's ServiceResolver).
    */
  private def resolveConstantMapGet(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): Option[List[Candidate]] = {
    if (call.name != "get") return None
    val valueArguments = call.argument.argumentIndexGt(0).l
    if (valueArguments.sizeIs != 1) return None
    val receiverName = call.argument.argumentIndexLte(0).headOption.collect {
      case identifier: Identifier if identifier.refsTo.headOption.exists(_.isInstanceOf[Local]) =>
        identifier.name
    }
    receiverName.flatMap { name =>
      val puts = call.method.ast.isCall
        .nameExact("put")
        .filter(_.argument.argumentIndexLte(0).headOption.collect { case i: Identifier =>
          i.name
        }.contains(name))
        .l
      val entries = puts.flatMap { put =>
        val args = put.argument.argumentIndexGt(0).l.sortBy(_.argumentIndex)
        args match {
          case (k: Literal) :: (v: Literal) :: Nil =>
            Some(stripQuotes(k.code) -> stripQuotes(v.code))
          case _ => None
        }
      }
      // Any non-constant put poisons the map; no puts means it is not ours.
      if (puts.isEmpty || entries.sizeIs != puts.size) None
      else lookupConstantMap(cpg, call, name, entries.toMap, depth, tracker, frame)
    }
  }

  private def lookupConstantMap(
    cpg: Cpg,
    call: Call,
    name: String,
    constMap: Map[String, String],
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): Option[List[Candidate]] = {
    val valueArguments = call.argument.argumentIndexGt(0).l
    val keyCandidates  = resolve(cpg, valueArguments.head, depth - 1, tracker, frame)
    keyCandidates match {
      case Candidate(List(Lit(key)), keyTrace, _, _, _, _, _) :: Nil =>
        constMap.get(key) match {
          case Some(value) =>
            Some(
              List(
                Candidate(
                  List(Lit(value)),
                  keyTrace :+ s"$name.get(\"$key\") = \"$value\" (constant map, ${constMap.size} entries)"
                )
              )
            )
          case None =>
            Some(
              List(
                Candidate(
                  List(Hole),
                  List(s"$name.get(\"$key\") -> constant map has no such entry")
                )
              )
            )
        }
      case candidates =>
        // Honesty (§5.2.5): a starved key resolution is a budget fact, not a
        // semantic one — saying "not a single constant" here was factually
        // wrong (the key WAS a literal) and hid the bug behind HIGH holes.
        val truncated = candidates.exists(_.truncated)
        val reason =
          if (truncated) s"$name.get(…) -> key resolution truncated by slice budget"
          else s"$name.get(…) -> key is not a single constant"
        Some(List(Candidate(List(Hole), List(reason), truncated = truncated)))
    }
  }

  /** A call into an in-CPG body (DI-resolved impls included): bind the
    * call-site arguments to the parameters and resolve the return expression.
    */
  private def resolveInterprocReturn(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): Option[List[Candidate]] = {
    if (frame.hops <= 0) return None
    val callee = call.callee
      .filterNot(_.isExternal)
      .filterNot(m => frame.visited.contains(m.id))
      .find(_.body.astChildren.nonEmpty)
    callee.flatMap { target =>
      val returns = target.ast.isReturn.l.sortBy(r => (lineOf(r), r.id))
      val returnedExpressions = returns.flatMap(_.astChildren.headOption)
      if (returnedExpressions.isEmpty) None
      else Some(resolveThroughCallee(cpg, call, target, returnedExpressions, depth, tracker, frame))
    }
  }

  private def resolveThroughCallee(
    cpg: Cpg,
    call: Call,
    target: Method,
    returnedExpressions: List[AstNode],
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] = {
    val parameters = target.parameter.indexGt(0).l.sortBy(_.index)
    val bindings = parameters.flatMap { parameter =>
      call.argument.argumentIndex(parameter.index).headOption.map { actual =>
        parameter.name -> resolve(cpg, actual, depth - 1, tracker, frame)
      }
    }.toMap
    val innerFrame = Frame(
      bindings = bindings,
      hops = frame.hops - 1,
      visited = frame.visited + target.id
    )
    tracker.capCandidates(
      returnedExpressions.flatMap { expression =>
        resolve(cpg, expression, depth - 1, tracker, innerFrame).map(c =>
          c.copy(
            trace = s"${call.name}(…) <- return of ${target.name} @ ${fileOf(target)}:${lineOf(target)}" :: c.trace,
            viaInterproc = true,
            viaMultiAssignment = c.viaMultiAssignment || returnedExpressions.sizeIs > 1
          )
        )
      }
    )
  }

  private def resolveIdentifier(
    cpg: Cpg,
    identifier: Identifier,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] =
    identifier.refsTo.headOption match {
      case Some(_: Local) =>
        val method = identifier.method
        val assignments = method.assignment
          .where(_.target.isIdentifier.nameExact(identifier.name))
          .l
          .sortBy(a => (lineOf(a), a.id))
        assignments match {
          case Nil =>
            List(Candidate(List(Hole), List(s"${identifier.name} -> no visible assignment")))
          case single :: Nil =>
            resolve(cpg, single.source, depth - 1, tracker, frame).map(c =>
              c.copy(trace =
                s"${identifier.name} <- ${firstLine(single.source.code)} @ line ${lineOf(single)}" :: c.trace
              )
            )
          case several =>
            tracker.capCandidates(several.flatMap { assignment =>
              resolve(cpg, assignment.source, depth - 1, tracker, frame).map(c =>
                c.copy(
                  trace =
                    s"${identifier.name} <- ${firstLine(assignment.source.code)} @ line ${lineOf(assignment)} (one of ${several.length} assignments)" :: c.trace,
                  viaMultiAssignment = true
                )
              )
            })
        }
      case Some(parameter: MethodParameterIn) =>
        frame.bindings.get(identifier.name) match {
          case Some(bound) =>
            bound.map(c =>
              c.copy(trace = s"${identifier.name} <- call-site argument" :: c.trace)
            )
          case None =>
            // Unbound parameters typically carry path variables — a benign hole.
            List(
              Candidate(
                List(Hole),
                List(s"${identifier.name} <- parameter of ${parameter.method.name}(…) -> {?}")
              )
            )
        }
      case Some(_: Member) =>
        resolveMember(
          cpg,
          identifier.method.typeDecl.headOption,
          identifier.name,
          depth,
          tracker,
          frame
        )
      case _ =>
        // javasrc2cpg renders bare field reads as identifiers with no local ref.
        resolveMember(
          cpg,
          identifier.method.typeDecl.headOption,
          identifier.name,
          depth,
          tracker,
          frame
        )
    }

  private def fieldNameOf(fieldAccess: Call): String =
    fieldAccess.argument.l
      .collectFirst { case fi: FieldIdentifier => fi.canonicalName }
      .getOrElse(firstLine(fieldAccess.code))

  private def resolveMember(
    cpg: Cpg,
    owner: Option[TypeDecl],
    fieldName: String,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): List[Candidate] = {
    val member = owner.iterator.flatMap(_.member.nameExact(fieldName)).nextOption()
    member.flatMap(configKeyOf) match {
      case Some(key) =>
        List(
          Candidate(
            List(ConfigKey(key)),
            List(s"$fieldName <- @Value(\"$${$key}\") config key"),
            viaConfigKey = true
          )
        )
      case None =>
        // Owner-scoped (§5.2.5): match assignments only inside the owning type
        // (or its ancestors — inherited fields are assigned in the parent's
        // constructor). A CPG-global name match conflated same-named fields
        // across classes into false multi-assignment fan-outs.
        val allowedOwners: Set[String] = owner match {
          case Some(o) => o.inheritsFromTypeFullName.toSet + o.fullName
          case None    => Set.empty
        }
        val assignments = cpg.assignment
          .where(_.target.isCall.name(Operators.fieldAccess))
          .filter(a =>
            a.target.ast
              .collectFirst { case fi: FieldIdentifier if fi.canonicalName == fieldName => fi }
              .nonEmpty
          )
          .filter(a =>
            allowedOwners.isEmpty ||
              a.method.typeDecl.headOption.exists(td => allowedOwners.contains(td.fullName))
          )
          .l
          .sortBy(a => (lineOf(a), a.id))
        assignments match {
          case Nil =>
            List(Candidate(List(Hole), List(s"$fieldName -> no visible field assignment")))
          case single :: Nil =>
            resolve(cpg, single.source, depth - 1, tracker, frame).map(c =>
              c.copy(
                trace =
                  s"$fieldName <- field = ${firstLine(single.source.code)} @ ${fileOf(single)}:${lineOf(single)} (single assignment)" :: c.trace,
                viaField = true
              )
            )
          case several =>
            tracker.capCandidates(several.flatMap { assignment =>
              resolve(cpg, assignment.source, depth - 1, tracker, frame).map(c =>
                c.copy(
                  trace =
                    s"$fieldName <- field = ${firstLine(assignment.source.code)} @ ${fileOf(assignment)}:${lineOf(assignment)} (one of ${several.length} assignments)" :: c.trace,
                  viaField = true,
                  viaMultiAssignment = true
                )
              )
            })
        }
    }
  }

  /** Lombok getter bridge: a call to a generated `getX()` on a Lombok-annotated
    * type resolves as a read of the backing field `x` — the field initializer
    * IS in the original source even though the getter body is not (recorded
    * decision: exact anchors + bridge; run-delombok rejected).
    */
  private def resolveGetterBridge(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget,
    frame: Frame
  ): Option[List[Candidate]] = {
    val getterField = getterFieldName(call.name)
    val receiverType = call.argument.argumentIndexLte(0).headOption
      .flatMap(receiver => cpg.typeDecl.fullNameExact(receiver.typ.fullName.l*).headOption)
      .orElse(call.method.typeDecl.headOption)
    (getterField, receiverType) match {
      case (Some(field), Some(owner)) if isLombokAnnotated(owner) =>
        if (owner.member.nameExact(field).nonEmpty)
          Some(
            resolveMember(cpg, Some(owner), field, depth, tracker, frame).map(c =>
              c.copy(trace = s"${call.name}() <- lombok getter bridged to field '$field'" :: c.trace)
            )
          )
        else
          Some(
            List(
              Candidate(
                List(Hole),
                List(s"${call.name}() <- $LombokBlockedMarker of ${owner.name} (no backing field)")
              )
            )
          )
      case _ => None
    }
  }

  private def getterFieldName(callName: String): Option[String] =
    if (callName.length > 3 && callName.startsWith("get") && callName(3).isUpper)
      Some(callName(3).toLower.toString + callName.drop(4))
    else None

  private def isLombokAnnotated(typeDecl: TypeDecl): Boolean =
    typeDecl.ast.isAnnotation
      .filter(_.astParent == typeDecl)
      .exists(a => LombokTypeAnnotations.contains(a.name))

  private def configKeyOf(member: Member): Option[String] =
    member.ast.isAnnotation
      .filter(_.name == "Value")
      .headOption
      .flatMap { annotation =>
        "\\$\\{([^}:]+)(?::[^}]*)?\\}".r.findFirstMatchIn(annotation.code).map(_.group(1).trim)
      }

  // --- rendering + confidence -----------------------------------------------------

  private def render(call: Call, candidate: Candidate): UrlCandidate = {
    val text = candidate.parts.map {
      case Lit(t)         => t
      case ConfigKey(key) => s"$${$key}"
      case Hole           => "{?}"
    }.mkString
    val hasLiteral = candidate.parts.exists { case Lit(t) => t.nonEmpty; case _ => false }
    val holes      = candidate.parts.count(_ == Hole)
    val confidence =
      if (!hasLiteral && !candidate.parts.exists(_.isInstanceOf[ConfigKey])) "none"
      else if (holes > 0 && !allHolesBenign(text)) "heuristic"
      else if (candidate.truncated || candidate.viaMultiAssignment) "heuristic"
      else if (candidate.viaConfigKey || candidate.viaField || candidate.viaInterproc || holes > 0)
        "high"
      else "exact"
    val header = s"slice: ${firstLine(call.code)} @ ${fileOf(call)}:${lineOf(call)}"
    val traceLines =
      if (candidate.truncated) (header :: candidate.trace) :+ s"[$BudgetTruncatedMarker]"
      else header :: candidate.trace
    val trace = traceLines.mkString("\n  ")
    if (confidence == "none") UrlCandidate(None, "none", trace)
    else UrlCandidate(Some(text), confidence, trace)
  }

  /** A hole is benign iff it occupies one complete path segment after the
    * authority — `http://inventory:8080/stock/{?}` aligns with the endpoint
    * identity form; `{?}/stock/5` (unknown authority) does not.
    */
  private def allHolesBenign(rendered: String): Boolean = {
    val pathStart = {
      val schemeIdx = rendered.indexOf("://")
      if (schemeIdx >= 0) {
        val idx = rendered.indexOf('/', schemeIdx + 3)
        if (idx >= 0) idx else rendered.length
      } else 0
    }
    val (authority, path) = rendered.splitAt(pathStart)
    if (authority.contains("{?}")) return false
    path.split("/", -1).forall(segment => !segment.contains("{?}") || segment == "{?}")
  }

  // --- small helpers --------------------------------------------------------------

  private def stripQuotes(literal: String): String =
    literal.stripPrefix("\"").stripSuffix("\"")

  private def lineOf(node: AstNode): Int =
    node.lineNumber.map(_.toString.toInt).getOrElse(0)

  private def fileOf(node: AstNode): String =
    node.file.name.headOption.getOrElse("<unknown>")

  private def firstLine(code: String): String =
    code.linesIterator.nextOption().getOrElse("").take(200)
}
