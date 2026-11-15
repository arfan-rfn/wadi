"""Coverage-report builder tests: totals arithmetic and honest listings."""

from wadi_contracts import (
    AnalysisCoverage,
    AuthEffect,
    AuthEvidence,
    AuthEvidenceKind,
    AuthRelationship,
    AuthResolution,
    CfgAnomaly,
    CfgAnomalyCode,
    Confidence,
    Endpoint,
    EndpointAuth,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityGateFlagState,
    EntityOperation,
    HttpMethod,
    MethodRef,
    Provenance,
    Reachability,
    ServiceKind,
    SourceAnchor,
    StitchedEdge,
    TargetKind,
    UnresolvedCallEntry,
    placeholder_service_id,
)
from wadi_stitcher.coverage import (
    build_analysis_coverage,
    build_auth_coverage,
    build_cfg_anomalies,
    build_coverage_report,
    build_entity_coverage,
)
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
    """§5.4.2: a system whose only client is unmodelled must not read as a
    clean zero (the yas RestClient lesson; RestClient itself is modelled
    since T2, so okhttp/retrofit play the unmodelled role here)."""
    from wadi_stitcher.coverage import build_unmodelled_mechanisms

    snapshot = make_snapshot(make_system())
    a = make_service(snapshot, "services/a")
    b = make_service(snapshot, "services/b")
    a = a.model_copy(update={"client_libraries": ["okhttp", "resttemplate", "restclient"]})
    b = b.model_copy(update={"client_libraries": ["okhttp", "retrofit"]})

    entries = build_unmodelled_mechanisms([a, b])
    assert [(e.mechanism, len(e.service_ids)) for e in entries] == [
        ("okhttp", 2),
        ("retrofit", 1),
    ]
    # Modelled clients (resttemplate, restclient) never appear.
    assert all(e.mechanism not in ("resttemplate", "restclient") for e in entries)

    report = build_coverage_report(
        snapshot.id,
        remote_calls=[],
        edges=[],
        unresolved=[],
        phonebook_conflicts=[],
        placeholder_names={},
        unmodelled_mechanisms=entries,
    )
    assert [e.mechanism for e in report.unmodelled_mechanisms] == ["okhttp", "retrofit"]


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


def test_cfg_anomalies_rollup_and_unchecked_services() -> None:
    """§5.2.8 M2: per-code totals sum across services; a service whose
    boundary carries None was never checked and stays distinct from clean."""
    snapshot = make_snapshot(make_system())
    anchor = SourceAnchor(file="src/A.java", start_line=5, end_line=5)
    noisy = make_service(snapshot, "services/noisy").model_copy(
        update={
            "cfg_anomalies": [
                CfgAnomaly(code=CfgAnomalyCode.DISCONNECTED_NODE, count=3, sample_sites=[anchor]),
                CfgAnomaly(code=CfgAnomalyCode.BRANCH_ARITY, count=1),
            ]
        }
    )
    clean = make_service(snapshot, "services/clean").model_copy(update={"cfg_anomalies": []})
    failed = make_service(snapshot, "services/failed").model_copy(
        update={"extraction_error": "RuntimeError: parse failed"}
    )

    section = build_cfg_anomalies([noisy, clean, failed])
    assert section.total_by_code == {"branch-arity": 1, "disconnected-node": 3}
    by_name = {entry.name: entry for entry in section.services}
    assert by_name["clean"].checked
    assert by_name["clean"].anomalies == []
    assert not by_name["failed"].checked
    assert by_name["noisy"].checked
    assert {a.code for a in by_name["noisy"].anomalies} == {
        "branch-arity",
        "disconnected-node",
    }


def test_cfg_anomalies_excludes_libraries_and_travels_on_the_report() -> None:
    snapshot = make_snapshot(make_system())
    service = make_service(snapshot, "services/app").model_copy(update={"cfg_anomalies": []})
    library = make_service(snapshot, "libs/common").model_copy(update={"kind": ServiceKind.LIBRARY})
    section = build_cfg_anomalies([service, library])
    assert [entry.name for entry in section.services] == ["app"]
    report = build_coverage_report(
        snapshot.id,
        remote_calls=[],
        edges=[],
        unresolved=[],
        phonebook_conflicts=[],
        placeholder_names={},
        cfg_anomalies=section,
    )
    assert report.cfg_anomalies is not None
    assert report.cfg_anomalies.total_by_code == {}


class TestAuthCoverage:
    """§5.2.9 — auth blind spots stay counted on every snapshot, never prose."""

    @staticmethod
    def _endpoint(uri: str, auth: EndpointAuth) -> Endpoint:
        return Endpoint.create(
            snapshot_id="snap_a",
            service_id="svc_" + "a" * 16,
            http_method=HttpMethod.GET,
            full_uri=uri,
            handler=MethodRef(id="m_" + "0" * 16, signature=f"C.h{uri}:void()"),
            auth=auth,
        )

    def test_states_partition_and_unread_guards_are_counted_by_kind(self) -> None:
        protected = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail='/a -> hasRole("ADMIN")',
            effect=AuthEffect.REQUIRE_ROLES,
            roles=["ADMIN"],
        )
        permissive = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail="/b -> permitAll()",
            effect=AuthEffect.PERMIT_ALL,
        )
        unread = AuthEvidence(
            kind=AuthEvidenceKind.INTERCEPTOR,
            detail="AuthInterceptor",
            effect=AuthEffect.UNKNOWN,
            resolution=AuthResolution.OPAQUE,
            pattern="/c",
        )
        section = build_auth_coverage(
            [
                self._endpoint("/a", EndpointAuth(authenticated=True, evidence=[protected])),
                self._endpoint("/b", EndpointAuth(authenticated=False, evidence=[permissive])),
                self._endpoint("/c", EndpointAuth(authenticated=None, evidence=[unread])),
                self._endpoint("/d", EndpointAuth()),
            ]
        )
        assert section.endpoints == 4
        assert (section.authenticated, section.unauthenticated) == (1, 1)
        # withheld vs no_evidence stay apart: one is a wadi gap, the other a
        # possible hole in the system, and they call for opposite responses.
        assert (section.withheld, section.no_evidence) == (1, 1)
        assert section.unread_by_kind == {"interceptor": 1}

    def test_a_clean_snapshot_reports_no_blind_spots(self) -> None:
        section = build_auth_coverage([])
        assert section.unread_by_kind == {}
        assert section.endpoints == 0

    def test_relationship_scoped_endpoints_are_counted_apart_from_roles(self) -> None:
        # §5.2.12. A system whose policy is relational reports every endpoint
        # `authenticated` with an empty role list, and without this counter that
        # is indistinguishable from a role list nobody managed to read. On ICPC
        # it is 562 of 804 — the difference between "no roles required" and
        # "the requirement is not a role".
        relational = AuthEvidence(
            kind=AuthEvidenceKind.ASPECT,
            detail="ContestManagerAuthorizer via @ContestManager",
            effect=AuthEffect.REQUIRE_RELATIONSHIP,
            relationship=AuthRelationship(relation="contest-manager", resource_type="Contest"),
            pattern="/a",
        )
        section = build_auth_coverage(
            [
                self._endpoint(
                    "/a",
                    EndpointAuth(
                        authenticated=True,
                        evidence=[relational],
                        relationships=[
                            AuthRelationship(relation="contest-manager", resource_type="Contest")
                        ],
                    ),
                ),
                self._endpoint(
                    "/b",
                    EndpointAuth(
                        authenticated=True,
                        evidence=[relational],
                        relationships=[
                            AuthRelationship(relation="contest-manager"),
                            AuthRelationship(relation="site-manager"),
                        ],
                        composition_unresolved=True,
                    ),
                ),
                self._endpoint("/c", EndpointAuth(authenticated=True, evidence=[relational])),
            ]
        )
        assert section.relationship_scoped == 2
        # The counter that stops the relationship numbers being read as exact.
        assert section.composition_unresolved == 1
        assert "relationships" not in section.unexercised_vocabulary
        # `roles` never fired on this snapshot, and the report says so rather
        # than letting a zero read as a measured absence.
        assert "roles" in section.unexercised_vocabulary


def test_async_rooted_sites_are_split_out_of_the_unreachable_count() -> None:
    """§5.2.11 T2: startup traffic is excluded from stitching, not dead.

    Rolling both into one number is what made 430 real async roots on
    train-ticket-aitest read as unwired code.
    """
    snapshot = make_snapshot(make_system())
    caller = make_service(snapshot, "services/petstore")
    calls = [
        make_remote_call(snapshot, caller, url="http://a/1", line=1),
        make_remote_call(
            snapshot,
            caller,
            url="http://a/2",
            line=2,
            reachable=False,
            reachability=Reachability.ASYNC_ROOT,
        ),
        make_remote_call(
            snapshot,
            caller,
            url="http://a/3",
            line=3,
            reachable=False,
            reachability=Reachability.UNREACHED,
        ),
    ]
    report = build_coverage_report(
        snapshot.id,
        remote_calls=calls,
        edges=[],
        unresolved=[],
        phonebook_conflicts=(),
        placeholder_names={},
    )
    assert report.totals.unreachable_call_sites == 2
    assert report.totals.async_rooted_call_sites == 1
    assert report.totals.call_sites == 1


def test_a_zero_says_whether_it_was_measured_or_never_exercised() -> None:
    """§5.2.11 T6 — `denied: 0` is not evidence the denial path works.

    On train-ticket-aitest `authorities`, `denied` and `withheld` all read 0.
    Each is CORRECT — the corpus uses only hasAnyRole, has no denyAll route,
    and every idiom in it is readable — but a reader cannot tell that from a
    zero, and the role/authority split shipped in 0.6.0 is fixture-proven only.
    """
    snapshot = make_snapshot(make_system())
    service = make_service(snapshot, "services/petstore")
    # One plainly authenticated endpoint carrying a role and nothing else.
    endpoint = make_endpoint(
        snapshot,
        service,
        uri="/orders",
        auth=EndpointAuth(
            authenticated=True,
            roles=["ADMIN"],
            evidence=[
                AuthEvidence(
                    kind=AuthEvidenceKind.SECURITY_DSL,
                    detail="/orders -> hasRole('ADMIN')",
                    effect=AuthEffect.REQUIRE_ROLES,
                    resolution=AuthResolution.RESOLVED,
                    anchor=SourceAnchor(file="Sec.java", start_line=1, end_line=1),
                )
            ],
        ),
    )
    section = build_auth_coverage([endpoint], [service])

    assert section.authenticated == 1
    # roles WERE exercised, so their presence is real evidence...
    assert "roles" not in section.unexercised_vocabulary
    # ...while these zeros are evidence of nothing, and say so.
    assert "authorities" in section.unexercised_vocabulary
    assert "denied" in section.unexercised_vocabulary
    assert "withheld" in section.unexercised_vocabulary


def _accounting(
    *,
    in_no_endpoint_flow: int = 0,
    flush: int = 0,
    implemented_in_project: int = 0,
    entity_undetermined: int = 0,
    unknown_operation: int = 0,
    create_or_update: int = 0,
    bound: int = 0,
    accesses: dict[EntityOperation, int] | None = None,
    sites: dict[EntityAccessBasis, int] | None = None,
    enabled: frozenset[tuple[EntityAccessBasis, EntityOperation]] = frozenset(),
) -> EntityAccessAccounting:
    """One service's accounting, with every unnamed counter at zero.

    ``call_sites`` is the outcome partition's sum, and every site not named
    as outside an endpoint flow is inside one, so both validators hold by
    construction and each test names only the counters it is about.
    """
    call_sites = (
        flush
        + implemented_in_project
        + entity_undetermined
        + unknown_operation
        + create_or_update
        + bound
    )
    return EntityAccessAccounting(
        call_sites=call_sites,
        in_endpoint_flow=call_sites - in_no_endpoint_flow,
        in_no_endpoint_flow=in_no_endpoint_flow,
        flush=flush,
        implemented_in_project=implemented_in_project,
        entity_undetermined=entity_undetermined,
        unknown_operation=unknown_operation,
        create_or_update=create_or_update,
        bound=bound,
        accesses_by_operation={op.value: (accesses or {}).get(op, 0) for op in EntityOperation},
        sites_by_basis={basis.value: (sites or {}).get(basis, 0) for basis in EntityAccessBasis},
        rules_version="rules-1",
        gate_flags=[
            EntityGateFlagState(
                basis=basis,
                operation=op,
                enabled=(basis, op) in enabled,
                scored_rules_version="rules-1" if (basis, op) in enabled else None,
            )
            for basis in (EntityAccessBasis.ARGUMENT_ORIGIN, EntityAccessBasis.EXISTENCE_GUARD)
            for op in (EntityOperation.CREATE, EntityOperation.UPDATE)
        ],
    )


class TestEntityCoverage:
    """§5.2.17: the per-service repository-call accounting, summed per snapshot."""

    def test_counters_and_both_dicts_sum_across_services(self) -> None:
        snapshot = make_snapshot(make_system())
        orders = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    in_no_endpoint_flow=1,
                    flush=1,
                    entity_undetermined=1,
                    create_or_update=1,
                    bound=2,
                    accesses={EntityOperation.READ: 3, EntityOperation.CREATE_OR_UPDATE: 1},
                    sites={EntityAccessBasis.METHOD_NAME: 4, EntityAccessBasis.ARGUMENT_ORIGIN: 1},
                )
            }
        )
        # A gate flag on, so the per-service row can be seen to carry the
        # flag state the worker recorded rather than one the stitcher assumed (E3).
        pets = make_service(snapshot, "services/pets").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    implemented_in_project=1,
                    unknown_operation=1,
                    bound=1,
                    accesses={EntityOperation.CREATE: 1, EntityOperation.UNKNOWN: 2},
                    sites={EntityAccessBasis.METHOD_NAME: 2, EntityAccessBasis.QUERY_TEXT: 1},
                    enabled=frozenset(
                        {(EntityAccessBasis.ARGUMENT_ORIGIN, EntityOperation.CREATE)}
                    ),
                )
            }
        )

        section = build_entity_coverage([pets, orders])

        assert section is not None
        assert (section.services_reporting, section.services_predating) == (2, 0)
        assert section.call_sites == 8
        assert (section.in_endpoint_flow, section.in_no_endpoint_flow) == (7, 1)
        assert section.flush == 1
        assert section.implemented_in_project == 1
        assert section.entity_undetermined == 1
        assert section.unknown_operation == 1
        assert section.create_or_update == 1
        assert section.bound == 3
        assert section.accesses_by_operation == {
            "create": 1,
            "read": 3,
            "update": 0,
            "delete": 0,
            "create-or-update": 1,
            "unknown": 2,
        }
        assert section.sites_by_basis == {
            "method-name": 6,
            "query-text": 1,
            "argument-origin": 1,
            "existence-guard": 0,
        }
        # Sorted by name, whatever order the boundaries arrived in.
        assert [row.service_name for row in section.by_service] == ["orders", "pets"]
        assert [row.service_id for row in section.by_service] == [
            orders.service_id,
            pets.service_id,
        ]
        assert section.by_service[0].accounting == orders.entity_access_accounting
        assert section.by_service[1].accounting == pets.entity_access_accounting
        [enabled] = [flag for flag in section.by_service[1].accounting.gate_flags if flag.enabled]
        assert (enabled.basis, enabled.operation) == (
            EntityAccessBasis.ARGUMENT_ORIGIN,
            EntityOperation.CREATE,
        )

    def test_a_service_written_before_the_phase_is_counted_never_summed_as_zero(self) -> None:
        snapshot = make_snapshot(make_system())
        current = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=2,
                    accesses={EntityOperation.READ: 2},
                    sites={EntityAccessBasis.METHOD_NAME: 2},
                )
            }
        )
        predating = make_service(snapshot, "services/legacy")

        section = build_entity_coverage([current, predating])

        assert section is not None
        assert (section.services_reporting, section.services_predating) == (1, 1)
        # The sums are the reporting service's alone; the older boundary is a
        # count of its own, never a row of zeros a reader could take as measured.
        assert (section.call_sites, section.bound) == (2, 2)
        assert section.accesses_by_operation["read"] == 2
        assert [row.service_name for row in section.by_service] == ["orders"]

    def test_a_snapshot_from_before_the_phase_has_no_section(self) -> None:
        # Every snapshot stored before 0.9.0. A section of zeros would claim
        # the repository calls were counted and none were found.
        snapshot = make_snapshot(make_system())
        boundaries = [make_service(snapshot, "services/a"), make_service(snapshot, "services/b")]

        assert build_entity_coverage(boundaries) is None
        assert build_entity_coverage([]) is None

    def test_a_zero_count_names_its_vocabulary_value_as_unexercised(self) -> None:
        # §5.2.11 T6, E8: `delete: 0` on a corpus with no delete endpoint is
        # evidence of nothing, and the section says so instead of letting the
        # zero read as "deletes are measured and there are none".
        snapshot = make_snapshot(make_system())
        reads = make_service(snapshot, "services/reads").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=2,
                    accesses={EntityOperation.READ: 2},
                    sites={EntityAccessBasis.METHOD_NAME: 2},
                )
            }
        )
        # Exercised by one service only: the summed count decides, so these
        # stay off the list although `reads` has zero of each.
        writes = make_service(snapshot, "services/writes").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    create_or_update=1,
                    bound=1,
                    accesses={EntityOperation.CREATE_OR_UPDATE: 1, EntityOperation.UPDATE: 1},
                    sites={EntityAccessBasis.QUERY_TEXT: 1, EntityAccessBasis.ARGUMENT_ORIGIN: 1},
                )
            }
        )

        section = build_entity_coverage([reads, writes])

        assert section is not None
        assert section.unexercised_vocabulary == [
            "basis:existence-guard",
            "operation:create",
            "operation:delete",
            "operation:unknown",
        ]

    def test_the_unmeasured_cases_travel_on_every_section(self) -> None:
        # Q2, Q17, Q4: cascades, dirty-checking updates and other persistence
        # mechanisms are outside this phase, and the section says so even when
        # every repository call bound cleanly.
        snapshot = make_snapshot(make_system())
        service = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=1,
                    accesses={EntityOperation.READ: 1},
                    sites={EntityAccessBasis.METHOD_NAME: 1},
                )
            }
        )

        section = build_entity_coverage([service])

        assert section is not None
        assert [case.value for case in section.unmeasured] == [
            "cascaded-operations",
            "dirty-checking-updates",
            "other-persistence-mechanisms",
        ]

    def test_a_library_is_not_a_service_that_predates_the_phase(self) -> None:
        # A library boundary is written with no export of its own (§5.2.6), so
        # it never carries accounting. Counting it as predating would report
        # every fresh analysis of a system with a shared jar as partly stale.
        snapshot = make_snapshot(make_system())
        service = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=1,
                    accesses={EntityOperation.READ: 1},
                    sites={EntityAccessBasis.METHOD_NAME: 1},
                )
            }
        )
        library = make_service(snapshot, "libs/common").model_copy(
            update={"kind": ServiceKind.LIBRARY}
        )

        section = build_entity_coverage([service, library])

        assert section is not None
        assert (section.services_reporting, section.services_predating) == (1, 0)
        assert [row.service_name for row in section.by_service] == ["orders"]

    def test_the_section_travels_on_the_report(self) -> None:
        snapshot = make_snapshot(make_system())
        service = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=1,
                    accesses={EntityOperation.DELETE: 1},
                    sites={EntityAccessBasis.METHOD_NAME: 1},
                )
            }
        )
        section = build_entity_coverage([service])

        report = build_coverage_report(
            snapshot.id,
            remote_calls=[],
            edges=[],
            unresolved=[],
            phonebook_conflicts=[],
            placeholder_names={},
            entity_coverage=section,
        )

        assert report.entity_coverage is not None
        assert report.entity_coverage.accesses_by_operation["delete"] == 1

    def test_a_failed_extraction_counts_as_unmeasured_not_as_zero(self) -> None:
        # A service whose extraction failed has no accounting either. It joins
        # the predating count, where its `extraction_error` tells it apart.
        snapshot = make_snapshot(make_system())
        service = make_service(snapshot, "services/orders").model_copy(
            update={
                "entity_access_accounting": _accounting(
                    bound=1,
                    accesses={EntityOperation.READ: 1},
                    sites={EntityAccessBasis.METHOD_NAME: 1},
                )
            }
        )
        failed = make_service(snapshot, "services/failed").model_copy(
            update={"extraction_error": "RuntimeError: parse failed"}
        )

        section = build_entity_coverage([service, failed])

        assert section is not None
        assert (section.services_reporting, section.services_predating) == (1, 1)
        assert section.call_sites == 1
