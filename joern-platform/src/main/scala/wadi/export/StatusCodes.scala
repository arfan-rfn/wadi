package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{AstNode, Call, Literal, Method}
import io.shiftleft.semanticcpg.language.*

/** HTTP statuses a handler DECLARES (§5.2.7 T9).
  *
  * Deliberately not "the statuses this endpoint returns". A 500 raised by an
  * uncaught exception, a 403 from the security layer, a 404 from Spring's own
  * dispatcher — none of those appear in handler source, so none appear here.
  * Publishing this list as if it were complete would let a reader conclude an
  * endpoint cannot fail, which is a stronger claim than the evidence supports
  * and the opposite of what P10 asks for. The contract field says `declared`
  * for the same reason.
  *
  * Measured on train-ticket-aitest: 409 handlers end in `ok(...)`, 15 in
  * `new ResponseEntity<>(body, HttpStatus.CREATED)`, one carries
  * `@ResponseStatus(HttpStatus.ACCEPTED)`. A corpus with a poorer status
  * vocabulary than most, which is exactly why the extraction has to cover the
  * builders rather than only the explicit constants.
  */
object StatusCodes {

  /** `ResponseEntity` static builders that fix a status by their name alone. */
  private val BuilderStatus: Map[String, Int] = Map(
    "ok"                  -> 200,
    "created"             -> 201,
    "accepted"            -> 202,
    "noContent"           -> 204,
    "badRequest"          -> 400,
    "notFound"            -> 404,
    "unprocessableEntity" -> 422,
    "internalServerError" -> 500
  )

  /** The subset of `HttpStatus` a first-party handler realistically names.
    *
    * Kept explicit rather than reflected: the enum lives outside every analyzed
    * source root, so its constants are not in the CPG to read.
    */
  private val ConstantStatus: Map[String, Int] = Map(
    "OK" -> 200, "CREATED" -> 201, "ACCEPTED" -> 202, "NO_CONTENT" -> 204,
    "RESET_CONTENT" -> 205, "PARTIAL_CONTENT" -> 206,
    "MOVED_PERMANENTLY" -> 301, "FOUND" -> 302, "SEE_OTHER" -> 303,
    "NOT_MODIFIED" -> 304, "TEMPORARY_REDIRECT" -> 307, "PERMANENT_REDIRECT" -> 308,
    "BAD_REQUEST" -> 400, "UNAUTHORIZED" -> 401, "PAYMENT_REQUIRED" -> 402,
    "FORBIDDEN" -> 403, "NOT_FOUND" -> 404, "METHOD_NOT_ALLOWED" -> 405,
    "NOT_ACCEPTABLE" -> 406, "REQUEST_TIMEOUT" -> 408, "CONFLICT" -> 409,
    "GONE" -> 410, "PRECONDITION_FAILED" -> 412, "PAYLOAD_TOO_LARGE" -> 413,
    "UNSUPPORTED_MEDIA_TYPE" -> 415, "UNPROCESSABLE_ENTITY" -> 422,
    "TOO_MANY_REQUESTS" -> 429,
    "INTERNAL_SERVER_ERROR" -> 500, "NOT_IMPLEMENTED" -> 501, "BAD_GATEWAY" -> 502,
    "SERVICE_UNAVAILABLE" -> 503, "GATEWAY_TIMEOUT" -> 504
  )

  private case class Declared(code: Int, origin: String, detail: String, line: Int)

  /** Every status the handler's own code names, deduplicated by (code, origin). */
  def declaredBy(cpg: Cpg, method: Method): List[ujson.Obj] = {
    val fromAnnotation = method.ast.isAnnotation
      .filter(_.astParent == method)
      .filter(_.name == "ResponseStatus")
      .l
      .flatMap { annotation =>
        constantIn(annotation.code).map(code =>
          Declared(code, "annotation", firstLine(annotation.code), lineOf(annotation.lineNumber))
        )
      }

    val fromBody = method.ast.isReturn.l.flatMap { ret =>
      ret.astChildren.l.flatMap(statusesOf(_, lineOf(ret.lineNumber)))
    }

    // An `@ResponseStatus` REPLACES the status a bare builder would imply — it
    // is the declared answer for the normal path, so a co-located `ok(...)`
    // would otherwise publish a 200 the framework never sends.
    val declared =
      if (fromAnnotation.nonEmpty) fromAnnotation
      else if (fromBody.nonEmpty) fromBody
      else frameworkDefault(method).toList
    declared
      .distinctBy(d => (d.code, d.origin))
      .sortBy(d => (d.code, d.line))
      .map(d =>
        ujson.Obj(
          "code"   -> d.code,
          "origin" -> d.origin,
          "detail" -> d.detail,
          "line"   -> d.line
        )
      )
  }

  /** Spring's own answer for a handler that names no status.
    *
    * A handler returning `String`/`boolean`/a DTO is serialized with 200 — the
    * framework decides, not the code. Claimed ONLY when the return type is not
    * a `ResponseEntity` family type: where the status IS under program control
    * and we failed to read it, saying 200 would be a guess dressed as a
    * framework rule. Marked `default` so it never reads as something the
    * handler declared. 50 of the 60 statusless train-ticket handlers return a
    * bare `String`; leaving them empty beside endpoints showing `200` made an
    * identical outcome look like an unknown.
    */
  private def frameworkDefault(method: Method): Option[Declared] =
    TypeShapes
      .returnTypeTextOf(method)
      .map(_.takeWhile(_ != '<').trim)
      .filterNot(name => name.endsWith("ResponseEntity") || name.endsWith("HttpEntity"))
      .map(name => Declared(200, "default", s"returns $name — Spring's default status", lineOf(method.lineNumber)))

  private def statusesOf(node: AstNode, line: Int): List[Declared] = node match {
    case call: Call =>
      val here = call.name match {
        // `status(X)` fixes the code; the `.body(...)`/`.build()` that follows
        // carries the payload, not the status.
        case "status" =>
          call.argument.l
            .filter(_.argumentIndex >= 1)
            .flatMap(argument => codeOfArgument(argument))
            .map(code => Declared(code, "explicit", firstLine(call.code), line))
        case "<init>" if call.methodFullName.contains("ResponseEntity") =>
          call.argument.l
            .filter(_.argumentIndex >= 1)
            .flatMap(argument => codeOfArgument(argument))
            .map(code => Declared(code, "explicit", firstLine(call.code), line))
        case name =>
          BuilderStatus.get(name).map(Declared(_, "builder", firstLine(call.code), line)).toList
      }
      // A chain (`status(X).body(y)`) nests, so keep walking — but a builder
      // that already answered does not need its arguments searched.
      here ++ (if (here.nonEmpty) Nil else call.argument.l.flatMap(statusesOf(_, line)))
    case other => other.astChildren.l.flatMap(statusesOf(_, line))
  }

  /** `HttpStatus.CREATED` -> 201; a bare `201` -> 201. */
  private def codeOfArgument(argument: AstNode): Option[Int] = argument match {
    case literal: Literal => literal.code.trim.toIntOption.filter(c => c >= 100 && c < 600)
    case call: Call       => constantIn(call.code)
    case _                => constantIn(argument.code)
  }

  private def constantIn(code: String): Option[Int] =
    "HttpStatus\\.([A-Z_]+)".r
      .findFirstMatchIn(code)
      .flatMap(m => ConstantStatus.get(m.group(1)))
      .orElse("\\b([1-5][0-9]{2})\\b".r.findFirstMatchIn(code).flatMap(_.group(1).toIntOption))

  private def firstLine(code: String): String = code.linesIterator.next().trim.take(120)

  private def lineOf(line: Option[Int]): Int = line.getOrElse(0)
}
