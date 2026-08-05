"""Cross-language golden for the auth enforcement model (§5.2.9).

Consumes the REAL sbt-produced `spring-auth-matrix` export and assembles it
into contract artifacts, proving the whole chain end to end: the Scala packs
read a SecurityConfig, the export carries what they found *and what they could
not read*, and the worker turns that into a claim or an honest refusal to make
one.

The unit tests in `test_auth_merge.py` pin the merge logic against synthetic
rules; this pins it against what Joern actually produces from Java source,
which is where the original nine defects lived.
"""

import json
from pathlib import Path

import pytest

from wadi_contracts import AuthEvidenceKind, AuthResolution, Endpoint
from wadi_joern_client.export import RulePatternConfidence, ServiceExport
from wadi_worker.appconfig import parse_app_config
from wadi_worker.assembler import Assembler

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "joern-platform"
EXPORT = FIXTURE_ROOT / "target" / "spring-auth-matrix-export" / "export.json"

pytestmark = pytest.mark.skipif(
    not EXPORT.exists(),
    reason="spring-auth-matrix export not present — run `sbt test` in joern-platform first",
)


@pytest.fixture(scope="module")
def endpoints() -> dict[tuple[str, str], Endpoint]:
    export = ServiceExport.model_validate(json.loads(EXPORT.read_text()))
    config = parse_app_config(FIXTURE_ROOT / "fixtures" / "spring-auth-matrix")
    assembled = Assembler(
        snapshot_id="snap_authmatrix",
        service_id="svc_" + "a" * 16,
        config_env=config.env,
        config_structured=config.structured,
    ).assemble(export)
    # Keyed by (verb, uri): the fixture puts POST and PUT on the same path
    # on purpose, and collapsing them would silently test only one.
    return {
        (endpoint.http_method.value, endpoint.full_uri): endpoint
        for endpoint in assembled.endpoints
    }


class TestClaimsSurviveTheBoundary:
    def test_a_verb_scoped_rule_with_a_constant_pattern_produces_its_claim(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        """The train-ticket defect, end to end.

        `.antMatchers(HttpMethod.POST, orders).hasAnyRole(admin, "USER")` used
        to lose its verb to the chain's first `HttpMethod`, lose its pattern to
        the literal-only reader, and lose `admin` to the quoted-only role
        reader — leaving the endpoint to fall through to a later `permitAll()`
        and publish as "no authentication (evidenced)".
        """
        auth = endpoints[("POST", "/api/v1/orders")].auth
        assert auth.authenticated is True
        assert auth.roles == ["ADMIN", "USER"]

    def test_an_authority_rule_survives_as_an_authority(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        # `hasAuthority("ORDER_DELETE")` requires the authority ORDER_DELETE —
        # NOT the role ORDER_DELETE, which Spring would spell ROLE_ORDER_DELETE.
        # Reporting it under `roles` names a grant the rule never asks for.
        auth = endpoints[("DELETE", "/api/v1/orders/{orderId}")].auth
        assert auth.authenticated is True
        assert auth.authorities == ["ORDER_DELETE"]
        assert auth.roles == []

    def test_deny_all_is_carried_across_the_boundary(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        auth = endpoints[("GET", "/api/v1/orders/legacy")].auth
        assert auth.denied is True
        assert auth.authenticated is True


class TestHonestRefusals:
    def test_an_unreadable_rule_followed_by_permit_all_withholds(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        # `antMatchers(reportsPattern()).hasRole("AUDITOR")` may or may not
        # govern this path; what it falls through to is `/api/v1/orders/**
        # permitAll`. Genuinely uncertain between protected and open, so no
        # claim — the exact shape that used to publish a wrong `false`.
        auth = endpoints[("GET", "/api/v1/orders/{orderId}")].auth
        assert auth.authenticated is None
        assert auth.unread_enforcement, "a withheld claim must say what it could not read"

    def test_an_unreadable_rule_followed_by_authenticated_still_claims(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        # Same unreadable rule, but everything it could fall through to also
        # requires auth — protected either way, so withholding here would
        # throw away an answer that was never in doubt.
        auth = endpoints[("GET", "/internal/health")].auth
        assert auth.authenticated is True

    def test_an_inline_handler_guard_withholds_a_permissive_answer(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        # The chain's permitAll sweep covers /api/v1/orders/**. Without
        # detecting the in-handler check this endpoint reads as evidenced-open.
        auth = endpoints[("GET", "/api/v1/orders/export")].auth
        assert auth.authenticated is None
        assert AuthEvidenceKind.IN_HANDLER in {item.kind for item in auth.unread_enforcement}


class TestAnnotationsAndMechanisms:
    def test_an_annotation_with_unknown_enablement_is_marked_unread(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        # @IsAdmin resolves to @PreAuthorize("hasRole('ADMIN')"), but this
        # fixture never writes @EnableMethodSecurity — so whether it is
        # enforced at all is unknown, and neither believing nor dismissing it
        # would be honest.
        auth = endpoints[("GET", "/api/v1/audit/config")].auth
        annotation = next(i for i in auth.evidence if i.kind is AuthEvidenceKind.ANNOTATION)
        assert "hasRole('ADMIN')" in annotation.detail
        assert annotation.resolution is AuthResolution.OPAQUE
        # The claim still stands: the chain's `anyRequest().authenticated()`
        # requires auth regardless of whether the annotation is enforced, and
        # an unread guard can only ADD restriction. What stays uncertain is the
        # role list, not whether auth is needed.
        assert auth.authenticated is True
        assert auth.roles == []

    def test_mechanisms_reach_every_endpoint_of_the_service(
        self, endpoints: dict[tuple[str, str], Endpoint]
    ) -> None:
        auth = endpoints[("POST", "/api/v1/orders")].auth
        by_kind = {mechanism.kind.value: mechanism for mechanism in auth.mechanisms}
        # Promoted by the `Bearer` literal inside the filter, never its name.
        assert by_kind["jwt-bearer"].active is True
        # httpBasic().disable() — recorded, and never claimed as in effect.
        assert by_kind["http-basic"].active is False
        assert by_kind["http-basic"].inactive_reason == "disabled in chain"


class TestConfigDefinedPolicy:
    """§5.2.9 D5 — the yas shape, proven against a real CPG + real YAML."""

    def test_roles_declared_only_in_yaml_reach_the_endpoint(self) -> None:
        # There is no endpoint under /config-driven in this fixture (the chain
        # exists to prove extraction, not routing), so assert on the rules the
        # worker recovered rather than on a claim.
        from wadi_worker.auth_merge import (
            _expand_config_rules,  # pyright: ignore[reportPrivateUsage]
        )

        export = ServiceExport.model_validate(json.loads(EXPORT.read_text()))
        config = parse_app_config(FIXTURE_ROOT / "fixtures" / "spring-auth-matrix")
        bound = next(
            rule
            for rule in export.security_rules
            if rule.pattern_confidence is RulePatternConfidence.CONFIG
        )
        recovered = _expand_config_rules(bound, config.structured)
        assert recovered is not None, "the bound prefix must correlate to the parsed YAML"
        by_pattern = {rule.pattern: rule.access for rule in recovered}
        assert by_pattern["/config-driven/admin/**"].startswith("hasAnyRole")
        assert "ADMIN" in by_pattern["/config-driven/admin/**"]
        assert by_pattern["/config-driven/public/**"] == "permitAll()"
