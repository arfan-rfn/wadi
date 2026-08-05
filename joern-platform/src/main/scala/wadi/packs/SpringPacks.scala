package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder}
import io.shiftleft.codepropertygraph.generated.nodes.{
  Call,
  FieldIdentifier,
  Identifier,
  Literal,
  Method,
  TypeDecl
}
import io.shiftleft.passes.CpgPass
import io.shiftleft.semanticcpg.language.*

/** Framework query packs for Spring (§5.1): find and TAG nodes.
  *
  * Tags persist in the CPG; the exporter collects tags rather than
  * re-detecting. Only registry-governed vocabulary is emitted (§7):
  * `endpoint=<METHOD> <path>`, `sink=db`, `sink=http-client`, `model=<Entity>`,
  * `async-root=<kind>` (T4 §5.4.2).
  */
object SpringPacks {

  /** All packs, applied in order. The token-propagation pass runs LAST — it
    * reads the sink tags the client/feign passes just stored.
    */
  def applyAll(cpg: Cpg): Unit = {
    new SpringEndpointPass(cpg).createAndApply()
    new SpringAsyncRootPass(cpg).createAndApply()
    new SpringHttpClientSinkPass(cpg).createAndApply()
    new SpringSecurityPack.SpringFeignSinkPass(cpg).createAndApply()
    new SpringSecurityPack.SpringHttpInterfaceSinkPass(cpg).createAndApply()
    new SpringDataSinkPass(cpg).createAndApply()
    new SpringModelPass(cpg).createAndApply()
    new SpringSecurityPack.SpringSecurityAnnotationPass(cpg).createAndApply()
    new SpringSecurityPack.SpringSecurityDslPass(cpg).createAndApply()
    new SpringSecurityPack.SpringSecurityBypassPass(cpg).createAndApply()
    new SpringSecurityPack.SpringAuthMechanismPass(cpg).createAndApply()
    new SpringSecurityPack.SpringAuthEnforcementPass(cpg).createAndApply()
    new SpringSecurityPack.SpringRequestPolicyPass(cpg).createAndApply()
    new SpringSecurityPack.SpringAuthorityModelPass(cpg).createAndApply()
    new SpringSecurityPack.SpringTokenPropagationPass(cpg).createAndApply()
  }

  private[wadi] val MappingAnnotations: Map[String, String] = Map(
    "GetMapping"    -> "GET",
    "PostMapping"   -> "POST",
    "PutMapping"    -> "PUT",
    "DeleteMapping" -> "DELETE",
    "PatchMapping"  -> "PATCH"
  )

  /** First quoted string in an annotation's code, e.g. `@GetMapping("/pets/{id}")`. */
  private[wadi] def pathFromAnnotationCode(code: String): Option[String] = {
    val quoted = "\"([^\"]*)\"".r
    quoted.findFirstMatchIn(code).map(_.group(1))
  }

  /** ALL paths a mapping annotation declares (§5.4.2 endpoint idioms):
    *   - `@GetMapping({"/storefront/x", "/backoffice/x"})` — one endpoint per
    *     array entry (the yas multi-path idiom; first-string-only lost the rest)
    *   - `@RequestMapping(Constants.ApiConstant.COUNTRIES_URL)` — a static
    *     final constant reference, resolved from the in-CPG initializer (the
    *     yas prefix idiom)
    *   - `@RequestMapping(PREFIX + "/api")` — a concatenation, resolved
    *     operand by operand (§5.4.2, 2026-08-05)
    *
    * A constant that does NOT resolve falls back to the literal tail. That
    * fallback was once recorded as "honest truncation, better than CIMET's
    * raw constant text" — and a production system falsified it: two
    * controllers whose prefixes both truncated to `/search` produced identical
    * URIs, and since endpoint ids are content-derived from the URI, the store
    * upsert REPLACED one with the other and three endpoints vanished. A
    * truncated path is not merely less precise; under content-derived identity
    * it is destructive, while unresolved constant text is at least unique.
    * Endpoint-id collisions are now recorded (§7) so the loss cannot recur
    * silently, and the remaining work is to hole the path rather than truncate
    * it.
    */
  private[wadi] def pathsFromAnnotationCode(cpg: Cpg, code: String): List[String] = {
    // Greedy across nested `{id}` template braces: the array block is the
    // OUTERMOST brace pair (`{"/a/{id}", "/b/{id}"}`).
    val arrayInner = "\\{(.*)\\}".r.findFirstMatchIn(code).map(_.group(1))
    val arrayPaths = arrayInner.toList.flatMap { inner =>
      "\"([^\"]*)\"".r.findAllMatchIn(inner).map(_.group(1)).toList
    }
    if (arrayPaths.nonEmpty) arrayPaths
    else
      // Concatenation is tried BEFORE the first-quoted-string reader, and the
      // order is the whole fix: `@RequestMapping(PREFIX + "/api")` contains a
      // quoted literal, so first-quoted-string answered `/api` and every URI
      // in the service silently lost the prefix that told two controllers
      // apart. A truncated path is worse than an unresolved one — it collides
      // with real routes elsewhere in the system.
      concatenatedPathFromCode(cpg, code)
        // A concatenation whose operands do not ALL resolve is holed, never
        // truncated. Falling through to the first quoted string here is what
        // collapsed `/person/search` and `/team/search` onto `/search`, and
        // since ids derive from the path, one endpoint replaced the other.
        // `{?}/search` is imprecise; `/search` was destructive.
        .orElse(holedConcatPathFromCode(cpg, code))
        .orElse(pathFromAnnotationCode(code))
        .map(List(_))
        .getOrElse(constantPathFromCode(cpg, code).toList)
  }

  /** `@RequestMapping(PREFIX + "/api")` → the joined path, when every operand
    * resolves. Returns None for annotations with no top-level `+`, leaving the
    * existing readers untouched.
    */
  private def holedConcatPathFromCode(cpg: Cpg, code: String): Option[String] =
    holedStringExpression(cpg, annotationArgument(code), owner = None)

  private def annotationArgument(code: String): String = {
    val inner =
      code.dropWhile(_ != '(').stripPrefix("(").reverse.dropWhile(_ != ')').drop(1).reverse
    inner.replaceAll("^\\s*(?:value|path)\\s*=\\s*", "").trim
  }

  private def concatenatedPathFromCode(cpg: Cpg, code: String): Option[String] = {
    val inner     = code.dropWhile(_ != '(').stripPrefix("(").reverse.dropWhile(_ != ')').drop(1).reverse
    val reference = inner.replaceAll("^\\s*(?:value|path)\\s*=\\s*", "").trim
    stringExpression(cpg, reference, owner = None)
  }

  /** Resolve `Klass.FIELD` (possibly nested, `Constants.ApiConstant.X`) to its
    * static-final string literal via the constructor/clinit-lowered
    * assignment. Only a literal counts (P10 — never a guess).
    */
  private def constantPathFromCode(cpg: Cpg, code: String): Option[String] = {
    val inner = code.dropWhile(_ != '(').stripPrefix("(").takeWhile(_ != ')')
    val reference = inner.replaceAll("^\\s*(?:value|path)\\s*=\\s*", "").trim
    // `@RequestMapping(PREFIX + "/x")` — without the concatenation reader the
    // path truncates to its tail, and every URI in the service silently loses
    // the segment that told two controllers apart.
    constantString(cpg, reference, owner = None)
      .orElse(stringExpression(cpg, reference, owner = None))
  }

  /** Resolve a source-text reference to the string literal it names.
    *
    * Handles `FIELD`, `this.FIELD`, `Klass.FIELD` and nested
    * `Outer.Inner.FIELD`, reading the constructor/clinit-lowered assignment.
    * Shared by every pack that meets a non-literal where it wanted a string —
    * mapping annotations, `@FeignClient` names, and SecurityConfig matcher
    * patterns and role arguments (§5.2.9), which is why it lives here rather
    * than being re-derived per pass.
    *
    * `owner` scopes a BARE name to the class that wrote it: member lookup is
    * owner-scoped (§5.2.5), because two classes that both declare `order`
    * would otherwise conflate into a false match. Returns None when the
    * reference resolves to conflicting literals — an ambiguous constant is an
    * honest unknown, never a pick (P10).
    */
  private[wadi] def constantString(
      cpg: Cpg,
      reference: String,
      owner: Option[TypeDecl]
  ): Option[String] = constantString(cpg, reference, owner, depth = 0)

  /** `depth` bounds the recursion when a constant's initializer is ITSELF an
    * expression (`static final String B = A + "/x"`). Java allows that chain to
    * any length and the JLS keeps every link a compile-time constant, so the
    * only real risks are a cycle (illegal in Java, but a malformed graph can
    * still present one) and pathological depth. Four links is far past any
    * observed idiom and costs nothing to allow.
    */
  private def constantString(
      cpg: Cpg,
      reference: String,
      owner: Option[TypeDecl],
      depth: Int
  ): Option[String] = {
    val normalized = reference.trim.stripPrefix("this.").trim
    val segments   = normalized.split('.').toList.filter(_.nonEmpty)
    if (segments.isEmpty || !segments.forall(_.matches("[A-Za-z_$][\\w$]*"))) return None
    val fieldName  = segments.last
    val qualifier  = Option.when(segments.sizeIs >= 2)(segments(segments.length - 2))

    // Materialised: these are LAZY traversals, and the owner fallback below
    // has to ask whether a candidate set is empty before choosing it. Asking
    // an iterator that question consumes it, so a lazy `named` would answer
    // the question and then hand back nothing — the fix would silently no-op.
    val named = cpg.assignment
      .filter(a =>
        a.target.ast.exists {
          case fi: FieldIdentifier => fi.canonicalName == fieldName
          case id: Identifier      => id.name == fieldName
          case _                   => false
        }
      )
      .l
    val scoped = qualifier match {
      // Nested constant holders (yas `Constants.ApiConstant`): the lowered
      // assignment may sit in the inner OR outer class's initializer, and the
      // inner name only appears as a `$` segment of the fullName.
      case Some(className) =>
        named.filter(a =>
          a.method.typeDecl.exists(td =>
            td.name == className || td.fullName.split("[.$]").contains(className)
          ) || a.target.code.contains(s"$className.")
        )
      // A bare name belongs to the type that declared it (§5.2.5) — UNLESS the
      // owner did not declare it, in which case the name came from elsewhere
      // and owner scoping would answer "unresolvable" for a constant sitting
      // in plain sight.
      //
      // Measured 2026-08-05: `SecurityConfig` references `REST_PERSON_PREFIX`
      // through `import static ...RestConstants.*`. The same constant in the
      // same CPG resolved for endpoint paths (which pass owner = None) and
      // failed for matcher patterns (which pass the owner), leaving 9 rules
      // without scope and withholding the auth claim on 729 endpoints. The
      // scoping is still right when the owner DOES declare the name — that is
      // what keeps two classes declaring `order` apart — so it keeps
      // precedence and only yields when it has nothing to say.
      case None =>
        owner match {
          case Some(td) =>
            val declaredHere =
              named.filter(_.method.typeDecl.exists(_.fullName == td.fullName))
            if (declaredHere.nonEmpty) declaredHere else named
          case None => named
        }
    }
    val literals = scoped
      .flatMap(_.source match {
        case literal: Literal => Some(literal.code.stripPrefix("\"").stripSuffix("\""))
        // `static final String B = A + "/x"` — the initializer is a constant
        // EXPRESSION, not a literal. Reading only literals answered
        // "unresolvable" for a value the graph fully determines.
        case other if depth < MaxConstantDepth =>
          stringExpression(cpg, other.code, owner, depth + 1)
        case _ => None
      })
      .distinct
    Option.when(literals.sizeIs == 1)(literals.head)
  }

  /** A source-text string EXPRESSION → its value, concatenation included.
    *
    * `PREFIX + "/public/x"` is the prevailing way a codebase
    * writes a route once and reuses it, and it defeated every reader here:
    * `constantString` resolves a bare reference and a literal is a literal,
    * but neither handles the `+` between them. The cost is paid twice, which
    * is why this lives in the shared resolver rather than in either caller —
    * the endpoint pass loses its URI prefix (paths truncate to the tail) and
    * the security pass loses its pattern (the rule reads as unscoped, which
    * §5.2.10 then has to withhold on).
    *
    * All-or-nothing by design: a concatenation with one unresolvable operand
    * yields None rather than a partial path, because half a pattern silently
    * matches the wrong endpoints (P10 — an honest hole beats a plausible
    * string).
    */
  private[wadi] val MaxConstantDepth = 4

  /** The marker a path carries where an operand could not be resolved (§5.4.2).
    *
    * Deliberately NOT an empty string. Dropping the operand shortens the path
    * onto whatever other routes share the tail, and endpoint ids are derived
    * from the path — a production system lost three endpoints to exactly that
    * collapse. A hole keeps the path unique, so an unresolved prefix costs
    * precision and never a row.
    */
  private[wadi] val PathHole = "{?}"

  private[wadi] def stringExpression(
      cpg: Cpg,
      text: String,
      owner: Option[TypeDecl]
  ): Option[String] = stringExpression(cpg, text, owner, depth = 0)

  private def stringExpression(
      cpg: Cpg,
      text: String,
      owner: Option[TypeDecl],
      depth: Int
  ): Option[String] = {
    val resolved = concatOperands(cpg, text, owner, depth)
    if (resolved.isEmpty) return None
    Option.when(resolved.forall(_.isDefined))(resolved.flatten.mkString)
  }

  /** The same evaluation, but rendering unresolved operands as holes.
    *
    * Only meaningful for an expression that IS a concatenation — a bare
    * unresolvable reference has nothing to anchor a hole against, and the
    * existing readers already answer honestly there.
    */
  private[wadi] def holedStringExpression(
      cpg: Cpg,
      text: String,
      owner: Option[TypeDecl]
  ): Option[String] = {
    val resolved = concatOperands(cpg, text, owner, depth = 0)
    if (resolved.isEmpty || resolved.forall(_.isDefined)) return None
    Some(resolved.map(_.getOrElse(PathHole)).mkString)
  }

  private def concatOperands(
      cpg: Cpg,
      text: String,
      owner: Option[TypeDecl],
      depth: Int
  ): List[Option[String]] = {
    val operands = splitTopLevelConcat(text)
    if (operands.isEmpty) return Nil
    operands.map { operand =>
      val trimmed = operand.trim
      if (trimmed.length >= 2 && trimmed.startsWith("\"") && trimmed.endsWith("\""))
        Some(trimmed.substring(1, trimmed.length - 1))
      else constantString(cpg, trimmed, owner, depth)
    }
  }

  /** Split on `+` that sits OUTSIDE string literals. A `+` inside a quoted
    * segment is part of the path (`"/a+b"`), not an operator.
    */
  private def splitTopLevelConcat(text: String): List[String] = {
    val parts    = scala.collection.mutable.ListBuffer.empty[String]
    val current  = new StringBuilder
    var inString = false
    var escaped  = false
    text.foreach { char =>
      if (escaped) { current.append(char); escaped = false }
      else
        char match {
          case '\\' if inString      => current.append(char); escaped = true
          case '"'                   => inString = !inString; current.append(char)
          case '+' if !inString      => parts += current.toString; current.clear()
          case other                 => current.append(other)
        }
    }
    parts += current.toString
    val cleaned = parts.toList.map(_.trim).filter(_.nonEmpty)
    // Nothing to do for a single operand — the caller's own resolvers already
    // handle a bare literal or reference, and returning it here would make
    // this function a second, competing path to the same answer.
    if (cleaned.sizeIs <= 1) Nil else cleaned
  }

  /** Every in-repo supertype of `typeDecl`, transitively (classes AND
    * interfaces), cycle-guarded.
    *
    * Resolves by full name first and falls back to the short name for jar-less
    * parses (§5.2.6). Shared by the feign shared-contract idiom and the
    * security-annotation inheritance walk (§5.2.9) — both need "what did my
    * ancestors declare", and re-deriving it per pass is how one of them ends
    * up with the fallback and the other without it.
    */
  private[wadi] def transitiveParents(cpg: Cpg, typeDecl: TypeDecl): List[TypeDecl] = {
    val visited = scala.collection.mutable.Set.empty[Long]
    def walk(current: TypeDecl): List[TypeDecl] = {
      if (visited.contains(current.id)) return Nil
      visited.add(current.id)
      val parents = current.inheritsFromTypeFullName.l.flatMap { parent =>
        (cpg.typeDecl.fullNameExact(parent).l ++
          cpg.typeDecl.nameExact(parent.split('.').last).filterNot(_.isExternal).l).distinct
      }
      parents.flatMap(p => p :: walk(p))
    }
    walk(typeDecl).distinctBy(_.id)
  }

  private[wadi] def joinPaths(prefix: String, path: String): String = {
    val left = prefix.stripSuffix("/")
    val joined =
      if (path.isEmpty) left
      else if (path.startsWith("/")) s"$left$path"
      else s"$left/$path"
    if (joined.isEmpty) "/" else joined
  }
}

/** Tags controller methods: `endpoint=GET /pets/{id}` (class-level prefix respected).
  *
  * Only types annotated `@RestController`/`@Controller` count: `@FeignClient`
  * interfaces also carry `@GetMapping` etc., but there they declare OUTBOUND
  * calls, not served endpoints (found against TrainTicket ground truth —
  * counting them is a false positive an endpoint inventory must not make).
  */
class SpringEndpointPass(cpg: Cpg) extends CpgPass(cpg) {
  import SpringPacks.*

  private val ControllerAnnotations = Set("RestController", "Controller")

  override def run(builder: DiffGraphBuilder): Unit =
    cpg.typeDecl
      .filterNot(_.isExternal)
      .filter { td =>
        td.ast.isAnnotation
          .filter(_.astParent == td)
          .exists(a => ControllerAnnotations.contains(a.name))
      }
      .l
      .foreach { controller =>
        val classPrefix = controller.ast.isAnnotation
          .filter(a => a.name == "RequestMapping")
          .filter(_.astParent == controller)
          .headOption
          .flatMap(a => pathsFromAnnotationCode(cpg, a.code).headOption)
          .getOrElse("")

        controller.method.l.foreach { method =>
          method.ast.isAnnotation.filter(_.astParent == method).l.foreach { annotation =>
            MappingAnnotations.get(annotation.name).foreach { httpMethod =>
              // A path-less mapping serves the class prefix itself — an empty
              // path must not append a trailing slash (identity form, §7).
              // Multi-path arrays emit one endpoint per declared path (§5.4.2).
              val paths = pathsFromAnnotationCode(cpg, annotation.code) match {
                case Nil      => List("")
                case declared => declared
              }
              paths.foreach { path =>
                val uri = joinPaths(classPrefix, path)
                Iterator(method).newTagNodePair("endpoint", s"$httpMethod $uri").store()(using builder)
              }
            }
            if (annotation.name == "RequestMapping" && MappingAnnotations.values.exists(v => annotation.code.contains(v))) {
              MappingAnnotations.values.filter(v => annotation.code.contains(v)).foreach { httpMethod =>
                val paths = pathsFromAnnotationCode(cpg, annotation.code) match {
                  case Nil      => List("/")
                  case declared => declared
                }
                paths.foreach { path =>
                  Iterator(method).newTagNodePair("endpoint", s"$httpMethod ${joinPaths(classPrefix, path)}").store()(using builder)
                }
              }
            }
          }
        }
      }
}

/** Tags outbound HTTP client call sites (§5.2.5).
  *
  * Four shapes:
  *   - RestTemplate: any call on the RestTemplate type -> `sink=http-client`.
  *   - WebClient / RestClient (T2, §5.4.2): both are the same fluent shape —
  *     the chain's `.uri(...)` step is the sink (it carries the URL argument;
  *     the chain root `.get()` does not) -> `sink=http-client` plus
  *     `wadi-client=<webclient|restclient>` and, when the chain root names a
  *     verb, `wadi-verb=<VERB>`. RestClient was the yas lesson: 34 real call
  *     sites exported as a clean zero because no pass modelled the type.
  *     *Rejected: tagging the chain root (Phase 2 as-shipped) — no URL
  *     argument, every WebClient sink exported null.*
  *   - Suspected: an HTTP-shaped call name on a receiver the CPG could not
  *     resolve -> `sink=http-client-suspected`. A countable maybe (P10) —
  *     silently vanishing sinks were how coverage losses became invisible.
  */
class SpringHttpClientSinkPass(cpg: Cpg) extends CpgPass(cpg) {

  private val RestTemplatePrefixes = List(
    "org.springframework.web.client.RestTemplate",
    // Unresolved-type fallback (no dependency jars): javasrc2cpg emits short names.
    "RestTemplate"
  )

  /** Fluent-chain verb steps (chain root, receiver = WebClient/RestClient). */
  private val FluentVerbSteps =
    Set("get", "post", "put", "delete", "patch", "head", "options", "method")

  /** Fluent HTTP clients that share the verb-root + `.uri(...)` chain shape,
    * in detection order (a chain mentions exactly one of them).
    */
  private val FluentClients = List("WebClient" -> "webclient", "RestClient" -> "restclient")

  /** Unambiguously HTTP-shaped call names for suspected-sink detection —
    * deliberately excludes generic names (`put`, `delete`, `execute`, `get`).
    */
  private val SuspectedHttpNames = Set(
    "getForObject",
    "getForEntity",
    "postForObject",
    "postForEntity",
    "postForLocation",
    "patchForObject",
    "headForHeaders",
    "optionsForAllow",
    "exchange"
  )

  private val VerbArgument = """(?:org\.springframework\.http\.)?HttpMethod\.([A-Z]+)""".r

  override def run(builder: DiffGraphBuilder): Unit =
    cpg.call.l.foreach { call =>
      val target = call.methodFullName
      lazy val fluentClient: Option[(String, Call)] =
        if (call.name != "uri") None
        else
          FluentClients.iterator.flatMap { case (marker, mechanism) =>
            fluentChainRoot(call, marker).map(root => (mechanism, root))
          }.nextOption()
      if (RestTemplatePrefixes.exists(prefix => target.startsWith(prefix + "."))) {
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
        // RequestEntity-form exchange (T2): the verb lives on the entity's
        // builder chain, off the call site — recover it here so the export's
        // literal-HttpMethod fallback isn't the only source.
        if (call.name == "exchange") {
          requestEntityVerbOf(call).foreach { verb =>
            Iterator(call).newTagNodePair("wadi-verb", verb).store()(using builder)
          }
        }
      } else if (fluentClient.isDefined) {
        val (mechanism, root) = fluentClient.get
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
        Iterator(call).newTagNodePair("wadi-client", mechanism).store()(using builder)
        verbOfChainRoot(root).foreach { verb =>
          Iterator(call).newTagNodePair("wadi-verb", verb).store()(using builder)
        }
      } else if (receiverUnresolvable(call) && declaredReceiverMentions(call, "RestTemplate")) {
        // The receiver's DECLARED member type says RestTemplate even though
        // the frontend couldn't type the access — the inherited-field idiom
        // (client held by an abstract base, §5.2.6): a confirmed sink, not a
        // suspected one.
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
      } else if (SuspectedHttpNames.contains(call.name) && receiverUnresolvable(call)) {
        Iterator(call).newTagNodePair("sink", "http-client-suspected").store()(using builder)
      }
    }

  /** The declared type of the receiver's backing member, resolved through the
    * in-CPG class hierarchy — inherited `protected final RestTemplate` fields
    * defeat the frontend's receiver typing but their declarations don't lie.
    */
  private def declaredReceiverMentions(call: Call, marker: String): Boolean = {
    val receiver = call.argument.argumentIndexLte(0).headOption
    val receiverTyped = receiver.exists {
      case identifier: io.shiftleft.codepropertygraph.generated.nodes.Identifier =>
        identifier.typeFullName.contains(marker)
      case _ => false
    }
    if (receiverTyped) return true
    val fieldName = receiver.flatMap {
      case identifier: io.shiftleft.codepropertygraph.generated.nodes.Identifier =>
        Some(identifier.name)
      case access: Call if access.name == "<operator>.fieldAccess" =>
        access.ast.collectFirst {
          case fi: io.shiftleft.codepropertygraph.generated.nodes.FieldIdentifier =>
            fi.canonicalName
        }
      case _ => None
    }
    fieldName.exists { name =>
      var owners  = call.method.typeDecl.l
      val visited = scala.collection.mutable.Set.empty[Long]
      var found   = false
      while (owners.nonEmpty && !found) {
        val fresh = owners.filterNot(td => visited.contains(td.id))
        fresh.foreach(td => visited.add(td.id))
        found = fresh.exists(_.member.nameExact(name).typeFullName.exists(_.contains(marker)))
        owners =
          if (found) Nil
          else
            fresh
              .flatMap(_.inheritsFromTypeFullName)
              .flatMap(parent =>
                cpg.typeDecl.fullNameExact(parent).l ++
                  cpg.typeDecl.nameExact(parent.split('.').last).filterNot(_.isExternal).l
              )
      }
      found
    }
  }

  /** The verb step under a `.uri(...)` call: its receiver, when that is a
    * fluent client chain (resolved `WebClient`/`RestClient` (+`$…Spec`) type,
    * or — for jar-less CPGs — a receiver chain touching a marker-typed node).
    */
  private def fluentChainRoot(uriCall: Call, marker: String): Option[Call] =
    uriCall.argument.argumentIndexLte(0).headOption.collect {
      case root: Call if FluentVerbSteps.contains(root.name) && chainTouches(root, marker) =>
        root
    }

  private def chainTouches(
    node: io.shiftleft.codepropertygraph.generated.nodes.Expression,
    marker: String
  ): Boolean = {
    val mentions = (s: String) => s == marker || s.contains(s".$marker") || s.contains(s"$marker$$")
    node match {
      case call: Call =>
        mentions(call.methodFullName.split(':').head) ||
        call.argument.argumentIndexLte(0).headOption.exists(chainTouches(_, marker))
      case identifier: io.shiftleft.codepropertygraph.generated.nodes.Identifier =>
        mentions(identifier.typeFullName)
      case _ => false
    }
  }

  private def verbOfChainRoot(root: Call): Option[String] =
    root.name match {
      case "method" =>
        root.argument.argumentIndexGt(0).code.headOption.map(_.trim).collect {
          case VerbArgument(verb) => verb
        }
      case verbName if FluentVerbSteps.contains(verbName) => Some(verbName.toUpperCase)
      case _                                              => None
    }

  private val RequestEntityVerbs = Map(
    "get"     -> "GET",
    "post"    -> "POST",
    "put"     -> "PUT",
    "delete"  -> "DELETE",
    "patch"   -> "PATCH",
    "head"    -> "HEAD",
    "options" -> "OPTIONS"
  )

  /** The verb of a `RequestEntity` passed to `exchange(entity, …)` — from the
    * inline builder chain, or from the method-local assignment feeding the
    * argument. Only a RequestEntity-anchored verb call counts (never a guess).
    */
  private def requestEntityVerbOf(call: Call): Option[String] = {
    def verbIn(node: io.shiftleft.codepropertygraph.generated.nodes.AstNode): Option[String] =
      node.ast.isCall.l.sortBy(_.id).collectFirst {
        case c
            if RequestEntityVerbs.contains(c.name) &&
              (c.methodFullName.contains("RequestEntity") ||
                c.code.replaceAll("\\s", "").contains("RequestEntity.")) =>
          RequestEntityVerbs(c.name)
      }
    call.argument.argumentIndex(1).headOption.flatMap {
      case inline: Call => verbIn(inline)
      case identifier: io.shiftleft.codepropertygraph.generated.nodes.Identifier =>
        call.method.assignment
          .where(_.target.isIdentifier.nameExact(identifier.name))
          .l
          .sortBy(_.id)
          .iterator
          .flatMap(a => verbIn(a.source))
          .nextOption()
      case _ => None
    }
  }

  /** javasrc2cpg marks unsolvable receivers with placeholder namespaces. */
  private def receiverUnresolvable(call: Call): Boolean = {
    val declaring = call.methodFullName.split(':').head
    declaring.startsWith("<unresolved") || declaring.startsWith("ANY.") ||
    declaring.startsWith("<empty>") || !declaring.contains(".")
  }
}

/** Tags spring-data repository call sites: `sink=db`. */
class SpringDataSinkPass(cpg: Cpg) extends CpgPass(cpg) {

  private val RepositoryMarkers = List(
    "org.springframework.data.repository",
    "org.springframework.data.mongodb.repository",
    "org.springframework.data.jpa.repository",
    "MongoRepository",
    "CrudRepository",
    "JpaRepository",
    "PagingAndSortingRepository"
  )

  override def run(builder: DiffGraphBuilder): Unit = {
    val repositoryTypes: Set[String] =
      cpg.typeDecl
        .filter(td => td.inheritsFromTypeFullName.exists(parent => RepositoryMarkers.exists(parent.contains)))
        .fullName
        .toSet

    if (repositoryTypes.isEmpty) return

    cpg.call.l.foreach { call =>
      val declaring = call.methodFullName.split(':').head
      val owner     = declaring.substring(0, math.max(declaring.lastIndexOf('.'), 0))
      if (repositoryTypes.contains(owner)) {
        Iterator(call).newTagNodePair("sink", "db").store()(using builder)
      }
    }
  }
}

/** Tags persisted entities: `model=<Entity>` on @Document / @Entity classes. */
/** T4 (§5.4.2): non-endpoint reachability roots — methods the framework
  * invokes without an HTTP request. The export roots the reachable closure at
  * endpoints ∪ these, so scheduled jobs, listeners, and boot runners stop
  * being invisible flows. Tag value is the root kind; MQ *semantics* of the
  * listener kinds stay with the Phase 3 MQ packs — this tag only roots
  * reachability.
  */
/** The `async-root` tag vocabulary this pack may emit (§7, recorded
  * 2026-08-05). Enumerated in ONE place so the pack has a set to conform with:
  * the vocabulary is owned by `wadi-contracts` (`ASYNC_ROOT_KINDS`) and
  * published to `schemas/vocabulary/async_root_kinds.json`, which
  * `AsyncRootVocabularyTest` diffs against `All` in both directions. Nothing
  * else spans the Scala/Python boundary — a kind added here and not there is
  * exactly the drift that took a snapshot down on 2026-08-05.
  */
object AsyncRootKind {
  val Scheduled         = "scheduled"
  val EventListener     = "event-listener"
  val KafkaListener     = "kafka-listener"
  val RabbitListener    = "rabbit-listener"
  val JmsListener       = "jms-listener"
  val ApplicationRunner = "application-runner"
  val Bean              = "bean"
  val FrameworkCallback = "framework-callback"

  val All: Set[String] = Set(
    Scheduled,
    EventListener,
    KafkaListener,
    RabbitListener,
    JmsListener,
    ApplicationRunner,
    Bean,
    FrameworkCallback
  )
}

class SpringAsyncRootPass(cpg: Cpg) extends CpgPass(cpg) {

  private val AnnotationKinds: Map[String, String] = Map(
    "Scheduled"                  -> AsyncRootKind.Scheduled,
    "Schedules"                  -> AsyncRootKind.Scheduled,
    "EventListener"              -> AsyncRootKind.EventListener,
    "TransactionalEventListener" -> AsyncRootKind.EventListener,
    "KafkaListener"              -> AsyncRootKind.KafkaListener,
    "RabbitListener"             -> AsyncRootKind.RabbitListener,
    "JmsListener"                -> AsyncRootKind.JmsListener
  )

  /** Both spellings: fully-qualified when javasrc2cpg resolves the import,
    * bare when it cannot (the same fallback every sibling pass carries).
    */
  private val RunnerInterfaces = Set(
    "org.springframework.boot.ApplicationRunner",
    "org.springframework.boot.CommandLineRunner",
    "ApplicationRunner",
    "CommandLineRunner"
  )

  /** Stereotypes whose instances the container constructs and hands to
    * framework machinery (the `framework-callback` rule below).
    */
  private val StereotypeAnnotations =
    Set("Component", "Service", "Configuration", "Repository")

  override def run(builder: DiffGraphBuilder): Unit = {
    cpg.method.filterNot(_.isExternal).l.foreach { method =>
      method.ast.isAnnotation.filter(_.astParent == method).l.foreach { annotation =>
        AnnotationKinds.get(annotation.name).foreach { kind =>
          Iterator(method).newTagNodePair("async-root", kind).store()(using builder)
        }
        // @Bean factory methods run at context startup (§5.4.2 T4).
        if (annotation.name == "Bean") {
          Iterator(method).newTagNodePair("async-root", AsyncRootKind.Bean).store()(using builder)
        }
      }
    }
    cpg.typeDecl
      .filterNot(_.isExternal)
      .filter(_.inheritsFromTypeFullName.exists(RunnerInterfaces.contains))
      .method
      .nameExact("run")
      .filterNot(_.isExternal)
      .l
      .foreach { method =>
        Iterator(method).newTagNodePair("async-root", AsyncRootKind.ApplicationRunner).store()(using builder)
      }
    // A stereotype component implementing an EXTERNAL supertype is a framework
    // callback: the container constructs it and invokes its overrides through
    // an interface the CPG cannot see into (`@Component implements
    // feign.RequestInterceptor`). Internal-interface dispatch stays with the
    // DI pass; java.lang.Object is inherited by everything and proves nothing.
    cpg.typeDecl
      .filterNot(_.isExternal)
      .filter { td =>
        td.ast.isAnnotation
          .filter(_.astParent == td)
          .exists(a => StereotypeAnnotations.contains(a.name))
      }
      .filter { td =>
        // `_refOut`, not `.referencedTypeDecl` — the strict accessor throws
        // on a TYPE missing its mandatory REF edge (same failure class as
        // unresolvable method refs; benchmark-proven).
        td.inheritsFromOut.l
          .flatMap(_._refOut.collectAll[TypeDecl])
          .filterNot(_.fullName == "java.lang.Object")
          .exists(_.isExternal)
      }
      .method
      .filterNot(_.isExternal)
      .filterNot(_.name.startsWith("<"))
      .filterNot(_.modifier.modifierType.l.contains("STATIC"))
      .filterNot(_.modifier.modifierType.l.contains("PRIVATE"))
      .l
      .foreach { method =>
        Iterator(method).newTagNodePair("async-root", AsyncRootKind.FrameworkCallback).store()(using builder)
      }
  }
}

class SpringModelPass(cpg: Cpg) extends CpgPass(cpg) {

  private val PersistenceAnnotations = Set("Document", "Entity")

  override def run(builder: DiffGraphBuilder): Unit =
    cpg.typeDecl.filterNot(_.isExternal).l.foreach { typeDecl =>
      val annotated = typeDecl.ast.isAnnotation
        .filter(_.astParent == typeDecl)
        .exists(a => PersistenceAnnotations.contains(a.name))
      if (annotated) {
        Iterator(typeDecl).newTagNodePair("model", typeDecl.name).store()(using builder)
      }
    }
}
