"""Auth-evidence merge tests (§5.2 step 5): three sources, honest claims."""

from typing import ClassVar

from wadi_contracts import (
    AuthEffect,
    AuthEvidence,
    AuthEvidenceKind,
    AuthResolution,
    EndpointAuth,
    HttpMethod,
    SourceAnchor,
)
from wadi_joern_client.export import (
    UNRESOLVABLE_PATTERN,
    ExportAnchor,
    ExportAuthEnforcement,
    ExportAuthMechanism,
    ExportAuthorityModel,
    ExportMethodSecurity,
    ExportSecurityRule,
    RulePatternConfidence,
)
from wadi_worker.auth_merge import (
    _ant_match,  # pyright: ignore[reportPrivateUsage] — the matching core deserves direct tests
    merge_endpoint_auth,
)

ANCHOR = SourceAnchor(file="src/C.java", start_line=10, end_line=12)


def _rule(
    pattern: str, access: str, http_method: str | None = None, line: int = 21
) -> ExportSecurityRule:
    return ExportSecurityRule(
        pattern=pattern,
        http_method=http_method,
        access=access,
        kind="filter-chain",
        anchor=ExportAnchor(file="src/SecurityConfig.java", line=line),
        evidence=f'requestMatchers("{pattern}").{access}',
    )


CHAIN = [
    _rule("/admin/**", 'hasRole("ADMIN")'),
    _rule("/stock/**", "permitAll()", line=22),
    _rule("/**", "authenticated()", line=23),
]


class TestAnnotationEvidence:
    def test_pre_authorize_yields_role_claim(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/admin/restock",
            http_method=HttpMethod.POST,
            auth_tags=["auth=annotation:@PreAuthorize(\"hasRole('ADMIN')\")"],
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]
        assert auth.mechanism == "spring-security"
        [evidence] = auth.evidence
        assert evidence.kind is AuthEvidenceKind.ANNOTATION
        assert "@PreAuthorize" in evidence.detail
        assert evidence.anchor == ANCHOR

    def test_unparseable_expression_claims_auth_without_roles(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=['auth=annotation:@PreAuthorize("@guard.check(#id)")'],
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == []  # raw text preserved in evidence, never guessed

    def test_jsr250_roles_allowed(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=['auth=jsr250:@RolesAllowed({"ROLE_OPS", "AUDIT"})'],
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["AUDIT", "OPS"]


class TestDslRules:
    def test_first_match_wins(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/admin/restock",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=CHAIN,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]
        [evidence] = auth.evidence
        assert evidence.kind is AuthEvidenceKind.SECURITY_DSL
        assert evidence.detail == '/admin/** -> hasRole("ADMIN")'

    def test_permit_all_is_a_false_claim_with_evidence(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/stock/{id}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=CHAIN,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is False
        assert auth.evidence  # the claims-need-evidence validator is satisfied

    def test_catch_all_authenticated(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/other/thing",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=CHAIN,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == []

    def test_verb_restricted_rule_skipped_on_other_verbs(self) -> None:
        rules = [_rule("/x", "permitAll()", http_method="GET"), _rule("/**", "authenticated()")]
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=rules,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True


class TestConflictsAndUnknowns:
    def test_chain_permit_all_does_not_cancel_method_security(self) -> None:
        # Corrected in §5.2.9: these are not competing claims to pick between,
        # they COMPOSE. `permitAll()` means the filter chain does not block;
        # @PreAuthorize still runs at method invocation, so the endpoint really
        # does require ROLE_OPS. The old "conflict -> unknown" reading modelled
        # two layers of Spring as if only one could apply, and threw away a
        # sound answer.
        auth = merge_endpoint_auth(
            full_uri="/stock/special",
            http_method=HttpMethod.GET,
            auth_tags=["auth=annotation:@PreAuthorize(\"hasRole('OPS')\")"],
            security_rules=CHAIN,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["OPS"]
        assert len(auth.evidence) == 2  # both sides attached

    def test_no_evidence_is_honest_unknown(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is None
        assert auth.evidence == []
        assert auth.mechanism is None

    def test_config_only_evidence_makes_no_claim(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={"spring.security.oauth2.resourceserver.jwt.issuer-uri": "https://i"},
        )
        assert auth.authenticated is None  # evidence without a claim
        [evidence] = auth.evidence
        assert evidence.kind is AuthEvidenceKind.CONFIG


class TestAntMatching:
    def test_patterns(self) -> None:
        assert _ant_match("/admin/**", "/admin/restock")
        assert _ant_match("/admin/**", "/admin/a/b/c")
        assert _ant_match("/admin/**", "/admin")  # ** matches zero segments
        assert _ant_match("/**", "/anything/at/all")
        assert _ant_match("/stock/*", "/stock/5")
        assert not _ant_match("/stock/*", "/stock/5/deep")
        assert _ant_match("/stock/**", "/stock/{id}")  # template segment
        assert _ant_match("/s?ock/*", "/stock/5")
        assert not _ant_match("/admin/**", "/stock/5")


class TestClaimWithholding:
    """§5.2.9 — the defect class this model replaces.

    Measured on train-ticket: `.antMatchers(HttpMethod.POST, orders)` with a
    constant pattern was dropped, so POST /api/v1/orderservice/order fell
    through to a later `permitAll()` and was published as "no authentication
    (evidenced)" while requiring ROLE_ADMIN/ROLE_USER.
    """

    def test_an_unreadable_rule_withholds_instead_of_falling_through(self) -> None:
        chain = [
            _rule(UNRESOLVABLE_PATTERN, 'hasAnyRole("ADMIN", "USER")', http_method="POST"),
            _rule("/api/v1/orders/**", "permitAll()", line=22),
        ]
        auth = merge_endpoint_auth(
            full_uri="/api/v1/orders",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=chain,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is None, "an unread rule must never reach permitAll"
        assert [item.kind for item in auth.unread_enforcement] == [AuthEvidenceKind.SECURITY_DSL]

    def test_an_unreadable_rule_for_another_verb_does_not_withhold(self) -> None:
        # The opaque rule is POST-scoped; a GET request never reaches it, so
        # the walk continues and the answer stays precise. Withholding on every
        # endpoint because one rule is unreadable would be its own failure.
        chain = [
            _rule(UNRESOLVABLE_PATTERN, 'hasRole("ADMIN")', http_method="POST"),
            _rule("/api/v1/orders/**", "permitAll()", line=22),
        ]
        auth = merge_endpoint_auth(
            full_uri="/api/v1/orders",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=chain,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is False

    def test_an_uninterpretable_guard_withholds(self) -> None:
        # An interceptor guarding /api/** that we cannot read must not leave
        # the endpoint reading as unprotected.
        auth = merge_endpoint_auth(
            full_uri="/api/v1/orders",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="interceptor",
                    pattern="/api/**",
                    detail="AuthInterceptor.preHandle",
                    anchor=ExportAnchor(file="src/WebConfig.java", line=30),
                )
            ],
        )
        assert auth.authenticated is None
        assert auth.unread_enforcement[0].kind is AuthEvidenceKind.INTERCEPTOR

    def test_a_guard_scoped_elsewhere_does_not_withhold(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/public/health",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="interceptor",
                    pattern="/api/**",
                    detail="AuthInterceptor.preHandle",
                    anchor=ExportAnchor(file="src/WebConfig.java", line=30),
                )
            ],
        )
        assert auth.authenticated is False

    def test_an_annotation_bound_aspect_withholds_the_endpoint_it_names(self) -> None:
        # §5.2.12. The chain says permitAll and the project's own vocabulary
        # says ADMIN; without the aspect record the endpoint publishes an
        # evidenced-open claim, which is the ICPC defect exactly (637 of 803).
        auth = merge_endpoint_auth(
            full_uri="/common/country/export",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/common/country/export",
                    detail="AdminAuthorizer via @Admin",
                    anchor=ExportAnchor(file="src/AdminAuthorizer.java", line=26),
                )
            ],
        )
        assert auth.authenticated is None
        assert auth.unread_enforcement[0].kind is AuthEvidenceKind.ASPECT

    def test_an_annotation_bound_aspect_does_not_leak_across_a_template_sibling(self) -> None:
        # The hazard that makes this kind endpoint-scoped rather than
        # pattern-scoped: `{a2}` ant-matches the literal `export`, so a guard
        # on the template route would lend itself to every sibling and the
        # count of genuinely unguarded endpoints — the finding the tranche
        # exists to surface — would quietly collapse to zero.
        auth = merge_endpoint_auth(
            full_uri="/common/country/export",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/common/country/{a2}",
                    detail="AdminAuthorizer via @Admin",
                    anchor=ExportAnchor(file="src/AdminAuthorizer.java", line=26),
                )
            ],
        )
        assert auth.authenticated is False

    def test_an_aspect_of_unresolvable_scope_still_withholds_everything(self) -> None:
        # Exact matching must not cost the blanket case: an `execution(...)`
        # pointcut is honestly unreadable and has to withhold service-wide, or
        # the §5.2.9 rule that an unread guard withholds becomes conditional on
        # the guard happening to be annotation-bound.
        auth = merge_endpoint_auth(
            full_uri="/anything/at/all",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="{?}",
                    detail="UserAuthorizer",
                    anchor=ExportAnchor(file="src/UserAuthorizer.java", line=15),
                )
            ],
        )
        assert auth.authenticated is None

    def test_a_read_relationship_guard_is_published_not_withheld(self) -> None:
        # §5.2.12 M2. The guard states its policy in the annotation the
        # developer wrote, so there is nothing unread about it — publishing
        # `withheld` here would trade a read answer for an unread one.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/camp/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/contest/public/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/contest/{contestId}/camp/create",
                    detail="ContestManagerAuthorizer via @ContestManager(context = Contest.class)",
                    anchor=ExportAnchor(file="src/ContestManagerAuthorizer.java", line=59),
                    relation="contest-manager",
                    resource_type="Contest",
                    authorities=["CONTEST_CREATE_SUBCONTEST"],
                )
            ],
        )
        assert auth.authenticated is True
        assert auth.unread_enforcement == []
        assert [r.relation for r in auth.relationships] == ["contest-manager"]
        assert auth.relationships[0].resource_type == "Contest"
        # Required IN ADDITION to the relation, so it appears in both places.
        assert auth.relationships[0].authorities == ["CONTEST_CREATE_SUBCONTEST"]
        assert auth.authorities == ["CONTEST_CREATE_SUBCONTEST"]
        assert auth.composition_unresolved is False

    def test_a_relationship_guard_beats_a_permit_all_that_matched_by_template(self) -> None:
        # The live ICPC defect: `{contestId}` ant-matches the literal `public`
        # in `/contest/public/**`, so seven contest-administration write routes
        # published as `authenticated=False` — no authentication, evidenced.
        # A read relationship guard now settles it in the restrictive direction.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/subcontest/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/contest/public/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/contest/{contestId}/subcontest/create",
                    detail="ContestManagerAuthorizer via @ContestManager",
                    anchor=ExportAnchor(file="src/ContestManagerAuthorizer.java", line=59),
                    relation="contest-manager",
                )
            ],
        )
        assert auth.authenticated is True

    def test_two_relationship_guards_leave_their_composition_unresolved(self) -> None:
        # ICPC stacks @Admin and @ContestManager on one handler and admits the
        # caller if EITHER voted yes; Spring's layered enforcement composes the
        # other way. Nothing read so far says which, and listing both
        # requirements as though all were needed overstates what a caller must
        # have — an over-restrictive answer is still a wrong one.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "authenticated()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/contest/{contestId}",
                    detail="ContestManagerAuthorizer via @ContestManager",
                    anchor=ExportAnchor(file="src/A.java", line=59),
                    relation="contest-manager",
                    resource_type="Contest",
                ),
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="/contest/{contestId}",
                    detail="SiteManagerAuthorizer via @SiteManager",
                    anchor=ExportAnchor(file="src/B.java", line=44),
                    relation="site-manager",
                    resource_type="Site",
                ),
            ],
        )
        assert auth.composition_unresolved is True
        assert {r.relation for r in auth.relationships} == {"contest-manager", "site-manager"}

    def test_a_guard_with_no_relation_still_withholds(self) -> None:
        # The M1 behaviour must survive M2: a guard we detected but could not
        # read is still unread, and gaining a vocabulary for the ones we CAN
        # read must not quietly promote the ones we cannot.
        auth = merge_endpoint_auth(
            full_uri="/api/v1/orders",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="aspect",
                    pattern="{?}",
                    detail="UserAuthorizer",
                    anchor=ExportAnchor(file="src/UserAuthorizer.java", line=15),
                )
            ],
        )
        assert auth.authenticated is None
        assert auth.relationships == []

    def test_a_permit_all_reached_by_template_absorption_does_not_open_a_route(self) -> None:
        # §5.2.13, the live ICPC defect with the annotation guard removed so the
        # matcher alone decides. `/contest/{contestId}/camp/create` "matches"
        # `/contest/public/**` only for the single request whose contestId is
        # the string `public`; a later rule requires auth for every other. The
        # answer is protected, and it used to be `authenticated=false` —
        # no authentication, evidenced, on a sub-contest creation route.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/camp/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[
                _rule("/contest/public/**", "permitAll()"),
                _rule("/**", "authenticated()"),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True

    def test_partial_coverage_is_its_own_fact_not_a_reading_failure(self) -> None:
        # `resolution` says how completely the enforcement was READ, and this
        # rule was read perfectly — `/contest/public/** -> permitAll()`, every
        # character of it. What is partial is its SCOPE. Overloading resolution
        # would tell a reader the analysis failed on a rule it understood, and
        # would leave no way to explain why a permitAll sits on a protected
        # endpoint without opening the code.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/camp/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[
                _rule("/contest/public/**", "permitAll()"),
                _rule("/**", "authenticated()"),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        permit = next(item for item in auth.evidence if item.effect is AuthEffect.PERMIT_ALL)
        assert permit.covers_route is False
        assert permit.resolution is AuthResolution.RESOLVED
        catch_all = next(
            item for item in auth.evidence if item.effect is AuthEffect.REQUIRE_AUTHENTICATED
        )
        assert catch_all.covers_route is True

    def test_a_literal_permit_all_still_opens_the_route_it_names(self) -> None:
        # The control. Narrowing the matcher must not cost real answers: this
        # endpoint's path is literal all the way, so the rule covers every
        # request it serves and `open` is the correct, evidenced claim.
        auth = merge_endpoint_auth(
            full_uri="/contest/public/list",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/contest/public/**", "permitAll()"),
                _rule("/**", "authenticated()"),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is False

    def test_a_wildcard_permit_all_over_a_template_is_still_exact(self) -> None:
        # `*` genuinely covers a template segment — every value of `{id}` — so
        # this is not speculation and must keep answering. Conflating the two
        # would withhold every public templated route in every system.
        auth = merge_endpoint_auth(
            full_uri="/contest/public/{contestId}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/contest/public/*", "permitAll()"),
                _rule("/**", "authenticated()"),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is False

    def test_a_speculative_permit_all_with_nothing_else_withholds(self) -> None:
        # No later rule requires auth, so "open" would rest entirely on a match
        # that is false for every request but one. That is the same shape as an
        # unread permit, and it withholds the same way rather than claiming.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/camp/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/contest/public/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is None

    def test_a_speculative_match_still_restricts_where_that_is_the_safe_direction(self) -> None:
        # The asymmetry stated plainly: over-approximating a template into a
        # literal adds restriction here, so it stands. Only the permissive
        # direction is narrowed — withdrawing enforcement on a guess is what
        # publishes wrong facts.
        auth = merge_endpoint_auth(
            full_uri="/contest/{contestId}/camp/create",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/contest/admin/**", "hasRole('ADMIN')")],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_a_chain_bypass_reached_by_template_absorption_is_ignored(self) -> None:
        # A bypass switches the chain off entirely, so it is held to an exact
        # match: granting it on one possible value of a template would take the
        # security chain off a whole route.
        auth = merge_endpoint_auth(
            full_uri="/api/{resource}/data",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "authenticated()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="chain-bypass",
                    pattern="/api/static/**",
                    detail="ignoring()",
                    anchor=ExportAnchor(file="src/SecurityConfig.java", line=40),
                )
            ],
        )
        assert auth.authenticated is True

    def test_a_chain_bypass_means_nothing_runs(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/static/app.js",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "authenticated()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_enforcements=[
                ExportAuthEnforcement(
                    kind="chain-bypass",
                    pattern="/static/**",
                    detail="ignoring()",
                    anchor=ExportAnchor(file="src/SecurityConfig.java", line=40),
                )
            ],
        )
        # The catch-all says authenticated(), but the chain never runs here.
        assert auth.authenticated is False


class TestMethodSecurityEnablement:
    """§5.2.9 D6 — an annotation only enforces if its family is switched on."""

    TAG: ClassVar[list[str]] = ['auth=annotation:@Secured("ROLE_ADMIN")']

    def test_a_disabled_family_is_inert_and_marked(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=self.TAG,
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            method_security=ExportMethodSecurity(
                present=True, style="EnableMethodSecurity", pre_post=True, secured=False
            ),
        )
        # securedEnabled=false: @Secured does nothing, so permitAll governs.
        assert auth.authenticated is False
        annotation = next(i for i in auth.evidence if i.kind is AuthEvidenceKind.ANNOTATION)
        assert annotation.active is False
        assert annotation.inactive_reason is not None

    def test_an_enabled_family_enforces(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=self.TAG,
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            method_security=ExportMethodSecurity(
                present=True, style="EnableMethodSecurity", secured=True
            ),
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_unknown_enablement_withholds(self) -> None:
        # No enabling annotation found: the annotation may be inert, or enabled
        # from XML outside this CPG. Neither guess is honest.
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=self.TAG,
            security_rules=[_rule("/**", "permitAll()")],
            handler_anchor=ANCHOR,
            config_env={},
            method_security=ExportMethodSecurity(present=False),
        )
        assert auth.authenticated is None

    def test_a_pre_2_7_export_keeps_its_previous_reading(self) -> None:
        # method_security=None means the exporter predates the field. Behaving
        # as before beats retroactively withholding on every stored artifact.
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=self.TAG,
            security_rules=[],
            handler_anchor=ANCHOR,
            config_env={},
            method_security=None,
        )
        assert auth.authenticated is True


class TestMechanisms:
    def test_a_disabled_mechanism_is_carried_as_inactive(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/x",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/**", "authenticated()")],
            handler_anchor=ANCHOR,
            config_env={},
            auth_mechanisms=[
                ExportAuthMechanism(
                    kind="jwt-bearer",
                    detail="JwtAuthFilter",
                    anchor=ExportAnchor(file="src/SecurityConfig.java", line=50),
                ),
                ExportAuthMechanism(
                    kind="http-basic",
                    detail="httpBasic()",
                    active=False,
                    inactive_reason="disabled in chain",
                    anchor=ExportAnchor(file="src/SecurityConfig.java", line=44),
                ),
            ],
        )
        assert [(m.kind.value, m.active) for m in auth.mechanisms] == [
            ("jwt-bearer", True),
            ("http-basic", False),
        ]


class TestConfigDefinedAuthorization:
    """§5.2.9 D5 — the policy lives in application.yaml, not in the Java.

    Shape taken verbatim from yas, which binds
    `@ConfigurationProperties(prefix="app.security")` and loops over the bound
    rules: not one literal pattern appears in the SecurityConfig, so the whole
    policy used to be invisible and every endpoint fell to the catch-all.
    """

    STRUCTURED: ClassVar[dict[str, list[dict[str, object]]]] = {
        "app.security.rules": [
            {"patterns": ["/actuator/health/**", "/swagger-ui/**"], "permit-all": True},
            {"patterns": ["/storefront/**"], "permit-all": True},
            {"patterns": ["/backoffice/**"], "roles": ["ADMIN"]},
            {"patterns": ["/internal/**"], "methods": ["POST"], "roles": ["SERVICE"]},
        ]
    }

    def _merge(self, uri: str, verb: HttpMethod = HttpMethod.GET) -> EndpointAuth:
        bound = _rule("@app.security", "hasAnyRole(rolesArray)")
        catch_all = _rule("/**", "authenticated()", line=30)
        return merge_endpoint_auth(
            full_uri=uri,
            http_method=verb,
            auth_tags=[],
            security_rules=[bound, catch_all],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured=self.STRUCTURED,
        )

    def test_roles_are_recovered_from_yaml(self) -> None:
        auth = self._merge("/backoffice/products")
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_permit_all_is_recovered_from_yaml(self) -> None:
        auth = self._merge("/storefront/products")
        assert auth.authenticated is False

    def test_verb_scoped_config_rules_respect_their_verb(self) -> None:
        assert self._merge("/internal/sync", HttpMethod.POST).roles == ["SERVICE"]
        # A GET falls past the POST-scoped rule to the catch-all.
        assert self._merge("/internal/sync", HttpMethod.GET).roles == []

    def test_an_uncorrelatable_binding_withholds_rather_than_falling_through(self) -> None:
        # The Java says "patterns come from app.security"; the config has no
        # such key. Falling through to the catch-all would invent a policy.
        auth = merge_endpoint_auth(
            full_uri="/backoffice/products",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("@app.security", "hasAnyRole(rolesArray)"),
                _rule("/**", "permitAll()", line=30),
            ],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured={"unrelated.key": [{"a": 1}]},
        )
        assert auth.authenticated is None
        assert auth.unread_enforcement[0].kind is AuthEvidenceKind.SECURITY_DSL


class TestAuthoritiesAreNotRoles:
    """`hasRole("X")` and `hasAuthority("X")` match DIFFERENT grants in Spring.

    Spring's `hasRole("ADMIN")` tests for the authority `ROLE_ADMIN`;
    `hasAuthority("ADMIN")` tests for `ADMIN`. Pooling both into `roles` reads
    as "the ADMIN role is required" for a rule that requires no role at all.
    """

    def test_has_authority_populates_authorities_not_roles(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/orders/42",
            http_method=HttpMethod.DELETE,
            auth_tags=[],
            security_rules=[_rule("/orders/*", 'hasAuthority("ORDER_DELETE")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.authorities == ["ORDER_DELETE"]
        assert auth.roles == []
        [evidence] = auth.evidence
        assert evidence.effect is AuthEffect.REQUIRE_AUTHORITIES
        assert evidence.authorities == ["ORDER_DELETE"]
        assert evidence.roles == []

    def test_has_any_authority_keeps_every_named_authority(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/orders/42",
            http_method=HttpMethod.DELETE,
            auth_tags=[],
            security_rules=[_rule("/orders/*", 'hasAnyAuthority("ORDER_DELETE", "ORDER_ADMIN")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authorities == ["ORDER_ADMIN", "ORDER_DELETE"]
        assert auth.roles == []

    def test_has_role_still_populates_roles_only(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/admin/restock",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/admin/**", 'hasRole("ADMIN")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.roles == ["ADMIN"]
        assert auth.authorities == []
        [evidence] = auth.evidence
        assert evidence.effect is AuthEffect.REQUIRE_ROLES


class TestDenyAll:
    """`denyAll()` admits nobody — unreachable, not merely protected (§12).

    Reporting it as an ordinary protected route tells an auditor a dead
    endpoint is live surface, which is the class of wrong security fact this
    model exists to prevent.
    """

    def test_deny_all_is_a_claim_of_its_own(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/orders/legacy",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/orders/legacy", "denyAll()"),
                _rule("/orders/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.denied is True
        # Still authenticated=True: no unauthenticated request passes either.
        # `denied` REFINES the positive claim rather than replacing it, so every
        # existing reader of the tri-state keeps working.
        assert auth.authenticated is True
        assert auth.roles == []
        assert auth.evidence[0].effect is AuthEffect.DENY_ALL

    def test_an_ordinary_protected_route_is_not_denied(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/admin/restock",
            http_method=HttpMethod.POST,
            auth_tags=[],
            security_rules=[_rule("/admin/**", 'hasRole("ADMIN")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.denied is False

    def test_first_match_wins_so_a_later_deny_never_reaches_the_endpoint(self) -> None:
        # Chain order is the rule: an earlier permitAll shadows the denyAll
        # below it, exactly as Spring evaluates it.
        auth = merge_endpoint_auth(
            full_uri="/orders/open",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/orders/**", "permitAll()"),
                _rule("/orders/open", "denyAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.denied is False
        assert auth.authenticated is False


class TestDenialIsAReadClaim:
    def test_the_contract_refuses_a_denial_without_a_positive_claim(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="denied=True requires authenticated=True"):
            EndpointAuth(authenticated=None, denied=True)


class TestRuleScoping:
    """A rule governs the endpoint it decides — not every request it could serve."""

    def test_a_literal_rule_does_not_reach_a_templated_sibling(self) -> None:
        # Ant matching lets `{orderId}` swallow `legacy`. At runtime Spring
        # routes /orders/legacy to its own more-specific handler, so the deny
        # belongs to that endpoint alone. Left over-approximating, this reported
        # a live route as unreachable.
        auth = merge_endpoint_auth(
            full_uri="/orders/{orderId}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/orders/legacy", "denyAll()"),
                _rule("/orders/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.denied is False
        assert auth.authenticated is False

    def test_a_wildcard_rule_still_covers_the_whole_template(self) -> None:
        # The over-approximation stays where it only ADDS restriction.
        auth = merge_endpoint_auth(
            full_uri="/orders/{orderId}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/orders/*", 'hasRole("ADMIN")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_a_templated_rule_matches_a_differently_named_variable(self) -> None:
        # `{orderId}` in the rule and `{id}` on the handler are the same route;
        # requiring a literal string match here would drop the rule entirely.
        auth = merge_endpoint_auth(
            full_uri="/orders/{id}",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[_rule("/orders/{orderId}", 'hasRole("ADMIN")')],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_an_exact_literal_rule_still_governs_its_own_endpoint(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/orders/legacy",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("/orders/legacy", "denyAll()"),
                _rule("/orders/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.denied is True


class TestPropertyPlaceholderScopes:
    """§5.2.10: a `${…}` pattern is a scope, not a string.

    The exporter now passes placeholders through instead of reporting `{?}`,
    which is more informative — and would be actively dangerous if the worker
    compared them literally. A pattern still holding `${…}` matches no
    endpoint, so the rule would govern nothing and the endpoint would fall
    through to whatever comes next. These pin the two halves apart.
    """

    def test_a_resolvable_placeholder_governs_the_endpoint_it_names(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/api/admin/reports",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("${app.admin-path}/**", 'hasRole("ADMIN")'),
                _rule("/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={"app.admin-path": "/api/admin"},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_a_placeholder_default_is_used_when_config_is_silent(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/api/admin/reports",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("${app.admin-path:/api/admin}/**", 'hasRole("ADMIN")'),
                _rule("/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN"]

    def test_an_unresolvable_placeholder_withholds_instead_of_falling_through(self) -> None:
        # The regression that matters. Left as a literal `${…}` this rule
        # matches nothing, the endpoint reaches `permitAll()`, and wadi
        # publishes "no authentication, evidenced" for a route that may well
        # require ADMIN — the exact §5.2.9 wrong answer by a new road.
        auth = merge_endpoint_auth(
            full_uri="/api/admin/reports",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[
                _rule("${app.admin-path}/**", 'hasRole("ADMIN")'),
                _rule("/**", "permitAll()", line=22),
            ],
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is None, "an unread scope must withhold, never fall through"
        assert auth.unread_enforcement, "and it must say which construct it could not read"


class TestConfigDefinedRuleShapes:
    """§5.2.10 T4: the config reader knew yas's shape, not the shape space.

    Every case here is a real train-ticket-aitest construct. The verb one is a
    measured wrong answer, not a hypothetical: without it a GET-only permitAll
    widened to every verb and `POST /adminbasic/configs` published as
    evidenced-open against a ROLE_ADMIN ground truth.
    """

    PREFIX = "@security"

    def _bound(self, access: str = "hasAnyRole(roles)") -> ExportSecurityRule:
        return ExportSecurityRule(
            call_id=1,
            pattern=self.PREFIX,
            pattern_confidence=RulePatternConfidence.CONFIG,
            access=access,
            kind="filter-chain",
            anchor=ExportAnchor(file="src/SecurityConfig.java", line=21),
            evidence="authorizedUrl.hasAnyRole(roles)",
        )

    #: The real ts-admin-service policy, verbatim in shape.
    AITEST_RULES: ClassVar[dict[str, list[dict[str, object]]]] = {
        "security.authorization-rules": [
            {
                "paths": ["/api/v1/adminbasicservice/adminbasic/configs"],
                "method": "GET",
                "authorities": ["permitAll"],
            },
            {"paths": ["/api/v1/adminbasicservice/**"], "authorities": ["ROLE_ADMIN"]},
        ]
    }

    def _auth(self, uri: str, verb: HttpMethod, **kwargs: object) -> EndpointAuth:
        return merge_endpoint_auth(
            full_uri=uri,
            http_method=verb,
            auth_tags=[],
            security_rules=[self._bound(), _rule("/**", "authenticated()", line=99)],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured=self.AITEST_RULES,
            **kwargs,  # pyright: ignore[reportArgumentType]
        )

    def test_a_scalar_method_key_keeps_the_rule_verb_scoped(self) -> None:
        # The measured regression: `method: "GET"` was read from lists only.
        opened = self._auth("/api/v1/adminbasicservice/adminbasic/configs", HttpMethod.GET)
        assert opened.authenticated is False, "GET is permitAll by rule 1"

        guarded = self._auth("/api/v1/adminbasicservice/adminbasic/configs", HttpMethod.POST)
        assert guarded.authenticated is True, "POST must fall to the ROLE_ADMIN rule"
        assert guarded.roles == ["ADMIN"]

    def test_a_permissive_sentinel_in_the_authority_list_opens_the_route(self) -> None:
        # Not as a demand for a role literally named "permitAll".
        auth = self._auth("/api/v1/adminbasicservice/adminbasic/configs", HttpMethod.GET)
        assert auth.roles == []
        assert auth.authenticated is False

    def test_role_vs_authority_follows_the_java_not_the_yaml_key(self) -> None:
        # The key is spelled "authorities", but the loop called hasAnyRole, so
        # ROLE_ADMIN is a role. A reader that trusted the key name would emit
        # an authority and the chip would name a grant the rule never asks for.
        auth = merge_endpoint_auth(
            full_uri="/api/v1/adminbasicservice/x",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[self._bound()],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured=self.AITEST_RULES,
        )
        assert auth.roles == ["ADMIN"]
        assert auth.authorities == []

        as_authority = merge_endpoint_auth(
            full_uri="/api/v1/adminbasicservice/x",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[self._bound(access="hasAnyAuthority(auths)")],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured=self.AITEST_RULES,
        )
        assert as_authority.authorities == ["ROLE_ADMIN"]
        assert as_authority.roles == []

    def test_an_undeterminable_entry_withholds_instead_of_inventing_a_grant(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/api/v1/thing",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[self._bound(), _rule("/**", "permitAll()", line=99)],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured={"security.rules": [{"paths": ["/api/v1/**"], "note": "tbd"}]},
        )
        assert auth.authenticated is None

    def test_a_deny_sentinel_is_a_denial_not_a_role(self) -> None:
        auth = merge_endpoint_auth(
            full_uri="/api/v1/legacy",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=[self._bound()],
            handler_anchor=ANCHOR,
            config_env={},
            config_structured={
                "security.rules": [{"paths": ["/api/v1/legacy"], "authorities": ["denyAll"]}]
            },
        )
        assert auth.denied is True


class TestAuthorityModel:
    """§5.2.10 T7: what a grant means is not whether a request gets through."""

    def _model(self, kind: str, detail: str) -> ExportAuthorityModel:
        return ExportAuthorityModel(
            kind=kind,
            detail=detail,
            anchor=ExportAnchor(file="src/SecurityConfig.java", line=30),
        )

    def _auth(self, *models: ExportAuthorityModel, **kwargs: object) -> EndpointAuth:
        return merge_endpoint_auth(
            full_uri="/admin/reports",
            http_method=HttpMethod.GET,
            auth_tags=[],
            handler_anchor=ANCHOR,
            config_env={},
            authority_models=list(models),
            **kwargs,  # pyright: ignore[reportArgumentType]
        )

    def test_an_authority_model_never_gates_on_its_own(self) -> None:
        # The trap. With effect UNKNOWN these land in `requiring` unless
        # excluded, and every service that merely declares a UserDetailsService
        # would claim all its endpoints demand authentication — a wrong fact
        # invented by the machinery meant to prevent wrong facts.
        auth = self._auth(
            self._model("user-details-service", "userDetailsService"), security_rules=[]
        )
        assert auth.authenticated is None
        assert auth.roles == []

    def test_a_role_hierarchy_marks_the_role_list_incomplete(self) -> None:
        # ROLE_ADMIN > ROLE_USER means ADMIN reaches a [USER] endpoint too, so
        # the published list under-states who can get in.
        auth = self._auth(
            self._model("role-hierarchy", "RoleHierarchyImpl"),
            security_rules=[_rule("/admin/**", 'hasRole("USER")')],
        )
        assert auth.authenticated is True, "the hierarchy must not cost the claim"
        assert auth.roles == ["USER"]
        partial = [
            item
            for item in auth.evidence
            if item.kind is AuthEvidenceKind.AUTHORITY_MODEL
            and item.resolution is AuthResolution.PARTIAL
        ]
        assert partial, "the incompleteness must be visible on the endpoint"

    def test_a_default_authority_prefix_changes_nothing_and_says_so(self) -> None:
        # A GrantedAuthorityDefaults that restates ROLE_ rewires nothing;
        # flagging it would be crying wolf on a no-op bean.
        auth = self._auth(
            self._model("authority-defaults", 'GrantedAuthorityDefaults("ROLE_")'),
            security_rules=[_rule("/admin/**", 'hasRole("ADMIN")')],
        )
        model = next(i for i in auth.evidence if i.kind is AuthEvidenceKind.AUTHORITY_MODEL)
        assert model.resolution is AuthResolution.RESOLVED

    def test_a_custom_authority_prefix_is_flagged(self) -> None:
        auth = self._auth(
            self._model("authority-defaults", 'GrantedAuthorityDefaults("")'),
            security_rules=[_rule("/admin/**", 'hasRole("ADMIN")')],
        )
        model = next(i for i in auth.evidence if i.kind is AuthEvidenceKind.AUTHORITY_MODEL)
        assert model.resolution is AuthResolution.PARTIAL


class TestOrderedAlternativesAreNotConjunctive:
    """§5.2.10: the §5.2.9 defect, mirrored.

    "Enforcement is a conjunction — an unknown gate can add a requirement,
    never remove one" is true for LAYERED enforcement (a chain rule and method
    security both run). It is false for ORDERED ALTERNATIVES inside one chain:
    authorizeHttpRequests is first-match-wins, so an earlier match means the
    later rules never execute.

    An unread-scope permitAll() ahead of a readable anyRequest().authenticated()
    therefore leaves the endpoint genuinely uncertain, and discounting it
    published a confident `True` — the same root shape as the original defect
    (an unread rule not permitted to withhold), pointing the other way.
    """

    def _opaque(self, access: str, line: int) -> ExportSecurityRule:
        return ExportSecurityRule(
            call_id=line,
            pattern=None,
            pattern_confidence=RulePatternConfidence.NONE,
            access=access,
            kind="filter-chain",
            anchor=ExportAnchor(file="src/SecurityConfig.java", line=line),
            evidence=access,
        )

    def _claim(self, *rules: ExportSecurityRule) -> EndpointAuth:
        return merge_endpoint_auth(
            full_uri="/contest/public/list",
            http_method=HttpMethod.GET,
            auth_tags=[],
            security_rules=list(rules),
            handler_anchor=ANCHOR,
            config_env={},
        )

    def test_an_unread_permit_all_withholds_a_protected_answer(self) -> None:
        auth = self._claim(
            self._opaque("permitAll()", 10),
            _rule("/**", "authenticated()", line=20),
        )
        assert auth.authenticated is None, (
            "a permitAll whose scope is unknown can remove enforcement exactly "
            "as a chain bypass can; claiming protected here is a false positive"
        )
        assert auth.unread_enforcement

    def test_an_unread_restrictive_rule_still_leaves_the_claim_standing(self) -> None:
        # The control that keeps the fix from becoming a wall of unknowns: an
        # unread hasRole can only ADD restriction, so protected either way.
        auth = self._claim(
            self._opaque('hasRole("AUDITOR")', 10),
            _rule("/**", "authenticated()", line=20),
        )
        assert auth.authenticated is True

    def test_an_unread_restrictive_rule_before_permit_all_still_withholds(self) -> None:
        auth = self._claim(
            self._opaque('hasRole("AUDITOR")', 10),
            _rule("/**", "permitAll()", line=20),
        )
        assert auth.authenticated is None

    def test_fully_readable_chains_are_unaffected(self) -> None:
        opened = self._claim(
            _rule("/contest/public/**", "permitAll()"),
            _rule("/**", "authenticated()", line=20),
        )
        assert opened.authenticated is False
        guarded = self._claim(
            _rule("/admin/**", 'hasRole("ADMIN")'),
            _rule("/**", "authenticated()", line=20),
        )
        assert guarded.authenticated is True


class TestConfigRecoveredProvenance:
    """A recovered rule must cite the branch that applies it, and the config
    it was declared in (§5.2.10).

    Neither pattern nor roles appear anywhere in the Java, so a reader who
    follows the anchor lands on a loop over values they cannot see. If the
    anchor also points at the wrong branch — a rule reading
    `hasAnyRole('ROLE_ADMIN')` citing a line that says `denyAll()` — the reader
    who checks is told the analysis is wrong. The value being right does not
    save it; a false citation is its own defect.
    """

    RULES: ClassVar[dict[str, list[dict[str, object]]]] = {
        "security.authorization-rules": [
            {"paths": ["/admin/open"], "method": "GET", "authorities": ["permitAll"]},
            {"paths": ["/admin/**"], "authorities": ["ROLE_ADMIN"]},
        ]
    }

    def _site(self, line: int, access: str) -> ExportSecurityRule:
        return ExportSecurityRule(
            call_id=line,
            pattern="@security",
            pattern_confidence=RulePatternConfidence.CONFIG,
            access=access,
            kind="filter-chain",
            chain_id="chain",
            anchor=ExportAnchor(file="src/SecurityConfig.java", line=line),
            evidence=access,
        )

    def _chain(self) -> list[ExportSecurityRule]:
        # One site per branch of the loop's if/else, exactly as the pass emits.
        return [
            self._site(87, "denyAll()"),
            self._site(89, "permitAll()"),
            self._site(91, "authenticated()"),
            self._site(97, "hasAnyRole(roles)"),
        ]

    def _evidence(self, uri: str, verb: HttpMethod) -> list[AuthEvidence]:
        from wadi_worker.auth_merge import (
            _rule_evidence,  # pyright: ignore[reportPrivateUsage]
        )

        return _rule_evidence(self._chain(), uri, verb, self.RULES, {})

    def test_a_role_rule_cites_the_role_branch(self) -> None:
        item = self._evidence("/admin/thing", HttpMethod.POST)[0]
        assert item.roles == ["ADMIN"]
        # NOT line 87 (denyAll) — a branch this rule never takes.
        assert item.anchor is not None
        assert item.anchor.start_line == 97

    def test_a_permit_rule_cites_the_permit_branch(self) -> None:
        item = self._evidence("/admin/open", HttpMethod.GET)[0]
        assert item.effect is AuthEffect.PERMIT_ALL
        assert item.anchor is not None
        assert item.anchor.start_line == 89

    def test_the_config_key_is_named_so_the_policy_can_be_read(self) -> None:
        item = self._evidence("/admin/thing", HttpMethod.POST)[0]
        assert "security.authorization-rules" in item.detail

    def test_one_binding_expands_once_not_once_per_branch(self) -> None:
        # Four sites bind the same prefix. Expanding each would replay the
        # whole policy four times and make the chain read as 4x its length.
        from wadi_worker.auth_merge import (
            _rule_evidence,  # pyright: ignore[reportPrivateUsage]
        )

        evidence = _rule_evidence(self._chain(), "/admin/thing", HttpMethod.POST, self.RULES, {})
        assert len(evidence) == 1
