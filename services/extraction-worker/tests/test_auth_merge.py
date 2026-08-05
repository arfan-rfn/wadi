"""Auth-evidence merge tests (§5.2 step 5): three sources, honest claims."""

from typing import ClassVar

from wadi_contracts import (
    AuthEffect,
    AuthEvidenceKind,
    EndpointAuth,
    HttpMethod,
    SourceAnchor,
)
from wadi_joern_client.export import (
    UNRESOLVABLE_PATTERN,
    ExportAnchor,
    ExportAuthEnforcement,
    ExportAuthMechanism,
    ExportMethodSecurity,
    ExportSecurityRule,
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
