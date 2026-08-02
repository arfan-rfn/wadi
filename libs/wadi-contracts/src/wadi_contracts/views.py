"""API view models: read-time enrichments over stored artifacts.

Views are DERIVED — never written to storage (the stored artifact stays pure,
§7). They live in the contracts package because every consumer of the API
(CLI, frontend via generated types, third parties via published schemas)
shares one definition.
"""

from pydantic import Field

from wadi_contracts.base import WadiModel
from wadi_contracts.boundary import ServiceBoundary
from wadi_contracts.enums import Confidence, HttpMethod, Provenance, TargetKind


class ServiceSummary(ServiceBoundary):
    """A service boundary plus counts aggregated at read time."""

    endpoint_count: int = Field(default=0, ge=0)


class RemoteEdgeItem(WadiModel):
    """One stitched edge enriched for display (read-time join over the graph)."""

    edge_id: str
    remote_call_id: str
    caller_service_id: str
    caller_service_name: str | None = None
    mechanism: str
    http_verb: HttpMethod | None = None
    url: str | None = None
    target_kind: TargetKind
    target_service_id: str | None = None
    target_service_name: str | None = None
    target_endpoint_id: str | None = None
    target_http_method: HttpMethod | None = None
    target_simplified_uri: str | None = None
    external_host: str | None = None
    confidence: Confidence
    provenance: Provenance
    evidence: str | None = None


class RemoteEdgesView(WadiModel):
    """Who a service calls and who calls it (§8 ``remote_edges``)."""

    service_id: str
    outbound: list[RemoteEdgeItem] = Field(default_factory=list[RemoteEdgeItem])
    inbound: list[RemoteEdgeItem] = Field(default_factory=list[RemoteEdgeItem])
