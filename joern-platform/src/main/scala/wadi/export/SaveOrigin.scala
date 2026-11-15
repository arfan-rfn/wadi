package wadi.`export`

import io.shiftleft.codepropertygraph.generated.{ControlStructureTypes, DispatchTypes, Operators}
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Block,
  Call,
  ControlStructure,
  Expression,
  Identifier,
  Literal,
  Method,
  MethodParameterIn,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import scala.annotation.tailrec
import scala.collection.mutable

/** Rule 3's raw inputs for one save-family call: the A1 `save` object
  * (§5.2.17; Q22, Q23, R1-27).
  *
  * A `save` is a create or an update depending on where its argument came
  * from, which the method name cannot say. These are the facts the worker's
  * split reads; nothing here picks a verb, and the gate keeps the split off
  * until it is scored. So every fact is the narrow one: what def-use inside
  * ONE method shows, plus one caller hop for a parameter. No alias analysis,
  * no interprocedural return tracking. Where that is not enough the answer
  * is `other` or `none`, which the split reads as create-or-update (P10).
  *
  * Def-use is a backward walk over the method's own CFG from the use to the
  * assignments of the same variable, so only definitions that can reach the
  * save count: two branches assigning two origins reach it as `mixed`
  * (golden `save-upsert-by-branch`), and an assignment after the save does
  * not reach it at all.
  *
  * A walk that stops at a bound (`MaxDepth`, `walkBudget`) has not seen every
  * path, so what it found is not the answer: the origin is `other` (review
  * A5). `walkBudget` is a parameter so a test can reach it; the export uses
  * `WalkBudget`.
  */
private[`export`] final class SaveOrigin(
  exportedMethodIds: Set[Long],
  repositories: SaveOrigin.Repositories,
  walkBudget: Int = SaveOrigin.WalkBudget
) {

  import SaveOrigin.*

  // Existing CALL edges only, the DI pass's included (same rule as the export).
  private given ICallResolver = NoResolve

  /** The `save` object for `call`, or null when it is not save-family.
    * `repository` and `entity` are the row's own `db.repository` and
    * `db.entity_type_full_name`: "same repository" and "same entity" mean
    * exactly what the row says.
    */
  def saveObj(call: Call, repository: String, entity: Option[String]): ujson.Value =
    if (!SaveFamily.contains(call.name)) ujson.Null
    else {
      val target = Target(repository, entity)
      val method = call.method
      val atoms  = argumentAtoms(call, 1, target)
      val origin = classify(atoms)
      val guard  = guardOf(call, target)
      ujson.Obj(
        "argument_origin"        -> origin,
        "lookup_same_repository" -> looksUp(method, call, target),
        "guard_arm"              -> guard.map(g => if (g.found) Found else NotFound).getOrElse(NoArm),
        // Export 2.15.0: the method the guard tests, so the worker can tell
        // a lookup by identity from a match on some other field (review A1).
        "guard_lookup_method" -> guard.map(g => ujson.Str(g.lookup)).getOrElse(ujson.Null),
        "caller_origins" -> ujson.Arr.from(
          if (origin == Parameter) callerOrigins(method, atoms, target).map(ujson.Str(_)) else Nil
        )
      )
    }

  // --- argument origin (Q22) -------------------------------------------------

  private def argumentAtoms(call: Call, index: Int, target: Target): Set[Atom] =
    call.argument.argumentIndex(index).headOption.map(atomsOf(_, target, 0)).getOrElse(Set(OtherAtom))

  /** Where a value can come from, as the set of origins that reach it. A
    * `null` literal contributes nothing: saving null throws, so it is not an
    * alternative entity (`findById(id).orElse(null)` is a read).
    */
  private def atomsOf(node: AstNode, target: Target, depth: Int): Set[Atom] =
    if (depth > MaxDepth) Set(TruncatedAtom)
    else
      node match {
        case literal: Literal if literal.code == "null" => Set.empty
        // javasrc2cpg lowers `new X(..)` in argument position to a BLOCK
        // `{ $obj = alloc; $obj.<init>(..); $obj }`: its value is the last child.
        case block: Block =>
          block.astChildren.collect { case e: Expression => e }.l.sortBy(_.order).lastOption match {
            case Some(last) => atomsOf(last, target, depth + 1)
            case None       => Set(OtherAtom)
          }
        case identifier: Identifier => variableAtoms(identifier, target, depth)
        case call: Call             => callAtoms(call, target, depth)
        case _                      => Set(OtherAtom)
      }

  /** A local's reaching definitions, or the parameter itself when the walk
    * reaches the method entry with no assignment on the way.
    */
  private def variableAtoms(use: Identifier, target: Target, depth: Int): Set[Atom] = {
    val reach = reachingDefinitions(use)
    val fromDefinitions = reach.definitions.flatMap { definition =>
      definition.argument.argumentIndex(2).headOption
        .map(atomsOf(_, target, depth + 1))
        .getOrElse(Set(OtherAtom))
    }.toSet
    // A captured local in a lambda also reaches the lambda's entry
    // unassigned; its definition is in another method, out of reach.
    val fromEntry: Set[Atom] =
      if (!reach.reachesEntry) Set.empty
      else Set(use._refOut.collectFirst { case p: MethodParameterIn => ParamAtom(p.index) }.getOrElse(OtherAtom))
    fromDefinitions ++ fromEntry ++ (if (reach.exhausted) Set(TruncatedAtom) else Set.empty)
  }

  private def callAtoms(call: Call, target: Target, depth: Int): Set[Atom] =
    call.name match {
      case Operators.alloc =>
        if (isEntityType(call.typeFullName, target)) Set(ConstructedAtom) else Set(OtherAtom)
      // Both branches of a ternary reach the value.
      case Operators.conditional =>
        argumentNodes(call, 2, 3).flatMap(atomsOf(_, target, depth + 1)).toSet
      case _ if isReadOn(call, target) => Set(ReadAtom)
      // `Optional` unwrapping, only where the Optional is itself a read: the
      // name alone would take `supplier.get()` for one (an unresolved jar-less
      // parse types neither `findById` nor `orElseThrow`, so names it is). A
      // receiver whose walk stopped leaves the unwrapped value unknown too.
      case "get" | "orElseThrow" | "orElse" | "orElseGet" =>
        val receiver = argumentNodes(call, 0).headOption.map(atomsOf(_, target, depth + 1)).getOrElse(Set(OtherAtom))
        if (receiver.contains(TruncatedAtom)) Set(TruncatedAtom)
        else if (receiver != Set(ReadAtom)) constructionAtoms(call, target)
        else
          call.name match {
            case "orElse"    => Set[Atom](ReadAtom) ++ argumentNodes(call, 1).flatMap(atomsOf(_, target, depth + 1))
            case "orElseGet" => Set(ReadAtom, OtherAtom)
            case _           => Set(ReadAtom)
          }
      case _ => constructionAtoms(call, target)
    }

  /** A read (rule 2's read names) on a repository of the save's entity. */
  private def isReadOn(call: Call, target: Target): Boolean =
    hasPrefix(call.name, ReadPrefixes) && repositories.repositoryOf(call).exists(sameEntity(_, target))

  private def sameEntity(repository: RepositoryRef, target: Target): Boolean =
    sameRepository(repository, target) || target.entity.exists(entity => repository.entity.contains(entity))

  /** The row's repository. A Spring Data interface names no entity by itself
    * (`CrudRepository<Order, String>` and `CrudRepository<Customer, Long>`
    * are one name), so on one the entity must be bound and equal too
    * (review A2).
    */
  private def sameRepository(repository: RepositoryRef, target: Target): Boolean =
    repository.name == target.repository &&
      (repositories.isProjectType(repository.name) || (repository.entity.nonEmpty && repository.entity == target.entity))

  /** A static factory or a builder rooted at the entity type: the call yields
    * the entity, and the chain of receivers it is called on starts at a
    * static method the entity declares (`Order.withId(id)`,
    * `Pet.builder().status(s).build()`). `existing.toBuilder()..build()`
    * starts at an instance, which may be a read, so it is not a construction.
    * A chain longer than the bound is not followed to its root.
    */
  private def constructionAtoms(call: Call, target: Target): Set[Atom] =
    if (!isEntityType(call.typeFullName, target)) Set(OtherAtom)
    else
      chainRoot(call, 0) match {
        case None => Set(TruncatedAtom)
        case Some(root)
            if root.dispatchType == DispatchTypes.STATIC_DISPATCH && !root.name.startsWith("<operator") &&
              isEntityType(EntityAccessFacts.declaringTypeOf(root), target) =>
          Set(ConstructedAtom)
        // A cast, a helper's return, a getter on a wrapper (golden 23): what
        // it returns is another method's business.
        case Some(_) => Set(OtherAtom)
      }

  /** The first call of a receiver chain; None past the depth bound. */
  @tailrec private def chainRoot(call: Call, steps: Int): Option[Call] =
    receiverCall(call) match {
      case None                         => Some(call)
      case Some(_) if steps >= MaxDepth => None
      case Some(receiver)               => chainRoot(receiver, steps + 1)
    }

  private def receiverCall(call: Call): Option[Call] =
    argumentNodes(call, 0).headOption.collect {
      case receiver: Call if !receiver.name.startsWith("<operator") => receiver
    }

  /** The entity, or a project subtype of it. With the entity unbound, any
    * project type: a collection or other library type is still not the entity.
    */
  private def isEntityType(typeFullName: String, target: Target): Boolean =
    target.entity match {
      case Some(entity) => repositories.isA(typeFullName, entity)
      case None         => repositories.isProjectType(typeFullName)
    }

  // --- reaching definitions ---------------------------------------------------

  /** Assignments to `use`'s variable that reach it along the method's CFG.
    * A path that reaches the entry first reports that instead; a walk past
    * the budget says so rather than reporting what it saw as complete.
    */
  private def reachingDefinitions(use: Identifier): Reach = {
    val definitions = mutable.LinkedHashMap.empty[Long, Call]
    val seen        = mutable.Set.empty[Long]
    val pending     = mutable.Stack.from(use.cfgPrev.l)
    var entry       = false
    while (pending.nonEmpty && seen.size < walkBudget) {
      val node = pending.pop()
      if (seen.add(node.id)) node match {
        case _: Method                              => entry = true
        case call: Call if assigns(call, use.name) => definitions(call.id) = call
        case other                                  => pending.pushAll(other.cfgPrev)
      }
    }
    Reach(definitions.values.toList, entry, exhausted = pending.nonEmpty)
  }

  private def assigns(call: Call, variable: String): Boolean =
    call.name == Operators.assignment && argumentNodes(call, 1).headOption.exists {
      case target: Identifier => target.name == variable
      case _                  => false
    }

  // --- lookup on the same repository ------------------------------------------

  /** The method also reads from the save's repository (contract A1's lookup
    * names). The same variable is the same type, so the type is the test.
    */
  private def looksUp(method: Method, save: Call, target: Target): Boolean =
    method.call.exists(call =>
      call.id != save.id && hasPrefix(call.name, ReadPrefixes) &&
        repositories.repositoryOf(call).exists(sameRepository(_, target))
    )

  // --- guard arm (Q23) ---------------------------------------------------------

  /** `found` / `not-found` only when the save sits DIRECTLY in the then or
    * else arm of an `if` whose condition tests a lookup on the save's own
    * repository. Directly: the first construct above the save that could
    * make it conditional is that `if`. A loop, a `try`, a switch, a ternary
    * or a short-circuit operator in between is `none`, and so is the early
    * return (`if (exists) return ..; repo.save(..)`, golden 18): the save
    * there is in no arm. A check on one key can guard a save of another
    * (Q23's own caveat); the guard names the method it tests, so the worker
    * can tell a lookup by identity from one on another field (review A1).
    */
  private def guardOf(save: Call, target: Target): Option[Guard] = {
    var child: AstNode = save
    var parent         = save.astParent
    var steps          = 0
    while (steps < MaxAstClimb) {
      parent match {
        case _: Method | _: TypeDecl => return None
        case cs: ControlStructure if cs.controlStructureType == ControlStructureTypes.IF =>
          if (cs.condition.exists(_.id == child.id)) return None
          val inThen = cs.whenTrue.exists(_.id == child.id)
          val inElse = cs.whenFalse.exists(_.id == child.id)
          return cs.condition.headOption
            .flatMap(testOf(_, target, 0))
            .filter(_ => inThen || inElse)
            .map(test => Guard(found = test.foundWhenTrue == inThen, test.lookup))
        case _: ControlStructure                   => return None
        case call: Call if Conditional(call.name) => return None
        case _                                     =>
      }
      child = parent
      parent = parent.astParent
      steps += 1
    }
    None
  }

  /** What the condition tests: whether it holds exactly when the lookup found
    * something, or exactly when it did not, and which lookup. None for
    * anything else. Only the plain shapes: `exists*(..)`, `isPresent()`,
    * `isEmpty()`, `== null` / `!= null`, a negation of one, or a local
    * holding one; a conjunction says nothing about its else arm and is left
    * alone.
    */
  private def testOf(condition: AstNode, target: Target, depth: Int): Option[Test] =
    if (depth > MaxDepth) None
    else
      condition match {
        case call: Call if call.name == Operators.logicalNot =>
          argumentNodes(call, 1).headOption.flatMap(testOf(_, target, depth + 1)).map(t => t.copy(foundWhenTrue = !t.foundWhenTrue))
        case call: Call if call.name == Operators.equals || call.name == Operators.notEquals =>
          argumentNodes(call, 1, 2) match {
            case List(left, right) =>
              val tested = if (isNullLiteral(right)) Some(left) else if (isNullLiteral(left)) Some(right) else None
              tested
                .flatMap(lookupOf(_, target, depth + 1, nullTest = true))
                .map(Test(call.name == Operators.notEquals, _))
            case _ => None
          }
        case call: Call if call.name == "isPresent" || call.name == "isEmpty" =>
          if (argumentNodes(call, 1).nonEmpty) None
          else
            argumentNodes(call, 0).headOption
              .flatMap(lookupOf(_, target, depth + 1, nullTest = false))
              .map(Test(call.name == "isPresent", _))
        case call: Call if hasPrefix(call.name, ExistsPrefixes) =>
          Option.when(repositories.repositoryOf(call).exists(sameRepository(_, target)))(Test(foundWhenTrue = true, call.name))
        case identifier: Identifier =>
          val reach = reachingDefinitions(identifier)
          val answers = reach.definitions.map(definition =>
            argumentNodes(definition, 2).headOption.flatMap(testOf(_, target, depth + 1))
          )
          answers.distinct match {
            case List(Some(test)) if !reach.reachesEntry && !reach.exhausted => Some(test)
            case _                                                           => None
          }
        case _ => None
      }

  /** The lookup method whose value `node` is, when it is the value of a
    * lookup on the save's repository: the call itself, `.orElse(null)` on
    * one, or a local every reaching definition of which is one and the same
    * method.
    *
    * For a null test the lookup must be able to return null, which only a
    * declaration returning the entity type can (review A1): a `List`,
    * `Optional`, `Page`, `Stream` or primitive is never null, so a null test
    * on one holds always or never. `orElse(null)` is the Optional unwrapped,
    * the entity or null, whatever the lookup returns.
    */
  private def lookupOf(node: AstNode, target: Target, depth: Int, nullTest: Boolean): Option[String] =
    if (depth > MaxDepth) None
    else
      node match {
        case call: Call if hasPrefix(call.name, ReadPrefixes) =>
          Option.when(
            repositories.repositoryOf(call).exists(sameRepository(_, target)) && (!nullTest || returnsEntity(call, target))
          )(call.name)
        case call: Call if call.name == "orElse" =>
          if (!argumentNodes(call, 1).headOption.exists(isNullLiteral)) None
          else argumentNodes(call, 0).headOption.flatMap(lookupOf(_, target, depth + 1, nullTest = false))
        case identifier: Identifier =>
          val reach = reachingDefinitions(identifier)
          if (reach.definitions.isEmpty || reach.reachesEntry || reach.exhausted) None
          else
            reach.definitions
              .map(d => argumentNodes(d, 2).headOption.flatMap(lookupOf(_, target, depth + 1, nullTest)))
              .distinct match {
              case List(found @ Some(_)) => found
              case _                     => None
            }
        case _ => None
      }

  /** The project declaration of `call` returns the save's entity type (or a
    * project subtype, the same test `isEntityType` applies). A method Spring
    * Data declares has no project declaration and is never such a lookup:
    * `findById` returns an Optional, `getReferenceById` never returns null.
    */
  private def returnsEntity(call: Call, target: Target): Boolean =
    target.entity.exists(entity => repositories.declaredReturnType(call).exists(repositories.isA(_, entity)))

  // --- one caller hop (R1-27) --------------------------------------------------

  /** For a parameter: the matching argument's origin at each call site of the
    * saving method that the export holds, in source order, by the same rule
    * and with no second hop (an argument that is the caller's own parameter
    * stays `parameter`). Empty when nothing in the export calls it.
    */
  private def callerOrigins(method: Method, atoms: Set[Atom], target: Target): List[String] = {
    val indexes = atoms.collect { case ParamAtom(index) => index }.toList.sorted
    method.callIn
      .filter(call => exportedMethodIds.contains(call.method.id))
      .l
      .distinctBy(_.id)
      .sortBy(call => (call.method.filename, positionOf(call.lineNumber), positionOf(call.columnNumber), call.id))
      .map(call => classify(indexes.flatMap(argumentAtoms(call, _, target)).toSet))
  }

  // --- helpers -------------------------------------------------------------------

  private def argumentNodes(call: Call, indexes: Int*): List[Expression] =
    indexes.toList.flatMap(index => call.argument.argumentIndex(index).headOption)

  private def isNullLiteral(node: AstNode): Boolean = node match {
    case literal: Literal => literal.code == "null"
    case _                => false
  }

  private def positionOf(value: Option[Int | Integer]): Int =
    value.map(_.toString.toInt).getOrElse(-1)
}

private[`export`] object SaveOrigin {

  /** What the pass needs from the repository index `EntityAccessFacts` has
    * already built, and nothing else.
    */
  trait Repositories {

    /** The repository a call is made on (the receiver's declared type) with
      * the entity it binds, when it is one: the row's own `db.repository` and
      * `db.entity_type_full_name` for a db call.
      */
    def repositoryOf(call: Call): Option[RepositoryRef]

    /** The return type the project's declaration of `call` names; None when
      * Spring Data declares the method or the declaration is not found.
      */
    def declaredReturnType(call: Call): Option[String]

    /** `typeFullName` is `entity` or a project subtype of it. */
    def isA(typeFullName: String, entity: String): Boolean

    def isProjectType(typeFullName: String): Boolean
  }

  /** A repository as a `db` row names it: the declared type, and the entity
    * the row binds when it resolved.
    */
  final case class RepositoryRef(name: String, entity: Option[String])

  /** The methods A1 attaches a `save` object to. */
  val SaveFamily: Set[String] = Set("save", "saveAndFlush", "saveAll", "saveAllAndFlush", "insert")

  /** Rule 2's read names, which are also contract A1's lookup names
    * (`lookup_same_repository`, guard tests): a saved value one of these
    * returned was read, and a method that calls one looked up. ONE list,
    * exactly the `READ` rows of the worker's `NAME_PREFIXES` (review B4): the
    * two Scala lists had already drifted from it and from each other.
    */
  private val ReadPrefixes = List("find", "get", "read", "query", "search", "stream", "count", "exists")

  private val ExistsPrefixes = List("exists")

  /** `findById`, `find`, never `finder`: the prefix ends the name or a word. */
  private def hasPrefix(name: String, prefixes: List[String]): Boolean =
    prefixes.exists(p => name == p || (name.startsWith(p) && name.charAt(p.length).isUpper))

  /** Operators whose operands are evaluated conditionally. */
  private val Conditional: Set[String] = Set(Operators.conditional, Operators.logicalAnd, Operators.logicalOr)

  /** Bounds: definitions chained through locals, receiver chains, AST levels
    * between a save and its `if`, CFG nodes per walk. Each keeps one save's
    * cost proportional to its own method.
    */
  private val MaxDepth    = 8
  private val MaxAstClimb = 64
  private[`export`] val WalkBudget = 20000

  private val Parameter = "parameter"
  private val Other     = "other"
  private val Found     = "found"
  private val NotFound  = "not-found"
  private val NoArm     = "none"

  /** The save's repository and its entity, as the row names them. */
  private final case class Target(repository: String, entity: Option[String])

  private final case class Reach(definitions: List[Call], reachesEntry: Boolean, exhausted: Boolean)

  /** A guard's condition: true when it holds exactly when the lookup found. */
  private final case class Test(foundWhenTrue: Boolean, lookup: String)

  /** The arm a save sits in, and the lookup its condition tests. */
  private final case class Guard(found: Boolean, lookup: String)

  /** One possible origin of a value; a set of them is classified once. */
  private sealed trait Atom
  private case object ReadAtom              extends Atom
  private case object ConstructedAtom       extends Atom
  private case object OtherAtom             extends Atom
  private final case class ParamAtom(index: Int) extends Atom

  /** The walk stopped at a bound before it had seen every path. */
  private case object TruncatedAtom extends Atom

  /** A walk that stopped is `other`, whatever else it found (review A5):
    * `mixed` would claim two origins on two paths, and the paths it did not
    * see may hold any. Otherwise several parameters are still `parameter`;
    * anything else that differs between paths is `mixed`; nothing at all is
    * `other`.
    */
  private def classify(atoms: Set[Atom]): String =
    if (atoms.contains(TruncatedAtom)) Other
    else
      atoms.map {
        case ReadAtom        => "read"
        case ConstructedAtom => "constructed"
        case ParamAtom(_)    => Parameter
        case _               => Other
      }.toList match {
        case Nil       => Other
        case List(one) => one
        case _         => "mixed"
      }
}
