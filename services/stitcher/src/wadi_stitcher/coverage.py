"""Coverage-report assembly (§5.4) — what the map knows it doesn't know.

Every consumer surfaces this FIRST (P10). All aggregation is deterministic:
sorted inputs in, sorted listings out.
"""

from collections.abc import Sequence

from wadi_contracts import (
    MODELLED_CLIENT_LIBRARIES,
    AnalysisCoverageSection,
    Confidence,
    CoverageReport,
    CoverageTotals,
    ExternalApiEntry,
    PlaceholderEntry,
    RemoteCall,
    ServiceBoundary,
    ServiceCoverageEntry,
    ServiceKind,
    StitchedEdge,
    TargetKind,
    UnmodelledMechanismEntry,
    UnresolvedCallEntry,
)


def build_unmodelled_mechanisms(
    boundaries: Sequence[ServiceBoundary],
) -> list[UnmodelledMechanismEntry]:
    """§5.4.2 census: client libraries present but outside the modelled set —
    the yas lesson (a zero-edge system must be distinguishable from a correct
    zero-edge answer).
    """
    by_mechanism: dict[str, list[str]] = {}
    for boundary in boundaries:
        for library in boundary.client_libraries:
            if library not in MODELLED_CLIENT_LIBRARIES:
                by_mechanism.setdefault(library, []).append(boundary.service_id)
    return [
        UnmodelledMechanismEntry(mechanism=mechanism, service_ids=sorted(service_ids))
        for mechanism, service_ids in sorted(by_mechanism.items())
    ]


def _percent(reachable: int, production: int) -> float | None:
    """None when the denominator is 0 — a service with no production methods
    has no meaningful ratio (and 0/0 rendered as 0% would read as a finding)."""
    if production == 0:
        return None
    return round(100.0 * reachable / production, 1)


def build_analysis_coverage(boundaries: Sequence[ServiceBoundary]) -> AnalysisCoverageSection:
    """§5.4.3: per-service production-vs-reachable method counts + rollup.

    Libraries are excluded entirely (not analysis units, §5.2.6). A service
    without the fact (extraction failed, pre-metric snapshot) appears with
    None counts — unknown stays visible, never becomes zero (P10). Rollup
    sums cover only services with known counts.
    """
    entries: list[ServiceCoverageEntry] = []
    services = [b for b in boundaries if b.kind is ServiceKind.SERVICE]
    for boundary in sorted(services, key=lambda b: (b.name, b.service_id)):
        coverage = boundary.analysis_coverage
        if coverage is None:
            entries.append(ServiceCoverageEntry(service_id=boundary.service_id, name=boundary.name))
        else:
            entries.append(
                ServiceCoverageEntry(
                    service_id=boundary.service_id,
                    name=boundary.name,
                    production_methods=coverage.production_methods,
                    reachable_methods=coverage.reachable_methods,
                    coverage_percent=_percent(
                        coverage.reachable_methods, coverage.production_methods
                    ),
                )
            )
    known = [e for e in entries if e.production_methods is not None]
    production_total = sum(e.production_methods or 0 for e in known)
    reachable_total = sum(e.reachable_methods or 0 for e in known)
    return AnalysisCoverageSection(
        production_methods=production_total,
        reachable_methods=reachable_total,
        coverage_percent=_percent(reachable_total, production_total) if known else None,
        services=entries,
    )


def build_coverage_report(
    snapshot_id: str,
    *,
    remote_calls: Sequence[RemoteCall],
    edges: Sequence[StitchedEdge],
    unresolved: Sequence[UnresolvedCallEntry],
    phonebook_conflicts: Sequence[str],
    placeholder_names: dict[str, tuple[str, str]],
    unmodelled_mechanisms: Sequence[UnmodelledMechanismEntry] = (),
    analysis_coverage: AnalysisCoverageSection | None = None,
) -> CoverageReport:
    by_kind: dict[TargetKind, list[StitchedEdge]] = {kind: [] for kind in TargetKind}
    by_confidence: dict[str, int] = {}
    for edge in edges:
        by_kind[edge.target_kind].append(edge)
        by_confidence[edge.confidence.value] = by_confidence.get(edge.confidence.value, 0) + 1

    placeholders: list[PlaceholderEntry] = []
    placeholder_edges: dict[str, list[StitchedEdge]] = {}
    for edge in by_kind[TargetKind.PLACEHOLDER]:
        assert edge.target_service_id is not None
        placeholder_edges.setdefault(edge.target_service_id, []).append(edge)
    for placeholder_id in sorted(placeholder_edges):
        group = placeholder_edges[placeholder_id]
        name, resolved_via = placeholder_names.get(placeholder_id, ("<unknown>", "unknown"))
        placeholders.append(
            PlaceholderEntry(
                placeholder_id=placeholder_id,
                name=name,
                resolved_via=resolved_via,
                call_count=len(group),
                caller_service_ids=sorted({e.service_id for e in group}),
            )
        )

    external_edges: dict[str, list[StitchedEdge]] = {}
    for edge in by_kind[TargetKind.EXTERNAL]:
        assert edge.external_host is not None
        external_edges.setdefault(edge.external_host, []).append(edge)
    external_apis = [
        ExternalApiEntry(
            host=host,
            call_count=len(group),
            caller_service_ids=sorted({e.service_id for e in group}),
        )
        for host, group in sorted(external_edges.items())
    ]

    low_confidence = sorted(
        edge.id
        for edge in edges
        if edge.confidence is Confidence.HEURISTIC
        and edge.target_kind is not TargetKind.UNDETERMINED
    )

    # Inventory facts (§5.2.5): excluded from matching by design, counted so
    # the exclusion is queryable. `call_sites` stays the stitchable population.
    unreachable_count = sum(1 for call in remote_calls if not call.reachable)
    suspected_count = sum(1 for call in remote_calls if call.reachable and call.suspected)
    stitchable_count = sum(1 for call in remote_calls if call.reachable and not call.suspected)

    return CoverageReport(
        snapshot_id=snapshot_id,
        totals=CoverageTotals(
            call_sites=stitchable_count,
            edges=len(edges),
            analyzed=len(by_kind[TargetKind.ANALYZED]),
            external=len(by_kind[TargetKind.EXTERNAL]),
            placeholder=len(by_kind[TargetKind.PLACEHOLDER]),
            undetermined=len(by_kind[TargetKind.UNDETERMINED]),
            unreachable_call_sites=unreachable_count,
            suspected_call_sites=suspected_count,
            by_confidence=dict(sorted(by_confidence.items())),
        ),
        placeholders=placeholders,
        external_apis=external_apis,
        unresolved=sorted(unresolved, key=lambda u: (u.service_id, u.remote_call_id)),
        low_confidence_edge_ids=low_confidence,
        phonebook_conflicts=list(phonebook_conflicts),
        unmodelled_mechanisms=list(unmodelled_mechanisms),
        analysis_coverage=analysis_coverage,
    )
