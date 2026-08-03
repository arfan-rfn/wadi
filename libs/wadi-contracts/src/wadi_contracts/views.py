"""API view models: read-time enrichments over stored artifacts.

Views are DERIVED — never written to storage (the stored artifact stays pure,
§7). They live in the contracts package because every consumer of the API
(CLI, frontend via generated types, third parties via published schemas)
shares one definition.
"""

from pydantic import Field

from wadi_contracts.base import WadiModel
from wadi_contracts.boundary import ServiceBoundary
from wadi_contracts.enums import Confidence, HttpMethod, Provenance, SourceVariant, TargetKind


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


class SourceView(WadiModel):
    """Source-on-demand response (§5.3): the exact analyzed text at the pinned
    SHA — the delombok'd variant when preprocessing rewrote the file, flagged
    so consumers can say so.

    1.9.0 (§11 Phase 2.7): ``total_lines`` (whole-file length, so clients can
    render "showing 1-2000 of 4200" and fetch the next window) and
    ``truncated`` (the served window hit the server's line cap — an honest
    partial, never a silent one)."""

    file: str
    start_line: int
    end_line: int
    variant: SourceVariant
    content: str
    total_lines: int | None = Field(
        default=None,
        ge=0,
        description="Total lines in the file at the pinned SHA; None = pre-1.9 response",
    )
    truncated: bool = Field(
        default=False,
        description="True when the requested window exceeded the server cap and was cut",
    )
