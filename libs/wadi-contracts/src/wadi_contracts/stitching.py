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
trusting what it claims (§5.4).
"""

from typing import Self

from pydantic import Field, field_validator, model_validator

from wadi_contracts.base import ArtifactEnvelope, SnapshotEnvelope, WadiModel
from wadi_contracts.boundary import CfgAnomaly, EndpointCollision, QuarantinedFact
from wadi_contracts.enums import (
    Confidence,
    HttpMethod,
    Provenance,
    TargetKind,
    UnresolvedReasonCode,
)
from wadi_contracts.ids import remote_edge_id
from wadi_contracts.source import SourceAnchor
from wadi_contracts.version import SCHEMA_VERSION

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


UNRESOLVED_REASON_CODES: frozenset[str] = frozenset(code.value for code in UnresolvedReasonCode)
"""Value view of :class:`UnresolvedReasonCode`, derived so the two cannot drift.

The enum is the vocabulary (§7, recorded 2026-08-05); the
``unsupported-idiom:<name>`` prefix family is dynamic and validated
separately by :class:`UnresolvedCallEntry`."""

UNSUPPORTED_IDIOM_PREFIX = "unsupported-idiom:"
"""Prefix family of reason codes: dynamic slugs name the unmodelled idiom."""


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
        description="One of wadi_contracts.stitching.UNRESOLVED_REASON_CODES",
    )
    reason: str = Field(min_length=1, description="Human-readable explanation")

    @field_validator("reason_code")
    @classmethod
    def _registered_reason_code(cls, value: str) -> str:
        is_idiom = value.startswith(UNSUPPORTED_IDIOM_PREFIX) and len(value) > len(
            UNSUPPORTED_IDIOM_PREFIX
        )
        if value not in UNRESOLVED_REASON_CODES and not is_idiom:
            raise ValueError(
                f"unregistered reason_code {value!r}; the vocabulary is "
                f"UNRESOLVED_REASON_CODES plus the {UNSUPPORTED_IDIOM_PREFIX}<name> "
                f"family (schema {SCHEMA_VERSION})"
            )
        return value


class CoverageTotals(WadiModel):
    """Aggregate counts for a snapshot's stitched graph."""

    call_sites: int = Field(ge=0, description="Distinct remote-call facts considered")
    edges: int = Field(ge=0)
    analyzed: int = Field(ge=0)
    external: int = Field(ge=0)
    placeholder: int = Field(ge=0)
    undetermined: int = Field(ge=0)
    unreachable_call_sites: int = Field(
        ge=0,
        default=0,
        description=(
            "Sink call sites outside the endpoint-reachable closure — excluded "
            "from the map by design, inventoried so the exclusion is queryable "
            "(§5.2.5; detail rows live in remote_calls with reachable=false)"
        ),
    )
    suspected_call_sites: int = Field(
        ge=0,
        default=0,
        description=(
            "HTTP-shaped calls on receivers the CPG could not type-resolve — "
            "never matched, never blended into resolved results (P7); detail "
            "rows live in remote_calls with suspected=true"
        ),
    )
    by_confidence: dict[str, int] = Field(
        default_factory=dict[str, int], description="Edge count per Confidence value"
    )


class UnmodelledMechanismEntry(WadiModel):
    """A client library the census detected but no sink pass models (§5.4.2).

    The yas lesson: a system whose calls all use an unmodelled client produced
    a clean-looking zero-edge coverage report. This entry is the truthful
    sentence — "present, unmodelled" — never a call count (imports are not
    calls, P10).
    """

    mechanism: str = Field(
        min_length=1, description="KNOWN_CLIENT_LIBRARIES value outside the modelled set"
    )
    service_ids: list[str] = Field(min_length=1, description="Services whose census detected it")


class ServiceCoverageEntry(WadiModel):
    """Analysis coverage of one service (§5.4.3).

    ``None`` counts mean the fact is unavailable for this service (extraction
    failed, or the snapshot predates the metric) — unknown is reported as
    unknown, never as zero (P10).
    """

    service_id: str = Field(min_length=1)
    name: str = Field(min_length=1, description="Service display name, denormalized for reads")
    production_methods: int | None = Field(default=None, ge=0)
    reachable_methods: int | None = Field(default=None, ge=0)
    coverage_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="reachable/production * 100, 1dp; None when unknown or 0 methods",
    )

    @model_validator(mode="after")
    def _counts_travel_together(self) -> Self:
        if (self.production_methods is None) != (self.reachable_methods is None):
            raise ValueError("production_methods and reachable_methods must both be set or unset")
        if self.production_methods is None and self.coverage_percent is not None:
            raise ValueError("coverage_percent requires counts (unknown is never a percentage)")
        return self


class AnalysisCoverageSection(WadiModel):
    """Snapshot rollup of per-service analysis coverage (§5.4.3).

    Rollup sums cover only services whose counts are known; the per-service
    listing is where unknowns stay visible. Low coverage is a *finding*
    (dead code and/or unreached roots — T4's scope), not an error.
    """

    production_methods: int = Field(ge=0, description="Sum over services with known counts")
    reachable_methods: int = Field(ge=0)
    coverage_percent: float | None = Field(
        default=None, ge=0.0, le=100.0, description="None when no service has known counts"
    )
    services: list[ServiceCoverageEntry] = Field(
        default_factory=list[ServiceCoverageEntry],
        description="One entry per analyzed service (libraries excluded, §5.2.6), sorted by name",
    )


class ServiceCfgAnomalyEntry(WadiModel):
    """§5.2.8 M2: one service's structural-invariant violations.

    Services that were never checked (extraction failed, pre-1.8 snapshot)
    carry ``checked=False`` with no anomalies — unknown is never conflated
    with clean (P10).
    """

    service_id: str = Field(min_length=1)
    name: str = Field(min_length=1, description="Service display name, denormalized for reads")
    checked: bool = Field(description="False = invariants never ran for this service")
    anomalies: list[CfgAnomaly] = Field(
        default_factory=list[CfgAnomaly],
        description="Per-code counts with sample sites; empty when checked and clean",
    )

    @model_validator(mode="after")
    def _unchecked_carries_no_anomalies(self) -> Self:
        if not self.checked and self.anomalies:
            raise ValueError("an unchecked service cannot report anomalies")
        return self


class CfgAnomalySection(WadiModel):
    """Snapshot rollup of ICFG structural-invariant violations (§5.2.8 M2).

    Every snapshot is a continuous CFG test: a violation is a queryable fact
    about how far the graph can be trusted for that code, never an error.
    """

    total_by_code: dict[str, int] = Field(
        default_factory=dict,
        description="Snapshot-wide counts per anomaly code (CFG_ANOMALY_CODES)",
    )
    services: list[ServiceCfgAnomalyEntry] = Field(
        default_factory=list[ServiceCfgAnomalyEntry],
        description="One entry per analyzed service (libraries excluded), sorted by name",
    )


class AuthCoverageSection(WadiModel):
    """Snapshot rollup of what the auth layer could and could not read (§5.2.9).

    The standing tracking mechanism for auth blind spots, playing the role
    ``cfg_anomalies`` plays for control flow: an idiom wadi cannot interpret
    stays counted here rather than living in prose, so the next tranche is
    scheduled by measured demand rather than intuition.
    """

    endpoints: int = Field(default=0, ge=0)
    authenticated: int = Field(default=0, ge=0)
    unauthenticated: int = Field(default=0, ge=0)
    withheld: int = Field(
        default=0, ge=0, description="No claim because an in-scope guard could not be read"
    )
    no_evidence: int = Field(
        default=0, ge=0, description="No claim because nothing that could gate was found"
    )
    unread_by_kind: dict[str, int] = Field(
        default_factory=dict,
        description="Enforcement points detected but not readable, counted per AuthEvidenceKind",
    )
    extraction_gaps: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "§5.2.10: independent-oracle findings per AuthGapCode. Every other "
            "counter here is derived from evidence the auth layer EMITTED, so "
            "a construct dropped before emission is invisible to them — this "
            "is the one that can see a miss"
        ),
    )


class CoverageReport(SnapshotEnvelope):
    """What the map knows it doesn't know (§5.4) — surfaced FIRST everywhere.

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
    unmodelled_mechanisms: list[UnmodelledMechanismEntry] = Field(
        default_factory=list[UnmodelledMechanismEntry],
        description=(
            "Client libraries present but not modelled by any sink pass "
            "(§5.4.2 census) — a zero-edge system is distinguishable from a "
            "correct zero-edge answer"
        ),
    )
    analysis_coverage: AnalysisCoverageSection | None = Field(
        default=None,
        description=(
            "How much of the source the analysis walked (§5.4.3, schema "
            "1.5.0). None only on reports written before the metric existed"
        ),
    )
    cfg_anomalies: CfgAnomalySection | None = Field(
        default=None,
        description=(
            "ICFG structural-invariant violations (§5.2.8 M2, schema 1.8.0). "
            "None only on reports written before the invariants existed"
        ),
    )
    auth_coverage: AuthCoverageSection | None = Field(
        default=None,
        description=(
            "What the auth layer could and could not read (§5.2.9, schema 1.13.0). "
            "None only on reports written before the enforcement model existed"
        ),
    )
    endpoint_collisions: list[EndpointCollision] = Field(
        default_factory=list[EndpointCollision],
        description=(
            "Endpoints that derived the same content-derived id and so could "
            "not all be stored (§7, schema 1.18.0), rolled up across services. "
            "**Expected empty**: non-empty means the inventory is missing "
            "endpoints the analysis actually found — the loss happens at the "
            "storage key, downstream of every other counter here"
        ),
    )
    quarantined_facts: list[QuarantinedFact] = Field(
        default_factory=list[QuarantinedFact],
        description=(
            "Diagnostic facts whose vocabulary this build does not recognize "
            "(§7, schema 1.16.0), rolled up across services. **Expected empty**: "
            "non-empty means version drift between a producer and its registry, "
            "never a property of the analyzed code. CI fails on non-empty for "
            "the fixtures and benchmarks; a user's run only loses the footnote"
        ),
    )
    applied_hint_ids: list[str] = Field(
        default_factory=list[str], description="Reserved — stitching hints land in Phase 4"
    )
    stale_hint_ids: list[str] = Field(
        default_factory=list[str], description="Reserved — stitching hints land in Phase 4"
    )
