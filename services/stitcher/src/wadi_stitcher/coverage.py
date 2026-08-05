"""Coverage-report assembly (§5.4) — what the map knows it doesn't know.

Every consumer surfaces this FIRST (P10). All aggregation is deterministic:
sorted inputs in, sorted listings out.
"""

from collections.abc import Sequence

from wadi_contracts import (
    MODELLED_CLIENT_LIBRARIES,
    AnalysisCoverageSection,
    AuthCoverageSection,
    CfgAnomalySection,
    Confidence,
    CoverageReport,
    CoverageTotals,
    Endpoint,
    EndpointCollision,
    ExternalApiEntry,
    PlaceholderEntry,
    QuarantinedFact,
    Reachability,
    RemoteCall,
    ServiceBoundary,
    ServiceCfgAnomalyEntry,
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


def build_cfg_anomalies(boundaries: Sequence[ServiceBoundary]) -> CfgAnomalySection:
    """§5.2.8 M2: per-service structural-invariant violations + rollup.

    A service whose boundary carries ``cfg_anomalies=None`` was never checked
    (extraction failed, pre-1.8 snapshot) and appears with ``checked=False``
    — unknown stays distinct from clean (P10).
    """
    entries: list[ServiceCfgAnomalyEntry] = []
    total_by_code: dict[str, int] = {}
    services = [b for b in boundaries if b.kind is ServiceKind.SERVICE]
    for boundary in sorted(services, key=lambda b: (b.name, b.service_id)):
        anomalies = boundary.cfg_anomalies
        entries.append(
            ServiceCfgAnomalyEntry(
                service_id=boundary.service_id,
                name=boundary.name,
                checked=anomalies is not None,
                anomalies=anomalies or [],
            )
        )
        for anomaly in anomalies or []:
            total_by_code[anomaly.code] = total_by_code.get(anomaly.code, 0) + anomaly.count
    return CfgAnomalySection(total_by_code=dict(sorted(total_by_code.items())), services=entries)


def build_quarantined_facts(boundaries: Sequence[ServiceBoundary]) -> list[QuarantinedFact]:
    """§7: roll up diagnostic facts whose vocabulary this build cannot read.

    Expected empty. Non-empty means a producer emitted vocabulary its registry
    does not carry — version drift between the pack, the contracts, and the
    stored artifact — never a property of the analyzed code. Identical values
    from one service fold into one entry so the count means occurrences, not
    rows. Libraries are included: a library boundary carries a census too, and
    unreadable vocabulary is a fact about wadi regardless of what emitted it.
    """
    folded: dict[tuple[str, str, str | None], QuarantinedFact] = {}
    for boundary in sorted(boundaries, key=lambda b: (b.name, b.service_id)):
        for fact in boundary.quarantined_facts:
            key = (fact.registry, fact.value, fact.service_id)
            if (existing := folded.get(key)) is None:
                folded[key] = fact
            else:
                folded[key] = existing.model_copy(update={"count": existing.count + fact.count})
    return [folded[key] for key in sorted(folded, key=lambda k: (k[0], k[1], k[2] or ""))]


def build_endpoint_collisions(
    boundaries: Sequence[ServiceBoundary],
) -> list[EndpointCollision]:
    """§7: endpoints that could not all be stored because their ids collided.

    Expected empty. Non-empty means the endpoint inventory — product goal 1 —
    is missing routes the analysis actually found, which no other counter in
    this report can express: the loss happens at the storage key, downstream
    of everything else here.
    """
    collisions: list[EndpointCollision] = []
    for boundary in sorted(boundaries, key=lambda b: (b.name, b.service_id)):
        collisions.extend(boundary.endpoint_collisions)
    return collisions


def build_auth_coverage(
    endpoints: Sequence[Endpoint], boundaries: Sequence[ServiceBoundary] = ()
) -> AuthCoverageSection:
    """Snapshot rollup of what the auth layer could and could not read (§5.2.9).

    The standing tracking mechanism for auth blind spots, playing the role
    `cfg_anomalies` plays for control flow: an idiom wadi cannot interpret is
    counted on EVERY snapshot rather than living in prose, so the next tranche
    is scheduled by measured demand. `withheld` and `no_evidence` are split
    because they call for opposite responses — one is a gap in wadi, the other
    a possible hole in the system.

    *Corrected 2026-08-05 (§5.2.10).* Every counter below except
    ``extraction_gaps`` is derived from evidence the auth layer EMITTED, which
    made this section blind to the one failure it was built to catch: a
    construct dropped before emission raises none of them and leaves its
    endpoint reading as cleanly authenticated. ``extraction_gaps`` carries the
    independent oracle's findings from the service boundaries, so a miss is
    countable rather than invisible.
    """
    unread_by_kind: dict[str, int] = {}
    authenticated = unauthenticated = withheld = no_evidence = 0
    for endpoint in endpoints:
        unread = endpoint.auth.unread_enforcement
        for item in unread:
            unread_by_kind[item.kind.value] = unread_by_kind.get(item.kind.value, 0) + 1
        if endpoint.auth.authenticated is True:
            authenticated += 1
        elif endpoint.auth.authenticated is False:
            unauthenticated += 1
        elif unread:
            withheld += 1
        else:
            no_evidence += 1
    extraction_gaps: dict[str, int] = {}
    for boundary in boundaries:
        for gap in boundary.auth_extraction_gaps or ():
            extraction_gaps[gap.code.value] = extraction_gaps.get(gap.code.value, 0) + gap.count
    return AuthCoverageSection(
        endpoints=len(endpoints),
        authenticated=authenticated,
        unauthenticated=unauthenticated,
        withheld=withheld,
        no_evidence=no_evidence,
        unread_by_kind=dict(sorted(unread_by_kind.items())),
        extraction_gaps=dict(sorted(extraction_gaps.items())),
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
    cfg_anomalies: CfgAnomalySection | None = None,
    auth_coverage: AuthCoverageSection | None = None,
    quarantined_facts: Sequence[QuarantinedFact] = (),
    endpoint_collisions: Sequence[EndpointCollision] = (),
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
    # §5.2.11 T2: of the excluded sites, the ones a startup/scheduled root DOES
    # reach. Counting them together with dead code made real production traffic
    # read as unwired.
    async_rooted_count = sum(
        1 for call in remote_calls if call.reachability is Reachability.ASYNC_ROOT
    )
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
            async_rooted_call_sites=async_rooted_count,
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
        cfg_anomalies=cfg_anomalies,
        auth_coverage=auth_coverage,
        quarantined_facts=list(quarantined_facts),
        endpoint_collisions=list(endpoint_collisions),
    )
