"""Coverage-report builder tests: totals arithmetic and honest listings."""

from wadi_contracts import (
    AnalysisCoverage,
    Confidence,
    Provenance,
    ServiceKind,
    SourceAnchor,
    StitchedEdge,
    TargetKind,
    UnresolvedCallEntry,
    placeholder_service_id,
)
from wadi_stitcher.coverage import build_analysis_coverage, build_coverage_report
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)


def test_totals_listings_and_low_confidence() -> None:
    snapshot = make_snapshot(make_system())
    caller = make_service(snapshot, "services/petstore")
    callee = make_service(snapshot, "services/inventory")
    target = make_endpoint(snapshot, callee, uri="/stock/{id}")

    analyzed_call = make_remote_call(snapshot, caller, line=10)
    heuristic_call = make_remote_call(snapshot, caller, line=11, url="http://billing/x")
    external_call = make_remote_call(
        snapshot, caller, line=12, url="https://api.stripe.com/v1/charges"
    )
    undetermined_call = make_remote_call(snapshot, caller, line=13, url=None)

    ph = placeholder_service_id("billing")
    edges = [
        make_analyzed_edge(analyzed_call, target),
        StitchedEdge.create(
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_id=heuristic_call.id,
            mechanism="resttemplate",
            url=heuristic_call.url,
            target_kind=TargetKind.PLACEHOLDER,
            target_service_id=ph,
            confidence=Confidence.HEURISTIC,
            provenance=Provenance.HEURISTIC,
        ),
        StitchedEdge.create(
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_id=external_call.id,
            mechanism="resttemplate",
            url=external_call.url,
            target_kind=TargetKind.EXTERNAL,
            external_host="api.stripe.com",
            confidence=Confidence.EXACT,
            provenance=Provenance.MACHINE_PROVEN,
        ),
        StitchedEdge.create(
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_id=undetermined_call.id,
            mechanism="resttemplate",
            target_kind=TargetKind.UNDETERMINED,
            confidence=Confidence.NONE,
            provenance=Provenance.MACHINE_PROVEN,
        ),
    ]
    unresolved = [
        UnresolvedCallEntry(
            remote_call_id=undetermined_call.id,
            service_id=caller.service_id,
            site=SourceAnchor(file="src/A.java", start_line=13, end_line=13),
            reason_code="url-undetermined",
            reason="target is runtime-only (P10)",
        )
    ]
    calls = [analyzed_call, heuristic_call, external_call, undetermined_call]

    report = build_coverage_report(
        snapshot.id,
        remote_calls=calls,
        edges=edges,
        unresolved=unresolved,
        phonebook_conflicts=("identity 'x' shadowed",),
        placeholder_names={ph: ("billing", "bare-hostname")},
    )

    assert report.totals.call_sites == 4
    assert report.totals.edges == 4
    assert report.totals.analyzed == 1
    assert report.totals.external == 1
    assert report.totals.placeholder == 1
    assert report.totals.undetermined == 1
    assert report.totals.by_confidence == {"exact": 2, "heuristic": 1, "none": 1}

    [placeholder] = report.placeholders
    assert placeholder.name == "billing"
    assert placeholder.resolved_via == "bare-hostname"
    assert placeholder.call_count == 1
    assert placeholder.caller_service_ids == [caller.service_id]

    [external] = report.external_apis
    assert external.host == "api.stripe.com"

    assert report.low_confidence_edge_ids == [edges[1].id]  # HEURISTIC matched edge only
    assert report.unresolved == unresolved
    assert report.phonebook_conflicts == ["identity 'x' shadowed"]
    assert report.applied_hint_ids == []


def test_empty_snapshot_reports_zero() -> None:
    snapshot = make_snapshot(make_system())
    report = build_coverage_report(
        snapshot.id,
        remote_calls=[],
        edges=[],
        unresolved=[],
        phonebook_conflicts=(),
        placeholder_names={},
    )
    assert report.totals.call_sites == 0
    assert report.totals.edges == 0
    assert report.placeholders == []
    assert report.external_apis == []
    assert report.unresolved == []


def test_inventory_facts_are_counted_not_stitched() -> None:
    """T1 (§5.2.5): unreachable/suspected call facts appear in totals only."""
    snapshot = make_snapshot(make_system())
    caller = make_service(snapshot, "services/petstore")
    callee = make_service(snapshot, "services/inventory")
    target = make_endpoint(snapshot, callee, uri="/stock/{id}")

    stitched = make_remote_call(snapshot, caller, line=10)
    unreachable = make_remote_call(snapshot, caller, line=20, reachable=False)
    suspected = make_remote_call(snapshot, caller, line=30, suspected=True, mechanism="unknown")

    report = build_coverage_report(
        snapshot.id,
        remote_calls=[stitched, unreachable, suspected],
        edges=[make_analyzed_edge(stitched, target)],
        unresolved=[],
        phonebook_conflicts=[],
        placeholder_names={},
    )
    assert report.totals.call_sites == 1
    assert report.totals.unreachable_call_sites == 1
    assert report.totals.suspected_call_sites == 1
    assert report.totals.analyzed == 1


def test_unmodelled_mechanisms_surface_in_coverage() -> None:
    """§5.4.2: RestClient-only systems must not read as a clean zero (yas)."""
    from wadi_stitcher.coverage import build_unmodelled_mechanisms

    snapshot = make_snapshot(make_system())
    a = make_service(snapshot, "services/a")
    b = make_service(snapshot, "services/b")
    a = a.model_copy(update={"client_libraries": ["restclient", "resttemplate"]})
    b = b.model_copy(update={"client_libraries": ["restclient", "okhttp"]})

    entries = build_unmodelled_mechanisms([a, b])
    assert [(e.mechanism, len(e.service_ids)) for e in entries] == [
        ("okhttp", 1),
        ("restclient", 2),
    ]
    # Modelled clients (resttemplate) never appear.
    assert all(e.mechanism != "resttemplate" for e in entries)

    report = build_coverage_report(
        snapshot.id,
        remote_calls=[],
        edges=[],
        unresolved=[],
        phonebook_conflicts=[],
        placeholder_names={},
        unmodelled_mechanisms=entries,
    )
    assert [e.mechanism for e in report.unmodelled_mechanisms] == ["okhttp", "restclient"]


# --- analysis coverage (§5.4.3) ----------------------------------------------------


def test_analysis_coverage_rollup_and_percentages() -> None:
    snapshot = make_snapshot(make_system())
    petstore = make_service(snapshot, "services/petstore").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=24, reachable_methods=19)}
    )
    inventory = make_service(snapshot, "services/inventory").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=7, reachable_methods=6)}
    )

    section = build_analysis_coverage([petstore, inventory])
    # Sorted by name: inventory before petstore.
    rows = [
        (e.name, e.production_methods, e.reachable_methods, e.coverage_percent)
        for e in section.services
    ]
    assert rows == [("inventory", 7, 6, 85.7), ("petstore", 24, 19, 79.2)]
    assert section.production_methods == 31
    assert section.reachable_methods == 25
    assert section.coverage_percent == 80.6


def test_analysis_coverage_unknown_stays_visible_not_zero() -> None:
    """A service without the fact (extraction failed / pre-metric snapshot)
    appears with None counts — unknown is never rendered as 0% (P10)."""
    snapshot = make_snapshot(make_system())
    healthy = make_service(snapshot, "services/healthy").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=10, reachable_methods=5)}
    )
    failed = make_service(snapshot, "services/failed").model_copy(
        update={"extraction_error": "RuntimeError: parse failed"}
    )

    section = build_analysis_coverage([healthy, failed])
    failed_entry = next(e for e in section.services if e.name == "failed")
    assert failed_entry.production_methods is None
    assert failed_entry.reachable_methods is None
    assert failed_entry.coverage_percent is None
    # Rollup sums only known counts; the unknown stays in the listing.
    assert section.production_methods == 10
    assert section.reachable_methods == 5
    assert section.coverage_percent == 50.0


def test_analysis_coverage_zero_production_has_no_percent() -> None:
    """0/0 is not 0% — a service with no production methods has no ratio."""
    snapshot = make_snapshot(make_system())
    empty = make_service(snapshot, "services/empty").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=0, reachable_methods=0)}
    )

    section = build_analysis_coverage([empty])
    assert section.services[0].coverage_percent is None
    # Counts are known (zeros), so the rollup includes them; the percent stays None.
    assert section.production_methods == 0
    assert section.coverage_percent is None


def test_analysis_coverage_excludes_libraries() -> None:
    """Libraries are not analysis units (§5.2.6) — no entry, no rollup share."""
    snapshot = make_snapshot(make_system())
    service = make_service(snapshot, "services/app").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=4, reachable_methods=4)}
    )
    library = make_service(snapshot, "libs/common").model_copy(update={"kind": ServiceKind.LIBRARY})

    section = build_analysis_coverage([service, library])
    assert [e.name for e in section.services] == ["app"]
    assert section.production_methods == 4
    assert section.coverage_percent == 100.0


def test_analysis_coverage_empty_snapshot() -> None:
    section = build_analysis_coverage([])
    assert section.services == []
    assert section.production_methods == 0
    assert section.reachable_methods == 0
    assert section.coverage_percent is None


def test_analysis_coverage_travels_on_the_report() -> None:
    snapshot = make_snapshot(make_system())
    service = make_service(snapshot, "services/app").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=3, reachable_methods=2)}
    )
    section = build_analysis_coverage([service])
    report = build_coverage_report(
        snapshot.id,
        remote_calls=[],
        edges=[],
        unresolved=[],
        phonebook_conflicts=[],
        placeholder_names={},
        analysis_coverage=section,
    )
    assert report.analysis_coverage is not None
    assert report.analysis_coverage.coverage_percent == 66.7
