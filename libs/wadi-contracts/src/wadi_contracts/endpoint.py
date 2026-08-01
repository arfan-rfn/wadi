"""Endpoint — the per-route artifact with structured auth (§7, goal 9)."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import HttpMethod, TriggerKind
from wadi_contracts.ids import endpoint_id, simplify_uri
from wadi_contracts.source import MethodRef, SourceAnchor


class ParamLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    BODY = "body"
    HEADER = "header"


class EndpointParam(WadiModel):
    name: str = Field(min_length=1)
    location: ParamLocation
    type_name: str | None = None
    required: bool = True


class AuthEvidenceKind(StrEnum):
    ANNOTATION = "annotation"
    SECURITY_DSL = "security-dsl"
    CONFIG = "config"


class AuthEvidence(WadiModel):
    """One piece of evidence behind an auth claim — every claim carries its source (§5.2)."""

    kind: AuthEvidenceKind
    detail: str = Field(min_length=1, description="e.g. '@PreAuthorize(\"hasRole('ADMIN')\")'")
    anchor: SourceAnchor | None = None


class EndpointAuth(WadiModel):
    """Structured authorization state of an endpoint.

    ``authenticated`` is tri-state (P10): True/False are *claims backed by
    evidence*; None means honestly unknown — never defaulted to False.
    """

    authenticated: bool | None = None
    roles: list[str] = Field(default_factory=list[str])
    mechanism: str | None = Field(
        default=None, description="e.g. 'spring-security'; None when no framework was detected"
    )
    evidence: list[AuthEvidence] = Field(default_factory=list[AuthEvidence])

    @model_validator(mode="after")
    def _claims_need_evidence(self) -> Self:
        if self.authenticated is not None and not self.evidence:
            raise ValueError(
                "an authenticated=True/False claim requires at least one piece of evidence; "
                "use authenticated=None for unknown (P10)"
            )
        return self


class Endpoint(ArtifactEnvelope):
    """One REST endpoint of one service within a snapshot."""

    id: str = Field(pattern=r"^ep_[0-9a-f]{16}$")
    http_method: HttpMethod
    full_uri: str = Field(min_length=1, description="Route as written, e.g. /orders/{orderId}")
    simplified_uri: str = Field(min_length=1, description="Identity form, e.g. /orders/{?}")
    params: list[EndpointParam] = Field(default_factory=list[EndpointParam])
    response_type: str | None = None
    auth: EndpointAuth = Field(default_factory=EndpointAuth)
    handler: MethodRef
    trigger: TriggerKind = TriggerKind.HTTP

    @model_validator(mode="after")
    def _enforce_identity(self) -> Self:
        expected_uri = simplify_uri(self.full_uri)
        if self.simplified_uri != expected_uri:
            raise ValueError(
                f"simplified_uri {self.simplified_uri!r} does not match "
                f"simplify_uri(full_uri) = {expected_uri!r}"
            )
        expected_id = endpoint_id(self.service_id, self.http_method.value, self.full_uri)
        if self.id != expected_id:
            raise ValueError(
                f"endpoint id {self.id!r} is not the content-derived id {expected_id!r} "
                "(identity-stability rule, §7)"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        service_id: str,
        http_method: HttpMethod,
        full_uri: str,
        handler: MethodRef,
        params: list[EndpointParam] | None = None,
        response_type: str | None = None,
        auth: EndpointAuth | None = None,
        trigger: TriggerKind = TriggerKind.HTTP,
    ) -> "Endpoint":
        """Construct an endpoint with its derived id and simplified URI computed."""
        return cls(
            snapshot_id=snapshot_id,
            service_id=service_id,
            id=endpoint_id(service_id, http_method.value, full_uri),
            http_method=http_method,
            full_uri=full_uri,
            simplified_uri=simplify_uri(full_uri),
            params=params or [],
            response_type=response_type,
            auth=auth or EndpointAuth(),
            handler=handler,
            trigger=trigger,
        )
