"""API view models: read-time enrichments over stored artifacts.

Views are DERIVED — never written to storage (the stored artifact stays pure,
§7). They live in the contracts package because every consumer of the API
(CLI, frontend via generated types, third parties via published schemas)
shares one definition.
"""

from pydantic import Field

from wadi_contracts.base import WadiModel
from wadi_contracts.boundary import ServiceBoundary
from wadi_contracts.endpoint import Endpoint
from wadi_contracts.enums import (
    CalleeUnboundReason,
    Confidence,
    HttpMethod,
    Provenance,
    ServiceKind,
    SourceVariant,
    TargetKind,
)


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


class SystemGraphService(WadiModel):
    """One service node on the system map (§11 Phase 2.7 M4)."""

    service_id: str
    name: str
    kind: ServiceKind
    endpoint_count: int = Field(ge=0)
    async_root_count: int = Field(ge=0)
    gateway: bool = Field(
        description="Has gateway routes or a discovery locator (drawn distinctly)"
    )
    extraction_error: str | None = Field(
        default=None,
        description="Extraction failed — the node renders as a stated-cause hole (P10)",
    )
    cfg_anomaly_count: int | None = Field(
        default=None,
        ge=0,
        description="Total §5.2.8 anomalies; None = never checked (never conflated with 0)",
    )


class SystemGraphView(WadiModel):
    """The whole snapshot's service graph in one read (§11 Phase 2.7 M4).

    ``stitched=False`` means the stitcher has not run: services render,
    and the empty edge list is 'not yet', never 'none' (P10).
    """

    snapshot_id: str
    stitched: bool
    services: list[SystemGraphService] = Field(default_factory=list[SystemGraphService])
    edges: list[RemoteEdgeItem] = Field(default_factory=list[RemoteEdgeItem])


class EndpointTouchedFile(WadiModel):
    """One file the endpoint's flow touches (derived from ICFG anchors)."""

    file: str = Field(min_length=1, description="Path relative to the service build root")
    variant: SourceVariant
    node_count: int = Field(ge=1, description="ICFG nodes anchored in this file")


class UnopenableCallCount(WadiModel):
    """Call sites sharing one reason for having no interior (§5.4.2 T5).

    Deliberately a count per reason rather than a bare total: "12 calls you
    cannot open" reads as damage, while "10 Lombok accessors, 2 JDK methods"
    reads as what it is — code that was never the system's to show.
    """

    reason: CalleeUnboundReason
    call_count: int = Field(ge=1, description="Call sites in this endpoint's flow with this reason")


class EndpointDetailView(WadiModel):
    """Everything the endpoint workspace needs in one read (§11 Phase 2.8).

    1.11.0 (additive): replaces the client-side compose of endpoint +
    service-wide remote edges. The ICFG stays its own fetch (it is large) and
    source stays on demand (§5.3) — ``touched_files`` carries names, never
    content. ``stitched=False`` means the stitcher has not run: the empty
    ``outbound`` is 'not yet', never 'none'; ``icfg_available=False`` states
    that no flow graph exists for this endpoint (P10).
    """

    snapshot_id: str
    system_id: str
    service_id: str
    service_name: str
    endpoint: Endpoint
    icfg_available: bool
    stitched: bool
    outbound: list[RemoteEdgeItem] = Field(default_factory=list[RemoteEdgeItem])
    touched_files: list[EndpointTouchedFile] = Field(default_factory=list[EndpointTouchedFile])
    unopenable_calls: list[UnopenableCallCount] = Field(
        default_factory=list[UnopenableCallCount],
        description=(
            "1.12.0 (§5.4.2 T5): how many call sites in this endpoint's flow "
            "have no interior to open, by reason. This is the endpoint-level "
            "honesty surface — `analysis_coverage` sizes reachability system-"
            "wide and the coverage report's unresolved counts cover only "
            "cross-service edges, so intra-service unopenable calls were "
            "counted NOWHERE per endpoint. Empty means every call in the flow "
            "opens, or the ICFG predates 1.12.0."
        ),
    )


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
