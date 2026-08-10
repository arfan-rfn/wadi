package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Block,
  Call,
  Identifier,
  Literal,
  Member,
  Method,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

/** Provider-side wire-shape recovery (§5.2.7).
  *
  * Generics come from the DECLARED SOURCE TEXT (javasrc2cpg erases them in
  * type names); simple names resolve against in-CPG TypeDecls with the
  * §5.2.6 short-name fallback. Honest terminals: `unresolved` (off-CPG type,
  * name only — never fabricated fields, P10), `cycle` (self-reference on the
  * walk path), `truncated` (the walk stopped and said so — depth cap or node
  * budget, §5.2.15; a reader treats both the same way). Jackson field-level
  * semantics:
  * `@JsonProperty` renames the wire name, `@JsonIgnore` omits the field —
  * the shape is the wire contract, not the class layout.
  */
object TypeShapes {

  private val MaxDepth = 6

  /** Expanded objects allowed in ONE shape before the walk emits `truncated`.
    *
    * Measured, not picked. Across ICPC's 804 response shapes the distribution
    * is bimodal, and 200 sits in the empty part between the two modes:
    *
    * {{{
    *      0-1 objects   545 shapes  67.8%   <- the shapes people read
    *     2-10           141          17.5%
    *    11-50            14           1.7%
    *    51-200            5           0.6%  <- the trough the cap sits in
    *   201-500           31           3.9%   <- entity graphs from here up
    *   501-1000          54           6.7%
    *     1001+           14           1.7%   (worst: 2365)
    * }}}
    *
    * So the ceiling clips 99 shapes (12.3%) and every one of them is a
    * bidirectional entity walk, while 87% of shapes — everything a reader
    * actually consults — are 10 objects or fewer and untouched. A shape that
    * hits the ceiling says so in-band via `truncated`; it is never silently
    * shortened, and `truncated` already meant exactly this (§5.2.7).
    */
  private val MaxNodes = 200

  /** Wrappers whose payload is the (first) generic argument. */
  private val UnwrapOne = Set(
    "ResponseEntity",
    "HttpEntity",
    "Optional",
    "Mono",
    "CompletableFuture",
    "Callable",
    "Supplier"
  )
  private val ArrayLike = Set("List", "Set", "Collection", "Iterable", "Flux", "Stream")
  private val MapLike   = Set("Map", "HashMap", "TreeMap", "SortedMap")

  /** `ResponseEntity` static builders whose first argument IS the payload.
    *
    * `ok(x)` covers the static-import form; `body(x)` covers every builder
    * chain that ends in it (`status(...).body(x)`, `badRequest().body(x)`),
    * since the outermost call is what a `return` statement holds. `ok()` with
    * no argument returns a builder, not an entity — it contributes nothing,
    * which is the honest answer rather than an empty object.
    */
  private val ResponseBuilders = Set("ok", "body")

  private val ScalarSimpleNames = Set(
    "String", "CharSequence", "Integer", "int", "Long", "long", "Short", "short",
    "Double", "double", "Float", "float", "Boolean", "boolean", "Byte", "byte",
    "Character", "char", "BigDecimal", "BigInteger", "UUID", "Object", "void", "Void",
    "LocalDate", "LocalDateTime", "LocalTime", "Instant", "OffsetDateTime",
    "ZonedDateTime", "Date", "Duration", "Period", "Number"
  )

  private[`export`] case class RawType(name: String, args: List[RawType], array: Boolean = false)

  /** Structural parse of a declared type text: `A<B, C<D>>[]`. */
  private[`export`] def parseTypeText(text: String): Option[RawType] = {
    val trimmed = text.trim
    if (trimmed.isEmpty) return None
    val (core, isArray) =
      if (trimmed.endsWith("[]")) (trimmed.dropRight(2).trim, true) else (trimmed, false)
    val open = core.indexOf('<')
    if (open < 0) {
      val name = core.trim
      if (name.isEmpty || !name.forall(c => c.isLetterOrDigit || c == '.' || c == '_' || c == '$'))
        None
      else Some(RawType(name, Nil, isArray))
    } else {
      if (!core.endsWith(">")) return None
      val name  = core.substring(0, open).trim
      val inner = core.substring(open + 1, core.length - 1)
      val args  = splitTopLevel(inner).flatMap(parseTypeText)
      if (name.isEmpty) None else Some(RawType(name, args, isArray))
    }
  }

  private def splitTopLevel(text: String): List[String] = {
    val parts = scala.collection.mutable.ListBuffer.empty[String]
    val sb    = new StringBuilder
    var depth = 0
    text.foreach {
      case '<'           => depth += 1; sb.append('<')
      case '>'           => depth -= 1; sb.append('>')
      case ',' if depth == 0 => parts += sb.toString; sb.clear()
      case c             => sb.append(c)
    }
    if (sb.nonEmpty) parts += sb.toString
    parts.toList
  }

  /** The declared return-type text of a method, generics preserved. */
  private[`export`] def returnTypeTextOf(method: Method): Option[String] = {
    val beforeParen = method.code.takeWhile(_ != '(')
    val nameIdx     = beforeParen.lastIndexOf(method.name)
    if (nameIdx <= 0) return None
    trailingTypeToken(beforeParen.substring(0, nameIdx))
  }

  /** The trailing whitespace-delimited token, respecting `<>` nesting —
    * skips modifiers/annotations that precede the type.
    */
  private def trailingTypeToken(text: String): Option[String] = {
    val trimmed = text.trim
    var depth   = 0
    var idx     = trimmed.length - 1
    while (idx >= 0) {
      val c = trimmed(idx)
      if (c == '>') depth += 1
      else if (c == '<') depth -= 1
      else if (c.isWhitespace && depth == 0) return Some(trimmed.substring(idx + 1)).filter(_.nonEmpty)
      idx -= 1
    }
    Some(trimmed).filter(_.nonEmpty)
  }

  /** Build the wire shape for a declared type text.
    *
    * `defs` collects the type definitions the shape references and is shared
    * across ONE endpoint's request and response, which routinely name the same
    * types (§5.2.16).
    */
  def shapeOf(cpg: Cpg, typeText: String, defs: Defs): Option[ujson.Obj] =
    shapeOf(cpg, typeText, Map.empty, defs)

  private def shapeOf(
    cpg: Cpg,
    typeText: String,
    bindings: Map[String, RawType],
    defs: Defs
  ): Option[ujson.Obj] =
    parseTypeText(typeText).map(raw => build(cpg, raw, MaxDepth, bindings, defs))

  /** `T` -> the type the producing method actually puts in that field.
    *
    * §5.2.7 (amended again 2026-08-05, T8): recovering the ENVELOPE is not
    * recovering the response. TrainTicket wraps every payload in
    * `Response<T>` and declares the service method that builds it as a RAW
    * `Response`, so the walk reached `{status, msg, data}` with `data` an
    * unbound `T` on **291 of 365 endpoints** — a shape that names the wrapper
    * and withholds the only field a reader wants.
    *
    * The type argument is not in any signature; it is in the producer's return
    * statement (`return new Response<>(1, "ok", payments)`). javasrc2cpg erases
    * the argument's own type to `java.util.List`, but the LOCAL's declaration
    * text keeps `List<InsidePayment>` — the same "read the declared text, not
    * typeFullName" rule this section already rests on, applied one hop deeper.
    */
  /** The members that make up the WIRE shape, in declaration order.
    *
    * Shared by the shape walk and the type-argument binding so the two cannot
    * disagree about which fields exist: the binding maps field POSITION onto
    * constructor argument position, so a member the walk hides but the binding
    * counts corrupts every index after it.
    */
  private def wireMembers(typeDecl: TypeDecl): List[Member] =
    typeDecl.member.l
      .filterNot(isJsonIgnored)
      .filterNot(_.name.startsWith("$"))
      .filterNot(m => m.modifier.modifierType.l.contains("STATIC"))

  private def typeArgumentBindings(
    cpg: Cpg,
    typeText: String,
    producer: Method
  ): Map[String, RawType] = {
    val bindings = for {
      raw      <- parseTypeText(typeText).toList
      typeDecl <- resolveTypeDecl(cpg, raw.name).toList
      // The SAME member set the shape walk renders. Using the raw member list
      // here silently broke every envelope with a `static final Logger` — the
      // arity guard counted a field the generated constructor never takes, so
      // the binding was skipped, and had the count happened to match, the
      // field-to-argument mapping would have been off by one.
      members = wireMembers(typeDecl)
      // Only the all-args shape is safe to bind positionally: field order maps
      // to argument order (argument 0 is the allocation receiver). Any other
      // arity means the mapping is a guess, and a guessed payload type is
      // worse than an honest `T` (P10).
      inits = producer.ast.isCall
        .filter(c => c.name == "<init>" && c.methodFullName.startsWith(typeDecl.fullName + "."))
        .filter(_.argument.size == members.size + 1)
        .l
      if inits.nonEmpty
      (member, index) <- members.zipWithIndex
      parameterName   <- typeParameterNameOf(cpg, member).toList
      bound           <- reconcileArgument(cpg, producer, inits, index).toList
    } yield parameterName -> bound
    bindings.toMap
  }

  /** The member's declared text when it names a TYPE PARAMETER rather than a
    * type: `T data` on a class the CPG holds no `T` for.
    */
  private def typeParameterNameOf(cpg: Cpg, member: Member): Option[String] =
    memberTypeTextOf(member)
      .filter(text => !text.contains('<') && !text.contains('.'))
      .filter(text => !ScalarSimpleNames.contains(text))
      .filter(text => !ArrayLike.contains(text) && !MapLike.contains(text))
      .filter(text => resolveTypeDecl(cpg, text).isEmpty)

  /** The type every construction agrees this field holds, ignoring `null`.
    *
    * A `null` in the payload position is an ABSENCE, not a competing claim:
    * TrainTicket's failure branches are all `new Response<>(0, "failed",
    * null)`, and treating that as a disagreement would withhold the type the
    * success branch states plainly. Two non-null constructions that disagree
    * still yield nothing.
    */
  private def reconcileArgument(
    cpg: Cpg,
    producer: Method,
    inits: List[Call],
    fieldIndex: Int
  ): Option[RawType] = {
    val arguments = inits.flatMap(_.argument.l.find(_.argumentIndex == fieldIndex + 1))
    // EVERY construction passes null: the field is not unknown, it is empty.
    // TrainTicket writes whole services this way — `pay(...)` returns
    // `new Response<>(_, _, null)` on all five paths — and reporting that as
    // `unresolved` says analysis failed about code that states plainly it
    // sends no payload.
    if (arguments.nonEmpty && arguments.forall(isNullLiteral))
      return Some(RawType(AlwaysNullMarker, Nil))
    val texts = arguments
      .filterNot(isNullLiteral)
      .flatMap(declaredTextOfValue(cpg, producer, _))
      .distinct
    if (texts.sizeIs == 1) texts.headOption.flatMap(parseTypeText) else None
  }

  /** Internal sentinel: a field every construction sets to `null`. */
  private val AlwaysNullMarker = "<always-null>"

  private def isNullLiteral(argument: AstNode): Boolean = argument match {
    case literal: Literal => literal.code.trim == "null"
    case _                => false
  }

  /** The declared type text of a value inside `producer`, generics intact. */
  private def declaredTextOfValue(cpg: Cpg, producer: Method, value: AstNode): Option[String] =
    value match {
      case identifier: Identifier =>
        producer.local
          .nameExact(identifier.name)
          .l
          .flatMap(local => declarationTypeText(local.code, local.name))
          .headOption
          .orElse(
            producer.parameter
              .nameExact(identifier.name)
              .l
              .flatMap(p => declarationTypeText(p.code, p.name))
              .headOption
          )
          .orElse(usableTypeName(identifier.typeFullName))
      case call: Call =>
        cpg.method
          .fullNameExact(call.methodFullName)
          .filterNot(_.isExternal)
          .headOption
          .flatMap(returnTypeTextOf)
          .orElse(usableTypeName(call.typeFullName))
      case literal: Literal => usableTypeName(literal.typeFullName)
      case _                => None
    }

  /** `List<InsidePayment> payments` -> `List<InsidePayment>`. */
  private def declarationTypeText(code: String, name: String): Option[String] = {
    val nameIdx = code.lastIndexOf(name)
    if (nameIdx <= 0) None else trailingTypeToken(code.substring(0, nameIdx))
  }

  /** The response shape for a handler, carrying the provenance of the type it read.
    *
    * §5.2.7 (amended 2026-08-05): the declared return type is the primary
    * evidence and is always tried first. When it is a wrapper written RAW —
    * `public HttpEntity query(...)`, the dominant TrainTicket idiom at 376
    * occurrences against 9 generic ones — there is no type argument to unwrap
    * and the walk would terminate on an off-CPG framework type. The payload is
    * still recoverable, just from the return EXPRESSION rather than the
    * signature. Recovery is strictly a fallback: it can never override a
    * declared generic, and it yields nothing unless every return agrees.
    */
  private[`export`] def responseShapeOf(cpg: Cpg, method: Method, defs: Defs): Option[ujson.Obj] = {
    val declaredText = returnTypeTextOf(method)
    // The producer is needed on BOTH paths. `ResponseEntity<Response>` is a
    // DECLARED generic — so it never took the recovery path — wrapping a RAW
    // `Response` whose `T` is exactly as unbound as the recovered case's.
    // Binding only on recovery left those endpoints showing `data: T` while a
    // handler one line different resolved fully.
    val producer = producerFromReturns(cpg, method)
    val declaredShape = declaredText
      .flatMap(text => shapeOf(cpg, text, bindingsForText(cpg, text, producer), defs))
      .map(withOrigin(_, "declared"))
    val rawWrapper = declaredText
      .flatMap(parseTypeText)
      .exists(raw => UnwrapOne.contains(simpleName(raw.name)) && raw.args.isEmpty)
    if (!rawWrapper) declaredShape
    else
      inferredPayloadOf(cpg, method)
        .flatMap { case (text, inferredProducer) =>
          shapeOf(cpg, text, bindingsForText(cpg, text, inferredProducer.orElse(producer)), defs)
        }
        .map(withOrigin(_, "return-expression"))
        .orElse(declaredShape)
  }

  /** Bindings for the PAYLOAD type inside a wrapper, not the wrapper itself.
    *
    * `ResponseEntity<Response>` needs `Response`'s `T` bound; asking about
    * `ResponseEntity` finds an external type with no members and no answer.
    */
  private def bindingsForText(
    cpg: Cpg,
    typeText: String,
    producer: Option[Method]
  ): Map[String, RawType] =
    parseTypeText(typeText)
      .map(unwrapToPayload)
      .map { payload =>
        // A declared argument is the better evidence when there is one:
        // `Response<Order>` says T=Order outright, no dataflow needed.
        val fromDeclaration = declaredArgumentBindings(cpg, payload)
        if (fromDeclaration.nonEmpty) fromDeclaration
        else producer.map(typeArgumentBindings(cpg, payload.name, _)).getOrElse(Map.empty)
      }
      .getOrElse(Map.empty)

  private def unwrapToPayload(raw: RawType): RawType =
    if (UnwrapOne.contains(simpleName(raw.name)) && raw.args.nonEmpty) unwrapToPayload(raw.args.head)
    else raw

  /** `Response<Order>` -> `T` = `Order`, when the class has ONE parameter.
    *
    * Positional beyond one is not safe: javasrc2cpg materializes no
    * TYPE_PARAMETER nodes for these classes, so with two parameters there is
    * no order to map arguments onto and the binding would be a guess.
    */
  private def declaredArgumentBindings(cpg: Cpg, payload: RawType): Map[String, RawType] = {
    if (payload.args.sizeIs != 1) return Map.empty
    val parameterNames = resolveTypeDecl(cpg, payload.name).toList
      .flatMap(_.member.l)
      .flatMap(typeParameterNameOf(cpg, _))
      .distinct
    if (parameterNames.sizeIs == 1) Map(parameterNames.head -> payload.args.head) else Map.empty
  }

  /** The body-carrying callee of whatever the handler's returns hand back. */
  private def producerFromReturns(cpg: Cpg, method: Method): Option[Method] =
    method.ast.isReturn.l
      .flatMap(ret => payloadExpressionOf(ret.astChildren.l))
      .flatMap(producerOf(cpg, _))
      .headOption

  private def withOrigin(shape: ujson.Obj, origin: String): ujson.Obj = {
    shape("origin") = origin
    shape
  }

  /** The payload type text agreed by every return statement, or None.
    *
    * Disagreement is an honest unknown (P10): if two returns resolve to
    * different types, neither is "the" response shape and we do not elect a
    * winner. `return ok()` with no argument contributes nothing, as does any
    * expression whose type is off-CPG.
    */
  private def inferredPayloadOf(cpg: Cpg, method: Method): Option[(String, Option[Method])] = {
    val resolved = method.ast.isReturn.l
      .flatMap(ret => payloadExpressionOf(ret.astChildren.l))
      .flatMap { expression =>
        typeTextOfExpression(cpg, expression)
          .filterNot(isRawWrapperText)
          .map(text => (text, producerOf(cpg, expression)))
      }
    val texts = resolved.map(_._1).distinct
    // The producer is the method whose body constructs the value, reached
    // through the DI edge — the interface declaration carries the type name but
    // only the implementation carries the type ARGUMENT.
    if (texts.sizeIs == 1) Some((texts.head, resolved.flatMap(_._2).headOption)) else None
  }

  private def producerOf(cpg: Cpg, expression: AstNode): Option[Method] = expression match {
    case call: Call => call.callee(using NoResolve).filterNot(_.isExternal).find(_.body.astChildren.nonEmpty)
    case _          => None
  }

  /** A recovered type that is ITSELF a raw wrapper is not a recovery.
    *
    * `ResponseEntity.noContent().build()` types as `HttpEntity` again, and
    * accepting it published an `object` with zero fields — a shape invented
    * out of an external stub that has no members, which is precisely the
    * fabrication P10 forbids. Learning "it returns a wrapper" is learning
    * nothing, so the claim goes back to being withheld.
    */
  private def isRawWrapperText(text: String): Boolean =
    parseTypeText(text).exists(raw => UnwrapOne.contains(simpleName(raw.name)) && raw.args.isEmpty)

  /** Unwrap the response-builder call around the payload, if there is one. */
  private def payloadExpressionOf(returned: List[AstNode]): Option[AstNode] =
    returned.headOption.flatMap {
      case call: Call if ResponseBuilders.contains(call.name) => firstRealArgument(call)
      case call: Call if isWrapperInit(call)                  => firstRealArgument(call)
      // javasrc2cpg lowers `new X(a, b)` into a BLOCK (alloc, `<init>`, temp),
      // so a directly-returned constructor is nested rather than the returned
      // node itself.
      case block: Block => block.ast.isCall.find(isWrapperInit).flatMap(firstRealArgument)
      case other        => Some(other)
    }

  private def isWrapperInit(call: Call): Boolean =
    call.name == "<init>" &&
      UnwrapOne.contains(simpleName(call.methodFullName.split("\\.<init>").head))

  /** Argument index 0 is the receiver (or the allocation for `<init>`). */
  private def firstRealArgument(call: Call): Option[AstNode] =
    call.argument.l.filter(_.argumentIndex >= 1).sortBy(_.argumentIndex).headOption

  /** A type text for an expression, generics preserved where recoverable.
    *
    * A call resolves through its CALLEE's declaration text — the same rule the
    * declared-generics decision already establishes, applied one hop further,
    * because `typeFullName` is erased and would drop `Response<ArrayList<Order>>`
    * to a bare `Response`.
    */
  private def typeTextOfExpression(cpg: Cpg, expr: AstNode): Option[String] =
    expr match {
      case call: Call =>
        cpg.method
          .fullNameExact(call.methodFullName)
          .filterNot(_.isExternal)
          .headOption
          .flatMap(returnTypeTextOf)
          .orElse(usableTypeName(call.typeFullName))
      case identifier: Identifier => usableTypeName(identifier.typeFullName)
      case literal: Literal       => usableTypeName(literal.typeFullName)
      case _                      => None
    }

  /** javasrc2cpg writes `ANY`/`<empty>`/`<unresolved…>` where it knows nothing —
    * those are not type names and must not be fabricated into a shape (P10).
    */
  private def usableTypeName(name: String): Option[String] =
    Option(name)
      .map(_.trim)
      .filter(n => n.nonEmpty && n != "ANY" && !n.startsWith("<"))

  private def simpleName(name: String): String = {
    val stripped = name.takeWhile(_ != '<')
    stripped.substring(stripped.lastIndexOf('.') + 1)
  }

  /** Nodes left to spend on one shape (§5.2.15).
    *
    * `path` stops a type recurring along ONE root-to-leaf chain, which is
    * cycle detection and is not a bound on output: sibling branches re-expand
    * the same subgraph freely. Against a bidirectional entity graph that is
    * exponential in `MaxDepth` — ICPC's worst response shape reached 3 MB and
    * depth 25, repeating `label` 520 times, and one service's endpoint list
    * reached 114 MB. Depth cannot express "this type is wide"; a node budget
    * can, and it needs no new reader semantics because `truncated` already
    * means "the shape continues and we stopped".
    */
  /** The type definitions this endpoint's shapes reference (§5.2.16).
    *
    * A shape is a graph of types, and expanding it as a tree writes the same
    * definition once per path that reaches it: one real response emitted 2,365
    * object definitions of which 113 were distinct — `Site` 79 times — for
    * 3 MB that no context window could hold. Each type is built ONCE here and
    * referenced wherever it occurs.
    *
    * Two properties this buys beyond size. **Recursion becomes exact**: a type
    * that reaches itself refs back at its own definition, where the `cycle`
    * terminal could only say a loop existed without saying what was in it. And
    * **a definition does not depend on where it was discovered** — it is built
    * from the type, not from the walk position, so the same type cannot come
    * out complete on one path and truncated on another.
    *
    * Keyed including bindings: `Response<A>` and `Response<B>` are different
    * shapes under one name (§5.2.7 T8), so they must not share a definition.
    * Over-splitting merely shares less; sharing them would be wrong.
    */
  private[`export`] final class Defs(private val limit: Int = MaxNodes) {
    private val built     = scala.collection.mutable.LinkedHashMap.empty[String, ujson.Obj]
    private val reserved  = scala.collection.mutable.Set.empty[String]

    def isEmpty: Boolean  = built.isEmpty
    def nonEmpty: Boolean = built.nonEmpty

    /** The definition map, as it goes on the wire. */
    def toJson: ujson.Obj = {
      val obj = ujson.Obj()
      built.foreach { case (name, shape) => obj(name) = shape }
      obj
    }

    /** Ensure `key` is defined, building it with `define` on first request.
      *
      * Reserved before the body is built so a type reaching itself finds the
      * key present and refs it, rather than recursing forever.
      */
    def ensure(key: String)(define: () => ujson.Obj): Boolean = {
      if (built.contains(key) || reserved.contains(key)) return true
      // The budget counts DISTINCT definitions now, not expanded nodes, so it
      // is a backstop for a pathological type graph rather than the thing that
      // makes ordinary output affordable (§5.2.16).
      if (built.size + reserved.size >= limit) return false
      reserved += key
      val shape = define()
      reserved -= key
      built(key) = shape
      true
    }
  }

  /** A stable key for a type under the bindings in force. */
  private def defKey(raw: RawType, bindings: Map[String, RawType]): String = {
    val bound = raw.args.map(a => bindings.getOrElse(a.name, a).name)
    val args  = if (bound.isEmpty) "" else bound.mkString("<", ",", ">")
    raw.name + args
  }

  private def build(
    cpg: Cpg,
    raw: RawType,
    depth: Int,
    bindings: Map[String, RawType],
    defs: Defs
  ): ujson.Obj = {
    // A bound type PARAMETER stands for the type the producer actually supplies
    // (T8): substitute before anything else, or the walk resolves `T` itself.
    if (raw.name == AlwaysNullMarker) return node("always-null", "null")
    bindings.get(raw.name) match {
      case Some(bound) if bound.name != raw.name =>
        return build(cpg, bound, depth, bindings - raw.name, defs)
      case _ =>
    }
    val simple = simpleName(raw.name)
    if (raw.array)
      return node(
        "array",
        raw.name,
        element = Some(build(cpg, raw.copy(array = false), depth, bindings, defs))
      )
    if (UnwrapOne.contains(simple) && raw.args.nonEmpty)
      return build(cpg, raw.args.head, depth, bindings, defs)
    if (ArrayLike.contains(simple)) {
      val element = raw.args.headOption.map(build(cpg, _, depth, bindings, defs))
      return node("array", raw.name, element = element)
    }
    if (MapLike.contains(simple)) {
      val value = raw.args.lift(1).map(build(cpg, _, depth, bindings, defs))
      return node("map", raw.name, element = value)
    }
    if (ScalarSimpleNames.contains(simple)) return node("scalar", raw.name)
    // Depth bounds STRUCTURAL nesting only — `List<Map<String, List<...>>>`.
    // Object recursion is bounded by the definition map instead, so a type is
    // never truncated for being reached late.
    if (depth <= 0) return node("truncated", raw.name)

    resolveTypeDecl(cpg, raw.name) match {
      case None => node("unresolved", raw.name)
      case Some(typeDecl) =>
        val key = defKey(raw, bindings)
        val defined = defs.ensure(key) { () =>
          val fields = wireMembers(typeDecl)
            .map(fieldShape(cpg, _, MaxDepth, bindings, defs))
          node("object", raw.name, fields = fields)
        }
        if (defined) node("ref", key) else node("truncated", raw.name)
    }
  }

  private def fieldShape(
    cpg: Cpg,
    member: Member,
    depth: Int,
    bindings: Map[String, RawType],
    defs: Defs
  ): ujson.Obj = {
    val declaredText = memberTypeTextOf(member).getOrElse(member.typeFullName)
    val shape = parseTypeText(declaredText)
      .map(build(cpg, _, depth, bindings, defs))
      .getOrElse(node("unresolved", member.typeFullName))
    val wireName = jsonPropertyName(member)
    val obj = ujson.Obj("name" -> wireName.getOrElse(member.name), "shape" -> shape)
    if (wireName.exists(_ != member.name)) obj("java_name") = member.name
    obj
  }

  /** The member's declared type text (generics preserved) from its code:
    * `private List<Tag> tags` → `List<Tag>`.
    */
  private def memberTypeTextOf(member: Member): Option[String] = {
    val code    = member.code.takeWhile(c => c != '=' && c != ';')
    val nameIdx = code.lastIndexOf(member.name)
    if (nameIdx <= 0) None else trailingTypeToken(code.substring(0, nameIdx))
  }

  private def jsonPropertyName(member: Member): Option[String] =
    member.ast.isAnnotation
      .filter(_.name == "JsonProperty")
      .headOption
      .flatMap(a => "\"([^\"]*)\"".r.findFirstMatchIn(a.code).map(_.group(1)))
      .filter(_.nonEmpty)

  private def isJsonIgnored(member: Member): Boolean =
    member.ast.isAnnotation.exists(_.name == "JsonIgnore")

  private def resolveTypeDecl(cpg: Cpg, name: String): Option[TypeDecl] = {
    val bare   = name.takeWhile(_ != '<')
    val simple = simpleName(bare)
    cpg.typeDecl
      .fullNameExact(bare)
      .headOption
      .orElse(cpg.typeDecl.nameExact(simple).filterNot(_.isExternal).headOption)
      // Nested classes: javasrc2cpg renders `Outer$Inner` — match the last
      // `$` segment (`StockInfo` inside `PetDetails`).
      .orElse(
        cpg.typeDecl
          .filterNot(_.isExternal)
          .find(td => td.name.split('$').last == simple || td.fullName.endsWith("$" + simple))
      )
  }

  private def node(
    kind: String,
    typeName: String,
    fields: List[ujson.Obj] = Nil,
    element: Option[ujson.Obj] = None
  ): ujson.Obj = {
    val obj = ujson.Obj("kind" -> kind, "type_name" -> typeName)
    if (fields.nonEmpty) obj("fields") = fields
    element.foreach(e => obj("element") = e)
    obj
  }
}
