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
  * Confidence per candidate:
  *   - EXACT      everything literal, single path, no fields/config keys
  *   - HIGH       resolved through a `@Value("${key}")` config key (rendered
  *                as `${key}` for the stitcher) and/or a single-assignment
  *                field or local; everything else literal/benign
  *   - HEURISTIC  a non-benign hole remains, or the candidate set was
  *                truncated by budget, or multi-assignment fan-out
  *   - NONE       nothing recovered (url = null) — e.g. a URL from a DB row
  *
  * A `{?}` hole that occupies one complete path segment is BENIGN — it aligns
  * with the endpoint identity form (`/stock/{?}`) and never lowers confidence.
  * Every candidate carries a human-readable evidence trace; Lombok-blocked
  * resolutions carry the exact marker the stitcher's coverage report counts.
  */
object UrlSlicer {

  /** Marker consumed verbatim by the stitcher (coverage reason code). */
  val LombokBlockedMarker = "lombok-generated interior"

  final case class UrlCandidate(url: Option[String], confidence: String, evidence: String)

  final case class SliceBudget(
    maxDepth: Int = 8,
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
    viaMultiAssignment: Boolean = false,
    truncated: Boolean = false
  ) {
    def ++(other: Candidate): Candidate = Candidate(
      parts ++ other.parts,
      trace ++ other.trace,
      viaConfigKey || other.viaConfigKey,
      viaField || other.viaField,
      viaMultiAssignment || other.viaMultiAssignment,
      truncated || other.truncated
    )
  }

  private class Budget(budget: SliceBudget) {
    private val start           = System.nanoTime()
    private var visited         = 0
    var truncated: Boolean      = false
    def spend(): Boolean = {
      visited += 1
      val ok = visited <= budget.maxVisited && (System.nanoTime() - start) < budget.deadlineNanos
      if (!ok) truncated = true
      ok
    }
    def capCandidates(candidates: List[Candidate]): List[Candidate] =
      if (candidates.length <= budget.maxCandidates) candidates
      else {
        truncated = true
        candidates.take(budget.maxCandidates).map(_.copy(truncated = true))
      }
  }

  private val LombokTypeAnnotations = Set("Getter", "Data", "Value", "Builder")

  // --- public entrypoint ----------------------------------------------------------

  /** All candidate URLs for the URL argument (index 1) of an http-client call.
    * Never throws; never returns Nil (worst case one NONE candidate).
    */
  def slice(cpg: Cpg, call: Call, budget: SliceBudget = SliceBudget()): List[UrlCandidate] =
    try {
      val tracker = new Budget(budget)
      call.argument.argumentIndexGt(0).sortBy(_.argumentIndex).headOption match {
        case None => List(noneCandidate(call, "call has no argument to slice"))
        case Some(argument) =>
          val resolved = tracker.capCandidates(
            resolve(cpg, argument, depth = budget.maxDepth, tracker)
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

  private def resolve(cpg: Cpg, node: AstNode, depth: Int, tracker: Budget): List[Candidate] = {
    if (depth <= 0 || !tracker.spend())
      return List(Candidate(List(Hole), List("<budget exhausted>"), truncated = true))
    node match {
      case literal: Literal =>
        List(Candidate(List(Lit(stripQuotes(literal.code))), Nil))
      case call: Call if call.name == Operators.addition =>
        val operands = call.argument.l.sortBy(_.argumentIndex)
        operands.foldLeft(List(Candidate(Nil, Nil))) { (acc, operand) =>
          val resolvedOperand = resolve(cpg, operand, depth - 1, tracker)
          tracker.capCandidates(for {
            left  <- acc
            right <- resolvedOperand
          } yield left ++ right)
        }
      case call: Call if call.name == "format" && call.methodFullName.startsWith("java.lang.String") =>
        resolveStringFormat(cpg, call, depth, tracker)
      case call: Call if call.name == Operators.fieldAccess =>
        resolveFieldRead(cpg, call, fieldNameOf(call), depth, tracker)
      case call: Call =>
        resolveGetterBridge(cpg, call, depth, tracker)
      case identifier: Identifier =>
        resolveIdentifier(cpg, identifier, depth, tracker)
      case _ =>
        List(Candidate(List(Hole), List(s"${firstLine(node.code)} -> unresolvable expression")))
    }
  }

  private def resolveStringFormat(
    cpg: Cpg,
    call: Call,
    depth: Int,
    tracker: Budget
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
              val resolvedArg = resolve(cpg, vararg, depth - 1, tracker)
              val combined = tracker.capCandidates(for {
                left  <- acc
                right <- resolvedArg
              } yield left ++ right ++ Candidate(List(Lit(remaining.head)), Nil))
              combined -> remaining.tail
          }._1
        }
      case _ =>
        List(Candidate(List(Hole), List(s"String.format with non-literal template @ line ${lineOf(call)}")))
    }
  }

  private def resolveIdentifier(
    cpg: Cpg,
    identifier: Identifier,
    depth: Int,
    tracker: Budget
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
            resolve(cpg, single.source, depth - 1, tracker).map(c =>
              c.copy(trace = s"${identifier.name} <- ${firstLine(single.source.code)} @ line ${lineOf(single)}" :: c.trace)
            )
          case several =>
            tracker.capCandidates(several.flatMap { assignment =>
              resolve(cpg, assignment.source, depth - 1, tracker).map(c =>
                c.copy(
                  trace = s"${identifier.name} <- ${firstLine(assignment.source.code)} @ line ${lineOf(assignment)} (one of ${several.length} assignments)" :: c.trace,
                  viaMultiAssignment = true
                )
              )
            })
        }
      case Some(parameter: MethodParameterIn) =>
        // Method parameters typically carry path variables — a benign hole.
        List(Candidate(List(Hole), List(s"${identifier.name} <- parameter of ${parameter.method.name}(…) -> {?}")))
      case Some(_: Member) =>
        resolveMember(cpg, identifier.method.typeDecl.headOption, identifier.name, identifier, depth, tracker)
      case _ =>
        // javasrc2cpg renders bare field reads as identifiers with no local ref.
        resolveMember(cpg, identifier.method.typeDecl.headOption, identifier.name, identifier, depth, tracker)
    }

  private def fieldNameOf(fieldAccess: Call): String =
    fieldAccess.argument.l
      .collectFirst { case fi: FieldIdentifier => fi.canonicalName }
      .getOrElse(firstLine(fieldAccess.code))

  private def resolveFieldRead(
    cpg: Cpg,
    fieldAccess: Call,
    fieldName: String,
    depth: Int,
    tracker: Budget
  ): List[Candidate] =
    resolveMember(cpg, fieldAccess.method.typeDecl.headOption, fieldName, fieldAccess, depth, tracker)

  private def resolveMember(
    cpg: Cpg,
    owner: Option[TypeDecl],
    fieldName: String,
    site: AstNode,
    depth: Int,
    tracker: Budget
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
        val assignments = cpg.assignment
          .where(_.target.isCall.name(Operators.fieldAccess))
          .filter(a =>
            a.target.ast.collectFirst { case fi: FieldIdentifier if fi.canonicalName == fieldName => fi }.nonEmpty
          )
          .l
          .sortBy(a => (lineOf(a), a.id))
        assignments match {
          case Nil =>
            List(Candidate(List(Hole), List(s"$fieldName -> no visible field assignment")))
          case single :: Nil =>
            resolve(cpg, single.source, depth - 1, tracker).map(c =>
              c.copy(
                trace = s"$fieldName <- field = ${firstLine(single.source.code)} @ ${fileOf(single)}:${lineOf(single)} (single assignment)" :: c.trace,
                viaField = true
              )
            )
          case several =>
            tracker.capCandidates(several.flatMap { assignment =>
              resolve(cpg, assignment.source, depth - 1, tracker).map(c =>
                c.copy(
                  trace = s"$fieldName <- field = ${firstLine(assignment.source.code)} @ ${fileOf(assignment)}:${lineOf(assignment)} (one of ${several.length} assignments)" :: c.trace,
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
    tracker: Budget
  ): List[Candidate] = {
    val getterField = getterFieldName(call.name)
    val receiverType = call.argument.argumentIndexLte(0).headOption
      .flatMap(receiver => cpg.typeDecl.fullNameExact(receiver.typ.fullName.l*).headOption)
      .orElse(call.method.typeDecl.headOption)
    (getterField, receiverType) match {
      case (Some(field), Some(owner)) if isLombokAnnotated(owner) =>
        if (owner.member.nameExact(field).nonEmpty)
          resolveMember(cpg, Some(owner), field, call, depth, tracker).map(c =>
            c.copy(trace = s"${call.name}() <- lombok getter bridged to field '$field'" :: c.trace)
          )
        else
          List(
            Candidate(
              List(Hole),
              List(s"${call.name}() <- $LombokBlockedMarker of ${owner.name} (no backing field)")
            )
          )
      case _ =>
        List(Candidate(List(Hole), List(s"${firstLine(call.code)} -> opaque call result")))
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
      else if (candidate.viaConfigKey || candidate.viaField || holes > 0) "high"
      else "exact"
    val header = s"slice: ${firstLine(call.code)} @ ${fileOf(call)}:${lineOf(call)}"
    val trace  = (header :: candidate.trace).mkString("\n  ")
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
