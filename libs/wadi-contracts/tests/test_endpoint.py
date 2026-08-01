"""Endpoint model tests: identity enforcement and honest auth."""

import pytest
from pydantic import ValidationError

from wadi_contracts.endpoint import (
    AuthEvidence,
    AuthEvidenceKind,
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
