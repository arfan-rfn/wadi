package wadi.passes

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder, EdgeTypes}
import io.shiftleft.codepropertygraph.generated.nodes.{Method, TypeDecl}
import io.shiftleft.passes.CpgPass
import io.shiftleft.semanticcpg.language.*

/** Resolves Spring dependency-injected interface calls to their implementations (§5.1).
  *
  * Without this pass, endpoint→data-layer traversals dead-end at service
  * interfaces: a call to `PetService.findPet` has no static edge to
  * `PetServiceImpl.findPet`. For every call whose declared receiver type is an
  * interface with implementations in this CPG, the pass adds a CALL edge to
  * the matching implementation method and tags the call with the resolution
  * strategy:
  *
  *   - `wadi-di=exact`     — exactly one implementation
  *   - `wadi-di=primary`   — several implementations, one carries `@Primary`
  *     (Spring's own disambiguation rule) — the edge goes to that one
  *   - `wadi-di=ambiguous` — several implementations, none primary; edges to
  *     all of them (over-approximation is the honest answer for an
  *     architecture map, §5.2), confidence-marked for downstream consumers.
  *
  * `@Qualifier` needs a bean-naming model (bean name derivation, `@Bean`
  * methods, `@Component("name")`) — deferred to Phase 3, recorded here.
  */
class SpringDIPass(cpg: Cpg) extends CpgPass(cpg) {

  override def run(builder: DiffGraphBuilder): Unit = {
    val implementationsByInterface: Map[String, List[TypeDecl]] =
      cpg.typeDecl.filterNot(_.isExternal).l
        .flatMap(td => td.inheritsFromTypeFullName.map(parent => stripGenerics(parent) -> td))
        .groupMap(_._1)(_._2)

    if (implementationsByInterface.isEmpty) return

    cpg.call.l.foreach { call =>
      val calleeFullName = call.methodFullName
      declaringTypeOf(calleeFullName).foreach { declaringType =>
        implementationsByInterface.get(declaringType).foreach { implementations =>
          val primaries = implementations.filter(isPrimary)
          val (chosen, strategy) =
            if (implementations.sizeIs == 1) (implementations, "exact")
            else if (primaries.sizeIs == 1) (primaries, "primary")
            else (implementations, "ambiguous")
          val targets = chosen.flatMap(findMatchingMethod(_, calleeFullName))
          if (targets.nonEmpty) {
            targets.foreach(target => builder.addEdge(call, target, EdgeTypes.CALL))
            Iterator(call).newTagNodePair("wadi-di", strategy).store()(using builder)
          }
        }
      }
    }
  }

  private def isPrimary(typeDecl: TypeDecl): Boolean =
    typeDecl.ast.isAnnotation.filter(_.astParent == typeDecl).exists(_.name == "Primary")

  /** `com.acme.PetService.findPet:com.acme.Pet(java.lang.String)` -> `com.acme.PetService`. */
  private def declaringTypeOf(methodFullName: String): Option[String] = {
    val beforeSignature = methodFullName.split(':').head
    val lastDot         = beforeSignature.lastIndexOf('.')
    if (lastDot <= 0) None else Some(beforeSignature.substring(0, lastDot))
  }

  private def methodNameAndSignature(methodFullName: String): Option[(String, String)] = {
    val parts = methodFullName.split(':')
    if (parts.length < 2) return None
    val lastDot = parts(0).lastIndexOf('.')
    if (lastDot <= 0) return None
    Some((parts(0).substring(lastDot + 1), parts(1)))
  }

  private def findMatchingMethod(impl: TypeDecl, interfaceMethodFullName: String): Option[Method] =
    methodNameAndSignature(interfaceMethodFullName).flatMap { case (name, signature) =>
      impl.method.nameExact(name).filter(m => signatureTail(m.fullName).contains(signature)).headOption
    }

  private def signatureTail(fullName: String): Option[String] = {
    val parts = fullName.split(':')
    if (parts.length < 2) None else Some(parts(1))
  }

  private def stripGenerics(typeName: String): String =
    typeName.takeWhile(_ != '<')
}
