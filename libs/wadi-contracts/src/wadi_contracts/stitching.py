"""Stitched-edge and coverage-report contracts (§5.4).

The stitcher is the single writer of both artifact kinds (P4). A
:class:`StitchedEdge` is one per-call-site match result: every ``RemoteCall``
fact yields at least one edge — resolved calls land on one of three target
kinds (analyzed service / external API / placeholder service), and calls the
matcher cannot resolve become explicit ``UNDETERMINED`` edges, never silently
dropped (P10). Confidence and provenance are orthogonal annotations, never
blended (P7).

The :class:`CoverageReport` is snapshot-level and is surfaced *first* by every
consumer — the user always sees what the map knows it doesn't know before
trusting what it claims (§5.4.4).
"""

from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import ArtifactEnvelope, SnapshotEnvelope, WadiModel
from wadi_contracts.enums import Confidence, HttpMethod, Provenance, TargetKind
from wadi_contracts.ids import remote_edge_id
from wadi_contracts.source import SourceAnchor

_EXTERNAL_KEY_PREFIX = "external:"
_PLACEHOLDER_KEY_PREFIX = "placeholder:"
_UNDETERMINED_KEY = "undetermined"


def edge_target_key(
    *,
    target_kind: TargetKind,
    target_endpoint_id: str | None,
    target_service_id: str | None,
    external_host: str | None,
) -> str:
    """The identity component a stitched edge hashes for its id (§7)."""
    match target_kind:
        case TargetKind.ANALYZED:
            return target_endpoint_id or ""
        case TargetKind.EXTERNAL:
            return _EXTERNAL_KEY_PREFIX + (external_host or "")
        case TargetKind.PLACEHOLDER:
            return _PLACEHOLDER_KEY_PREFIX + (target_service_id or "")
        case TargetKind.UNDETERMINED:
            return _UNDETERMINED_KEY


class StitchedEdge(ArtifactEnvelope):
    """One resolved (or explicitly unresolved) cross-service call edge.

    The envelope ``service_id`` is the CALLER's service id — an edge belongs
    to the service whose call site it resolves. One ``RemoteCall`` fact can
    yield N edges (ambiguous resolution, multi-candidate URLs); each is its
    own row with its own content-derived id (§5.2 over-approximation).
    """

    id: str = Field(pattern=r"^re_[0-9a-f]{16}$")
    remote_call_id: str = Field(
        pattern=r"^rc_[0-9a-f]{16}$",
        description="The RemoteCall fact (and ICFG call node) this edge resolves",
    )
    mechanism: str = Field(min_length=1, description="Client mechanism, denormalized for reads")
    http_verb: HttpMethod | None = None
    url: str | None = Field(
        default=None,
        description="The candidate URL this edge resolved; None only when UNDETERMINED",
    )
    target_kind: TargetKind
    target_service_id: str | None = Field(
        default=None,
        description="svc_… (ANALYZED) or ph_… (PLACEHOLDER) — the resolved target service",
    )
    target_endpoint_id: str | None = Field(
        default=None, description="ep_… — set for ANALYZED targets only"
    )
    external_host: str | None = Field(
        default=None, description="Normalized host[:port] — set for EXTERNAL targets only"
    )
    confidence: Confidence = Field(
        description="Composed edge confidence: min(url recovery, resolution, path match)"
    )
    provenance: Provenance = Field(
        description="Where this claim came from — orthogonal to confidence, never blended (P7)"
    )
    evidence: str | None = Field(
        default=None, description="Human-readable resolution trail behind this edge"
    )

    @model_validator(mode="after")
    def _target_shape_is_honest(self) -> Self:
        match self.target_kind:
            case TargetKind.ANALYZED:
                if self.target_endpoint_id is None or self.target_service_id is None:
                    raise ValueError(
                        "ANALYZED edges require target_service_id and target_endpoint_id"
                    )
                if not self.target_service_id.startswith("svc_"):
                    raise ValueError("ANALYZED target_service_id must be a svc_ id")
                if self.external_host is not None:
                    raise ValueError("ANALYZED edges must not carry external_host")
                if self.confidence is Confidence.NONE:
                    raise ValueError("a matched edge cannot have confidence NONE")
            case TargetKind.PLACEHOLDER:
                if self.target_service_id is None or not self.target_service_id.startswith("ph_"):
                    raise ValueError("PLACEHOLDER edges require a ph_ target_service_id")
                if self.target_endpoint_id is not None or self.external_host is not None:
                    raise ValueError("PLACEHOLDER edges carry no endpoint or external host")
                if self.confidence is Confidence.NONE:
                    raise ValueError("a matched edge cannot have confidence NONE")
            case TargetKind.EXTERNAL:
                if not self.external_host:
                    raise ValueError("EXTERNAL edges require external_host")
                if self.target_service_id is not None or self.target_endpoint_id is not None:
                    raise ValueError("EXTERNAL edges carry no target service or endpoint")
                if self.confidence is Confidence.NONE:
                    raise ValueError("a matched edge cannot have confidence NONE")
            case TargetKind.UNDETERMINED:
                if (
                    self.target_service_id is not None
                    or self.target_endpoint_id is not None
                    or self.external_host is not None
                ):
                    raise ValueError("UNDETERMINED edges carry no target fields")
                if self.confidence is not Confidence.NONE:
                    raise ValueError("UNDETERMINED edges must have confidence NONE")
                if self.provenance not in (Provenance.MACHINE_PROVEN, Provenance.HEURISTIC):
                    raise ValueError("UNDETERMINED provenance must be machine-proven or heuristic")

        expected = remote_edge_id(
            self.remote_call_id,
            edge_target_key(
                target_kind=self.target_kind,
                target_endpoint_id=self.target_endpoint_id,
                target_service_id=self.target_service_id,
                external_host=self.external_host,
            ),
        )
        if self.id != expected:
            raise ValueError(f"edge id {self.id!r} does not match derived id {expected!r} (§7)")
        return self

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        service_id: str,
        remote_call_id: str,
        mechanism: str,
        target_kind: TargetKind,
        confidence: Confidence,
        provenance: Provenance,
        http_verb: HttpMethod | None = None,
        url: str | None = None,
        target_service_id: str | None = None,
        target_endpoint_id: str | None = None,
        external_host: str | None = None,
        evidence: str | None = None,
    ) -> "StitchedEdge":
        """Build an edge with its content-derived id computed (§7)."""
        derived = remote_edge_id(
            remote_call_id,
            edge_target_key(
                target_kind=target_kind,
                target_endpoint_id=target_endpoint_id,
                target_service_id=target_service_id,
                external_host=external_host,
            ),
        )
        return cls(
            id=derived,
            snapshot_id=snapshot_id,
            service_id=service_id,
            remote_call_id=remote_call_id,
            mechanism=mechanism,
            http_verb=http_verb,
            url=url,
            target_kind=target_kind,
            target_service_id=target_service_id,
            target_endpoint_id=target_endpoint_id,
            external_host=external_host,
            confidence=confidence,
            provenance=provenance,
            evidence=evidence,
        )


class PlaceholderEntry(WadiModel):
    """A config-resolved service name with no analyzed service behind it —
    honest partial coverage and a 'grant access to this repo' to-do item."""

    placeholder_id: str = Field(pattern=r"^ph_[0-9a-f]{16}$")
    name: str = Field(min_length=1, description="The config-resolved logical name")
    resolved_via: str = Field(
        min_length=1,
        description="'compose-service' | 'discovery-name' | 'gateway-route' | 'bare-hostname'",
    )
    call_count: int = Field(ge=1)
    caller_service_ids: list[str] = Field(min_length=1)


class ExternalApiEntry(WadiModel):
    """A real dependency on an address outside the analyzed system."""

    host: str = Field(min_length=1, description="Normalized host[:port]")
    call_count: int = Field(ge=1)
    caller_service_ids: list[str] = Field(min_length=1)


class UnresolvedCallEntry(WadiModel):
    """One call site the stitcher could not resolve, with the reason stated.

    ``reason_code`` is machine-readable so limitations are queryable, not just
    prose — e.g. counting how often Lombok-generated interiors block URL
    recovery is a coverage query, not an investigation.
    """

    remote_call_id: str = Field(pattern=r"^rc_[0-9a-f]{16}$")
    service_id: str
    site: SourceAnchor
    reason_code: str = Field(
        min_length=1,
        description=(
            "'url-undetermined' | 'url-unparseable' | 'host-unresolvable' | "
            "'no-endpoint-match' | 'lombok-generated-interior'"
        ),
    )
    reason: str = Field(min_length=1, description="Human-readable explanation")


class CoverageTotals(WadiModel):
    """Aggregate counts for a snapshot's stitched graph."""

    call_sites: int = Field(ge=0, description="Distinct remote-call facts considered")
    edges: int = Field(ge=0)
    analyzed: int = Field(ge=0)
    external: int = Field(ge=0)
    placeholder: int = Field(ge=0)
    undetermined: int = Field(ge=0)
    by_confidence: dict[str, int] = Field(
        default_factory=dict[str, int], description="Edge count per Confidence value"
    )


class CoverageReport(SnapshotEnvelope):
    """What the map knows it doesn't know (§5.4.4) — surfaced FIRST everywhere.

    Snapshot-level; the stitcher is this collection's single writer (P4).
    Hint fields are reserved now so the schema is hint-ready; hints themselves
    ship in Phase 4 (§11).
    """

    totals: CoverageTotals
    placeholders: list[PlaceholderEntry] = Field(default_factory=list[PlaceholderEntry])
    external_apis: list[ExternalApiEntry] = Field(default_factory=list[ExternalApiEntry])
    unresolved: list[UnresolvedCallEntry] = Field(default_factory=list[UnresolvedCallEntry])
    low_confidence_edge_ids: list[str] = Field(
        default_factory=list[str], description="Edges matched at HEURISTIC confidence"
    )
    phonebook_conflicts: list[str] = Field(
        default_factory=list[str],
        description="Config identities claimed by more than one source (never silently picked)",
    )
    applied_hint_ids: list[str] = Field(
        default_factory=list[str], description="Reserved — stitching hints land in Phase 4"
    )
    stale_hint_ids: list[str] = Field(
        default_factory=list[str], description="Reserved — stitching hints land in Phase 4"
    )
