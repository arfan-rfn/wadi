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

  // Follow existing CALL edges only — this pass runs before any edges it adds.
  private given ICallResolver = NoResolve

  override def run(builder: DiffGraphBuilder): Unit = {
    // Direct parent -> children, keyed by BOTH the rendered parent name and
    // its short name (§5.2.6): an out-of-CPG parent renders as a short name
    // on one side and an import-derived FQN on the other, and exact-string
    // matching here was the one place without the short-name fallback every
    // sibling pass carries.
    val childrenByParent: Map[String, List[TypeDecl]] =
      cpg.typeDecl
        .filterNot(_.isExternal)
        .l
        .flatMap { td =>
          td.inheritsFromTypeFullName.flatMap { parent =>
            val stripped = stripGenerics(parent)
            val keys     = Set(stripped, shortName(stripped))
            keys.map(_ -> td)
          }
        }
        .groupMap(_._1)(_._2)
        .view
        .mapValues(_.distinctBy(_.id))
        .toMap

    // Self-type linking (§5.2.6): an intra-class call whose signature carries
    // unresolved parameter types gets NO call edge from the frontend — the
    // TrainTicket BasicServiceImpl helpers. Index in-CPG types by both names.
    val typeDeclByName: Map[String, List[TypeDecl]] =
      cpg.typeDecl
        .filterNot(_.isExternal)
        .l
        .flatMap(td => Set(td.fullName, shortName(td.fullName)).map(_ -> td))
        .groupMap(_._1)(_._2)
        .view
        .mapValues(_.distinctBy(_.id))
        .toMap

    cpg.call.l.foreach { call =>
      val calleeFullName = call.methodFullName
      declaringTypeOf(calleeFullName).foreach { declaringType =>
        val viaHierarchy = transitiveDescendants(declaringType, childrenByParent)
        val descendants =
          if (viaHierarchy.nonEmpty) viaHierarchy
          else if (call.callee.filterNot(_.isExternal).exists(_.body.astChildren.nonEmpty)) Nil
          else
            typeDeclByName
              .getOrElse(declaringType, typeDeclByName.getOrElse(shortName(declaringType), Nil))
        val leaves = hierarchyLeaves(descendants)
        if (leaves.nonEmpty) {
          val primaries = leaves.filter(isPrimary)
          val (chosen, strategy) =
            if (leaves.sizeIs == 1) (leaves, "exact")
            else if (primaries.sizeIs == 1) (primaries, "primary")
            else (leaves, "ambiguous")
          // A leaf may inherit the method from an abstract ancestor without
          // overriding it — fall back up the collected chain per leaf.
          val ancestors = descendants.filterNot(d => chosen.exists(_.id == d.id))
          def resolve(exactSignature: Boolean): List[Method] =
            chosen.flatMap { leaf =>
              findMatchingMethod(leaf, calleeFullName, exactSignature)
                .orElse(
                  ancestors.iterator
                    .flatMap(findMatchingMethod(_, calleeFullName, exactSignature))
                    .find(_.body.astChildren.nonEmpty)
                )
            }.distinctBy(_.id)
          val exact = resolve(exactSignature = true)
          val (targets, finalStrategy) =
            if (exact.nonEmpty) (exact, strategy)
            else if (signatureUnresolvable(calleeFullName, descendants)) {
              // Name+arity fallback (§5.2.6): only when unresolved types make
              // exact matching impossible — never for resolvable overloads.
              // Tagged distinctly so downstream confidence degrades honestly.
              (resolve(exactSignature = false), "name-arity")
            } else (Nil, strategy)
          if (targets.nonEmpty) {
            targets.foreach(target => builder.addEdge(call, target, EdgeTypes.CALL))
            Iterator(call).newTagNodePair("wadi-di", finalStrategy).store()(using builder)
          }
        }
      }
    }
  }

  /** Walk the hierarchy downward (interface -> abstract base -> impl),
    * cycle-guarded; depth is naturally bounded by the hierarchy (§5.2.6 —
    * the flat one-hop map put DI edges on bodiless abstract stubs, which
    * dead-ends the closure BFS: the ts-common failure's delivery mechanism).
    */
  private def transitiveDescendants(
    declaringType: String,
    childrenByParent: Map[String, List[TypeDecl]]
  ): List[TypeDecl] = {
    val collected = scala.collection.mutable.LinkedHashMap.empty[Long, TypeDecl]
    val queue = scala.collection.mutable.Queue.from(
      childrenByParent.getOrElse(declaringType, childrenByParent.getOrElse(shortName(declaringType), Nil))
    )
    while (queue.nonEmpty) {
      val current = queue.dequeue()
      if (!collected.contains(current.id)) {
        collected.put(current.id, current)
        Set(current.fullName, shortName(current.fullName))
          .foreach(key => queue.enqueueAll(childrenByParent.getOrElse(key, Nil)))
      }
    }
    collected.values.toList
  }

  /** The bean candidates: descendants that no other descendant extends —
    * intermediate abstract bases are hierarchy structure, not beans, and must
    * not inflate a single-impl chain into "ambiguous".
    */
  private def hierarchyLeaves(descendants: List[TypeDecl]): List[TypeDecl] = {
    val parentKeys: Set[String] = descendants.iterator
      .flatMap(_.inheritsFromTypeFullName)
      .map(stripGenerics)
      .flatMap(parent => Iterator(parent, shortName(parent)))
      .toSet
    val leaves = descendants.filterNot(d =>
      parentKeys.contains(d.fullName) || parentKeys.contains(shortName(d.fullName))
    )
    if (leaves.nonEmpty) leaves else descendants
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

  private def findMatchingMethod(
    impl: TypeDecl,
    interfaceMethodFullName: String,
    exactSignature: Boolean
  ): Option[Method] =
    methodNameAndSignature(interfaceMethodFullName).flatMap { case (name, signature) =>
      val named = impl.method.nameExact(name).l
      val matched =
        if (exactSignature) named.filter(m => signatureTail(m.fullName).contains(signature))
        else named.filter(m => arityOf(signature).contains(m.parameter.indexGt(0).size))
      // Prefer a body-carrying method: the abstract declaration may match too.
      matched.find(_.body.astChildren.nonEmpty).orElse(matched.headOption)
    }

  /** True when unresolved types make exact signature matching impossible on
    * either side — the only condition under which name+arity is sound enough
    * to over-approximate (resolvable overloads must never fall through).
    */
  private def signatureUnresolvable(callFullName: String, candidates: List[TypeDecl]): Boolean = {
    def unresolved(s: String): Boolean =
      s.contains("<unresolved") || s.contains("<empty>") ||
        s.split("[^A-Za-z0-9_$]").contains("ANY")
    unresolved(callFullName) || candidates.exists(_.method.exists(m => unresolved(m.fullName)))
  }

  /** Parameter count from a signature tail: `ret(a,b)` -> 2, `ret()` -> 0,
    * `<unresolvedSignature>(3)` -> 3 (the frontend encodes arity directly).
    */
  private def arityOf(signature: String): Option[Int] = {
    val open  = signature.indexOf('(')
    val close = signature.lastIndexOf(')')
    if (open < 0 || close <= open) return None
    val inner = signature.substring(open + 1, close).trim
    if (inner.isEmpty) Some(0)
    else if (inner.forall(_.isDigit)) Some(inner.toInt)
    else Some(inner.count(_ == ',') + 1)
  }

  private def signatureTail(fullName: String): Option[String] = {
    val parts = fullName.split(':')
    if (parts.length < 2) None else Some(parts(1))
  }

  private def shortName(typeName: String): String = {
    val stripped = stripGenerics(typeName)
    val lastDot  = stripped.lastIndexOf('.')
    if (lastDot < 0) stripped else stripped.substring(lastDot + 1)
  }

  private def stripGenerics(typeName: String): String =
    typeName.takeWhile(_ != '<')
}
