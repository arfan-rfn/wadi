"""Auth-evidence merge tests (§5.2 step 5): three sources, honest claims."""

from wadi_contracts import AuthEvidenceKind, HttpMethod, SourceAnchor
from wadi_joern_client.export import ExportAnchor, ExportSecurityRule
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
    def test_conflicting_evidence_stays_unknown(self) -> None:
        # Annotation demands a role, the chain says permitAll — never pick (§12).
        auth = merge_endpoint_auth(
            full_uri="/stock/special",
            http_method=HttpMethod.GET,
            auth_tags=["auth=annotation:@PreAuthorize(\"hasRole('OPS')\")"],
            security_rules=CHAIN,
            handler_anchor=ANCHOR,
            config_env={},
        )
        assert auth.authenticated is None
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
