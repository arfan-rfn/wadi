"""Endpoint model tests: identity enforcement and honest auth."""

import pytest
from pydantic import ValidationError

from wadi_contracts.endpoint import (
    AuthEffect,
    AuthEvidence,
    AuthEvidenceKind,
    AuthMechanism,
    AuthMechanismKind,
    AuthResolution,
    Endpoint,
    EndpointAuth,
    EndpointParam,
    ParamLocation,
)
from wadi_contracts.enums import HttpMethod, TriggerKind
from wadi_contracts.ids import endpoint_id
from wadi_contracts.source import MethodRef


class TestEndpointCreate:
    def test_derives_id_and_simplified_uri(self, svc_id: str, handler_ref: MethodRef) -> None:
        ep = Endpoint.create(
            snapshot_id="snap_" + "0" * 16,
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{orderId}",
            handler=handler_ref,
        )
        assert ep.simplified_uri == "/orders/{?}"
        assert ep.id == endpoint_id(svc_id, "GET", "/orders/{orderId}")
        assert ep.trigger is TriggerKind.HTTP

    def test_same_logical_endpoint_same_id(self, svc_id: str, handler_ref: MethodRef) -> None:
        a = Endpoint.create(
            snapshot_id="snap_a",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{orderId}",
            handler=handler_ref,
        )
        b = Endpoint.create(
            snapshot_id="snap_b",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/orders/{id}",  # param renamed between snapshots
            handler=handler_ref,
        )
        assert a.id == b.id


class TestEndpointIdentityEnforcement:
    def test_rejects_wrong_id(self, svc_id: str, handler_ref: MethodRef) -> None:
        with pytest.raises(ValidationError, match="content-derived"):
            Endpoint(
                snapshot_id="snap",
                service_id=svc_id,
                id="ep_" + "0" * 16,
                http_method=HttpMethod.GET,
                full_uri="/orders",
                simplified_uri="/orders",
                handler=handler_ref,
            )

    def test_rejects_wrong_simplified_uri(self, svc_id: str, handler_ref: MethodRef) -> None:
        with pytest.raises(ValidationError, match="simplified_uri"):
            Endpoint(
                snapshot_id="snap",
                service_id=svc_id,
                id=endpoint_id(svc_id, "GET", "/orders/{id}"),
                http_method=HttpMethod.GET,
                full_uri="/orders/{id}",
                simplified_uri="/orders/{id}",  # not the {?} form
                handler=handler_ref,
            )


class TestEndpointAuth:
    def test_default_is_unknown(self) -> None:
        auth = EndpointAuth()
        assert auth.authenticated is None
        assert auth.roles == []

    def test_claim_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            EndpointAuth(authenticated=True)

    def test_claim_with_evidence(self) -> None:
        auth = EndpointAuth(
            authenticated=True,
            roles=["ADMIN"],
            mechanism="spring-security",
            evidence=[
                AuthEvidence(
                    kind=AuthEvidenceKind.ANNOTATION,
                    detail="@PreAuthorize(\"hasRole('ADMIN')\")",
                )
            ],
        )
        assert auth.roles == ["ADMIN"]

    def test_negative_claim_also_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            EndpointAuth(authenticated=False)


def _opaque(detail: str = "{?} -> permitAll()") -> AuthEvidence:
    """A guard that was detected but could not be read (§5.2.9)."""
    return AuthEvidence(
        kind=AuthEvidenceKind.SECURITY_DSL,
        detail=detail,
        effect=AuthEffect.PERMIT_ALL,
        resolution=AuthResolution.OPAQUE,
        pattern="{?}",
    )


def _resolved(role: str = "ADMIN") -> AuthEvidence:
    return AuthEvidence(
        kind=AuthEvidenceKind.SECURITY_DSL,
        detail=f'/x/** -> hasRole("{role}")',
        effect=AuthEffect.REQUIRE_ROLES,
        resolution=AuthResolution.RESOLVED,
        roles=[role],
        pattern="/x/**",
    )


class TestClaimWithholding:
    """The §5.2.9 rule, enforced by the contract rather than by convention.

    The defect this exists to prevent, measured on train-ticket: a rule whose
    pattern could not be read was dropped, so the endpoint fell through to a
    later ``permitAll()`` and published ``authenticated=False`` for a route
    that actually required ROLE_ADMIN/ROLE_USER.
    """

    def test_unread_guard_forbids_an_evidenced_open_claim(self) -> None:
        # The dangerous direction: "nothing guards this" is exactly what an
        # unread guard makes unsayable.
        with pytest.raises(ValidationError, match="detected but not read"):
            EndpointAuth(authenticated=False, evidence=[_opaque()])

    def test_unread_guard_does_not_forbid_a_protected_claim(self) -> None:
        # Enforcement is a conjunction, so an unread gate can only ADD a
        # requirement. Withholding here would throw away a sound answer: a
        # resolved rule already demands ADMIN, and nothing unread can undo it.
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved(), _opaque()])
        assert auth.authenticated is True

    def test_an_unread_bypass_forbids_even_a_protected_claim(self) -> None:
        # Bypasses are the one construct that REMOVES enforcement, so an
        # unreadable one could flip protected to open.
        bypass = AuthEvidence(
            kind=AuthEvidenceKind.CHAIN_BYPASS,
            detail="{?} bypasses the security chain",
            effect=AuthEffect.PERMIT_ALL,
            resolution=AuthResolution.OPAQUE,
            pattern="{?}",
        )
        with pytest.raises(ValidationError, match="detected but not read"):
            EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved(), bypass])

    def test_withheld_claim_keeps_the_reason_queryable(self) -> None:
        auth = EndpointAuth(authenticated=None, evidence=[_resolved(), _opaque()])
        assert [item.kind for item in auth.unread_enforcement] == [AuthEvidenceKind.SECURITY_DSL]

    def test_an_inactive_guard_does_not_gate_and_does_not_withhold(self) -> None:
        # @Secured under @EnableMethodSecurity(securedEnabled=false) is inert:
        # recorded so the reader sees it, but it enforces nothing.
        inert = AuthEvidence(
            kind=AuthEvidenceKind.ANNOTATION,
            detail='@Secured("ROLE_ADMIN")',
            resolution=AuthResolution.OPAQUE,
            active=False,
            inactive_reason="securedEnabled=false",
        )
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[inert, _resolved()])
        assert auth.unread_enforcement == []

    def test_fully_read_guards_permit_a_claim(self) -> None:
        auth = EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[_resolved()])
        assert auth.authenticated is True

    def test_partial_resolution_does_not_withhold(self) -> None:
        # hasAnyRole(ADMIN_CONST, "USER") — one role recovered, one not. The
        # claim (auth IS required) is sound; only the role list is incomplete.
        partial = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail='/x/** -> hasAnyRole(admin, "USER")',
            effect=AuthEffect.REQUIRE_ROLES,
            resolution=AuthResolution.PARTIAL,
            roles=["USER"],
            expression='hasAnyRole(admin, "USER")',
        )
        assert EndpointAuth(authenticated=True, roles=["USER"], evidence=[partial]).authenticated


class TestActiveFlagged:
    def test_inactive_requires_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="inactive_reason"):
            AuthEvidence(kind=AuthEvidenceKind.ANNOTATION, detail="@Secured", active=False)

    def test_reason_without_inactive_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="inactive_reason"):
            AuthMechanism(
                kind=AuthMechanismKind.HTTP_BASIC, detail="httpBasic()", inactive_reason="huh"
            )

    def test_disabled_mechanism_is_recorded_not_dropped(self) -> None:
        # train-ticket does httpBasic().disable() on 39 services — reporting it
        # as an active mechanism would be a fabricated fact.
        mechanism = AuthMechanism(
            kind=AuthMechanismKind.HTTP_BASIC,
            detail="httpBasic()",
            active=False,
            inactive_reason="disabled in chain",
        )
        assert mechanism.active is False


class TestBackwardCompatibility:
    def test_pre_enforcement_artifact_parses_and_keeps_its_claim(self) -> None:
        # Stored artifacts predate effect/resolution; defaults must preserve
        # what they were written with rather than invalidate them.
        auth = EndpointAuth.model_validate(
            {
                "authenticated": True,
                "roles": ["ADMIN"],
                "mechanism": "spring-security",
                "evidence": [{"kind": "security-dsl", "detail": '/a/** -> hasRole("ADMIN")'}],
            }
        )
        assert auth.authenticated is True
        assert auth.evidence[0].effect is AuthEffect.UNKNOWN
        assert auth.evidence[0].resolution is AuthResolution.RESOLVED
        assert auth.mechanisms == []


class TestEndpointParams:
    def test_params(self, svc_id: str, handler_ref: MethodRef) -> None:
        ep = Endpoint.create(
            snapshot_id="snap",
            service_id=svc_id,
            http_method=HttpMethod.POST,
            full_uri="/orders",
            handler=handler_ref,
            params=[
                EndpointParam(name="body", location=ParamLocation.BODY, type_name="OrderRequest"),
                EndpointParam(
                    name="dryRun", location=ParamLocation.QUERY, type_name="boolean", required=False
                ),
            ],
        )
        assert {p.location for p in ep.params} == {ParamLocation.BODY, ParamLocation.QUERY}
