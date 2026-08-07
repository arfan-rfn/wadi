package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder, Operators}
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Call,
  Expression,
  Identifier,
  Literal,
  Method,
  TypeDecl
}
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

  /** The honest hole: a construct was READ but its path could not be resolved.
    *
    * Deliberately the same spelling the sink passes use for an unresolvable
    * authority — one convention for "we saw this and could not read it", which
    * downstream turns into a withheld claim rather than a permissive one
    * (§5.2.9).
    */
  private[wadi] val Unresolvable = "{?}"

  /** Marks a pattern that lives in config rather than in code: the value is
    * `@<configuration-properties prefix>`, which the worker correlates against
    * the parsed config tree (§5.2.9 D5). Distinct from `{?}` on purpose — one
    * says "unreadable", this says "readable, but not from here".
    */
  private[wadi] val ConfigPrefix = "@"

  /** Everything that decides access on a matched request.
    *
    * Object-level because the exporter counts occurrences of these names to
    * report what the vocabulary saw against what it emitted (§5.2.10) — a
    * count computed from the same list the pass matches on, but deliberately
    * WITHOUT the pass's scope test, so the two cannot fail together.
    *
    * Names absent here silently produce no rule — the same fall-through
    * failure as a dropped pattern — so the list tracks the DSL rather than one
    * corpus.
    */
  private[wadi] val AccessCallNames = Set(
    "hasRole",
    "hasAnyRole",
    "hasAuthority",
    "hasAnyAuthority",
    "authenticated",
    "fullyAuthenticated",
    "anonymous",
    "rememberMe",
    "hasIpAddress",
    "permitAll",
    "denyAll",
    "access"
  )

  /** Method-level security annotations → `auth=annotation:<raw>` / `auth=jsr250:<raw>`.
    * Class-level annotations propagate to every declared method.
    *
    * Three things beyond "read the annotations on this method" (§5.2.9), each
    * of which is silence rather than error when missing:
    *
    *   - **Meta-annotations.** `@IsAdmin` declared as
    *     `@PreAuthorize("hasRole('ADMIN')")` is the standard way a mature
    *     codebase spells its policy once. Matching by name alone sees nothing.
    *   - **Inheritance.** A policy declared on an abstract base or an
    *     implemented interface governs the implementing handler; only the
    *     handler's own declarations were read before.
    *   - **Enablement is NOT decided here.** Whether `@PreAuthorize` is
    *     actually enforced depends on `@EnableMethodSecurity`'s flags, which is
    *     a service-wide fact — it travels in the export and the worker applies
    *     it, so an inert annotation is recorded and marked rather than either
    *     dropped or believed.
    */
  class SpringSecurityAnnotationPass(cpg: Cpg) extends CpgPass(cpg) {

    private val SpringAnnotations =
      Set("PreAuthorize", "PostAuthorize", "Secured", "PreFilter", "PostFilter")
    private val Jsr250Annotations = Set("RolesAllowed", "PermitAll", "DenyAll")

    override def run(builder: DiffGraphBuilder): Unit =
      cpg.typeDecl.filterNot(_.isExternal).l.foreach { typeDecl =>
        val ancestors  = SpringPacks.transitiveParents(cpg, typeDecl)
        val classLevel = (typeDecl :: ancestors).flatMap(declaredOn)
        typeDecl.method.filterNot(_.name.startsWith("<")).l.foreach { method =>
          // A supertype's declaration of the SAME method carries the policy the
          // override inherits; name+arity matching mirrors how SpringDIPass
          // copes with unresolved signatures (§5.2.6).
          val inherited = ancestors
            .flatMap(_.method.nameExact(method.name).l)
            .filter(_.parameter.size == method.parameter.size)
            .flatMap(declaredOn)
          (classLevel ++ declaredOn(method) ++ inherited).distinct.foreach { value =>
            Iterator(method).newTagNodePair("auth", value).store()(using builder)
          }
        }
      }

    /** Security annotations written directly on this node, meta-annotations
      * resolved.
      */
    private def declaredOn(node: AstNode): List[String] =
      node.ast.isAnnotation
        .filter(_.astParent == node)
        .l
        .flatMap(annotation => tagValue(annotation.name, annotation.code, Set.empty))

    /** An annotation → its tag value, following composed annotations.
      *
      * `visited` guards the cycle a self-referential annotation would create;
      * the composed form keeps BOTH names, because "@IsAdmin" alone tells a
      * reader nothing about what it grants.
      */
    private def tagValue(name: String, code: String, visited: Set[String]): Option[String] =
      if (SpringAnnotations.contains(name)) Some(s"annotation:${firstLine(code)}")
      else if (Jsr250Annotations.contains(name)) Some(s"jsr250:${firstLine(code)}")
      else if (visited.contains(name) || visited.sizeIs > 4) None
      else
        cpg.typeDecl
          .nameExact(name)
          .filterNot(_.isExternal)
          .l
          .flatMap(declaration =>
            declaration.ast.isAnnotation
              .filter(_.astParent == declaration)
              .l
              .flatMap(meta => tagValue(meta.name, meta.code, visited + name))
          )
          .headOption
          .map(resolved => s"$resolved via ${firstLine(code)}")
  }

  /** SecurityFilterChain DSL rules → `auth-rule=<verb>|<pattern>|<access>` on
    * the access call node. The pattern comes from the access call's immediate
    * receiver (requestMatchers("...").hasRole("...")); rule order within the
    * chain is preserved by line number for first-match-wins semantics
    * Python-side.
    *
    * Two rules earned the hard way (§5.2.9, measured on train-ticket):
    *
    *   - **The verb comes from the matcher's ARGUMENTS, never from its `code`.**
    *     Joern's `code` for a link in a fluent chain spans the whole receiver
    *     expression, so a regex over it picked up the FIRST `HttpMethod.X`
    *     anywhere in the chain and stamped it on every later rule —
    *     `ts-travel-service` resolved one rule and lost twelve endpoints to it.
    *   - **A rule that cannot be read is emitted as `{?}`, never dropped.**
    *     Dropping does not degrade to "unknown": the endpoint falls through to
    *     whatever permissive rule comes next, which is how
    *     `POST /api/v1/orderservice/order` came to be published as "no
    *     authentication (evidenced)" while requiring ROLE_ADMIN/ROLE_USER. The
    *     `{?}` rule withholds the claim worker-side instead.
    */
  class SpringSecurityDslPass(cpg: Cpg) extends CpgPass(cpg) {

    /** Everything that decides access on a matched request (object-level, so
      * the exporter's independent count reads the same vocabulary).
      */
    private val AccessCalls = AccessCallNames

    /** Rule-scoped matchers. `securityMatcher`/`antMatcher` are deliberately
      * absent: they scope a whole CHAIN, not one rule, and are read as chain
      * scope by the exporter instead.
      *
      * `pathMatchers`/`anyExchange` are the REACTIVE spellings (§5.2.10 T6).
      * Their absence was not a partial answer but a total one: a WebFlux
      * service's every rule failed the matcher test, so the whole chain
      * vanished and the service read as having no authorization at all. yas
      * ships two such modules.
      */
    private val MatcherCalls =
      Set(
        "requestMatchers",
        "antMatchers",
        "mvcMatchers",
        "regexMatchers",
        "anyRequest",
        "pathMatchers",
        "anyExchange"
      )

    /** Matchers that mean "everything this chain governs". */
    private val CatchAllMatchers = Set("anyRequest", "anyExchange")

    /** An argument that IS an HTTP verb reference, whole — anchored so a
      * chain's text can never leak a verb into a rule that has none.
      */
    private val VerbArgument = "^(?:org\\.springframework\\.http\\.)?HttpMethod\\.([A-Z]+)$".r

    /** The registry calls that open an authorization scope. */
    private val AuthorizeRegistries =
      Set("authorizeHttpRequests", "authorizeRequests", "authorizeExchange")

    /** Every detected access site emits a rule — always (§5.2.10).
      *
      * The predecessor fused detection with resolution: the pattern was read
      * from the access call's immediate receiver, and only when that receiver
      * *was a call*. Config-driven Spring code has to park the `AuthorizedUrl`
      * in a local variable (the access verb is chosen by an if/else), so the
      * receiver is an Identifier, the traversal yielded nothing, and the rule
      * was DROPPED — not marked `{?}`. The endpoint then fell through to the
      * chain's `anyRequest()` and read as a fully-resolved claim. That is how
      * 365 train-ticket-aitest endpoints published as authenticated with no
      * roles and no withheld claims.
      *
      * Now resolution can only degrade FIELDS. A site with no readable matcher
      * still emits, with `Unresolvable` standing in for its scope, which the
      * worker turns into a withheld claim rather than a permissive one.
      */
    override def run(builder: DiffGraphBuilder): Unit = {
      val scopes = authorizationScopes
      val candidates = cpg.call
        .nameExact(AccessCalls.toSeq*)
        .l
        .filter(call => scopes.contains(call.method.fullName))
      // An access name nested inside another access call's ARGUMENTS is that
      // call's expression, not a rule of its own:
      // `access(AuthorityAuthorizationManager.hasRole("X"))` is one rule whose
      // text already names the role. Emitting the inner call too would invent
      // a second, scopeless rule and withhold the claim it just answered.
      // Receivers are excluded from the scan (index > 0), so a matcher this
      // rule hangs off can never be mistaken for a nested expression.
      val nested = candidates.flatMap(_.argument.argumentIndexGt(0).ast.isCall.id).toSet
      candidates
        .filterNot(call => nested.contains(call.id))
        .foreach { accessCall =>
          val access   = accessText(accessCall)
          val matchers = matchersOf(accessCall)
          // Verb and patterns are read PER MATCHER, not once per access call.
          // A receiver assigned in both arms of an if/else really does have two
          // matchers — train-ticket-aitest picks the verb-scoped one or the
          // bare one that way — and they can carry different verbs, so a single
          // verb for the site would stamp one arm's restriction on the other.
          val resolved =
            if (matchers.isEmpty) List(("*", Unresolvable))
            else
              matchers.flatMap { matcher =>
                val verb = verbOf(matcher).getOrElse("*")
                patternsOf(matcher).map(pattern => (verb, pattern))
              }
          resolved.distinct.foreach { case (verb, pattern) =>
            Iterator(accessCall)
              .newTagNodePair("auth-rule", s"$verb|$pattern|$access")
              .store()(using builder)
          }
        }
    }

    /** Methods whose body sits inside an authorization registry.
      *
      * Needed only because emission no longer depends on finding a matcher:
      * `AccessCalls` holds ordinary words (`access`, `authenticated`,
      * `anonymous`), and without a scope test a business method named
      * `access()` would publish itself as a security rule — trading a silent
      * drop for a fabricated fact, which §12 rates worse.
      *
      * Three ways a method qualifies, because the DSL has three shapes:
      *   - it CONTAINS the registry call (Spring Security 5 fluent chains);
      *   - it IS the lambda handed to one (`authorizeHttpRequests(a -> …)`,
      *     which javasrc2cpg lowers to its own method whose full name appears
      *     verbatim as the call's argument text);
      *   - it CONTAINS a rule matcher (`requestMatchers`, `antMatchers`, …),
      *     which catches the helper a method reference points at
      *     (`authorizeHttpRequests(this::rules)`) — a shape neither of the
      *     first two sees.
      */
    private lazy val authorizationScopes: Set[String] = {
      val registries = cpg.call.nameExact(AuthorizeRegistries.toSeq*).l
      val declaring  = registries.map(_.method.fullName).toSet
      val lambdas    = registries.flatMap(_.argument.argumentIndexGt(0).code).toSet
      val matchers   = cpg.call.nameExact(MatcherCalls.toSeq*).method.fullName.toSet
      declaring ++ lambdas ++ matchers
    }

    /** How far to chase a receiver before giving up and reporting a hole. */
    private val MaxReceiverDepth = 6

    /** The rule matchers this access call is scoped by (§5.2.10 T3).
      *
      * The predecessor accepted only a receiver that WAS a matcher call, which
      * is a syntactic test on one shape of a fluent chain. Config-driven Spring
      * cannot be written that way — the access verb is chosen by an if/else, so
      * the `AuthorizedUrl` has to live in a variable — and the whole policy of
      * 20 train-ticket-aitest services disappeared into that gap.
      *
      * The receiver is now RESOLVED rather than pattern-matched, the way
      * `UrlSlicer` resolves a URL argument: follow assignments, both arms of a
      * ternary, and a helper method's returns. Several matchers is the correct
      * answer, not an ambiguity — a receiver assigned in two branches really is
      * governed by two matchers, and each keeps its own verb and patterns.
      *
      * Returning an empty list is still a legitimate outcome (a `RequestMatcher`
      * bean, a receiver built somewhere unreadable); it degrades the site to a
      * hole rather than deleting it.
      */
    private def matchersOf(accessCall: Call): List[Call] =
      accessCall.argument
        .argumentIndexLte(0)
        .headOption
        .toList
        .flatMap(receiver => resolveMatchers(receiver, 0))
        .distinctBy(_.id)

    private def resolveMatchers(expression: Expression, depth: Int): List[Call] =
      if (depth > MaxReceiverDepth) Nil
      else
        expression match {
          case call: Call if MatcherCalls.contains(call.name) => List(call)
          // `(flag ? a.requestMatchers(x) : a.requestMatchers(y)).hasRole(R)`:
          // both arms are governed, so both are matchers. Arguments 2 and 3 are
          // the branches; argument 1 is the condition.
          case call: Call if call.name == Operators.conditional =>
            call.argument.argumentIndexGt(1).l.flatMap(arm => resolveMatchers(arm, depth + 1))
          // Any other operator (field access, cast, …) is plumbing, not a
          // matcher, and following it would wander into the whole expression.
          case call: Call if call.name.startsWith("<operator>") => Nil
          case call: Call => calleeReturns(call).flatMap(value => resolveMatchers(value, depth + 1))
          case identifier: Identifier =>
            assignedValues(identifier).flatMap(value => resolveMatchers(value, depth + 1))
          case _ => Nil
        }

    /** Every value assigned to this local within its own method.
      *
      * Name-scoped rather than SSA-resolved: javasrc2cpg leaves these types
      * unresolved (the fixtures build without jars), so reaching-def is not
      * dependable here, and a chain configurator is small enough that every
      * assignment to the name really is a candidate. Over-approximating ADDS
      * matchers, which adds rules — the safe direction, since each carries its
      * own access expression rather than widening an existing one.
      */
    private def assignedValues(identifier: Identifier): List[Expression] =
      identifier.method.ast.isCall
        .nameExact(Operators.assignment)
        .filter(_.argument.argumentIndex(1).isIdentifier.name.exists(_ == identifier.name))
        .flatMap(_.argument.argumentIndex(2))
        .l

    /** What a helper method hands back — `pick(auth).hasRole(R)`.
      *
      * Matched by NAME, never by resolved full name: unresolved signatures are
      * the norm in this file's world, and `<unresolvedSignature>` would match
      * nothing at all.
      */
    private def calleeReturns(call: Call): List[Expression] =
      cpg.method
        .nameExact(call.name)
        .filterNot(_.isExternal)
        .l
        .take(MaxReceiverDepth)
        .flatMap(_.ast.isReturn.astChildren.collectAll[Expression].l)

    /** The verb restriction, read from the matcher's own arguments. */
    private def verbOf(matcher: Call): Option[String] =
      matcher.argument
        .argumentIndexGt(0)
        .flatMap(argument => VerbArgument.findFirstMatchIn(argument.code.trim).map(_.group(1)))
        .headOption

    /** Every path this rule is scoped to. A matcher whose arguments cannot all
      * be read contributes `{?}` ALONGSIDE whatever did resolve: the readable
      * part still answers precisely where it applies, and the unreadable part
      * withholds the claim everywhere else.
      */
    private def patternsOf(matcher: Call): List[String] = {
      if (CatchAllMatchers.contains(matcher.name)) return List("/**")
      val owner = matcher.method.typeDecl.headOption
      val arguments = matcher.argument
        .argumentIndexGt(0)
        .l
        .filterNot(argument => VerbArgument.matches(argument.code.trim))
      if (arguments.isEmpty) return List(Unresolvable) // e.g. requestMatchers(someMatcherBean())
      // Per ARGUMENT, because one argument can name several paths: a `String[]`
      // built from a list, or an array initializer, is a single argument
      // carrying many patterns. Counting resolved VALUES against argument count
      // (the predecessor) declared such a matcher unread the moment it resolved
      // more paths than it had arguments.
      val perArgument = arguments.map(argument => patternsFrom(argument, owner))
      val resolved    = perArgument.flatten.distinct
      if (perArgument.forall(_.nonEmpty)) resolved
      // Nothing in the Java names a path — but the rule still has patterns,
      // they just live in config. Naming the binding beats `{?}`: the worker
      // can read the YAML and recover the real policy (§5.2.9 D5).
      else resolved ++ List(configPrefixOf(matcher).map(ConfigPrefix + _).getOrElse(Unresolvable))
    }

    /** The `@ConfigurationProperties` prefix this rule's patterns are bound to.
      *
      * yas declares its entire authorization policy in `application.yaml` and
      * loops over the bound rules, so not one literal pattern appears in the
      * Java. Tracing the exact binding expression is a dataflow problem; what
      * is both cheap and honest is naming the properties bean in scope — the
      * worker then correlates the prefix against the parsed config tree and
      * either recovers concrete rules or leaves the enforcement opaque.
      */
    private def configPrefixOf(matcher: Call): Option[String] = {
      val enclosing = matcher.method
      // Parameters and locals only was a shape assumption too (§5.2.10 T3):
      // javasrc2cpg lifts a lambda's CAPTURED values into its parameters, so
      // `SecurityFilterChain chain(HttpSecurity http, Props props)` resolved
      // while `@Autowired private Props props` did not — and all 20
      // train-ticket-aitest services inject the field way, against yas's 15
      // that inject the parameter way. The fixture happened to model yas.
      // Members of the enclosing type (and its outer types, since a chain bean
      // is often a nested @Configuration) are now candidates too.
      val owners = enclosing.typeDecl.l ++ enclosing.typeDecl.l.flatMap(td =>
        cpg.typeDecl.fullNameExact(td.fullName.split('$').head).l
      )
      val members = owners.flatMap(td => td.member.typeFullName.l)
      val candidateTypes =
        (enclosing.parameter.typeFullName.l ++ enclosing.local.typeFullName.l ++ members).distinct
      candidateTypes
        .flatMap(typeName =>
          cpg.typeDecl.fullNameExact(typeName).l ++
            cpg.typeDecl.nameExact(typeName.split('.').last).filterNot(_.isExternal).l
        )
        .distinctBy(_.id)
        .flatMap(td =>
          td.ast.isAnnotation
            .filter(_.astParent == td)
            .nameExact("ConfigurationProperties")
            .l
            .flatMap(annotation =>
              "(?:prefix\\s*=\\s*)?\"([^\"]+)\"".r
                .findFirstMatchIn(annotation.code)
                .map(_.group(1))
            )
        )
        .headOption
    }

    /** One matcher argument → every path it names.
      *
      * A `${key}` placeholder is passed through verbatim rather than resolved
      * here: config lives worker-side, and §5.2.4 already fixes that split for
      * `@Value` — the exporter emits the symbol, the worker resolves it.
      *
      * Three sources beyond a bare literal (§5.2.10 T3), each of which was a
      * hole the argument could fall into:
      *   - a constant field, via the shared resolver;
      *   - a `@Value("${…}")` member, whose placeholder is the honest answer —
      *     the predecessor's comment promised this passthrough, but nothing
      *     read the annotation, so it reported `{?}`;
      *   - an array or collection assembled into a local, whose path literals
      *     are right there in the assignment.
      */
    private def patternsFrom(argument: Expression, owner: Option[TypeDecl]): List[String] = {
      val direct = argument match {
        case literal: Literal => List(literal.code.stripPrefix("\"").stripSuffix("\""))
        case _ =>
          SpringPacks
            .constantString(cpg, argument.code, owner)
            // `requestMatchers(PREFIX + "/public/x")`: without this the rule
            // has no readable scope, and §5.2.10 then correctly withholds the
            // claim on every endpoint it could cover — an honest answer to a
            // question that did not need to be uncertain.
            .orElse(SpringPacks.stringExpression(cpg, argument.code, owner))
            .toList
      }
      val symbolic = memberNameOf(argument).toList.flatMap(valuePlaceholderOf)
      val assembled = argument match {
        case identifier: Identifier =>
          assignedValues(identifier)
            .flatMap(value => value.ast.isLiteral.code.l)
            .map(code => code.stripPrefix("\"").stripSuffix("\""))
        case _ => Nil
      }
      (direct ++ symbolic ++ assembled).distinct
        .filter(value => value.startsWith("/") || value.startsWith("${"))
    }

    /** The simple name a pattern argument refers to, through a field access. */
    private def memberNameOf(argument: Expression): Option[String] = argument match {
      case identifier: Identifier => Some(identifier.name)
      case call: Call if call.name == Operators.fieldAccess =>
        call.argument.argumentIndex(2).isFieldIdentifier.canonicalName.headOption
      case _ => None
    }

    /** A `@Value("${key}")` member's placeholder, verbatim. */
    private def valuePlaceholderOf(name: String): Option[String] =
      cpg.member
        .nameExact(name)
        .l
        .flatMap(member =>
          member.astChildren.isAnnotation
            .nameExact("Value")
            .code
            .l
            .flatMap(code => "\"([^\"]+)\"".r.findFirstMatchIn(code).map(_.group(1)))
        )
        .headOption

    private def receiverCall(call: Call): Option[Call] =
      call.argument.argumentIndexLte(0).headOption.collect { case receiver: Call => receiver }

    /** The access expression, verbatim — role interpretation happens Python-side
      * against this text (§12), with constants resolved where they can be so a
      * `hasAnyRole(admin, "USER")` does not silently lose half its roles.
      */
    private def accessText(call: Call): String = {
      val owner = call.method.typeDecl.headOption
      val args = call.argument
        .argumentIndexGt(0)
        .l
        .map { argument =>
          argument match {
            case _: Literal => argument.code
            case _ =>
              SpringPacks
                .constantString(cpg, argument.code, owner)
                .map(value => s"\"$value\"")
                .getOrElse(argument.code)
          }
        }
        .mkString(", ")
      s"${call.name}($args)"
    }
  }

  /** Where a grant comes from and what it means → `auth-authority=<kind>|<detail>`
    * (§5.2.10 T7).
    *
    * Every layer above answers "what does this endpoint require?". This one
    * answers the question underneath it: **what does the required grant
    * actually mean, and where is it minted?** Two constructs can silently
    * falsify a role list wadi already publishes:
    *
    *   - **`RoleHierarchy`.** `ROLE_ADMIN > ROLE_USER` means an endpoint
    *     reported as requiring `[USER]` is ALSO reachable by ADMIN. The
    *     published set is narrower than reality — an under-statement of who
    *     can get in, which is the wrong direction for a security map.
    *   - **`GrantedAuthorityDefaults`.** A custom prefix (or `""`) rewires
    *     `hasRole("X")` from the authority `ROLE_X` to something else, which
    *     is exactly the mapping the role/authority split in 0.6.0 assumes.
    *
    * Neither GATES a request, so neither withholds a claim — that would be the
    * blunt-instrument error §5.2.9 already rejected. They mark the role list
    * incomplete instead.
    *
    * Provenance is the other half: a JWT claim converter or a
    * `UserDetailsService` says where `ADMIN` is minted, which is the first
    * question a reader asks after "which roles reach this?".
    */
  class SpringAuthorityModelPass(cpg: Cpg) extends CpgPass(cpg) {

    override def run(builder: DiffGraphBuilder): Unit = {
      // A bean METHOD returning the type, or a construction of it — either way
      // the model is in play for this service.
      tagType("RoleHierarchy", "role-hierarchy", builder)
      tagType("GrantedAuthorityDefaults", "authority-defaults", builder)
      tagType("UserDetailsService", "user-details-service", builder)

      cpg.call
        .nameExact("jwtAuthenticationConverter", "setJwtGrantedAuthoritiesConverter")
        .l
        .foreach { call =>
          Iterator(call)
            .newTagNodePair("auth-authority", s"jwt-claim-converter|${firstLine(call.code)}")
            .store()(using builder)
        }
    }

    /** Beans and constructions that put `typeName` in play. */
    private def tagType(typeName: String, kind: String, builder: DiffGraphBuilder): Unit = {
      val constructions = cpg.call
        .nameExact("<init>")
        .filter(_.methodFullName.split("\\.<init>").head.split('.').last == typeName)
        .l
      val beans = cpg.method
        .filterNot(_.isExternal)
        .filter(_.methodReturn.typeFullName.split('.').last == typeName)
        .l
      constructions.foreach { call =>
        // A `GrantedAuthorityDefaults("")` argument IS the new prefix, and the
        // difference between a harmless restatement of the default and a
        // rewiring of every hasRole in the service.
        val detail = call.argument.argumentIndexGt(0).code.l match {
          case Nil  => typeName
          case args => s"$typeName(${args.mkString(", ")})"
        }
        Iterator(call).newTagNodePair("auth-authority", s"$kind|$detail").store()(using builder)
      }
      if (constructions.isEmpty) {
        beans.foreach { method =>
          Iterator(method)
            .newTagNodePair("auth-authority", s"$kind|${method.name}")
            .store()(using builder)
        }
      }
    }
  }

  /** Request-level policy → `auth-policy=<kind>|<scope>|<detail>` (§5.2.10 T6).
    *
    * The third category a `SecurityConfig` declares, after authorization rules
    * and authentication mechanisms, and the one wadi had no vocabulary for at
    * all: CORS is the SECOND most common construct in the 76 security configs
    * measured (58 uses), and CSRF the most common after `disable` itself.
    *
    * These are **service-level facts, never inputs to the endpoint claim.** A
    * CORS policy decides which ORIGIN may call, not which principal — folding
    * it into `authenticated` would answer a different question than the one
    * asked. They are published so the question can be asked at all (P10),
    * which is the whole of the improvement: absent facts, not wrong ones.
    *
    * Nothing here is scored. `csrf().disable()` is near-universal on stateless
    * APIs and reporting it as a finding would train readers to ignore the
    * category; the fact is recorded and the judgement left to the reader.
    */
  class SpringRequestPolicyPass(cpg: Cpg) extends CpgPass(cpg) {

    /** CORS builders, whichever API the project reached for. */
    private val CorsOrigins = Set("allowedOrigins", "allowedOriginPatterns", "addAllowedOrigin")

    override def run(builder: DiffGraphBuilder): Unit = {
      tagCors(builder)
      tagCsrf(builder)
      tagHandlers(builder)
    }

    /** `registry.addMapping(path).allowedOrigins(ALL)` and the bean form. */
    private def tagCors(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact(CorsOrigins.toSeq*).l.foreach { origins =>
        val declared = literalArgs(origins)
        // `CorsConfiguration.ALL` and `"*"` are the same decision written two
        // ways; the constant resolves through the shared resolver, and an
        // unreadable origin stays `{?}` rather than being called restrictive.
        val values = if (declared.isEmpty) List(Unresolvable) else declared
        val scope  = corsScopeOf(origins).getOrElse("/**")
        Iterator(origins)
          .newTagNodePair("auth-policy", s"cors|$scope|${values.mkString(",")}")
          .store()(using builder)
      }

    /** The `addMapping(...)` this origin list hangs off, when there is one. */
    private def corsScopeOf(call: Call): Option[String] =
      call.method.ast.isCall
        .nameExact("addMapping")
        .flatMap(mapping => literalArgs(mapping))
        .headOption

    /** CSRF: off, or on with exemptions. Both are facts a reader wants. */
    private def tagCsrf(builder: DiffGraphBuilder): Unit = {
      cpg.call.nameExact("csrf").l.foreach { csrf =>
        val disabled = csrf.argument
          .argumentIndexGt(0)
          .code
          .exists(argument =>
            argument.contains("disable") ||
              cpg.method.fullNameExact(argument).exists(_.ast.isCall.nameExact("disable").nonEmpty)
          ) || cpg.call
          .nameExact("disable")
          .exists(_.argument.argumentIndexLte(0).headOption.exists {
            case receiver: Call => receiver.id == csrf.id
            case _              => false
          })
        if (disabled) {
          Iterator(csrf)
            .newTagNodePair("auth-policy", s"csrf-disabled|/**|${firstLine(csrf.code)}")
            .store()(using builder)
        }
      }
      cpg.call
        .nameExact("ignoringRequestMatchers", "ignoringAntMatchers")
        .l
        .foreach { ignoring =>
          val paths = literalArgs(ignoring)
          (if (paths.isEmpty) List(Unresolvable) else paths).foreach { path =>
            Iterator(ignoring)
              .newTagNodePair("auth-policy", s"csrf-exempt|$path|${firstLine(ignoring.code)}")
              .store()(using builder)
          }
        }
    }

    /** How rejection is answered — a 401 challenge or a 403 page. */
    private def tagHandlers(builder: DiffGraphBuilder): Unit =
      cpg.call
        .nameExact("authenticationEntryPoint", "accessDeniedHandler", "accessDeniedPage")
        .l
        .foreach { handler =>
          val kind = if (handler.name == "authenticationEntryPoint") "entry-point" else "access-denied"
          Iterator(handler)
            .newTagNodePair("auth-policy", s"$kind|/**|${firstLine(handler.code)}")
            .store()(using builder)
        }

    /** Framework constants whose value is a published part of the API.
      *
      * `CorsConfiguration.ALL` lives in a jar, so the in-graph constant
      * resolver cannot see it and every one of the 58 measured CORS configs
      * would report `{?}`. Resolving a documented framework constant is
      * reading the framework, not guessing a value — the line this stays on is
      * that only constants whose meaning is fixed by the library appear here.
      */
    private val FrameworkConstants = Map(
      "ALL"                    -> "*",
      "CorsConfiguration.ALL"  -> "*",
      "CorsConfiguration.ALL_PATTERN" -> "*"
    )

    private def literalArgs(call: Call): List[String] = {
      val owner = call.method.typeDecl.headOption
      call.argument
        .argumentIndexGt(0)
        .l
        .flatMap {
          case literal: Literal => Some(literal.code.stripPrefix("\"").stripSuffix("\""))
          case argument =>
            SpringPacks
              .constantString(cpg, argument.code, owner)
              .orElse(FrameworkConstants.get(argument.code.trim))
        }
        .distinct
    }
  }

  /** Authentication mechanisms → `auth-mechanism=<kind>:<raw>` (§5.2.9 D4).
    *
    * Authorization says what a caller may do; this says how it proved who it
    * is. Wadi reported the hardcoded string "spring-security" for both, which
    * is why 39 train-ticket services (JWT filter) and 15 yas modules (OAuth2
    * resource server) looked identical.
    *
    * Two rules the corpora forced:
    *
    *   - **`.disable()` is honored.** train-ticket writes
    *     `httpBasic().disable()` on every service; reporting basic auth there
    *     would be a fabricated fact on 39 services at once. A disabled link is
    *     recorded with `!<reason>` so the reader still sees the decision.
    *   - **A custom filter is never classified by its NAME.** `JWTFilter` is
    *     suggestive, not evidence. The promotion to `jwt-bearer` requires the
    *     filter class itself to reference a JWT library or a `Bearer` literal
    *     — otherwise it stays `custom-filter`, which is the honest answer
    *     (§12: a plausible security fact is still a fabricated one).
    */
  class SpringAuthMechanismPass(cpg: Cpg) extends CpgPass(cpg) {

    /** DSL call name → mechanism kind. Names, not resolved types, so the
      * matching survives jar-less parses (the file's standing design rule).
      */
    private val MechanismCalls = Map(
      "httpBasic"            -> "http-basic",
      "formLogin"            -> "form-login",
      "rememberMe"           -> "remember-me",
      "x509"                 -> "x509",
      "oauth2Login"          -> "oauth2-login",
      "oauth2ResourceServer" -> "oauth2-resource-server",
      "saml2Login"           -> "saml2"
    )

    private val FilterRegistrations = Set("addFilterBefore", "addFilterAfter", "addFilterAt", "addFilter")

    /** Evidence INSIDE a filter that it validates a bearer token. */
    private val JwtEvidence = List("io.jsonwebtoken", "com.auth0.jwt", "nimbusds", "Bearer ", "JwtParser")

    override def run(builder: DiffGraphBuilder): Unit = {
      MechanismCalls.foreach { case (callName, kind) =>
        cpg.call.nameExact(callName).l.foreach { call =>
          emit(call, kind, ownCode(call), disabledReasonOf(call), builder)
        }
      }

      // STATELESS sessions are a mechanism fact in their own right: they say
      // the service carries no server-side session, so every request must
      // present credentials.
      cpg.call.nameExact("sessionCreationPolicy").l.foreach { call =>
        if (call.argument.argumentIndexGt(0).code.exists(_.contains("STATELESS"))) {
          emit(call, "stateless-session", ownCode(call), None, builder)
        }
      }

      cpg.call.nameExact(FilterRegistrations.toSeq*).l.foreach { registration =>
        filterTypeOf(registration).foreach { filterType =>
          val kind = if (validatesBearerToken(filterType)) "jwt-bearer" else "custom-filter"
          emit(registration, kind, filterType, disabledReasonOf(registration), builder)
        }
      }
    }

    /** This link's own text, not the fluent chain it sits in.
      *
      * The same `code`-spans-the-chain property that caused the verb leak
      * (§5.2.9 D1) would otherwise make every mechanism's evidence the entire
      * SecurityConfig chain.
      */
    private def ownCode(call: Call): String = {
      val args = call.argument.argumentIndexGt(0).code.l.mkString(", ")
      s"${call.name}($args)"
    }

    private def emit(
        call: Call,
        kind: String,
        detail: String,
        disabled: Option[String],
        builder: DiffGraphBuilder
    ): Unit = {
      val suffix = disabled.map(reason => s"!$reason").getOrElse("")
      Iterator(call)
        .newTagNodePair("auth-mechanism", s"$kind:$detail$suffix")
        .store()(using builder)
    }

    /** Is this mechanism switched off? (§5.2.10 T3)
      *
      * Spring Security 5 wrote `httpBasic().disable()`, where `disable()`'s
      * receiver IS the mechanism call — the only form the predecessor knew.
      * Spring Security 6 made the lambda DSL mandatory, so the same intent is
      * written `httpBasic(t -> t.disable())` or `httpBasic(X::disable)`, where
      * the receiver is the lambda's parameter and the old test sees nothing.
      *
      * Reporting HTTP Basic as ACTIVE on a service that explicitly disabled it
      * is a fabricated security fact, which §12 rates worse than a missing one
      * — and every one of the 20 train-ticket-aitest services writes the lambda
      * form, so this was not an edge case but the whole corpus.
      */
    private def disabledReasonOf(call: Call): Option[String] = {
      val disabledFluently = cpg.call
        .nameExact("disable")
        .exists(off =>
          off.argument.argumentIndexLte(0).headOption.exists {
            case receiver: Call => receiver.id == call.id
            case _              => false
          }
        )
      // The lambda body is its own method; javasrc2cpg renders the argument's
      // code as that method's full name, and a method reference as its literal
      // text. Both are answered by asking whether the configurer this call
      // hands off to does nothing but disable.
      val disabledByLambda = call.argument
        .argumentIndexGt(0)
        .code
        .exists(argument =>
          MethodRefDisable.matches(argument.trim) ||
            cpg.method
              .fullNameExact(argument)
              .exists(_.ast.isCall.nameExact("disable").nonEmpty)
        )
      Option.when(disabledFluently || disabledByLambda)("disabled in chain")
    }

    /** `AbstractHttpConfigurer::disable` and friends — the Spring Security 6.1
      * shorthand, which carries no lambda body to inspect.
      */
    private val MethodRefDisable = "^[\\w.]*::disable$".r

    /** The filter class a registration installs: `new JwtAuthFilter()`.
      *
      * `new X()` lowers to a block whose own `code` is `<empty>`, so the type
      * comes from the `<init>` call inside it rather than from the argument's
      * text. The second argument names the *position* filter
      * (`UsernamePasswordAuthenticationFilter.class`) and is not what is being
      * installed — excluded by name.
      */
    private def filterTypeOf(registration: Call): Option[String] =
      registration.argument
        .argumentIndexGt(0)
        .l
        .flatMap { argument =>
          val constructed = argument.ast.isCall
            .nameExact("<init>")
            .l
            .map(init => init.methodFullName.split("\\.<init>").head)
          val written = Option(argument.code)
            .filter(_.startsWith("new "))
            .map(_.stripPrefix("new ").takeWhile(_ != '(').trim)
          (constructed ++ written).headOption
        }
        .map(_.split('.').last.trim)
        .find(name =>
          name.nonEmpty && name != "<empty>" && !name.contains("UsernamePassword")
        )

    /** Promotion evidence, read from the filter's own body — never its name. */
    private def validatesBearerToken(filterTypeName: String): Boolean = {
      val short = filterTypeName.split('.').last
      cpg.typeDecl
        .nameExact(short)
        .filterNot(_.isExternal)
        .exists(td =>
          td.method.ast.isLiteral.code.exists(code => JwtEvidence.exists(code.contains)) ||
            td.inheritsFromTypeFullName.exists(parent => JwtEvidence.exists(parent.contains))
        )
    }
  }

  /** `WebSecurity.ignoring()` / `WebSecurityCustomizer` → `auth-enforcement=chain-bypass|…`.
    *
    * These paths skip the security filter chain entirely, so no rule ever runs
    * on them. They carry no access call, which is exactly why the rule pass
    * cannot see them — and an endpoint that bypasses the chain is precisely
    * the one a reader most needs told about (§5.2.9).
    */
  class SpringSecurityBypassPass(cpg: Cpg) extends CpgPass(cpg) {

    private val MatcherCalls =
      Set("requestMatchers", "antMatchers", "mvcMatchers", "regexMatchers")

    override def run(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact("ignoring").l.foreach { ignoring =>
        // `web.ignoring().antMatchers("/static/**")` — the matcher is the call
        // whose RECEIVER is the ignoring() call, i.e. the next fluent link.
        val matchers = cpg.call
          .nameExact(MatcherCalls.toSeq*)
          .filter(matcher => receiverOf(matcher).exists(_.id == ignoring.id))
          .l
        val patterns =
          if (matchers.isEmpty) List(Unresolvable)
          else
            matchers.flatMap { matcher =>
              val owner = matcher.method.typeDecl.headOption
              val read = matcher.argument
                .argumentIndexGt(0)
                .l
                .flatMap {
                  case literal: Literal =>
                    Some(literal.code.stripPrefix("\"").stripSuffix("\""))
                  case argument => SpringPacks.constantString(cpg, argument.code, owner)
                }
                .filter(_.startsWith("/"))
              if (read.isEmpty) List(Unresolvable) else read
            }.distinct
        patterns.foreach { pattern =>
          Iterator(ignoring)
            .newTagNodePair("auth-enforcement", s"chain-bypass|$pattern|${firstLine(ignoring.code)}")
            .store()(using builder)
        }
      }

    private def receiverOf(call: Call): Option[Call] =
      call.argument.argumentIndexLte(0).headOption.collect { case receiver: Call => receiver }
  }

  /** Enforcement that is not Spring Security at all (§5.2.9 D9).
    *
    * Interceptors, servlet filters registered outside the chain, aspects over
    * controllers, and checks written inline in the handler. These carry no
    * access call, so the rule pass is structurally blind to them — and an
    * endpoint guarded by one previously read as completely ungoverned.
    *
    * **Detection is deliberately narrow, interpretation deliberately shallow.**
    * Narrow, because most interceptors and filters are logging, timing or
    * i18n: emitting every one as an unreadable guard would withhold claims
    * across the whole system and train readers to ignore the state. So a
    * construct qualifies only on evidence that it *gates* — it can answer 401
    * or 403, or it calls something whose name is a permission decision.
    * Shallow, because once something does qualify, its effect is left
    * `unknown`: guessing what a hand-written guard permits is exactly the
    * fabrication §12 forbids, and "something guards this and we cannot read
    * it" is the useful answer.
    */
  class SpringAuthEnforcementPass(cpg: Cpg) extends CpgPass(cpg) {

    /** Answering 401/403 is the clearest possible evidence of a gate. */
    private val RejectionMarkers =
      List("SC_UNAUTHORIZED", "SC_FORBIDDEN", "UNAUTHORIZED", "FORBIDDEN", "401", "403")

    /** Call names that ARE a permission decision (not merely auth-adjacent —
      * reading an Authorization header is propagation, not enforcement, and
      * train-ticket threads one through nearly every handler).
      */
    private val DecisionCalls = List(
      "verifytoken",
      "validatetoken",
      "checktoken",
      "checkpermission",
      "haspermission",
      "isauthorized",
      "isauthenticated",
      "checkauth",
      "verifyauth",
      "authorize",
      "authenticate",
      "checkrole",
      "hasrole"
    )

    /** Calls that read WHO the caller is (§5.2.12).
      *
      * The load-bearing discriminator for annotation-bound advice. A guard must
      * know the caller's identity; instrumentation need not. Measured **8/8**
      * on the ICPC authorizers — which spell their deny path
      * `permissionChecker.addFailure()` and hit no rejection marker at all, so
      * `RejectionMarkers`/`DecisionCalls` score 0/8 — and **0/4** on
      * train-ticket's `ms-monitoring-core` tracing advice, which would
      * otherwise withhold auth claims across that entire corpus.
      */
    private val IdentityCalls = List(
      "getauthentication",
      "getprincipal",
      "getsubject",
      "getcurrentuser",
      "getcurrentuserid",
      "getcurrentusername",
      "getcurrentprincipal",
      "getloginid",
      "getloginuser"
    )

    /** AspectJ advice kinds. `@Pointcut` is not advice but names the same
      * designators, so it is read for binding and never for gating.
      */
    private val AdviceAnnotations =
      Set("Around", "Before", "After", "AfterReturning", "AfterThrowing")

    private val PointcutAnnotations = AdviceAnnotations + "Pointcut"

    /** Bound by the pointcut, not by the annotation — never vocabulary. */
    private val JoinPointTypes =
      Set("org.aspectj.lang.ProceedingJoinPoint", "org.aspectj.lang.JoinPoint")

    /** How a `HandlerInterceptor`/`MethodInterceptor` reads its vocabulary. */
    private val AnnotationReads =
      Set("getMethodAnnotation", "isAnnotationPresent", "findAnnotation", "getAnnotation")

    private val AnnotationDesignator = """@annotation\(\s*([A-Za-z_][\w.]*)\s*\)""".r

    private val ClassLiteral = """^([A-Za-z_][\w.]*)\.class$""".r

    override def run(builder: DiffGraphBuilder): Unit = {
      tagAnnotationBound(builder)
      tagInterceptors(builder)
      tagServletFilters(builder)
      tagAspects(builder)
      tagInHandlerChecks(builder)
    }

    /** `registry.addInterceptor(new AuthInterceptor()).addPathPatterns(...)` */
    private def tagInterceptors(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact("addInterceptor").l.foreach { registration =>
        implementingTypeOf(registration).foreach { interceptor =>
          // An annotation-bound interceptor already emitted an exact record per
          // guarded endpoint. Its registered path scope is `/**` whenever no
          // `addPathPatterns` follows, so emitting both would withhold the
          // whole service and throw away the precision.
          if (gates(interceptor) && boundAnnotationsOf(interceptor).isEmpty) {
            val patterns = chainedPatterns(registration, "addPathPatterns")
            emit(registration, "interceptor", patterns, interceptor.name, builder)
          }
        }
      }

    /** `@WebFilter(urlPatterns = ...)` and `FilterRegistrationBean`.
      *
      * Filters installed INTO the security chain (`addFilterBefore`) are
      * already reported as authentication mechanisms; counting them again here
      * would withhold every claim on services that use one.
      */
    private def tagServletFilters(builder: DiffGraphBuilder): Unit = {
      val chainInstalled = cpg.call
        .nameExact("addFilter", "addFilterBefore", "addFilterAfter", "addFilterAt")
        .argument
        .argumentIndexGt(0)
        .ast
        .isCall
        .nameExact("<init>")
        .methodFullName
        .l
        .map(_.split("\\.<init>").head)
        .toSet

      cpg.typeDecl.filterNot(_.isExternal).l.foreach { typeDecl =>
        val annotation = typeDecl.ast.isAnnotation
          .filter(_.astParent == typeDecl)
          .nameExact("WebFilter")
          .headOption
        val registered = chainInstalled.contains(typeDecl.fullName)
        if (annotation.isDefined && !registered && gates(typeDecl)) {
          val patterns = annotation.toList
            .flatMap(a => "\"([^\"]*)\"".r.findAllMatchIn(a.code).map(_.group(1)).toList)
            .filter(_.startsWith("/"))
          typeDecl.method.headOption.foreach { anchor =>
            emitOn(anchor, "servlet-filter", orUnresolvable(patterns), typeDecl.name, builder)
          }
        }
      }

      cpg.call.nameExact("addUrlPatterns").l.foreach { registration =>
        val patterns = literalArguments(registration).filter(_.startsWith("/"))
        registrationBeanType(registration)
          .filter(gates)
          .foreach(filter =>
            emit(registration, "servlet-filter", orUnresolvable(patterns), filter.name, builder)
          )
      }
    }

    /** Enforcement bound to a PROJECT-DEFINED annotation (§5.2.12).
      *
      * The vocabulary is derived from the binding, never matched against a list
      * of names. A name list can only ever recognise the policies its author
      * had already seen; `@ContestManager` is invisible to one, and so is every
      * other word a project invents for its own policy. What is not
      * project-specific is how the word is *consumed* — an advice parameter
      * type, an `@annotation(...)` designator, a `getMethodAnnotation` read —
      * and that is a graph property.
      *
      * The scope of `@annotation(X)` is exactly the methods bearing X: as
      * readable as `@PreAuthorize`, and nothing like the pointcut-expression
      * problem that makes `execution(...)` honestly unresolvable. So this emits
      * one record per guarded ENDPOINT rather than one blanket per aspect, and
      * an endpoint the advice cannot reach keeps its claim. Measured on ICPC:
      * 643 of 804 endpoints guarded and 161 left alone, versus one blanket that
      * would have withheld all 804 and said nothing about any of them.
      */
    private def tagAnnotationBound(builder: DiffGraphBuilder): Unit =
      endpointHandlers.foreach { case (handler, uri, borne) =>
        borne.toList.sorted.foreach { annotation =>
          annotationBindings.getOrElse(annotation, Nil).foreach { guard =>
            emitOn(handler, "aspect", List(uri), s"${guard.name} via @$annotation", builder)
          }
        }
      }

    /** Annotation name → the gating constructs that consume it.
      *
      * Only names that are ACTUALLY annotations somewhere in the graph survive:
      * AspectJ binds non-annotation parameters too (`args(order)` binds an
      * `Order`), and without the cross-check a DTO type would enter the
      * security vocabulary.
      */
    private lazy val annotationBindings: Map[String, List[TypeDecl]] =
      cpg.typeDecl
        .filterNot(_.isExternal)
        .l
        // Bounded to constructs that can intercept a request, before any AST
        // walk: a service class that happens to call `isAnnotationPresent` is
        // doing reflection, not enforcement, and walking every type's AST to
        // find out costs a full traversal of the program on every snapshot.
        .filter(typeDecl => canIntercept(typeDecl) || typeDecl.method.exists(isAdvice))
        .flatMap { typeDecl =>
          val bound = boundAnnotationsOf(typeDecl)
          if (bound.isEmpty || !gates(typeDecl)) Nil else bound.toList.map(_ -> typeDecl)
        }
        .groupMap(_._1)(_._2)

    /** Can this type see a request before the handler does? */
    private def canIntercept(typeDecl: TypeDecl): Boolean =
      typeDecl.ast.isAnnotation.filter(_.astParent == typeDecl).exists(_.name == "Aspect") ||
        typeDecl.inheritsFromTypeFullName.exists(name =>
          name.contains("Interceptor") || name.contains("Filter")
        )

    /** Every endpoint handler with its URI and the annotations governing it.
      *
      * Class-level declarations count: these annotations are `@Target({TYPE,
      * METHOD})` by convention, and a policy declared once on the controller
      * governs every route it declares.
      */
    private lazy val endpointHandlers: List[(Method, String, Set[String])] =
      cpg.typeDecl.filterNot(_.isExternal).l.flatMap { typeDecl =>
        val classLevel = typeDecl.ast.isAnnotation.filter(_.astParent == typeDecl).name.toSet
        typeDecl.method.l.flatMap { method =>
          val own = method.ast.isAnnotation.filter(_.astParent == method).name.toSet
          // EVERY route the handler serves, not just the first. One method can
          // carry several (`@RequestMapping(method = {GET, POST})`, a value
          // array), and reading only the head would leave the siblings looking
          // unguarded — an under-approximation, which in auth is the one
          // direction that publishes a wrong fact rather than a missing one.
          method.tag.nameExact("endpoint").value.l.map { endpointTag =>
            (method, endpointTag.split(' ').lastOption.getOrElse(Unresolvable), own ++ classLevel)
          }
        }
      }

    /** The annotation vocabulary this type consumes, by any binding route.
      *
      * The two routes are filtered differently, and that asymmetry is the fix
      * for a real defect. An `@annotation(...)` designator PROVES its bound
      * names are annotations — that is what the designator means — so those
      * names need no confirmation. A `getMethodAnnotation(X.class)` read proves
      * nothing about `X`, so those are confirmed against the graph.
      */
    private def boundAnnotationsOf(typeDecl: TypeDecl): Set[String] = {
      val fromAdvice = typeDecl.method.l.filter(isAdvice).flatMap(boundAnnotationsOfMethod).toSet
      val fromReads = typeDecl.method.ast.isCall
        .filter(call => AnnotationReads.contains(call.name))
        .argument
        .argumentIndexGt(0)
        .code
        .l
        .flatMap(code => ClassLiteral.findFirstMatchIn(code.trim).map(m => simpleNameOf(m.group(1))))
        .toSet
      fromAdvice ++ fromReads.filter(annotationNames.contains)
    }

    private def isAdvice(method: Method): Boolean =
      method.ast.isAnnotation
        .filter(_.astParent == method)
        .exists(a => AdviceAnnotations.contains(a.name))

    /** `@Around(value = "@annotation(x)") … (JoinPoint jp, ContestManager x)`.
      *
      * Read from the PARAMETER TYPE first and the expression second, because
      * the two carry the binding redundantly and the parameter survives the
      * cases the string does not: `@annotation(acl)` names a variable, and an
      * unresolved type still keeps its FQN suffix
      * (`<unresolvedNamespace>.…​.TeamMember`).
      */
    private def boundAnnotationsOfMethod(method: Method): Set[String] =
      if (!isAnnotationBound(method)) Set.empty
      else {
        val fromParameters = method.parameter
          .filterNot(parameter =>
            parameter.name == "this" || JoinPointTypes.contains(parameter.typeFullName)
          )
          .typeFullName
          .l
          .map(simpleNameOf)
        val fromExpression = adviceExpressions(method)
          .flatMap(code =>
            AnnotationDesignator.findAllMatchIn(code).map(m => simpleNameOf(m.group(1)))
          )
        (fromParameters ++ fromExpression).toSet
      }

    /** Is this advice scoped by the annotations its targets carry?
      *
      * Read from the DESIGNATOR, not from whether the bound type resolves. The
      * first cut asked "is the bound name confirmably an annotation?", which
      * conflated two questions and re-created the blanket through a second
      * door: in a per-service CPG, ICPC's `@ACL` is declared in a sibling jar,
      * so it is neither used nor internally declared, the advice read as
      * unbound, and one `{?}` withheld all 803 endpoints of the service — the
      * same 804-endpoint failure as the unused-annotation case, arriving from
      * the opposite direction.
      *
      * `@annotation(x)` means the advice runs on methods carrying an
      * annotation. That is true whether or not the annotation's declaration is
      * on the CPG, so it — and nothing else — decides whether the scope is a
      * method set or an honest unknown.
      */
    private def isAnnotationBound(method: Method): Boolean =
      adviceExpressions(method).exists(_.contains("@annotation("))

    private def adviceExpressions(method: Method): List[String] =
      method.ast.isAnnotation
        .filter(_.astParent == method)
        .filter(a => PointcutAnnotations.contains(a.name))
        .code
        .l

    /** Names that really are annotation types.
      *
      * Two sources, because neither alone is right. USAGE alone misses an
      * annotation that is declared and not yet applied — ICPC's `@ACL` is
      * exactly that, and treating its authorizer as unbound sent it down the
      * `execution(...)` path and emitted a service-wide `{?}` that withheld all
      * 804 endpoints. DECLARATION alone misses annotations declared in a jar.
      *
      * javasrc gives an `@interface` no distinguishing TypeDecl property — it
      * reads as `public class ACL` with no supertype — so the declaration test
      * is its meta-annotations. That is not a heuristic here: an annotation a
      * running aspect can bind to MUST carry `@Retention(RUNTIME)`, or the
      * advice would never fire.
      */
    private lazy val annotationNames: Set[String] = {
      val used = cpg.annotation.name.toSet
      val declared = cpg.typeDecl
        .filterNot(_.isExternal)
        .filter(td =>
          td.ast.isAnnotation
            .filter(_.astParent == td)
            .exists(a => a.name == "Retention" || a.name == "Target")
        )
        .name
        .toSet
      used ++ declared
    }

    private def simpleNameOf(typeName: String): String =
      typeName.split('.').last.split('$').last

    /** `@Aspect` advice whose pointcut reaches controllers by SHAPE.
      *
      * Only advice that is not annotation-bound lands here. An annotation-bound
      * aspect has already emitted an exact record per guarded endpoint, and
      * adding the blanket would withhold every endpoint in the service — undoing
      * the precision that made it worth reading.
      */
    private def tagAspects(builder: DiffGraphBuilder): Unit =
      cpg.typeDecl
        .filterNot(_.isExternal)
        .filter(td => td.ast.isAnnotation.filter(_.astParent == td).exists(_.name == "Aspect"))
        .l
        .foreach { aspect =>
          val advice = aspect.method.l.filter(isAdvice)
          val fullyBound = advice.nonEmpty && advice.forall(isAnnotationBound)
          if (gates(aspect) && !fullyBound) {
            aspect.method.headOption.foreach { anchor =>
              // A pointcut is an expression language of its own; reading it is
              // a project in itself, so the scope is honestly unresolvable.
              emitOn(anchor, "aspect", List(Unresolvable), aspect.name, builder)
            }
          }
        }

    /** A gate written inline in the handler.
      *
      * Scoped to the endpoint that declares it, which the endpoint pass has
      * already tagged — so this needs no path matching of its own.
      */
    private def tagInHandlerChecks(builder: DiffGraphBuilder): Unit =
      cpg.method.where(_.tag.nameExact("endpoint")).l.foreach { handler =>
        if (gatesMethod(handler)) {
          // Every route the handler serves — the guard is written once and
          // governs all of them (§5.2.12, same reason as `endpointHandlers`).
          val uris = handler.tag
            .nameExact("endpoint")
            .value
            .l
            .map(_.split(' ').lastOption.getOrElse(Unresolvable))
            .distinct
          emitOn(handler, "in-handler", orUnresolvable(uris), s"${handler.name}()", builder)
        }
      }

    // --- shared shape reading --------------------------------------------------

    /** Does this type decide access anywhere in its body? */
    private def gates(typeDecl: TypeDecl): Boolean = typeDecl.method.exists(gatesMethod)

    private def gatesMethod(method: Method): Boolean = {
      val rejects = method.ast.isLiteral.code.exists(code =>
        RejectionMarkers.exists(code.contains)
      ) || method.ast.isIdentifier.name.exists(name => RejectionMarkers.exists(name.contains)) ||
        method.ast.isCall.code.exists(code =>
          RejectionMarkers.exists(marker => code.contains(marker) && marker.length > 3)
        )
      val decides = method.ast.isCall.name.exists(name =>
        DecisionCalls.contains(name.toLowerCase)
      )
      // §5.2.12: advice that VOTES rather than throws still gates. Requiring a
      // deny-shape scored 1/8 on the ICPC authorizers, which record the verdict
      // on a request-scoped bean that a LATER aspect turns into a 403 — the
      // deny is real and simply is not written here. Reading the caller's
      // identity and branching on it scored 8/8, and still excludes tracing
      // and timing advice, which branches constantly but never asks who you
      // are (0/4 on train-ticket's `ms-monitoring-core`).
      val judges = touchesIdentity(method) && method.ast.isControlStructure.nonEmpty
      rejects || decides || judges
    }

    private def touchesIdentity(method: Method): Boolean =
      method.ast.isCall.name.exists(name => IdentityCalls.contains(name.toLowerCase)) ||
        method.ast.isCall.code.exists(_.contains("SecurityContextHolder"))

    /** The class an `addInterceptor(new X())`-style registration installs. */
    private def implementingTypeOf(registration: Call): Option[TypeDecl] =
      registration.argument
        .argumentIndexGt(0)
        .l
        .flatMap(_.ast.isCall.nameExact("<init>").l.map(_.methodFullName.split("\\.<init>").head))
        .flatMap(fullName => cpg.typeDecl.fullNameExact(fullName).filterNot(_.isExternal).l)
        .headOption

    private def registrationBeanType(registration: Call): Option[TypeDecl] =
      registration.method.ast.isCall
        .nameExact("<init>")
        .l
        .map(_.methodFullName.split("\\.<init>").head)
        .flatMap(fullName => cpg.typeDecl.fullNameExact(fullName).filterNot(_.isExternal).l)
        .find(td => td.method.exists(gatesMethod))

    /** Literal path arguments on a later link of the same fluent chain. */
    private def chainedPatterns(registration: Call, callName: String): List[String] = {
      val patterns = cpg.call
        .nameExact(callName)
        .filter(_.method.fullName == registration.method.fullName)
        .l
        .flatMap(literalArguments)
        .filter(_.startsWith("/"))
        .distinct
      // No declared scope means the interceptor sees every request.
      if (patterns.isEmpty) List("/**") else patterns
    }

    private def literalArguments(call: Call): List[String] =
      call.argument.argumentIndexGt(0).isLiteral.code.l.map(_.stripPrefix("\"").stripSuffix("\""))

    private def orUnresolvable(patterns: List[String]): List[String] =
      if (patterns.isEmpty) List(Unresolvable) else patterns

    private def emit(
        anchor: Call,
        kind: String,
        patterns: List[String],
        detail: String,
        builder: DiffGraphBuilder
    ): Unit = patterns.foreach { pattern =>
      Iterator(anchor)
        .newTagNodePair("auth-enforcement", s"$kind|$pattern|$detail")
        .store()(using builder)
    }

    private def emitOn(
        anchor: Method,
        kind: String,
        patterns: List[String],
        detail: String,
        builder: DiffGraphBuilder
    ): Unit = patterns.foreach { pattern =>
      Iterator(anchor)
        .newTagNodePair("auth-enforcement", s"$kind|$pattern|$detail")
        .store()(using builder)
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
        val mechanism =
          if (isFeign && hasFeignInterceptor) Some("feign-interceptor")
          else if (carriesInboundHeaders(sink) || setsAuthorizationHeader(sink.method))
            Some("authorization-header")
          else None
        mechanism.foreach { value =>
          Iterator(sink).newTagNodePair("token-propagation", value).store()(using builder)
        }
        Iterator(sink)
          .newTagNodePair("token-propagation-state", stateOf(sink, mechanism.isDefined))
          .store()(using builder)
      }
    }

    /** Three states, because "no evidence of forwarding" is not "does not forward".
      *
      * `forwarded` rests on evidence. `not-forwarded` is only claimed where the
      * absence is PROVABLE — the request entity this call site passes was built
      * with no headers argument at all (`new HttpEntity(null)`, 98 sites on
      * train-ticket-aitest). Everything else is `undetermined`: over-approximating
      * toward "forwarded" would tell a reader that credentials propagate when
      * they may not, and toward "not-forwarded" would invent a finding. Same
      * rule the response-shape recovery uses — when the evidence disagrees, say
      * so rather than electing a winner (P10).
      */
    private def stateOf(sink: Call, forwarded: Boolean): String =
      if (forwarded) "forwarded"
      else {
        val verdicts = requestEntitiesOf(sink).map(headerVerdictOf)
        if (verdicts.isEmpty) "undetermined"
        else if (verdicts.forall(_ == NoHeaders)) "not-forwarded"
        else "undetermined"
      }

    private val Headers   = "headers"
    private val NoHeaders = "no-headers"
    private val Unknown   = "unknown"

    /** Does THIS entity construction carry headers: yes, no, or unknown.
      *
      * Three-way rather than boolean because the corpus makes the middle case
      * common and explicit: `new HttpEntity(info, null)` passes a null in the
      * headers position (81+ sites), which is a stronger negative than omitting
      * the argument. Treating "an argument is present at the headers position"
      * as forwarding — the first cut — reported 299 of 382 calls as forwarding
      * credentials, when the corpus contains 10 such sites.
      */
    private def headerVerdictOf(init: Call): String = {
      // Every real argument, not just the second: `new HttpEntity(headers)` is
      // Spring's headers-ONLY constructor and forwards, while
      // `new HttpEntity(body)` is the body-only one and does not. Position
      // cannot tell them apart — only the argument's TYPE can, which is why
      // reading from index 2 called a genuine forwarding a provable negative.
      val candidates = init.argument.l.filter(_.argumentIndex >= 1)
      if (candidates.isEmpty) NoHeaders // `new HttpEntity()`
      else if (candidates.exists(isHeaders)) Headers
      else if (candidates.forall(isDefinitelyNotHeaders)) NoHeaders
      else Unknown
    }

    /** The argument's type IS `HttpHeaders` — by declaration or by what the
      * helper that builds it returns (`HeadersUtils.prepareForSent(headers)`).
      */
    private def isHeaders(argument: AstNode): Boolean = argument match {
      case identifier: Identifier => identifier.typeFullName.endsWith("HttpHeaders")
      case call: Call =>
        call.typeFullName.endsWith("HttpHeaders") ||
        cpg.method
          .fullNameExact(call.methodFullName)
          .methodReturn
          .typeFullName
          .exists(_.endsWith("HttpHeaders"))
      case _ => false
    }

    /** This argument provably is NOT headers.
      *
      * A literal `null` states it outright; a typed argument whose type is
      * known and is something else settles it too. An argument javasrc2cpg
      * could not type settles nothing, so it yields `unknown` rather than
      * either verdict (P10).
      */
    private def isDefinitelyNotHeaders(argument: AstNode): Boolean = argument match {
      // No literal is ever an HttpHeaders instance — `null` states it outright
      // and every other literal settles it by construction.
      case _: Literal             => true
      case identifier: Identifier => isKnownNonHeaderType(identifier.typeFullName)
      case call: Call =>
        isKnownNonHeaderType(call.typeFullName) ||
        cpg.method
          .fullNameExact(call.methodFullName)
          .methodReturn
          .typeFullName
          .exists(isKnownNonHeaderType)
      case _ => false
    }

    private def isKnownNonHeaderType(typeName: String): Boolean =
      typeName.nonEmpty && !typeName.startsWith("<") && typeName != "ANY" &&
        !typeName.endsWith("HttpHeaders")

    /** The inbound `HttpHeaders` reach the request this call site sends.
      *
      * `new HttpEntity(body, headers)` — the TrainTicket idiom, and the shape
      * that actually forwards a caller's bearer token onward. Resolved at the
      * CALL SITE rather than method-wide: one method routinely builds both a
      * bare entity and a header-carrying one (`ConsignServiceImpl` does, at
      * lines 62 and 95), so a method-level answer would smear the two together.
      */
    private def carriesInboundHeaders(sink: Call): Boolean =
      requestEntitiesOf(sink).exists(headerVerdictOf(_) == Headers)

    /** `new HttpEntity(...)` constructions feeding this call site's arguments. */
    private def requestEntitiesOf(sink: Call): List[Call] =
      sink.argument.l.flatMap {
        case call: Call if isEntityInit(call) => List(call)
        case identifier: Identifier =>
          // `HttpEntity e = new HttpEntity(null, headers); …exchange(…, e, …)`
          // javasrc2cpg lowers that to `e = <alloc>` FOLLOWED BY
          // `<init>(e, null, headers)` — the constructor takes the variable as
          // its receiver, so it is a sibling of the assignment rather than a
          // child of it, and walking the assignment's AST finds nothing.
          identifier.method.ast.isCall
            .filter(isEntityInit)
            .filter(_.argument.l.exists {
              case receiver: Identifier =>
                receiver.argumentIndex == 0 && receiver.name == identifier.name
              case _ => false
            })
            .l
        case _ => Nil
      }.distinctBy(_.id)

    private def isEntityInit(call: Call): Boolean =
      call.name == "<init>" && {
        val owner = call.methodFullName.split("\\.<init>").head
        owner.endsWith("HttpEntity") || owner.endsWith("RequestEntity")
      }

    /** An `Authorization` header set explicitly on the outbound request. */
    private def setsAuthorizationHeader(method: Method): Boolean =
      method.ast.isCall.exists(call =>
        call.name == "setBearerAuth" ||
          (call.name.startsWith("set") || call.name == "add") && call.argument.exists(argument =>
            argument.label == "LITERAL" &&
              argument.code.stripPrefix("\"").stripSuffix("\"") == "Authorization"
          )
      )
  }

  /** Calls to `@FeignClient` interface methods are outbound http-client sinks.
    *
    * The composed URL `http://<feign-name><path><methodPath>` (or the `url=`
    * attribute when present) is the phone-book key the stitcher resolves via
    * discovery/compose names. The endpoint trap stays intact: mapping
    * annotations on feign interfaces still never count as served endpoints.
    *
    * T2 completeness (§5.4.2): mappings are collected from the feign
    * interface's TRANSITIVE parent interfaces too (the shared-contract idiom
    * previously produced no sink at all); `@RequestMapping(method = …)`
    * carries a verb; a non-literal `name`/`value` attribute resolves through
    * the in-CPG constant assignment or degrades to an honest `{?}` authority
    * (never the interface-name guess); `contextId` never names the target.
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
            .orElse(constantAttr(annotationCode, "name"))
            .orElse(constantAttr(annotationCode, "value"))
            .orElse(bareLiteralName(annotationCode))
            .getOrElse(
              if (hasUnresolvableName(annotationCode)) "{?}" // honest, never a guess
              else feignInterface.name.toLowerCase
            )
          val pathPrefix = attr(annotationCode, "path").getOrElse("")
          val urlAttr    = attr(annotationCode, "url").getOrElse("")
          // Shared-contract idiom: mappings may live on transitive parents.
          // Call sites can resolve against the parent's OR the child's method
          // full name (frontend receiver typing decides) — register both.
          val ownMethods    = feignInterface.method.l.map(m => m -> List(m.fullName))
          val parentMethods = parentInterfaceMethods(feignInterface).map { m =>
            m -> List(m.fullName, s"${feignInterface.fullName}.${m.name}:${m.signature}")
          }
          (ownMethods ++ parentMethods).flatMap { case (interfaceMethod, keys) =>
            mappingOf(interfaceMethod).toList.flatMap { case (verb, methodPath) =>
              val authority =
                if (urlAttr.nonEmpty) urlAttr
                else if (name == "{?}") "{?}"
                else s"http://$name"
              val url = SpringPacks.joinPaths(
                SpringPacks.joinPaths(authority, pathPrefix),
                methodPath
              )
              keys.map(_ -> s"$verb|$url")
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

    /** Transitive parent interfaces resolved in-CPG (short-name fallback for
      * jar-less parses, §5.2.6) — their methods carry the shared contract.
      */
    private def parentInterfaceMethods(feignInterface: TypeDecl): List[Method] =
      SpringPacks.transitiveParents(cpg, feignInterface).flatMap(_.method.l)

    private def attr(annotationCode: String, name: String): Option[String] =
      s"""$name\\s*=\\s*"([^"]*)"""".r.findFirstMatchIn(annotationCode).map(_.group(1)).filter(_.nonEmpty)

    /** `name = SOME_CONSTANT` — resolve the referenced static-final literal
      * from the in-CPG assignment; None when it isn't resolvable.
      */
    private def constantAttr(annotationCode: String, name: String): Option[String] =
      s"""$name\\s*=\\s*([A-Za-z_][\\w.]*)""".r
        .findFirstMatchIn(annotationCode)
        .map(_.group(1))
        .filterNot(_ == "true")
        .filterNot(_ == "false")
        .flatMap(reference => SpringPacks.constantString(cpg, reference, owner = None))

    /** `@FeignClient("inventory")` — the bare single-string form. */
    private def bareLiteralName(annotationCode: String): Option[String] = {
      val hasNamedAttrs = "\\w+\\s*=".r.findFirstIn(annotationCode).isDefined
      if (hasNamedAttrs) None else SpringPacks.pathFromAnnotationCode(annotationCode)
    }

    /** A name/value attribute exists but is neither a literal nor a resolvable
      * constant — guessing the interface name here would fabricate a target.
      */
    private def hasUnresolvableName(annotationCode: String): Boolean =
      "(?:name|value)\\s*=\\s*[A-Za-z_]".r.findFirstIn(annotationCode).isDefined

    private val RequestMethodVerb = """RequestMethod\.([A-Z]+)""".r

    private def mappingOf(method: Method): Option[(String, String)] =
      method.ast.isAnnotation
        .filter(_.astParent == method)
        .flatMap { annotation =>
          SpringPacks.MappingAnnotations.get(annotation.name).map { verb =>
            verb -> SpringPacks.pathFromAnnotationCode(annotation.code).getOrElse("")
          } ++ Option.when(annotation.name == "RequestMapping") {
            // @RequestMapping(method = RequestMethod.GET, value = "/x") on a
            // feign method (T2) — verb from the method attribute.
            RequestMethodVerb.findFirstMatchIn(annotation.code).map(_.group(1)).map { verb =>
              verb -> SpringPacks.pathFromAnnotationCode(annotation.code).getOrElse("")
            }
          }.flatten
        }
        .headOption
  }

  /** `@HttpExchange` declarative HTTP interfaces (Spring 6, T2 §5.4.2):
    * `@GetExchange("/x")` methods on an `@HttpExchange`-annotated interface
    * are outbound sinks, exactly like feign contracts. The base URL lives on
    * the proxy factory's underlying client — when the type-level annotation
    * carries an absolute `url`/value it is used; otherwise the authority is
    * an honest `{?}` (recorded limitation: proxy-factory base join).
    */
  class SpringHttpInterfaceSinkPass(cpg: Cpg) extends CpgPass(cpg) {

    private val ExchangeVerbs = Map(
      "GetExchange"    -> "GET",
      "PostExchange"   -> "POST",
      "PutExchange"    -> "PUT",
      "DeleteExchange" -> "DELETE",
      "PatchExchange"  -> "PATCH"
    )

    override def run(builder: DiffGraphBuilder): Unit = {
      val interfaceMethods: Map[String, String] = cpg.typeDecl
        .filterNot(_.isExternal)
        .filter(td =>
          td.ast.isAnnotation.filter(_.astParent == td).exists(_.name == "HttpExchange") ||
            td.method.exists(m =>
              m.ast.isAnnotation.filter(_.astParent == m).exists(a => ExchangeVerbs.contains(a.name))
            )
        )
        .l
        .flatMap { httpInterface =>
          val typeLevel = httpInterface.ast.isAnnotation
            .filter(_.astParent == httpInterface)
            .filter(_.name == "HttpExchange")
            .headOption
          val prefix = typeLevel
            .flatMap(a => SpringPacks.pathFromAnnotationCode(a.code))
            .getOrElse("")
          val authority =
            if (prefix.startsWith("http://") || prefix.startsWith("https://")) prefix
            else SpringPacks.joinPaths("{?}", prefix)
          httpInterface.method.l.flatMap { interfaceMethod =>
            interfaceMethod.ast.isAnnotation
              .filter(_.astParent == interfaceMethod)
              .flatMap(a => ExchangeVerbs.get(a.name).map(_ -> a))
              .headOption
              .map { case (verb, annotation) =>
                val path = SpringPacks.pathFromAnnotationCode(annotation.code).getOrElse("")
                interfaceMethod.fullName ->
                  s"$verb|${SpringPacks.joinPaths(authority, path)}|http-interface"
              }
          }
        }
        .toMap

      if (interfaceMethods.isEmpty) return

      cpg.call.l.foreach { call =>
        interfaceMethods.get(call.methodFullName).foreach { encoded =>
          Iterator(call).newTagNodePair("sink", "http-client").store()(using builder)
          Iterator(call).newTagNodePair("wadi-declared", encoded).store()(using builder)
        }
      }
    }
  }

  private def firstLine(code: String): String =
    code.linesIterator.nextOption().getOrElse("").take(500)
}
