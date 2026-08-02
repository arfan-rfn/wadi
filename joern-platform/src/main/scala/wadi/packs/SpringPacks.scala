package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder}
import io.shiftleft.codepropertygraph.generated.nodes.{Call, Method, TypeDecl}
import io.shiftleft.passes.CpgPass
import io.shiftleft.semanticcpg.language.*

/** Framework query packs for Spring (§5.1): find and TAG nodes.
  *
  * Tags persist in the CPG; the exporter collects tags rather than
  * re-detecting. Only registry-governed vocabulary is emitted (§7):
  * `endpoint=<METHOD> <path>`, `sink=db`, `sink=http-client`, `model=<Entity>`.
  */
object SpringPacks {

  /** All packs, applied in order. The token-propagation pass runs LAST — it
    * reads the sink tags the client/feign passes just stored.
    */
  def applyAll(cpg: Cpg): Unit = {
    new SpringEndpointPass(cpg).createAndApply()
    new SpringHttpClientSinkPass(cpg).createAndApply()
    new SpringSecurityPack.SpringFeignSinkPass(cpg).createAndApply()
    new SpringSecurityPack.SpringHttpInterfaceSinkPass(cpg).createAndApply()
    new SpringDataSinkPass(cpg).createAndApply()
    new SpringModelPass(cpg).createAndApply()
    new SpringSecurityPack.SpringSecurityAnnotationPass(cpg).createAndApply()
    new SpringSecurityPack.SpringSecurityDslPass(cpg).createAndApply()
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
    *     yas prefix idiom; unresolvable constants fall back to no prefix —
    *     honest truncation, and CIMET's raw-text alternative emits garbage
    *     paths, which is worse)
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
      pathFromAnnotationCode(code)
        .map(List(_))
        .getOrElse(constantPathFromCode(cpg, code).toList)
  }

  /** Resolve `Klass.FIELD` (possibly nested, `Constants.ApiConstant.X`) to its
    * static-final string literal via the constructor/clinit-lowered
    * assignment. Only a literal counts (P10 — never a guess).
    */
  private def constantPathFromCode(cpg: Cpg, code: String): Option[String] = {
    val inner = code.dropWhile(_ != '(').stripPrefix("(").takeWhile(_ != ')')
    val reference = inner.replaceAll("^\\s*(?:value|path)\\s*=\\s*", "").trim
    val segments  = reference.split('.').toList.filter(_.nonEmpty)
    if (segments.sizeIs < 2 || !segments.forall(_.matches("[A-Za-z_$][\\w$]*"))) return None
    val fieldName = segments.last
    val className = segments(segments.length - 2)
    cpg.assignment
      .filter(a =>
        a.target.ast.collectFirst {
          case fi: io.shiftleft.codepropertygraph.generated.nodes.FieldIdentifier
              if fi.canonicalName == fieldName =>
            fi
        }.nonEmpty
      )
      // Nested constant holders (yas `Constants.ApiConstant`): the lowered
      // assignment may sit in the inner OR outer class's initializer, and the
      // inner name only appears as a `$` segment of the fullName.
      .filter(a =>
        a.method.typeDecl.exists(td =>
          td.name == className || td.fullName.split("[.$]").contains(className)
        ) || a.target.code.contains(s"$className.")
      )
      .flatMap(_.source match {
        case literal: io.shiftleft.codepropertygraph.generated.nodes.Literal =>
          Some(literal.code.stripPrefix("\"").stripSuffix("\""))
        case _ => None
      })
      .headOption
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
