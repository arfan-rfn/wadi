package wadi.packs

import io.shiftleft.codepropertygraph.generated.{Cpg, DiffGraphBuilder}
import io.shiftleft.codepropertygraph.generated.nodes.{
  AstNode,
  Call,
  Expression,
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

    /** Everything that decides access on a matched request. Names absent here
      * would silently produce no rule — the same fall-through failure as a
      * dropped pattern — so the list tracks the DSL rather than one corpus.
      */
    private val AccessCalls = Set(
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

    /** Rule-scoped matchers. `securityMatcher`/`antMatcher` are deliberately
      * absent: they scope a whole CHAIN, not one rule, and are read as chain
      * scope by the exporter instead.
      */
    private val MatcherCalls =
      Set("requestMatchers", "antMatchers", "mvcMatchers", "regexMatchers", "anyRequest")

    /** An argument that IS an HTTP verb reference, whole — anchored so a
      * chain's text can never leak a verb into a rule that has none.
      */
    private val VerbArgument = "^(?:org\\.springframework\\.http\\.)?HttpMethod\\.([A-Z]+)$".r

    override def run(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact(AccessCalls.toSeq*).l.foreach { accessCall =>
        receiverCall(accessCall).filter(r => MatcherCalls.contains(r.name)).foreach { matcher =>
          val verb   = verbOf(matcher).getOrElse("*")
          val access = accessText(accessCall)
          patternsOf(matcher).foreach { pattern =>
            Iterator(accessCall)
              .newTagNodePair("auth-rule", s"$verb|$pattern|$access")
              .store()(using builder)
          }
        }
      }

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
      if (matcher.name == "anyRequest") return List("/**")
      val owner = matcher.method.typeDecl.headOption
      val arguments = matcher.argument
        .argumentIndexGt(0)
        .l
        .filterNot(argument => VerbArgument.matches(argument.code.trim))
      if (arguments.isEmpty) return List(Unresolvable) // e.g. requestMatchers(someMatcherBean())
      val resolved = arguments.flatMap(argument => patternOf(argument, owner)).distinct
      if (resolved.sizeIs == arguments.size) resolved
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
      val candidateTypes =
        (enclosing.parameter.typeFullName.l ++ enclosing.local.typeFullName.l).distinct
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

    /** One matcher argument → the path it names.
      *
      * A `${key}` placeholder is passed through verbatim rather than resolved
      * here: config lives worker-side, and §5.2.4 already fixes that split for
      * `@Value` — the exporter emits the symbol, the worker resolves it.
      */
    private def patternOf(argument: Expression, owner: Option[TypeDecl]): Option[String] = {
      val direct = argument match {
        case literal: Literal => Some(literal.code.stripPrefix("\"").stripSuffix("\""))
        case _                => SpringPacks.constantString(cpg, argument.code, owner)
      }
      direct.filter(value => value.startsWith("/") || value.startsWith("${"))
    }

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

    /** `httpBasic().disable()` — the mechanism call is the receiver of a
      * `disable()`, so the configured mechanism is switched off.
      */
    private def disabledReasonOf(call: Call): Option[String] =
      Option.when(
        cpg.call
          .nameExact("disable")
          .exists(off =>
            off.argument.argumentIndexLte(0).headOption.exists {
              case receiver: Call => receiver.id == call.id
              case _              => false
            }
          )
      )("disabled in chain")

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

    override def run(builder: DiffGraphBuilder): Unit = {
      tagInterceptors(builder)
      tagServletFilters(builder)
      tagAspects(builder)
      tagInHandlerChecks(builder)
    }

    /** `registry.addInterceptor(new AuthInterceptor()).addPathPatterns(...)` */
    private def tagInterceptors(builder: DiffGraphBuilder): Unit =
      cpg.call.nameExact("addInterceptor").l.foreach { registration =>
        implementingTypeOf(registration).foreach { interceptor =>
          if (gates(interceptor)) {
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

    /** `@Aspect` advice whose pointcut reaches controllers. */
    private def tagAspects(builder: DiffGraphBuilder): Unit =
      cpg.typeDecl
        .filterNot(_.isExternal)
        .filter(td => td.ast.isAnnotation.filter(_.astParent == td).exists(_.name == "Aspect"))
        .l
        .foreach { aspect =>
          if (gates(aspect)) {
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
        handler.tag.nameExact("endpoint").value.headOption.foreach { endpointTag =>
          if (gatesMethod(handler)) {
            val uri = endpointTag.split(' ').lastOption.getOrElse(Unresolvable)
            emitOn(handler, "in-handler", List(uri), s"${handler.name}()", builder)
          }
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
      rejects || decides
    }

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
