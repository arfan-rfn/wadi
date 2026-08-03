package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{Member, Method, TypeDecl}
import io.shiftleft.semanticcpg.language.*

/** Provider-side wire-shape recovery (§5.2.7).
  *
  * Generics come from the DECLARED SOURCE TEXT (javasrc2cpg erases them in
  * type names); simple names resolve against in-CPG TypeDecls with the
  * §5.2.6 short-name fallback. Honest terminals: `unresolved` (off-CPG type,
  * name only — never fabricated fields, P10), `cycle` (self-reference on the
  * walk path), `truncated` (depth cap). Jackson field-level semantics:
  * `@JsonProperty` renames the wire name, `@JsonIgnore` omits the field —
  * the shape is the wire contract, not the class layout.
  */
object TypeShapes {

  private val MaxDepth = 6

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

  /** Build the wire shape for a declared type text. */
  def shapeOf(cpg: Cpg, typeText: String): Option[ujson.Obj] =
    parseTypeText(typeText).map(raw => build(cpg, raw, Set.empty, MaxDepth))

  private def simpleName(name: String): String = {
    val stripped = name.takeWhile(_ != '<')
    stripped.substring(stripped.lastIndexOf('.') + 1)
  }

  private def build(cpg: Cpg, raw: RawType, path: Set[String], depth: Int): ujson.Obj = {
    val simple = simpleName(raw.name)
    if (raw.array)
      return node("array", raw.name, element = Some(build(cpg, raw.copy(array = false), path, depth)))
    if (UnwrapOne.contains(simple) && raw.args.nonEmpty)
      return build(cpg, raw.args.head, path, depth)
    if (ArrayLike.contains(simple)) {
      val element = raw.args.headOption.map(build(cpg, _, path, depth))
      return node("array", raw.name, element = element)
    }
    if (MapLike.contains(simple)) {
      val value = raw.args.lift(1).map(build(cpg, _, path, depth))
      return node("map", raw.name, element = value)
    }
    if (ScalarSimpleNames.contains(simple)) return node("scalar", raw.name)
    if (depth <= 0) return node("truncated", raw.name)

    resolveTypeDecl(cpg, raw.name) match {
      case None => node("unresolved", raw.name)
      case Some(typeDecl) =>
        if (path.contains(typeDecl.fullName)) node("cycle", raw.name)
        else {
          val fields = typeDecl.member.l
            .filterNot(isJsonIgnored)
            .filterNot(_.name.startsWith("$"))
            .filterNot(m => m.modifier.modifierType.l.contains("STATIC"))
            .map(fieldShape(cpg, _, path + typeDecl.fullName, depth - 1))
          node("object", raw.name, fields = fields)
        }
    }
  }

  private def fieldShape(cpg: Cpg, member: Member, path: Set[String], depth: Int): ujson.Obj = {
    val declaredText = memberTypeTextOf(member).getOrElse(member.typeFullName)
    val shape = parseTypeText(declaredText)
      .map(build(cpg, _, path, depth))
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
