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

  /** All Phase 1 packs, applied in order. */
  def applyAll(cpg: Cpg): Unit = {
    new SpringEndpointPass(cpg).createAndApply()
    new SpringHttpClientSinkPass(cpg).createAndApply()
    new SpringDataSinkPass(cpg).createAndApply()
    new SpringModelPass(cpg).createAndApply()
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

/** Tags RestTemplate/WebClient call sites: `sink=http-client`. */
class SpringHttpClientSinkPass(cpg: Cpg) extends CpgPass(cpg) {

  private val ClientTypePrefixes = List(
    "org.springframework.web.client.RestTemplate",
    "org.springframework.web.reactive.function.client.WebClient",
    // Unresolved-type fallbacks (no dependency jars): javasrc2cpg emits short names.
    "RestTemplate",
    "WebClient"
  )

  override def run(builder: DiffGraphBuilder): Unit =
    cpg.call.l.foreach { call =>
      val target = call.methodFullName
      if (ClientTypePrefixes.exists(prefix => target.startsWith(prefix + "."))) {
        Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
      }
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
