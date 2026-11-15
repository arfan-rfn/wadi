package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, Operators}
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Call,
  FieldIdentifier,
  Identifier,
  Local,
  Member,
  MethodParameterIn,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import scala.collection.mutable

/** Which types and calls are Spring Data repositories' (§5.2.17, Q10).
  *
  * One definition for the two readers that need it: the sink pass tags calls
  * on these types `sink=db`, and the export binds each call's entity through
  * the same chain. Two copies of the rule would drift into two answers to
  * "is this a repository call".
  */
object SpringDataRepositories {

  /** Spring Data's repository interfaces, and the classes its proxies run,
    * by qualified name. Each declares the entity as its first type
    * parameter, which is what binding by position reads.
    *
    * A name is a marker only when it IS one of these (review A4). The rule
    * before 2.15.0 took any name CONTAINING a marker's, so a project base
    * `KeyedJpaRepository<ID, E>` was read as Spring's `JpaRepository` and
    * bound its first argument, the key, as the entity; and the kind came
    * from the project name, so `BaseCrudRepository extends MongoRepository`
    * read `other`.
    */
  val Markers: Set[String] = Set(
    "org.springframework.data.repository.Repository",
    "org.springframework.data.repository.CrudRepository",
    "org.springframework.data.repository.ListCrudRepository",
    "org.springframework.data.repository.PagingAndSortingRepository",
    "org.springframework.data.repository.ListPagingAndSortingRepository",
    "org.springframework.data.repository.reactive.ReactiveCrudRepository",
    "org.springframework.data.repository.reactive.ReactiveSortingRepository",
    "org.springframework.data.repository.reactive.RxJava3CrudRepository",
    "org.springframework.data.repository.reactive.RxJava3SortingRepository",
    "org.springframework.data.repository.history.RevisionRepository",
    "org.springframework.data.repository.query.QueryByExampleExecutor",
    "org.springframework.data.repository.query.ListQueryByExampleExecutor",
    "org.springframework.data.repository.query.ReactiveQueryByExampleExecutor",
    "org.springframework.data.jpa.repository.JpaRepository",
    "org.springframework.data.jpa.repository.JpaSpecificationExecutor",
    "org.springframework.data.jpa.repository.support.JpaRepositoryImplementation",
    "org.springframework.data.jpa.repository.support.SimpleJpaRepository",
    "org.springframework.data.mongodb.repository.MongoRepository",
    "org.springframework.data.mongodb.repository.ReactiveMongoRepository",
    "org.springframework.data.mongodb.repository.support.SimpleMongoRepository",
    "org.springframework.data.mongodb.repository.support.SimpleReactiveMongoRepository"
  )

  private val BySimpleName: Map[String, String] = Markers.map(m => m.substring(m.lastIndexOf('.') + 1) -> m).toMap

  /** javasrc2cpg's spelling for a name it could not place in a package. */
  private val Unresolved = "<unresolvedNamespace>."

  /** `jpa` / `mongo` from the marker a chain reached; a store-agnostic
    * marker (`CrudRepository`) is `other`.
    */
  def kindOf(marker: String): String =
    if (marker.startsWith("org.springframework.data.mongodb.")) "mongo"
    else if (marker.startsWith("org.springframework.data.jpa.")) "jpa"
    else "other"

  /** One import of a source file; `entity` is the package for a wildcard. */
  final case class Import(alias: String, entity: String, wildcard: Boolean)

  /** The marker `name` names, written in a file with `imports`: the qualified
    * name itself, or a bare simple name the file imports from that marker's
    * package. javasrc2cpg places most names through the imports itself; the
    * bare spelling is what it leaves when it cannot (§5.2.6).
    */
  def markerOf(name: String, imports: List[Import]): Option[String] =
    if (Markers.contains(name)) Some(name)
    else {
      val simple = name.stripPrefix(Unresolved)
      BySimpleName.get(simple).filter { qualified =>
        imports.exists(i => if (i.wildcard) s"${i.entity}.$simple" == qualified else i.alias == simple && i.entity == qualified)
      }
    }

  /** The type a call's methodFullName names as declaring the method. */
  def declaringTypeOf(call: Call): String = {
    val declaring = call.methodFullName.split(':').head
    declaring.substring(0, math.max(declaring.lastIndexOf('.'), 0))
  }

  /** javasrc2cpg renders an interface's `code` as `public interface Name<E>`;
    * an annotation type is `@interface`, which declares no repository.
    */
  def isInterface(td: TypeDecl): Boolean =
    td.code.split("\\s+").contains("interface")

  /** The repository a call is made on. */
  sealed trait Receiver { def repository: String }

  /** A project repository type: its own extends chain binds the entity. */
  final case class ProjectReceiver(repository: String) extends Receiver

  /** A receiver declared as a Spring Data interface itself, or as a type
    * variable bounded by one (review A2): `repository` is that interface,
    * and `entity` its first type argument as written in `writtenIn`, a type
    * parameter of the declaring scope as a `VarTy`.
    */
  final case class MarkerReceiver(repository: String, entity: Option[GenericSignature.Ty], writtenIn: TypeDecl)
      extends Receiver

  /** java.lang.Object's methods: on a receiver typed by a type variable they
    * are Object's, not the repository's.
    */
  private val ObjectMethods = Set("equals", "hashCode", "toString", "getClass", "notify", "notifyAll", "wait")

  /** The project's types, imports and repository types, built once per CPG,
    * and the questions both readers ask of them.
    */
  final class Index(cpg: Cpg) {

    val projectTypes: List[TypeDecl] = cpg.typeDecl.filterNot(_.isExternal).l
    val byFullName: Map[String, TypeDecl] =
      projectTypes.groupBy(_.fullName).view.mapValues(_.head).toMap
    private val bySimpleName: Map[String, List[TypeDecl]] =
      projectTypes.groupBy(td => td.name.split('$').last)
    private val byName: Map[String, List[TypeDecl]] = projectTypes.groupBy(_.name)

    /** Per source file. */
    private val importsByFile: Map[String, List[Import]] =
      cpg.imports.l
        .flatMap { imp =>
          val entity   = imp.importedEntity.getOrElse("")
          val wildcard = imp.isWildcard.contains(true) || entity.endsWith(".*")
          imp.file.name.headOption.map(file =>
            file -> Import(imp.importedAs.getOrElse(entity.split('.').last), entity.stripSuffix(".*"), wildcard)
          )
        }
        .groupMap(_._1)(_._2)

    def importsOf(td: TypeDecl): List[Import] = importsByFile.getOrElse(td.filename, Nil)

    def markerOf(parent: String, writtenIn: TypeDecl): Option[String] =
      SpringDataRepositories.markerOf(parent, importsOf(writtenIn))

    /** The in-project types `td` names as parents: the full name, else the
      * short name for a jar-less parse (§5.2.6). Read from maps built once; a
      * graph lookup per name would scale with the project for every class.
      */
    def parentsOf(td: TypeDecl): List[TypeDecl] =
      td.inheritsFromTypeFullName.l.flatMap { parent =>
        byFullName.get(parent).map(List(_)).getOrElse(byName.getOrElse(parent.split('.').last, Nil))
      }.distinctBy(_.id)

    /** Full names of every repository type in the CPG.
      *
      * Direct: a type with a marker among its parents. Transitive (Q10): an
      * INTERFACE whose in-project parent is a repository, so `IssueRepository
      * extends BaseRepository<Issue>` qualifies through `BaseRepository<E>
      * extends JpaRepository<E, Long>`. ICPC writes all 111 of its
      * repositories that way and the direct rule saw none of them.
      *
      * Only interfaces inherit membership. Spring Data proxies interfaces; a
      * class that implements a repository interface is a hand-written type
      * (a fake, an adapter), and its own methods are not repository calls. A
      * class that extends a marker class directly (`SimpleJpaRepository`) is
      * still caught by the direct rule.
      */
    val repositoryTypes: Set[String] = {
      val members = mutable.Set.from(
        cpg.typeDecl.filter(td => td.inheritsFromTypeFullName.exists(markerOf(_, td).isDefined)).fullName
      )
      if (members.nonEmpty) {
        val candidates = projectTypes.filter(isInterface).map(td => td -> parentsOf(td))
        var grew       = true
        while (grew) {
          grew = false
          candidates.filterNot { case (td, _) => members.contains(td.fullName) }.foreach { case (td, parents) =>
            if (parents.exists(parent => members.contains(parent.fullName))) {
              members += td.fullName
              grew = true
            }
          }
        }
      }
      members.toSet
    }

    /** The name as written in `writtenIn` resolved to a project type, the way
      * javac would: single-type import, then same package, then on-demand
      * imports, then a simple name unique in the project. None when it names
      * no project type.
      */
    def resolveName(name: String, writtenIn: TypeDecl): Option[String] =
      if (name.contains('.')) {
        // Qualified, or a nested type `Outer.Inner` (javasrc2cpg: `Outer$Inner`).
        val segments = name.split('.').toList
        val qualified = (segments.size to 1 by -1).iterator
          .map(i => (segments.take(i).mkString(".") :: segments.drop(i)).mkString("$"))
          .find(byFullName.contains)
        qualified.orElse(
          resolveName(segments.head, writtenIn).map(outer => (outer :: segments.tail).mkString("$")).filter(byFullName.contains)
        )
      } else {
        val imports  = importsOf(writtenIn)
        val explicit = imports.find(i => !i.wildcard && i.alias == name)
        explicit match {
          // An explicit import settles it, even when it names a library type.
          case Some(i) => byFullName.get(i.entity).map(_.fullName)
          case None =>
            val samePackage = s"${writtenIn.fullName.stripSuffix("." + writtenIn.name)}.$name"
            if (byFullName.contains(samePackage)) Some(samePackage)
            else {
              val onDemand = imports.collect { case i if i.wildcard && byFullName.contains(s"${i.entity}.$name") => s"${i.entity}.$name" }
              onDemand match {
                case List(one) => Some(one)
                case Nil       => bySimpleName.get(name).collect { case List(only) => only.fullName }
                case _         => None
              }
            }
        }
      }

    private val receivers = mutable.Map.empty[Long, Option[Receiver]]

    /** The repository a call is made on: the receiver's type when it is a
      * project repository, else the type the call's methodFullName names
      * (the type the sink rule has always tagged by), else what the
      * receiver's DECLARATION says (review A2).
      */
    def receiverOf(call: Call): Option[Receiver] =
      receivers.getOrElseUpdate(
        call.id, {
          val receiver = call.argument.argumentIndex(0).headOption
          val erased   = receiver.flatMap(typeOf)
          erased
            .filter(repositoryTypes.contains)
            .orElse(Some(declaringTypeOf(call)).filter(repositoryTypes.contains))
            .map(ProjectReceiver(_))
            .orElse(receiver.flatMap(declaredReceiver(_, erased)))
        }
      )

    /** A `sink=db` call: the rule as it stood before 2.15.0, a call whose
      * methodFullName names a repository type, plus a call on a receiver
      * declared as a Spring Data interface or as a type variable bounded by a
      * repository. Without the second half `JpaRepository<E, Long> repository`
      * in a generic base service made a call no row counted, and its endpoint
      * read "no repository call found" (review A2).
      */
    def isRepositoryCall(call: Call): Boolean =
      repositoryTypes.contains(declaringTypeOf(call)) ||
        (!call.name.startsWith("<") && !ObjectMethods.contains(call.name) &&
          call.argument.argumentIndex(0).headOption.exists(r => declaredReceiver(r, typeOf(r)).isDefined))

    private def typeOf(node: AstNode): Option[String] = node match {
      case receiver: Call       => Some(receiver.typeFullName)
      case receiver: Identifier => Some(receiver.typeFullName)
      case _                    => None
    }

    /** Read only where javasrc2cpg's erased type leaves the question open: a
      * marker (which names no entity) or `Object` (what it erases a type
      * variable to, whatever its bound).
      */
    private def declaredReceiver(receiver: AstNode, erased: Option[String]): Option[Receiver] =
      erased.filter(t => Markers.contains(t) || t == "java.lang.Object").flatMap { erasedType =>
        declaredType(receiver).flatMap { case (ty, scope) =>
          ty match {
            case GenericSignature.VarTy(name) =>
              scope.bounds.get(name).flatMap(_.headOption).flatMap(boundReceiver(_, scope))
            case declared: GenericSignature.ClassTy if Markers.contains(erasedType) =>
              Some(MarkerReceiver(erasedType, firstArgument(declared, scope), scope.writtenIn))
            case _ => None
          }
        }
      }

    /** A type variable's first bound: a marker, or a project repository. */
    private def boundReceiver(bound: GenericSignature.Ty, scope: Scope): Option[Receiver] = bound match {
      case declared: GenericSignature.ClassTy =>
        markerOf(declared.name, scope.writtenIn)
          .map(marker => MarkerReceiver(marker, firstArgument(declared, scope), scope.writtenIn))
          .orElse(resolveName(declared.name, scope.writtenIn).filter(repositoryTypes.contains).map(ProjectReceiver(_)))
      case _ => None
    }

    /** The entity argument, a type parameter of the scope as a `VarTy` (a
      * TYPE_DECL signature spells one like a class).
      */
    private def firstArgument(declared: GenericSignature.ClassTy, scope: Scope): Option[GenericSignature.Ty] =
      declared.args.headOption.collect {
        case GenericSignature.ExactArg(GenericSignature.ClassTy(name, Nil)) if scope.bounds.contains(name) =>
          GenericSignature.VarTy(name)
        case GenericSignature.ExactArg(ty) => ty
      }

    /** The type parameters in scope where a type was written. */
    private final case class Scope(writtenIn: TypeDecl, bounds: Map[String, List[GenericSignature.Ty]])

    private def classScope(td: TypeDecl): Scope =
      Scope(td, GenericSignature.parseDecl(td.genericSignature).map(_.bounds).getOrElse(Map.empty))

    /** The receiver's declared type, from the field, local or parameter it
      * reads, and the scope it was written in. A method's own type
      * parameters shadow its class's.
      */
    private def declaredType(receiver: AstNode): Option[(GenericSignature.Ty, Scope)] = receiver match {
      // `this.repository`; javasrc2cpg writes an implicit field use the same way.
      case access: Call if access.name == Operators.fieldAccess =>
        for {
          owner  <- access.argument.argumentIndex(1).headOption.collect { case i: Identifier => i.typeFullName }
          td     <- byFullName.get(owner)
          field  <- access.argument.argumentIndex(2).headOption.collect { case f: FieldIdentifier => f.canonicalName }
          member <- memberOf(td, field)
          ty     <- GenericSignature.parseType(member.genericSignature)
          scope = classScope(member.typeDecl)
        } yield (ty, scope)
      case identifier: Identifier =>
        val method = identifier.method
        val methodBounds =
          GenericSignature.parseMethod(method.genericSignature).map(_.bounds).getOrElse(Map.empty)
        val scope = method.typeDecl.headOption.map(classScope).map(s => s.copy(bounds = s.bounds ++ methodBounds))
        val declared = identifier._refOut.headOption.flatMap {
          case local: Local => GenericSignature.parseType(local.genericSignature)
          case param: MethodParameterIn =>
            // The signature lists the declared parameters only; javasrc2cpg
            // numbers them from 1, the receiver being 0.
            val declaredParams = method.parameter.l.filter(_.index >= 1)
            GenericSignature
              .parseMethod(method.genericSignature)
              .filter(_.params.sizeIs == declaredParams.size)
              .flatMap(_.params.lift(param.index - 1))
          case _ => None
        }
        for { ty <- declared; s <- scope } yield (ty, s)
      case _ => None
    }

    /** The field by name on `td` or the nearest project ancestor declaring it. */
    private def memberOf(td: TypeDecl, name: String): Option[Member] = {
      val seen     = mutable.Set(td.id)
      var frontier = List(td)
      var found    = Option.empty[Member]
      while (found.isEmpty && frontier.nonEmpty) {
        found = frontier.iterator.flatMap(_.member.nameExact(name).headOption).nextOption()
        frontier = frontier.flatMap(parentsOf).filter(p => seen.add(p.id))
      }
      found
    }
  }
}
