package wadi.`export`

import io.shiftleft.codepropertygraph.generated.Cpg
import io.shiftleft.codepropertygraph.generated.nodes.{
  Annotation,
  AnnotationLiteral,
  AstNode,
  Call,
  Literal,
  Method,
  TypeDecl
}
import io.shiftleft.semanticcpg.language.*

import scala.collection.mutable

import wadi.packs.{GenericSignature, SpringDataRepositories, SpringPacks}
import wadi.packs.SpringDataRepositories.{MarkerReceiver, ProjectReceiver, Receiver}

/** Raw entity-access facts for repository calls (§5.2.17, export 2.14.0 A1;
  * 2.15.0 after the rigor review).
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
  * `TYPE_DECL.genericSignature` (the M0 probe, §5.2.17). A receiver declared
  * as Spring Data's own interface (`CrudRepository<Order, Long>`) or as a
  * type variable bounded by one names its entity in that declaration
  * (review A2).
  *
  * `exportedMethodIds` is the export's method closure: a save's caller hop
  * (R1-27) counts only call sites the export itself holds. `walkBudget` is
  * the save walk's node budget, a parameter so a test can reach it.
  */
private[`export`] final class EntityAccessFacts(
  cpg: Cpg,
  exportedMethodIds: Set[Long],
  walkBudget: Int = SaveOrigin.WalkBudget
) {

  import EntityAccessFacts.*

  // Existing CALL edges only, the DI pass's included (same rule as the export).
  private given ICallResolver = NoResolve

  private val index           = new SpringDataRepositories.Index(cpg)
  private val repositoryTypes = index.repositoryTypes
  private val projectTypes    = index.projectTypes
  private val byFullName      = index.byFullName

  private val bindings  = mutable.Map.empty[String, Binding]
  private val ancestors = mutable.Map.empty[Long, List[TypeDecl]]

  /** A1 `save` (M1b): rule 3's inputs, from this index's repositories. */
  private val saves = new SaveOrigin(
    exportedMethodIds,
    new SaveOrigin.Repositories {
      def repositoryOf(call: Call): Option[SaveOrigin.RepositoryRef] =
        index.receiverOf(call).map { receiver =>
          SaveOrigin.RepositoryRef(receiver.repository, bindingFor(Some(receiver)).entity.flatMap(resolveWritten))
        }
      def declaredReturnType(call: Call): Option[String] =
        declarationOf(call, projectRepository(index.receiverOf(call))).method.map(_.methodReturn.typeFullName)
      def isA(typeFullName: String, entity: String): Boolean =
        typeFullName == entity || byFullName.get(typeFullName).exists(td => ancestorsOf(td).exists(_.fullName == entity))
      def isProjectType(typeFullName: String): Boolean = byFullName.contains(typeFullName)
    },
    walkBudget
  )

  /** The `db` object for one `sink=db` call. */
  def dbObj(call: Call): ujson.Obj = {
    val receiver    = index.receiverOf(call)
    val binding     = bindingFor(receiver)
    val declaration = declarationOf(call, projectRepository(receiver))
    val entityText = binding.entity.map { case (ty, _) => GenericSignature.render(ty) }
    val entityFull = binding.entity.flatMap(resolveWritten)
    val kind       = binding.marker.map(SpringDataRepositories.kindOf).getOrElse("other")
    val repoName   = receiver.map(_.repository).getOrElse(declaringTypeOf(call))
    ujson.Obj(
      "repository"             -> repoName,
      "method_name"            -> call.name,
      "entity_type_text"       -> entityText.map(ujson.Str(_)).getOrElse(ujson.Null),
      "entity_type_full_name"  -> entityFull.map(ujson.Str(_)).getOrElse(ujson.Null),
      "repository_kind"        -> kind,
      "implemented_in_project" -> declaration.method.exists(implementedInProject),
      "query"                  -> declaration.method.flatMap(queryObj(_, entityFull, kind)).getOrElse(ujson.Null),
      // A1 `save`: rule 3's inputs for a save-family call (`save`,
      // `saveAndFlush`, `saveAll`, `saveAllAndFlush`, `insert`), an explicit
      // null for every other method.
      "save" -> saves.saveObj(call, repoName, entityFull),
      // Export 2.15.0 (review B1): what annotates the method, so an
      // annotation that changes what it does withholds the name's verb.
      "method_annotations" -> ujson.Arr.from(declaration.method.toList.flatMap(annotationNames).map(ujson.Str(_))),
      "declaration_resolved" -> declaration.resolved
    )
  }

  private def projectRepository(receiver: Option[Receiver]): Option[TypeDecl] =
    receiver.collect { case ProjectReceiver(name) => name }.flatMap(byFullName.get)

  /** A project repository binds through its chain; a receiver declared as a
    * Spring Data interface binds its declared argument, and its kind is that
    * interface's.
    */
  private def bindingFor(receiver: Option[Receiver]): Binding = receiver match {
    case Some(ProjectReceiver(name)) => byFullName.get(name).map(bindingOf).getOrElse(Binding(None, None))
    case Some(MarkerReceiver(marker, entity, writtenIn)) => Binding(Some(marker), entity.map(_ -> writtenIn))
    case None                                            => Binding(None, None)
  }

  private def resolveWritten(written: Written): Option[String] = resolve(written._1, written._2)

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
      "declared_by"           -> declaredBy,
      // Export 2.15.0 (review B2): a schema-qualified table names this
      // entity only when the entity declares that schema.
      "storage_schema" -> td.annotation.nameExact("Table").headOption
        .flatMap(attributeString(_, "schema", Some(td)))
        .filter(_.nonEmpty)
        .map(ujson.Str(_))
        .getOrElse(ujson.Null),
      // Export 2.15.0 (review B1): Hibernate runs this instead of the
      // delete, so a delete on the entity deletes no row.
      "delete_rewritten_by" -> deleteRewriterOf(td).map(ujson.Str(_)).getOrElse(ujson.Null)
    )

  /** `@SQLDelete` / `@SoftDelete` from `org.hibernate.annotations`, or the
    * simple name as written when the parse could not place it.
    */
  private def deleteRewriterOf(td: TypeDecl): Option[String] =
    inSourceOrder(td.annotation.nameExact("SQLDelete", "SoftDelete").l)
      .find(a => a.fullName == s"org.hibernate.annotations.${a.name}" || !isQualified(a))
      .map(annotationName)

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

  /** The project METHOD the call names, when the project declares one, and
    * whether the declaration is known.
    *
    * A resolved call takes the declaration its methodFullName names, which
    * is javasrc2cpg's own resolution; the DI pass can add others, such as the
    * base declaration a sub-interface redeclares with `@Query`. Failing that,
    * the nearest in the receiver's chain wins, as it does at runtime (review
    * A3): a sort by node id used to pick whichever file was parsed first.
    *
    * javasrc2cpg resolves a call on a repository receiver against the
    * receiver's own type, so a method declared on a base interface often
    * reaches no callee (`IssueRepository.findAllByIdIn:<unresolvedSignature>`).
    * The fallback looks the name up along the chain, nearest first, by name
    * and arity; an inherited Spring Data method (`findById`) has no project
    * declaration at all, which is the answer. When the chain declares the
    * name but nothing with the call's arity (varargs, an overload the parse
    * could not type), which declaration runs is not known, and none is read.
    */
  private def declarationOf(call: Call, repository: Option[TypeDecl]): Declaration = {
    val chain    = repository.toList.flatMap(nearestFirst)
    val resolved = call.callee.filterNot(_.isExternal).l
    if (resolved.nonEmpty) {
      val rank = chain.map(_.id).zipWithIndex.toMap
      val nearest = resolved.minBy(m => (m.typeDecl.headOption.flatMap(td => rank.get(td.id)).getOrElse(Int.MaxValue), m.id))
      Declaration(Some(resolved.find(_.fullName == call.methodFullName).getOrElse(nearest)), resolved = true)
    } else {
      val arity = call.argument.count(_.argumentIndex >= 1)
      val named = chain.flatMap(_.method.nameExact(call.name).filterNot(_.isExternal).l)
      named.find(_.parameter.count(_.index >= 1) == arity) match {
        case found @ Some(_) => Declaration(found, resolved = true)
        case None            => Declaration(None, resolved = named.isEmpty)
      }
    }
  }

  /** `td` and its in-project ancestors, breadth first: a sub-interface's
    * declaration comes before the one it redeclares.
    */
  private def nearestFirst(td: TypeDecl): List[TypeDecl] = {
    val seen     = mutable.LinkedHashMap(td.id -> td)
    var frontier = List(td)
    while (frontier.nonEmpty) {
      frontier = frontier.flatMap(directParents).filterNot(p => seen.contains(p.id)).distinctBy(_.id)
      frontier.foreach(p => seen(p.id) = p)
    }
    seen.values.toList
  }

  /** Every annotation on the declaration, qualified where the parse placed
    * it, in source order. An annotation type the project declares is
    * followed by its own annotations, one level, as `<annotation>><meta>`:
    * Spring Data merges `@Query` from a meta-annotation (review B1).
    */
  private def annotationNames(declaration: Method): List[String] =
    inSourceOrder(declaration.annotation.l).flatMap { annotation =>
      val name = annotationName(annotation)
      val meta = byFullName.get(annotation.fullName).toList.flatMap(td => inSourceOrder(td.annotation.l))
      name :: meta.map(m => s"$name>${annotationName(m)}")
    }

  private def annotationName(annotation: Annotation): String =
    if (isQualified(annotation)) annotation.fullName else annotation.name

  private def isQualified(annotation: Annotation): Boolean =
    annotation.fullName.contains('.') && !annotation.fullName.startsWith("<")

  private def inSourceOrder(annotations: List[Annotation]): List[Annotation] =
    annotations.sortBy(a => (positionOf(a.lineNumber), positionOf(a.columnNumber), a.id))

  private def positionOf(value: Option[Int | Integer]): Int =
    value.map(_.toString.toInt).getOrElse(-1)

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
  private def directParents(td: TypeDecl): List[TypeDecl] = index.parentsOf(td)

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
    val owner = declaration.typeDecl.headOption
    // Spring Data JPA 3.4's `@NativeQuery` is `@Query(nativeQuery = true)`
    // under another name, and is read as one (review B1).
    val nativeAnnotation = declaration.annotation.nameExact("NativeQuery").headOption
    val query            = declaration.annotation.nameExact("Query").headOption.orElse(nativeAnnotation)
    val modifying        = declaration.annotation.nameExact("Modifying").nonEmpty
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
      val nativeAttr =
        query.exists(_.name == "NativeQuery") || query.flatMap(attributeText(_, "nativeQuery")).exists(_.trim == "true")
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
      index.markerOf(parentName, td) match {
        case Some(marker) =>
          // Every Spring Data marker declares the entity first: Repository<T, ID>.
          Iterator(Binding(Some(marker), written.flatMap(_.args.headOption).flatMap(substitute)))
        case None =>
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
      }
    }.nextOption()
  }

  /** The bound type text resolved to a project type through the file it was
    * written in (`Index.resolveName`). A type variable resolves to nothing.
    */
  private def resolve(ty: GenericSignature.Ty, writtenIn: TypeDecl): Option[String] = ty match {
    case GenericSignature.ClassTy(name, _) => index.resolveName(name, writtenIn)
    case _                                 => None
  }

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

  /** A call's project declaration, and false when the chain declares the
    * call's name with no matching arity, so no declaration was read.
    */
  private final case class Declaration(method: Option[Method], resolved: Boolean)

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

  /** The type a call's methodFullName names as declaring the method. */
  def declaringTypeOf(call: Call): String = SpringDataRepositories.declaringTypeOf(call)
}
