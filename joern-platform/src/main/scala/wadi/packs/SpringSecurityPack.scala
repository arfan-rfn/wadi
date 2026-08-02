package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder}
import io.shiftleft.codepropertygraph.generated.nodes.{Call, Method, TypeDecl}
import io.shiftleft.passes.CpgPass
import io.shiftleft.semanticcpg.language.*

/** Spring Security packs (§5.1, goal 9): find and TAG auth evidence.
  *
  * Design rules (recorded):
  *   - Raw annotation/DSL text is always preserved verbatim — role-expression
  *     interpretation happens Python-side with the raw string as evidence.
  *     Wrong security facts are worse than absent ones (§12), so Scala never
  *     pairs DSL patterns with endpoints; the worker's auth merge does.
  *   - Matching is by NAME, never resolved full names — annotation names and
  *     DSL call names survive unresolved types (fixtures build without jars).
  */
object SpringSecurityPack {

  /** Method-level security annotations → `auth=annotation:<raw>` / `auth=jsr250:<raw>`.
    * Class-level annotations propagate to every declared method.
    */
  class SpringSecurityAnnotationPass(cpg: Cpg) extends CpgPass(cpg) {

    private val SpringAnnotations = Set("PreAuthorize", "PostAuthorize", "Secured")
    private val Jsr250Annotations = Set("RolesAllowed", "PermitAll", "DenyAll")

    override def run(builder: DiffGraphBuilder): Unit = {
      def tagValue(annotationName: String, code: String): Option[String] =
        if (SpringAnnotations.contains(annotationName)) Some(s"annotation:${firstLine(code)}")
        else if (Jsr250Annotations.contains(annotationName)) Some(s"jsr250:${firstLine(code)}")
        else None

      cpg.typeDecl.filterNot(_.isExternal).l.foreach { typeDecl =>
        val classLevel = typeDecl.ast.isAnnotation
          .filter(_.astParent == typeDecl)
          .flatMap(a => tagValue(a.name, a.code))
          .l
        typeDecl.method.filterNot(_.name.startsWith("<")).l.foreach { method =>
          val methodLevel = method.ast.isAnnotation
            .filter(_.astParent == method)
            .flatMap(a => tagValue(a.name, a.code))
            .l
          (classLevel ++ methodLevel).foreach { value =>
            Iterator(method).newTagNodePair("auth", value).store()(using builder)
          }
        }
      }
    }
  }

  /** SecurityFilterChain DSL rules → `auth-rule=<verb>|<pattern>|<access>` on
    * the access call node. The pattern comes from the access call's immediate
    * receiver (requestMatchers("...").hasRole("...")); rule order within the
    * chain is preserved by line number for first-match-wins semantics
    * Python-side.
    */
  class SpringSecurityDslPass(cpg: Cpg) extends CpgPass(cpg) {

    private val AccessCalls = Set(
      "hasRole",
      "hasAnyRole",
      "hasAuthority",
      "hasAnyAuthority",
      "authenticated",
      "permitAll",
      "denyAll",
      "access"
    )
    private val MatcherCalls = Set("requestMatchers", "antMatchers", "mvcMatchers", "anyRequest")
    private val VerbPattern  = "HttpMethod\\.([A-Z]+)".r

    override def run(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact(AccessCalls.toSeq*).l.foreach { accessCall =>
        receiverCall(accessCall).filter(r => MatcherCalls.contains(r.name)).foreach { matcher =>
          val verb = VerbPattern.findFirstMatchIn(matcher.code).map(_.group(1)).getOrElse("*")
          val patterns =
            if (matcher.name == "anyRequest") List("/**")
            else
              matcher.argument
                .filter(_.label == "LITERAL")
                .code
                .l
                .map(_.stripPrefix("\"").stripSuffix("\""))
                .filter(_.startsWith("/"))
          val access = accessText(accessCall)
          patterns.foreach { pattern =>
            Iterator(accessCall)
              .newTagNodePair("auth-rule", s"$verb|$pattern|$access")
              .store()(using builder)
          }
        }
      }

    private def receiverCall(call: Call): Option[Call] =
      call.argument.argumentIndexLte(0).headOption.collect { case receiver: Call => receiver }

    private def accessText(call: Call): String = {
      val args = call.argument.argumentIndexGt(0).code.l.mkString(", ")
      s"${call.name}($args)"
    }
  }

  /** Token-propagation evidence on outbound call sites (§5.1):
    *   - a `feign.RequestInterceptor` implementation in the service means every
    *     Feign call forwards what the interceptor adds → tag all feign sinks
    *     `token-propagation=feign-interceptor` (honest over-approximation);
    *   - an http-client sink whose enclosing method sets a literal
    *     `"Authorization"` header → `token-propagation=authorization-header`.
    */
  class SpringTokenPropagationPass(cpg: Cpg) extends CpgPass(cpg) {

    override def run(builder: DiffGraphBuilder): Unit = {
      val hasFeignInterceptor = cpg.typeDecl
        .filterNot(_.isExternal)
        .exists(_.inheritsFromTypeFullName.exists(_.contains("RequestInterceptor")))

      cpg.call.where(_.tag.nameExact("sink").valueExact("http-client")).l.foreach { sink =>
        val isFeign = sink.tag.nameExact("wadi-feign").nonEmpty
        if (isFeign && hasFeignInterceptor) {
          Iterator(sink)
            .newTagNodePair("token-propagation", "feign-interceptor")
            .store()(using builder)
        } else if (forwardsAuthorizationHeader(sink.method)) {
          Iterator(sink)
            .newTagNodePair("token-propagation", "authorization-header")
            .store()(using builder)
        }
      }
    }

    private def forwardsAuthorizationHeader(method: Method): Boolean =
      method.ast.isCall.exists(call =>
        call.argument.exists(arg =>
          arg.label == "LITERAL" && arg.code.stripPrefix("\"").stripSuffix("\"") == "Authorization"
        )
      )
  }

  /** Calls to `@FeignClient` interface methods are outbound http-client sinks.
    *
    * The composed URL `http://<feign-name><path><methodPath>` (or the `url=`
    * attribute when present) is the phone-book key the stitcher resolves via
    * discovery/compose names. The endpoint trap stays intact: mapping
    * annotations on feign interfaces still never count as served endpoints.
    */
  class SpringFeignSinkPass(cpg: Cpg) extends CpgPass(cpg) {

    override def run(builder: DiffGraphBuilder): Unit = {
      val feignMethods: Map[String, String] = cpg.typeDecl
        .filterNot(_.isExternal)
        .filter(td =>
          td.ast.isAnnotation.filter(_.astParent == td).exists(_.name == "FeignClient")
        )
        .l
        .flatMap { feignInterface =>
          val annotationCode = feignInterface.ast.isAnnotation
            .filter(_.astParent == feignInterface)
            .filter(_.name == "FeignClient")
            .head
            .code
          val name = attr(annotationCode, "name")
            .orElse(attr(annotationCode, "value"))
            .orElse(SpringPacks.pathFromAnnotationCode(annotationCode))
            .getOrElse(feignInterface.name.toLowerCase)
          val pathPrefix = attr(annotationCode, "path").getOrElse("")
          val urlAttr    = attr(annotationCode, "url").getOrElse("")
          feignInterface.method.l.flatMap { interfaceMethod =>
            mappingOf(interfaceMethod).map { case (verb, methodPath) =>
              val authority = if (urlAttr.nonEmpty) urlAttr else s"http://$name"
              val url = SpringPacks.joinPaths(
                SpringPacks.joinPaths(authority, pathPrefix),
                methodPath
              )
              interfaceMethod.fullName -> s"$verb|$url"
            }
          }
        }
        .toMap

      if (feignMethods.isEmpty) return

      cpg.call.l.foreach { call =>
        feignMethods.get(call.methodFullName).foreach { encoded =>
          Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
          Iterator(call).newTagNodePair("wadi-feign", encoded).store()(using builder)
        }
      }
    }

    private def attr(annotationCode: String, name: String): Option[String] =
      s"""$name\\s*=\\s*"([^"]*)"""".r.findFirstMatchIn(annotationCode).map(_.group(1)).filter(_.nonEmpty)

    private def mappingOf(method: Method): Option[(String, String)] =
      method.ast.isAnnotation
        .filter(_.astParent == method)
        .flatMap { annotation =>
          SpringPacks.MappingAnnotations.get(annotation.name).map { verb =>
            verb -> SpringPacks.pathFromAnnotationCode(annotation.code).getOrElse("")
          }
        }
        .headOption
  }

  private def firstLine(code: String): String =
    code.linesIterator.nextOption().getOrElse("").take(500)
}
