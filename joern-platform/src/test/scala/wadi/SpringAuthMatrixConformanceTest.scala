package wadi

import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.matchers.should.Matchers

/** §5.2.9 — the auth enforcement matrix, pinned per row.
  *
  * The auth layer's only fixture used to be `petstore-system`, whose
  * SecurityConfig is a plain modern lambda DSL: no verb-scoped matcher, no
  * constant pattern, no mechanism. Nine defects lived behind that green test,
  * two of them publishing confidently wrong security facts on real code. This
  * fixture is the enumeration — the §5.2.8 lesson applied to auth, where a
  * fixture that only contains what its author imagined is the failure mode.
  *
  * Every assertion here names the train-ticket/yas shape it stands in for, so
  * a future reader can tell which are regressions and which are coverage.
  */
class SpringAuthMatrixConformanceTest extends AnyFunSuite with Matchers with FixtureCpg {

  private lazy val exportJson: ujson.Value =
    exportFixture("spring-auth-matrix", "spring-auth-matrix-export")

  /** (verb, pattern, access) for every extracted filter-chain rule. */
  private lazy val rules: List[(String, String, String)] =
    exportJson("security_rules").arr.toList.map { rule =>
      val verb = rule("http_method") match {
        case ujson.Null => "*"
        case other      => other.str
      }
      (verb, rule("pattern").str, rule("access").str)
    }

  private def ruleFor(pattern: String, verb: String): (String, String, String) =
    rules
      .find { case (v, p, _) => p == pattern && v == verb }
      .getOrElse(
        fail(
          s"no rule for verb=$verb pattern=$pattern; extracted:\n" +
            rules.map { case (v, p, a) => s"  $v | $p | $a" }.mkString("\n")
        )
      )

  test("every endpoint in the fixture is extracted") {
    val endpoints = exportJson("endpoints").arr.map(e => s"${e("http_method").str} ${e("uri").str}")
    endpoints should contain allOf (
      "POST /api/v1/orders",
      "PUT /api/v1/orders",
      "DELETE /api/v1/orders/{orderId}",
      "GET /internal/health"
    )
  }

  // ---- D1: the verb leak (ts-travel-service lost 12 endpoints to this) ----

  test("D1: each rule carries ITS OWN verb, not the chain's first") {
    // Reading the verb from the fluent chain's `code` stamped the first
    // HttpMethod in the chain (POST here) onto every later rule.
    ruleFor("/api/v1/orders", "POST")._1 shouldBe "POST"
    ruleFor("/api/v1/orders", "PUT")._1 shouldBe "PUT"
    ruleFor("/api/v1/orders/*", "DELETE")._1 shouldBe "DELETE"
  }

  test("D1: verb-free matchers stay verb-free") {
    // The sweep and the catch-all follow three verb-scoped matchers. Under the
    // leak they inherited POST and stopped matching anything else.
    ruleFor("/api/v1/orders/**", "*")._3 should include("permitAll")
    ruleFor("/**", "*")._3 should include("authenticated")
  }

  // ---- D2: constants resolved, unreadable patterns kept as holes ----

  test("D2: a bare constant pattern resolves instead of dropping the rule") {
    // `.antMatchers(HttpMethod.POST, orders)` where `String orders = "..."`.
    // Dropped, POST fell through to the permitAll sweep and the endpoint was
    // published as "no authentication (evidenced)" — the worst outcome (§12).
    ruleFor("/api/v1/orders", "POST")._3 should include("hasAnyRole")
  }

  test("D2: an unreadable pattern is emitted as a hole, never dropped") {
    val opaque = rules.filter { case (_, pattern, _) => pattern == "{?}" }
    opaque should not be empty
    opaque.map(_._3).mkString should include("AUDITOR")
  }

  test("D3: constants inside the access expression resolve too") {
    // hasAnyRole(admin, "USER") — `admin` must not silently vanish, or the
    // endpoint reports half its roles as if that were the whole answer.
    val access = ruleFor("/api/v1/orders", "POST")._3
    access should include("ADMIN")
    access should include("USER")
  }

  // ---- D8: vocabulary gaps are silent missing rules ----

  test("D8: fullyAuthenticated is an access call") {
    ruleFor("/internal/**", "*")._3 should include("fullyAuthenticated")
  }

  test("denyAll is a rule, scoped to its own path") {
    // `denyAll()` admits nobody, so it must not be swallowed by the
    // `/api/v1/orders/**` permitAll sweep that follows it. It reaching the
    // export with its own pattern is what lets the worker tell an unreachable
    // route from a protected one (§12).
    ruleFor("/api/v1/orders/legacy", "*")._3 should include("denyAll")
  }

  test("D8: WebSecurity.ignoring() bypasses are visible") {
    // These paths skip the chain entirely and carry no access call, so the
    // rule pass could never see them.
    val bypasses = exportJson("auth_enforcements").arr.toList
      .filter(_("kind").str == "chain-bypass")
      .map(_("pattern").str)
    bypasses should contain("/static/**")
    bypasses should contain("/favicon.ico")
  }

  // ---- D6/D7: annotation-driven authorization ----

  /** `auth=` tags on the endpoint whose URI ends with `suffix`. */
  private def authTagsOf(suffix: String): List[String] = {
    val endpoint = exportJson("endpoints").arr.toList
      .find(_("uri").str.endsWith(suffix))
      .getOrElse(fail(s"no endpoint ending '$suffix'"))
    endpoint("auth_tags").arr.toList.map(_.str)
  }

  test("D7: a composed meta-annotation resolves to what it actually grants") {
    // @IsAdmin is declared as @PreAuthorize("hasRole('ADMIN')"). Name-matching
    // alone sees an unknown annotation and the endpoint reads as ungoverned.
    val tags = authTagsOf("/audit/config")
    tags.mkString should include("hasRole('ADMIN')")
    // Both names survive: "@IsAdmin" alone tells a reader nothing.
    tags.mkString should include("IsAdmin")
  }

  test("D7: a policy on an implemented interface reaches the handler") {
    authTagsOf("/audit/trail").mkString should include("ROLE_AUDITOR")
  }

  test("D6: method-security enablement is reported, not assumed") {
    // This fixture never writes @EnableMethodSecurity, so the annotations above
    // are inert. Reporting them as enforcement would be a fabricated fact; the
    // export states what it found and the worker decides.
    exportJson("method_security")("present").bool shouldBe false
  }

  // ---- D4: how the service authenticates, not just what it authorizes ----

  /** (kind, active, detail) per extracted mechanism. */
  private lazy val mechanisms: List[(String, Boolean, String)] =
    exportJson("auth_mechanisms").arr.toList
      .map(m => (m("kind").str, m("active").bool, m("detail").str))

  test("D4: a custom filter is promoted on evidence INSIDE it, never its name") {
    // JwtAuthFilter reads an Authorization header and checks a "Bearer "
    // literal. The class NAME must not be what earns the classification —
    // a plausible security fact is still a fabricated one (§12).
    mechanisms.map(m => (m._1, m._3)) should contain(("jwt-bearer", "JwtAuthFilter"))
  }

  test("D4: a disabled mechanism is recorded as inactive, never claimed") {
    // train-ticket writes httpBasic().disable() on 39 services; reporting
    // basic auth there would be a wrong fact 39 times over.
    val basic = mechanisms.filter(_._1 == "http-basic")
    basic should not be empty
    all(basic.map(_._2)) shouldBe false
  }

  test("D4: a stateless session policy is a mechanism fact") {
    mechanisms.map(_._1) should contain("stateless-session")
  }

  // ---- D9: enforcement that is not Spring Security at all ----

  /** (kind, pattern, detail) per detected non-framework guard. */
  private lazy val enforcements: List[(String, String, String)] =
    exportJson("auth_enforcements").arr.toList
      .map(e => (e("kind").str, e("pattern").str, e("detail").str))

  test("D9: a gating interceptor is detected, with its path scope") {
    enforcements should contain(
      ("interceptor", "/api/v1/audit", "TenantAuthInterceptor")
    )
  }

  test("D9: a non-gating interceptor is NOT reported as a guard") {
    // The counterweight to the test above, and the more important of the two:
    // treating every interceptor as an unreadable guard would withhold claims
    // system-wide and train readers to ignore the state entirely.
    enforcements.map(_._3) should not contain "TimingInterceptor"
  }

  test("D9: a check written inline in the handler is detected") {
    // No annotation, no chain rule — and the chain's permitAll sweep covers
    // this path, so undetected it reads as evidenced-open.
    enforcements should contain(
      ("in-handler", "/api/v1/orders/export", "export()")
    )
  }

  test("D9: a handler that merely reads a header is not a guard") {
    // train-ticket threads @RequestHeader HttpHeaders through nearly every
    // handler to forward it downstream. Reading a header is propagation, not
    // enforcement, and confusing the two would withhold on ~every endpoint.
    enforcements.filter(_._1 == "in-handler").map(_._2) should contain only
      "/api/v1/orders/export"
  }

  // ---- D5: the policy lives in config, not in the Java ----

  test("D5: a config-bound matcher names its binding instead of vanishing") {
    // Not one literal path appears in the config-driven chain, so a reader
    // that only sees Java literals extracts nothing and every endpoint under
    // it falls to a catch-all. Naming the prefix lets the worker read the YAML.
    rules.map(_._2) should contain("@app.api-security")
  }

  test("D5: the binding is distinguishable from an unreadable pattern") {
    // '{?}' means unreadable; '@prefix' means readable, just not from here.
    // Collapsing them would throw away a recoverable policy.
    val bound = rules.filter(_._2.startsWith("@"))
    bound.map(_._3).mkString should include("hasAnyRole")
    rules.map(_._2) should contain("{?}") // the genuinely unreadable one survives too
  }

  test("chain scoping: rules carry the chain that declared them") {
    val chains = exportJson("security_rules").arr.toList
      .map(rule => rule("chain_id").str)
      .distinct
    // Two chains in this fixture: the legacy configure(HttpSecurity) override
    // and the config-driven bean. Pooling them would apply one chain's
    // first-match-wins across the other's rules.
    chains.size should be >= 2
  }

  test("chain scoping: a securityMatcher scope travels with its rules") {
    val scoped = exportJson("security_rules").arr.toList
      .filter(_("chain_pattern") != ujson.Null)
      .map(_("chain_pattern").str)
      .distinct
    scoped should contain("/config-driven/**")
  }

  // ---- ordering: first-match-wins depends on declaration order ----

  test("rules arrive in declaration order WITHIN a chain") {
    // Order is per-chain, not global: first-match-wins applies inside one
    // chain, so ordering across two chains is meaningless and asserting on it
    // would pass or fail by accident of which chain the exporter walked first.
    val legacy = exportJson("security_rules").arr.toList
      .filter(_("chain_id").str.contains(".configure:"))
      .map(_("pattern").str)
    legacy.indexOf("/api/v1/orders") should be < legacy.indexOf("/api/v1/orders/**")
    legacy.indexOf("/api/v1/orders/**") should be < legacy.indexOf("/**")
  }
}
