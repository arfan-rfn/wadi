package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{
  Annotation,
  AnnotationLiteral,
  AstNode,
  Call,
  Identifier,
  Literal,
  Method,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import scala.collection.mutable

import wadi.packs.{SpringDataRepositories, SpringPacks}

/** Raw entity-access facts for repository calls (§5.2.17, export 2.14.0 A1).
  *
  * The export already lists every database call site as a `sinks` row; this
  * nests what the worker needs to classify the call on that row, as the `db`
  * object, instead of a second inventory of the same sites (E1). Nothing here
  * decides a verb. The facts are evidence; the worker's verb table reads them.
  *
  * Which entity a call touches comes from the RECEIVER's declared repository
  * type, never from the type named in the call's methodFullName (R1-4): a
  * method declared on `BaseRepository<E>` names a type whose `E` is unbound,
  * and only the receiver (`IssueRepository extends BaseRepository<Issue>`)
  * says what `E` is. The extends-clause text is read from
  * `TYPE_DECL.genericSignature` (the M0 probe, §5.2.17).
  */
private[`export`] final class EntityAccessFacts(cpg: Cpg) {

  import EntityAccessFacts.*

  // Existing CALL edges only, the DI pass's included (same rule as the export).
  private given ICallResolver = NoResolve

  private val repositoryTypes: Set[String] = SpringDataRepositories.repositoryTypes(cpg)

  private val projectTypes: List[TypeDecl] = cpg.typeDecl.filterNot(_.isExternal).l
  private val byFullName: Map[String, TypeDecl] =
    projectTypes.groupBy(_.fullName).view.mapValues(_.head).toMap
  private val bySimpleName: Map[String, List[TypeDecl]] =
    projectTypes.groupBy(td => td.name.split('$').last)
  private val byName: Map[String, List[TypeDecl]] = projectTypes.groupBy(_.name)

  /** Per source file: (alias, imported entity, wildcard). */
  private val importsByFile: Map[String, List[(String, String, Boolean)]] =
    cpg.imports.l
      .flatMap { imp =>
        val entity   = imp.importedEntity.getOrElse("")
        val wildcard = imp.isWildcard.contains(true) || entity.endsWith(".*")
        imp.file.name.headOption.map(file =>
          file -> (imp.importedAs.getOrElse(entity.split('.').last), entity.stripSuffix(".*"), wildcard)
        )
      }
      .groupMap(_._1)(_._2)

  private val bindings  = mutable.Map.empty[String, Binding]
  private val ancestors = mutable.Map.empty[Long, List[TypeDecl]]

  /** The `db` object for one `sink=db` call. */
  def dbObj(call: Call): ujson.Obj = {
    val repository  = repositoryOf(call)
    val binding     = repository.map(bindingOf).getOrElse(Binding(None, None))
    val declaration = declarationOf(call, repository)
    val entityText = binding.entity.map { case (ty, _) => GenericSignature.render(ty) }
    val entityFull = binding.entity.flatMap { case (ty, writtenIn) => resolve(ty, writtenIn) }
    val kind       = binding.marker.map(repositoryKindOf).getOrElse("other")
    ujson.Obj(
      "repository"             -> repository.map(_.fullName).getOrElse(declaringTypeOf(call)),
      "method_name"            -> call.name,
      "entity_type_text"       -> entityText.map(ujson.Str(_)).getOrElse(ujson.Null),
      "entity_type_full_name"  -> entityFull.map(ujson.Str(_)).getOrElse(ujson.Null),
      "repository_kind"        -> kind,
      "implemented_in_project" -> declaration.exists(implementedInProject),
      "query"                  -> declaration.flatMap(queryObj(_, entityFull, kind)).getOrElse(ujson.Null),
      "save"                   -> saveObj(call)
    )
  }

  /** A1 `save`: rule 3's inputs for a save-family call (`save`,
    * `saveAndFlush`, `saveAll`, `saveAllAndFlush`, `insert`), null for every
    * other method. M1b attaches them here from `SaveOrigin`; until then
    * every row carries null, which a reader takes as "not measured".
    */
  private def saveObj(call: Call): ujson.Value = ujson.Null

  /** A2: the entity records. Every `@Entity` / `@Document` class (the
    * `model=` tag), then every project type a repository's chain binds that
    * carries neither annotation (Q1): `AuditEntryRepository extends
    * CrudRepository<AuditEntry, Long>` makes `AuditEntry` an entity by its
    * repository alone. Rows are keyed by the qualified name, so two classes
    * with one simple name are two entities (C2).
    */
  def modelObjs(): List[ujson.Obj] = {
    val annotated = cpg.typeDecl.where(_.tag.nameExact("model")).l
    val declared  = annotated.map(_.fullName).toSet
    val byRepository = repositoryTypes.toList.sorted
      .flatMap(byFullName.get)
      .flatMap(td => bindingOf(td).entity.flatMap { case (ty, writtenIn) => resolve(ty, writtenIn) })
      .distinct
      .filterNot(declared.contains)
      .flatMap(byFullName.get)
    annotated.map(modelObj(_, "annotation")) ++ byRepository.map(modelObj(_, "repository-argument"))
  }

  private def modelObj(td: TypeDecl, declaredBy: String): ujson.Obj =
    ujson.Obj(
      "entity"         -> td.name,
      "type_full_name" -> td.fullName,
      "jpql_name"      -> jpqlNameOf(td).map(ujson.Str(_)).getOrElse(ujson.Null),
      "fields" -> td.member.l.map { m =>
        ujson.Obj(
          "name"          -> m.name,
          "type_name"     -> m.typeFullName,
          "declared_type" -> TypeShapes.memberTypeTextOf(m).map(ujson.Str(_)).getOrElse(ujson.Null)
        )
      },
      "persistence_framework" -> "spring-data",
      "storage_name"          -> storageNameOf(td).map(ujson.Str(_)).getOrElse(ujson.Null),
      "declared_by"           -> declaredBy
    )

  /** `@Table(name = "x")` (and the bare `@Table("x")` of Spring Data JDBC),
    * then `@Document("x")`, `@Document(value = "x")` or
    * `@Document(collection = "x")`. The query reader resolves native SQL
    * table names through it (R1-24).
    */
  private def storageNameOf(td: TypeDecl): Option[String] = {
    val owner = Some(td)
    td.annotation.nameExact("Table").headOption
      .flatMap(a => attributeString(a, "name", owner).orElse(attributeString(a, "value", owner)))
      .orElse(
        td.annotation.nameExact("Document").headOption
          .flatMap(a => attributeString(a, "collection", owner).orElse(attributeString(a, "value", owner)))
      )
      .filter(_.nonEmpty)
  }

  /** The receiver's declared type when it is a repository, else the type the
    * call's methodFullName names (the type the sink pass tagged it by).
    */
  private def repositoryOf(call: Call): Option[TypeDecl] = {
    val receiverType = call.argument.argumentIndex(0).headOption.flatMap {
      case receiver: Call       => Some(receiver.typeFullName)
      case receiver: Identifier => Some(receiver.typeFullName)
      case _                    => None
    }
    receiverType
      .filter(repositoryTypes.contains)
      .orElse(Some(declaringTypeOf(call)).filter(repositoryTypes.contains))
      .flatMap(byFullName.get)
  }

  /** The project METHOD the call names, when the project declares one.
    *
    * javasrc2cpg resolves a call on a repository receiver against the
    * receiver's own type, so a method declared on a base interface often
    * reaches no callee (`IssueRepository.findAllByIdIn:<unresolvedSignature>`).
    * The fallback looks the name up along the repository's own chain, by name
    * and arity; an inherited Spring Data method (`findById`) has no project
    * declaration at all, which is the answer.
    */
  private def declarationOf(call: Call, repository: Option[TypeDecl]): Option[Method] = {
    val resolved = call.callee.filterNot(_.isExternal).l
    if (resolved.nonEmpty) return resolved.sortBy(_.id).headOption
    val arity = call.argument.count(_.argumentIndex >= 1)
    repository.toList
      .flatMap(td => td :: ancestorsOf(td))
      .flatMap(_.method.nameExact(call.name).filterNot(_.isExternal).l)
      .filter(_.parameter.count(_.index >= 1) == arity)
      .sortBy(_.id)
      .headOption
  }

  /** C3: the called method has a body in the project. Either the declaration
    * is concrete (a `default` method), or it is abstract on an interface that
    * a project class implements with a concrete method of the same shape (a
    * custom fragment). The DI pass does not link a repository call to its
    * fragment, so the implementation is found from the declaring side.
    */
  private def implementedInProject(declaration: Method): Boolean =
    !isAbstract(declaration) || {
      val arity = declaration.parameter.count(_.index >= 1)
      declaration.typeDecl.headOption.exists { declaring =>
        concreteTypes.iterator
          .filter { case (_, ancestors) => ancestors.contains(declaring.id) }
          .flatMap { case (td, _) => td.method.nameExact(declaration.name).l }
          .exists(m => !isAbstract(m) && m.parameter.count(_.index >= 1) == arity)
      }
    }

  /** Every project class with the ids of its in-project ancestors. Walked
    * once, and only if some call resolves to an abstract declaration.
    */
  private lazy val concreteTypes: List[(TypeDecl, Set[Long])] =
    projectTypes
      .filterNot(SpringDataRepositories.isInterface)
      .map(td => td -> ancestorsOf(td).map(_.id).toSet)

  /** The in-project types `td` names as parents: the full name, else the
    * short name for a jar-less parse (§5.2.6), as `SpringDataRepositories`
    * resolves them. Read from maps built once; a graph lookup per name would
    * scale with the project for every class.
    */
  private def directParents(td: TypeDecl): List[TypeDecl] =
    td.inheritsFromTypeFullName.l.flatMap { parent =>
      byFullName.get(parent).map(List(_)).getOrElse(byName.getOrElse(parent.split('.').last, Nil))
    }.distinctBy(_.id)

  /** Every in-project ancestor, transitively, cycle-guarded and memoized. */
  private def ancestorsOf(td: TypeDecl): List[TypeDecl] =
    ancestors.get(td.id) match {
      case Some(known) => known
      case None =>
        ancestors(td.id) = Nil // a cycle reads as no further ancestors
        val all = directParents(td).flatMap(p => p :: ancestorsOf(p)).filterNot(_.id == td.id).distinctBy(_.id)
        ancestors(td.id) = all
        all
    }

  /** A1 `query`: what the repository METHOD declares about its query, read
    * as written and never interpreted here (the reader is M6, R1-24).
    *
    * Set when the method carries `@Query` or `@Modifying`, or when Spring
    * Data's implicit lookup would find a named query for it: the key is
    * `<entity name>.<method>`, where the entity name is `@Entity(name=)` when
    * set and the simple class name otherwise, the rule
    * `JpaQueryMethod.getNamedQueryName` applies. A declared `@Query` text wins
    * over any named query, as it does at runtime.
    */
  private def queryObj(declaration: Method, entityFullName: Option[String], kind: String): Option[ujson.Obj] = {
    val owner     = declaration.typeDecl.headOption
    val query     = declaration.annotation.nameExact("Query").headOption
    val modifying = declaration.annotation.nameExact("Modifying").nonEmpty
    val hasValue  = query.exists(hasAttribute(_, "value"))
    val text      = query.flatMap(attributeString(_, "value", owner))
    val explicitName = query.flatMap(attributeString(_, "name", owner))
    val implicitKey =
      Option
        .when(!hasValue && explicitName.isEmpty && kind != "mongo")(entityFullName)
        .flatten
        .flatMap(byFullName.get)
        .map(entity => s"${jpqlNameOf(entity).getOrElse(entity.name)}.${declaration.name}")
        .filter(namedQueries.contains)
    val namedRef = if (hasValue) None else explicitName.orElse(implicitKey)
    val named    = namedRef.flatMap(namedQueries.get)
    Option.when(query.isDefined || modifying || named.isDefined) {
      val nativeAttr = query.flatMap(attributeText(_, "nativeQuery")).exists(_.trim == "true")
      ujson.Obj(
        "text"      -> text.orElse(named.flatMap(_.text)).map(ujson.Str(_)).getOrElse(ujson.Null),
        "native"    -> (nativeAttr || named.exists(_.native)),
        "named_ref" -> namedRef.map(ujson.Str(_)).getOrElse(ujson.Null),
        "modifying" -> modifying
      )
    }
  }

  /** Every `@NamedQuery` / `@NamedNativeQuery` in the project by name,
    * including those inside a `@NamedQueries` container (the ICPC form, 726 of
    * them). A duplicated name keeps the first: JPA rejects duplicates at boot.
    */
  private lazy val namedQueries: Map[String, NamedQuery] =
    cpg.annotation
      .nameExact("NamedQuery", "NamedNativeQuery")
      .l
      .sortBy(_.id)
      .flatMap { annotation =>
        val owner = annotation.inAst.collectAll[TypeDecl].headOption
        attributeString(annotation, "name", owner).map { name =>
          name -> NamedQuery(
            attributeString(annotation, "query", owner),
            native = annotation.name == "NamedNativeQuery"
          )
        }
      }
      .distinctBy(_._1)
      .toMap

  private def jpqlNameOf(entity: TypeDecl): Option[String] =
    entity.annotation.nameExact("Entity").headOption.flatMap(attributeString(_, "name", Some(entity)))

  private def isAbstract(method: Method): Boolean =
    method.modifier.modifierType.l.contains("ABSTRACT")

  private def declaringTypeOf(call: Call): String = {
    val declaring = call.methodFullName.split(':').head
    declaring.substring(0, math.max(declaring.lastIndexOf('.'), 0))
  }

  /** Walks the extends chain from `root` to the first marker, carrying each
    * type parameter's binding by POSITION (R1-4). `root`'s own parameters are
    * unbound: a receiver declared as `BaseRepository<E>` binds nothing.
    */
  private def bindingOf(root: TypeDecl): Binding =
    bindings.getOrElseUpdate(root.fullName, walk(root, Map.empty, Set.empty).getOrElse(Binding(None, None)))

  private def walk(td: TypeDecl, env: Map[String, Option[Written]], visited: Set[Long]): Option[Binding] = {
    if (visited.contains(td.id)) return None
    val decl    = GenericSignature.parseDecl(td.genericSignature)
    val parents = td.inheritsFromTypeFullName.l
    // Without a readable signature the marker (and so the kind) is still
    // known from the erased parents; the entity is not.
    val supers: List[(String, Option[GenericSignature.ClassTy])] = decl match {
      case Some(d) =>
        d.supers.filterNot(s => s.name == "Object" || s.name == "java.lang.Object").map { s =>
          (parents.find(p => sameType(p, s.name)).getOrElse(s.name), Some(s))
        }
      case None => parents.map(p => (p, None))
    }
    val ownParams = decl.map(_.params).getOrElse(Nil).toSet
    def substitute(arg: GenericSignature.Arg): Option[Written] = arg match {
      case GenericSignature.ExactArg(GenericSignature.ClassTy(name, Nil)) if ownParams.contains(name) =>
        env.getOrElse(name, None)
      case GenericSignature.ExactArg(GenericSignature.VarTy(name)) => env.getOrElse(name, None)
      case GenericSignature.ExactArg(ty)                           => Some((ty, td))
      case _                                                       => None
    }
    supers.iterator.flatMap { case (parentName, written) =>
      if (SpringDataRepositories.isMarker(parentName))
        // Every Spring Data marker declares the entity first: Repository<T, ID>.
        Iterator(Binding(Some(parentName), written.flatMap(_.args.headOption).flatMap(substitute)))
      else
        directParents(td)
          .filter(p => sameType(p.fullName, parentName) && repositoryTypes.contains(p.fullName))
          .iterator
          .flatMap { parent =>
            val params = GenericSignature.parseDecl(parent.genericSignature).map(_.params).getOrElse(Nil)
            val args   = written.map(_.args).getOrElse(Nil)
            // A raw or mismatched reference binds nothing: guessing a position
            // is exactly the defect TypeShapes declines for the same reason.
            val parentEnv: Map[String, Option[Written]] =
              if (args.sizeIs == params.size) params.zip(args.map(substitute)).toMap
              else params.map(_ -> None).toMap
            walk(parent, parentEnv, visited + td.id)
          }
    }.nextOption()
  }

  /** The bound type text resolved to a project type, the way javac would:
    * single-type import, then same package, then on-demand imports, then a
    * simple name unique in the project. None when it names no project type.
    */
  private def resolve(ty: GenericSignature.Ty, writtenIn: TypeDecl): Option[String] = ty match {
    case GenericSignature.ClassTy(name, _) => resolveName(name, writtenIn)
    case _                                 => None
  }

  private def resolveName(name: String, writtenIn: TypeDecl): Option[String] =
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
      val imports  = importsByFile.getOrElse(writtenIn.filename, Nil)
      val explicit = imports.find { case (alias, _, wildcard) => !wildcard && alias == name }
      explicit match {
        // An explicit import settles it, even when it names a library type.
        case Some((_, entity, _)) => byFullName.get(entity).map(_.fullName)
        case None =>
          val samePackage = s"${packageOf(writtenIn)}.$name"
          if (byFullName.contains(samePackage)) Some(samePackage)
          else {
            val onDemand = imports.collect { case (_, pkg, true) if byFullName.contains(s"$pkg.$name") => s"$pkg.$name" }
            onDemand match {
              case List(one) => Some(one)
              case Nil       => bySimpleName.get(name).collect { case List(only) => only.fullName }
              case _         => None
            }
          }
      }
    }

  private def packageOf(td: TypeDecl): String =
    td.fullName.stripSuffix("." + td.name)

  /** An annotation attribute's value node; the single-element form
    * (`@Query("...")`) is the `value` attribute.
    */
  private def attributeNode(annotation: Annotation, name: String): Option[AstNode] =
    annotation.parameterAssign.l
      .find(_.parameter.code.l.contains(name))
      .flatMap(_.value.headOption)

  private def hasAttribute(annotation: Annotation, name: String): Boolean =
    annotation.parameterAssign.l.exists(_.parameter.code.l.contains(name)) ||
      attributeText(annotation, name).isDefined

  /** A string-valued attribute as Java would evaluate it: a literal, a
    * concatenation (the multi-line `@Query` idiom), or a constant reference.
    * None when it cannot be read: the fact is then "unknown text", never a
    * fragment of it.
    *
    * javasrc2cpg keeps the attribute but drops a concatenation's value node,
    * so the expression is read back from the annotation's own code then.
    */
  private def attributeString(annotation: Annotation, name: String, owner: Option[TypeDecl]): Option[String] =
    attributeNode(annotation, name) match {
      case Some(literal: AnnotationLiteral) => Some(unquote(literal.code))
      case Some(literal: Literal)           => Some(unquote(literal.code))
      case Some(other)                      => evaluate(other.code, owner)
      case None                             => attributeText(annotation, name).flatMap(evaluate(_, owner))
    }

  private def evaluate(expression: String, owner: Option[TypeDecl]): Option[String] = {
    val trimmed = expression.trim
    // `"a" + "b"` also starts and ends with a quote; one operand is a literal.
    if (topLevelSplit(trimmed, '+').sizeIs == 1 && trimmed.length >= 2 && trimmed.startsWith("\"") && trimmed.endsWith("\""))
      Some(trimmed.substring(1, trimmed.length - 1))
    else
      SpringPacks
        .stringExpression(cpg, trimmed, owner)
        .orElse(SpringPacks.constantString(cpg, trimmed, owner))
  }

  /** An attribute's expression text, from `@Name(a = x, b = "y, z")`. Commas
    * and `=` inside strings, parentheses and braces belong to the value. An
    * argument with no `name =` is the `value` attribute.
    */
  private def attributeText(annotation: Annotation, name: String): Option[String] = {
    val code  = annotation.code
    val open  = code.indexOf('(')
    if (open < 0 || !code.trim.endsWith(")")) return None
    val inner = code.substring(open + 1, code.lastIndexOf(')'))
    topLevelSplit(inner, ',').flatMap { part =>
      topLevelSplit(part, '=') match {
        case List(key, value) if key.trim.matches("[A-Za-z_]\\w*") => Some(key.trim -> value.trim)
        case List(value) if value.trim.nonEmpty                     => Some("value" -> value.trim)
        case _                                                      => None
      }
    }.collectFirst { case (`name`, value) => value }
  }

  private def topLevelSplit(text: String, separator: Char): List[String] = {
    val parts    = mutable.ListBuffer.empty[String]
    val current  = new StringBuilder
    var depth    = 0
    var inString = false
    var escaped  = false
    text.foreach { c =>
      if (escaped) { current.append(c); escaped = false }
      else if (inString) {
        if (c == '\\') escaped = true
        else if (c == '"') inString = false
        current.append(c)
      } else
        c match {
          case '"'                          => inString = true; current.append(c)
          case '(' | '{' | '['              => depth += 1; current.append(c)
          case ')' | '}' | ']'              => depth -= 1; current.append(c)
          case `separator` if depth == 0    => parts += current.toString; current.clear()
          case other                        => current.append(other)
        }
    }
    parts += current.toString
    parts.toList
  }

  private def unquote(code: String): String =
    if (code.length >= 2 && code.startsWith("\"") && code.endsWith("\"")) code.substring(1, code.length - 1)
    else code
}

private[`export`] object EntityAccessFacts {

  /** A type argument as written, with the declaration it was written in: the
    * text resolves against THAT file's imports and package.
    */
  private type Written = (GenericSignature.Ty, TypeDecl)

  /** A named query's text (None when unreadable) and whether it is native. */
  private final case class NamedQuery(text: Option[String], native: Boolean)

  /** The first marker the chain reached, and the entity bound to it. */
  private final case class Binding(marker: Option[String], entity: Option[Written])

  /** A signature name as written (`Account`, `Outer.Inner`, `a.b.Account`)
    * against a rendered full name (`a.b.Account`, `p.Outer$Inner`).
    */
  private def sameType(fullName: String, written: String): Boolean = {
    val normalized = fullName.replace('$', '.')
    normalized == written || normalized.endsWith("." + written)
  }

  /** `jpa` / `mongo` from the marker the chain reached; a store-agnostic
    * marker (`CrudRepository`) is `other`.
    */
  def repositoryKindOf(marker: String): String =
    if (marker.contains("mongodb") || marker.contains("MongoRepository")) "mongo"
    else if (marker.contains("data.jpa") || marker.contains("JpaRepository")) "jpa"
    else "other"
}

/** javasrc2cpg's TYPE_DECL.genericSignature, parsed (§5.2.17, the M0 probe).
  *
  * It is JVM generic-signature syntax built from the source text: names as
  * WRITTEN and dotted (`LAccount;`, `Lcom.acme.Account;`, `LOuter.Nested;`),
  * the declaration's own parameter list first (`<E:LObject;>`), then the
  * superclass (`LObject;` for an interface) and the interfaces with their
  * arguments. A type variable is spelled like a class (`LE;`), so it is told
  * apart only by the enclosing declaration's parameter list.
  */
private[`export`] object GenericSignature {

  sealed trait Ty
  final case class ClassTy(name: String, args: List[Arg]) extends Ty
  final case class ArrayTy(element: Ty)                    extends Ty
  final case class PrimitiveTy(code: Char)                 extends Ty
  final case class VarTy(name: String)                     extends Ty

  sealed trait Arg
  case object AnyArg                                  extends Arg
  final case class WildArg(variance: Char, bound: Ty) extends Arg
  final case class ExactArg(ty: Ty)                   extends Arg

  final case class Decl(params: List[String], supers: List[ClassTy])

  /** None on anything unexpected: an unreadable chain is an unbound entity,
    * never a guess.
    */
  def parseDecl(signature: String): Option[Decl] =
    if (signature == null || signature.isEmpty || signature == "<empty>") None
    else {
      val reader = new Reader(signature)
      try {
        val params = if (reader.peek == '<') reader.typeParams() else Nil
        val supers = mutable.ListBuffer.empty[ClassTy]
        while (!reader.atEnd) supers += reader.classTy()
        Some(Decl(params, supers.toList))
      } catch { case _: Reader.Malformed => None }
    }

  /** Java source text for a type: `Map<String, List<Integer>>`, `byte[]`. */
  def render(ty: Ty): String = ty match {
    case ClassTy(name, Nil)  => name
    case ClassTy(name, args) => s"$name<${args.map(renderArg).mkString(", ")}>"
    case ArrayTy(element)    => s"${render(element)}[]"
    case PrimitiveTy(code)   => Primitives.getOrElse(code, code.toString)
    case VarTy(name)         => name
  }

  private def renderArg(arg: Arg): String = arg match {
    case AnyArg                => "?"
    case WildArg('+', bound)   => s"? extends ${render(bound)}"
    case WildArg(_, bound)     => s"? super ${render(bound)}"
    case ExactArg(ty)          => render(ty)
  }

  private val Primitives: Map[Char, String] = Map(
    'B' -> "byte", 'C' -> "char", 'D' -> "double", 'F' -> "float", 'I' -> "int",
    'J' -> "long", 'S' -> "short", 'Z' -> "boolean", 'V' -> "void"
  )

  private object Reader {
    final class Malformed extends RuntimeException(null, null, false, false)
  }

  private final class Reader(text: String) {
    private var at = 0

    def atEnd: Boolean = at >= text.length
    def peek: Char     = if (atEnd) throw new Reader.Malformed else text.charAt(at)
    private def next(): Char = { val c = peek; at += 1; c }
    private def expect(c: Char): Unit = if (next() != c) throw new Reader.Malformed

    /** `<K:LObject;E:LComparable<LE;>;>`: names only; bounds are skipped. */
    def typeParams(): List[String] = {
      expect('<')
      val names = mutable.ListBuffer.empty[String]
      while (peek != '>') {
        val start = at
        while (peek != ':') at += 1
        names += text.substring(start, at)
        // One class bound and any interface bounds, each after a ':'; the
        // class bound may be empty (`T::LIface;`).
        while (!atEnd && peek == ':') {
          at += 1
          if (peek != ':' && peek != '>' && !isParamStart) ty()
        }
      }
      expect('>')
      names.toList
    }

    /** After a bound, a new parameter starts with an identifier and a ':'. */
    private def isParamStart: Boolean = {
      var i = at
      while (i < text.length && Character.isJavaIdentifierPart(text.charAt(i))) i += 1
      i > at && i < text.length && text.charAt(i) == ':'
    }

    def ty(): Ty = peek match {
      case 'L' => classTy()
      case '[' => at += 1; ArrayTy(ty())
      case 'T' =>
        at += 1
        val start = at
        while (peek != ';') at += 1
        val name = text.substring(start, at)
        at += 1
        VarTy(name)
      case c if Primitives.contains(c) => at += 1; PrimitiveTy(c)
      case _                           => throw new Reader.Malformed
    }

    def classTy(): ClassTy = {
      expect('L')
      val start = at
      while (peek != '<' && peek != ';') at += 1
      val name = text.substring(start, at)
      val args =
        if (peek == '<') {
          at += 1
          val buffer = mutable.ListBuffer.empty[Arg]
          while (peek != '>') buffer += arg()
          at += 1
          buffer.toList
        } else Nil
      // A suffix after the arguments (`LOuter<LA;>.Inner;`) is not a shape
      // the frontend was seen to write; refuse it rather than misread it.
      expect(';')
      if (name.isEmpty) throw new Reader.Malformed
      ClassTy(name, args)
    }

    private def arg(): Arg = peek match {
      case '*'       => at += 1; AnyArg
      case '+' | '-' => val v = next(); WildArg(v, ty())
      case _         => ExactArg(ty())
    }
  }
}
