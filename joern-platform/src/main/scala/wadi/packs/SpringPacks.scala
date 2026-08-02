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
          .flatMap(a => pathFromAnnotationCode(a.code))
          .getOrElse("")

        controller.method.l.foreach { method =>
          method.ast.isAnnotation.filter(_.astParent == method).l.foreach { annotation =>
            MappingAnnotations.get(annotation.name).foreach { httpMethod =>
              // A path-less mapping serves the class prefix itself — an empty
              // path must not append a trailing slash (identity form, §7).
              val path = pathFromAnnotationCode(annotation.code).getOrElse("")
              val uri  = joinPaths(classPrefix, path)
              Iterator(method).newTagNodePair("endpoint", s"$httpMethod $uri").store()(using builder)
            }
            if (annotation.name == "RequestMapping" && MappingAnnotations.values.exists(v => annotation.code.contains(v))) {
              MappingAnnotations.values.filter(v => annotation.code.contains(v)).foreach { httpMethod =>
                val path = pathFromAnnotationCode(annotation.code).getOrElse("/")
                Iterator(method).newTagNodePair("endpoint", s"$httpMethod ${joinPaths(classPrefix, path)}").store()(using builder)
              }
            }
          }
        }
      }
}

/** Tags outbound HTTP client call sites (§5.2.5).
  *
  * Three shapes:
  *   - RestTemplate: any call on the RestTemplate type -> `sink=http-client`.
  *   - WebClient: the fluent chain's `.uri(...)` step is the sink (it carries
  *     the URL argument; the chain root `.get()` does not) -> `sink=http-client`
  *     plus `wadi-client=webclient` and, when the chain root names a verb,
  *     `wadi-verb=<VERB>`. *Rejected: tagging the chain root (Phase 2
  *     as-shipped) — no URL argument, every WebClient sink exported null.*
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

  /** WebClient fluent chain verb steps (chain root, receiver = WebClient). */
  private val WebClientVerbSteps =
    Set("get", "post", "put", "delete", "patch", "head", "options", "method")

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
      if (RestTemplatePrefixes.exists(prefix => target.startsWith(prefix + "."))) {
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
      } else if (call.name == "uri" && webClientChainRoot(call).isDefined) {
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
        Iterator(call).newTagNodePair("wadi-client", "webclient").store()(using builder)
        webClientChainRoot(call).flatMap(verbOfChainRoot).foreach { verb =>
          Iterator(call).newTagNodePair("wadi-verb", verb).store()(using builder)
        }
      } else if (SuspectedHttpNames.contains(call.name) && receiverUnresolvable(call)) {
        Iterator(call).newTagNodePair("sink", "http-client-suspected").store()(using builder)
      }
    }

  /** The verb step under a `.uri(...)` call: its receiver, when that is a
    * WebClient chain (resolved `WebClient`/`WebClient$…Spec` type, or — for
    * jar-less CPGs — a receiver chain touching something WebClient-typed).
    */
  private def webClientChainRoot(uriCall: Call): Option[Call] =
    uriCall.argument.argumentIndexLte(0).headOption.collect {
      case root: Call if WebClientVerbSteps.contains(root.name) && chainTouchesWebClient(root) =>
        root
    }

  private def chainTouchesWebClient(node: io.shiftleft.codepropertygraph.generated.nodes.Expression): Boolean = {
    val mentionsWebClient = (s: String) => s == "WebClient" || s.contains(".WebClient") || s.contains("WebClient$")
    node match {
      case call: Call =>
        mentionsWebClient(call.methodFullName.split(':').head) ||
        call.argument.argumentIndexLte(0).headOption.exists(chainTouchesWebClient)
      case identifier: io.shiftleft.codepropertygraph.generated.nodes.Identifier =>
        mentionsWebClient(identifier.typeFullName)
      case _ => false
    }
  }

  private def verbOfChainRoot(root: Call): Option[String] =
    root.name match {
      case "method" =>
        root.argument.argumentIndexGt(0).code.headOption.map(_.trim).collect {
          case VerbArgument(verb) => verb
        }
      case verbName if WebClientVerbSteps.contains(verbName) => Some(verbName.toUpperCase)
      case _                                                 => None
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
