"""MCP entity facts (§5.2.17): `endpoint_detail`, `endpoint_icfg`, `entity_usage`.

An agent reads these instead of the code, so each tool has to say which of
three things an empty answer is: analyzed and nothing found, not looked at
because the snapshot predates the phase, or nothing local because the
endpoint forwards the work to another service (Q26, C5). "Analyzed and nothing
found" also says when the flow stopped at calls wadi could not open, behind
which a repository call may sit (pre-landing review #5). Documents are built
with the contract models; a pre-phase endpoint is a raw document with no
`entity_access` key, which is what one is.
"""

from typing import Any

import pytest
from mcp_support import make_accounting, make_data_model, make_site, make_two_method_icfg

from wadi_contracts import (
    CalleeUnboundReason,
    CoverageReport,
    CoverageTotals,
    Endpoint,
    EntityAccessSite,
    EntityOperation,
    Icfg,
    MethodRef,
    ServiceBoundary,
    ServiceKind,
    Snapshot,
    summarize_entity_access,
)
from wadi_mcp.service import MAY_HIDE_PROJECT_CODE, NotFoundError, WadiMcpService
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    GraphStore,
    SnapshotRepository,
    StitchRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_storage.codec import to_doc
from wadi_storage.mongo import ENDPOINTS
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_icfg,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration

_ORDER = "com.acme.Order"
_C, _U, _CU = EntityOperation.CREATE, EntityOperation.UPDATE, EntityOperation.CREATE_OR_UPDATE


def _offline_service(database: WadiDatabase) -> WadiMcpService:
    """A graph that connects lazily to nothing: these reads never need Neo4j."""
    store = GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused")
    return WadiMcpService(database, GraphRepository(store))


async def _snapshot(database: WadiDatabase) -> tuple[Snapshot, ServiceBoundary]:
    system = make_system("entity-shop")
    snapshot = make_snapshot(system)
    boundary = make_service(snapshot)
    await SystemRepository(database).insert(system)
    await SnapshotRepository(database).insert(snapshot)
    await ArtifactRepository(database).write_service_boundaries([boundary])
    return snapshot, boundary


async def _write_predating(database: WadiDatabase, endpoint: Endpoint) -> None:
    """Store an endpoint the way a pre-phase worker did: no `entity_access` key."""
    document = to_doc(endpoint)
    del document["entity_access"]
    await database.collection(ENDPOINTS).insert_one(document)


class TestEndpointDetailEntityFacts:
    async def test_an_analyzed_endpoint_says_so_and_carries_its_summary(
        self, database: WadiDatabase
    ) -> None:
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(
            update={
                "entity_access": summarize_entity_access([make_site(EntityOperation.READ)]),
            }
        )
        await ArtifactRepository(database).write_endpoints([endpoint])

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        assert detail["entity_facts"] == "analyzed"
        assert "entity_facts_note" not in detail
        assert detail["entity_access"] == [
            {
                "entity": _ORDER,
                "data_model_id": None,
                "operations": ["read"],
                "call_sites": 1,
                "call_sites_by_operation": {"read": 1},
            }
        ]
        # Pre-stitch: 'not yet', and Neo4j is never asked (P10).
        assert detail["stitched"] is False
        assert detail["outbound"] == []

    async def test_an_endpoint_predating_entity_facts_tells_the_agent_to_reanalyze(
        self, database: WadiDatabase
    ) -> None:
        """R1-6: `null` must not read as "this endpoint touches no data"."""
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary)
        await _write_predating(database, endpoint)

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        assert detail["entity_access"] is None
        assert detail["entity_facts"] == "predates-phase"
        note: str = detail["entity_facts_note"]
        assert "re-analyze" in note.lower()
        assert "\n" not in note

    async def test_a_forwarding_endpoint_shows_where_its_work_goes(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        """Q26, C5: no repository call here, and the outbound edges say why."""
        snapshot, caller = await _snapshot(database)
        callee = make_service(snapshot, "services/billing")
        target = make_endpoint(snapshot, callee, uri="/invoices/{id}")
        forwarder = make_endpoint(snapshot, caller).model_copy(update={"entity_access": []})
        call = make_remote_call(
            snapshot,
            caller,
            url="http://billing/invoices/{id}",
            file="src/OrderService.java",
            line=25,
        )
        edge = make_analyzed_edge(call, target)
        artifacts = ArtifactRepository(database)
        await artifacts.write_service_boundaries([callee])
        await artifacts.write_endpoints([forwarder, target])
        # The marker as the current worker writes it, list and legacy field
        # both; the support graph carries only the legacy one.
        icfg = make_two_method_icfg(snapshot, caller, forwarder)
        icfg = icfg.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"remote_call_ids": [call.id]})
                    if node.remote_call_id == call.id
                    else node
                    for node in icfg.nodes
                ]
            }
        )
        await artifacts.write_icfg(icfg)
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[forwarder, target],
            remote_calls=[call],
            edges=[edge],
        )
        await StitchRepository(database).write_coverage_report(
            CoverageReport(
                snapshot_id=snapshot.id,
                totals=CoverageTotals(
                    call_sites=1, edges=1, analyzed=1, external=0, placeholder=0, undetermined=0
                ),
            )
        )

        service = WadiMcpService(database, graph_repository)
        detail = await service.endpoint_detail(snapshot.id, forwarder.id)
        assert detail["entity_access"] == []
        assert detail["entity_facts"] == "analyzed"
        assert detail["stitched"] is True
        outbound: list[dict[str, Any]] = detail["outbound"]
        assert [item["remote_call_id"] for item in outbound] == [call.id]
        assert outbound[0]["target_endpoint_id"] == target.id
        assert outbound[0]["target_service_id"] == callee.service_id


def _icfg_stopping_at(
    snapshot: Snapshot, boundary: ServiceBoundary, endpoint: Endpoint, reasons: list[str]
) -> Icfg:
    """A flow whose statements are calls with these unbound reasons, in order."""
    icfg = make_icfg(snapshot, boundary, endpoint, statement_count=max(len(reasons), 1))
    callee = MethodRef(id="m_" + "e" * 16, signature="com.acme.RouteService.load()")
    by_node = {f"s{index}": reason for index, reason in enumerate(reasons)}
    return icfg.model_copy(
        update={
            "nodes": [
                node.model_copy(
                    update={
                        "callee": callee,
                        "callee_unbound_reason": CalleeUnboundReason(by_node[node.id]),
                    }
                )
                if node.id in by_node
                else node
                for node in icfg.nodes
            ]
        }
    )


def _refuse_whole_graphs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any read that assembles an ICFG: `endpoint_detail` needs two marks
    of the flow, read by projection, never the flow (review #6, §5.2.15)."""

    async def refuse(self: ArtifactRepository, snapshot_id: str, endpoint_id: str) -> Icfg | None:
        raise AssertionError(f"endpoint_detail assembled the ICFG of {endpoint_id}")

    monkeypatch.setattr(ArtifactRepository, "get_icfg", refuse)


class TestEndpointDetailSaysWhereAnEmptyFlowStopped:
    """`[]` covers only the flow wadi could open (§5.2.17, pre-landing review #5).

    The tool used to answer `analyzed` and nothing else, and its docstring
    told agents that an empty summary beside outbound calls means the
    endpoint forwards its work. When the flow stops at project calls wadi
    could not open, a repository call may sit behind one of them, and the
    agent cannot open the code to find out, so the answer has to say it.
    """

    async def test_an_empty_summary_names_the_calls_its_flow_stops_at(
        self, database: WadiDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(update={"entity_access": []})
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([endpoint])
        await artifacts.write_icfg(
            _icfg_stopping_at(
                snapshot,
                boundary,
                endpoint,
                [
                    "declared-not-bound",
                    "declared-not-bound",
                    "unresolved-receiver",
                    # Neither can hide a repository call: not counted.
                    "lombok-generated",
                    "third-party",
                ],
            )
        )
        _refuse_whole_graphs(monkeypatch)

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        assert detail["entity_access"] == []
        assert detail["entity_facts"] == "analyzed"
        note: str = detail["entity_facts_note"]
        assert "flow stops at 3 calls wadi could not open" in note
        assert "2 declared-not-bound, 1 unresolved-receiver" in note
        assert "may sit behind one of them" in note
        assert "lombok" not in note
        assert "\n" not in note

    async def test_endpoint_icfg_says_the_same_at_both_levels(self, database: WadiDatabase) -> None:
        """Two tools, one endpoint, one answer: the graph it already loaded
        gives the same note the projection gives `endpoint_detail` (C5)."""
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(update={"entity_access": []})
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([endpoint])
        await artifacts.write_icfg(
            _icfg_stopping_at(
                snapshot, boundary, endpoint, ["not-declared", "lombok-generated", "not-declared"]
            )
        )
        service = _offline_service(database)

        detail = await service.endpoint_detail(snapshot.id, endpoint.id)
        methods = await service.endpoint_icfg(snapshot.id, endpoint.id)
        statements = await service.endpoint_icfg(
            snapshot.id, endpoint.id, detail="statements", method_id=endpoint.handler.id
        )
        assert (
            "flow stops at 2 calls wadi could not open (2 not-declared)"
            in (detail["entity_facts_note"])
        )
        assert methods["entity_facts_note"] == detail["entity_facts_note"]
        assert statements["entity_facts_note"] == detail["entity_facts_note"]

    async def test_one_call_is_said_in_the_singular(self, database: WadiDatabase) -> None:
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(update={"entity_access": []})
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([endpoint])
        await artifacts.write_icfg(
            _icfg_stopping_at(snapshot, boundary, endpoint, ["ambiguous-overload"])
        )

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        note: str = detail["entity_facts_note"]
        assert "flow stops at 1 call wadi could not open (1 ambiguous-overload)" in note
        assert "may sit behind it" in note

    async def test_calls_that_cannot_hide_project_code_add_no_note(
        self, database: WadiDatabase
    ) -> None:
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(update={"entity_access": []})
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([endpoint])
        await artifacts.write_icfg(
            _icfg_stopping_at(
                snapshot,
                boundary,
                endpoint,
                ["lombok-generated", "compiler-generated", "inherited-external", "third-party"],
            )
        )

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        assert detail["entity_facts"] == "analyzed"
        assert "entity_facts_note" not in detail

    async def test_a_populated_summary_is_not_qualified(self, database: WadiDatabase) -> None:
        """The decision covers the empty state: rows are what was found."""
        snapshot, boundary = await _snapshot(database)
        endpoint = make_endpoint(snapshot, boundary).model_copy(
            update={"entity_access": summarize_entity_access([make_site(EntityOperation.READ)])}
        )
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([endpoint])
        await artifacts.write_icfg(
            _icfg_stopping_at(snapshot, boundary, endpoint, ["declared-not-bound"])
        )

        detail = await _offline_service(database).endpoint_detail(snapshot.id, endpoint.id)
        assert "entity_facts_note" not in detail

    def test_every_unbound_reason_is_decided(self) -> None:
        """A reason the contract adds must be classified before it is counted
        either way; the frontend's table in `lib/wadi/entity-access.ts` is
        checked the same way by `tsc`."""
        assert set(MAY_HIDE_PROJECT_CODE) == set(CalleeUnboundReason)
        assert {reason for reason, hides in MAY_HIDE_PROJECT_CODE.items() if not hides} == {
            CalleeUnboundReason.LOMBOK_GENERATED,
            CalleeUnboundReason.COMPILER_GENERATED,
            CalleeUnboundReason.INHERITED_EXTERNAL,
            CalleeUnboundReason.THIRD_PARTY,
        }


class TestEndpointIcfgEntityFacts:
    """The graph carries the sites; the endpoint says whether there could be any.

    A graph written before the phase has empty `entity_access_sites` on every
    node, exactly like one whose endpoint makes no repository call. Only the
    endpoint's summary tells them apart, so the tool reads it and says which.
    """

    async def _seed(
        self, database: WadiDatabase, *, predating: bool
    ) -> tuple[Snapshot, Endpoint, str]:
        snapshot, boundary = await _snapshot(database)
        sites = [] if predating else [make_site(EntityOperation.CREATE_OR_UPDATE)]
        endpoint = make_endpoint(snapshot, boundary)
        if predating:
            await _write_predating(database, endpoint)
        else:
            endpoint = endpoint.model_copy(update={"entity_access": summarize_entity_access(sites)})
            await ArtifactRepository(database).write_endpoints([endpoint])
        icfg = make_two_method_icfg(snapshot, boundary, endpoint, db_sites=sites)
        await ArtifactRepository(database).write_icfg(icfg)
        service_method = next(
            node.method.id for node in icfg.nodes if "OrderService" in node.method.signature
        )
        return snapshot, endpoint, service_method

    async def test_both_detail_levels_carry_the_sites_and_say_they_were_analyzed(
        self, database: WadiDatabase
    ) -> None:
        snapshot, endpoint, method_id = await self._seed(database, predating=False)
        service = _offline_service(database)

        rollup = await service.endpoint_icfg(snapshot.id, endpoint.id)
        assert rollup["entity_facts"] == "analyzed"
        assert "entity_facts_note" not in rollup
        method = next(m for m in rollup["methods"] if m["id"] == method_id)
        [db_call] = [c for c in method["calls"] if c.get("sink") == "db"]
        [site] = db_call["entity_access_sites"]
        assert site["accesses"][0]["operation"] == "create-or-update"
        assert site["accesses"][0]["candidate_operation"] == "update"

        statements = await service.endpoint_icfg(snapshot.id, endpoint.id, "statements", method_id)
        assert statements["entity_facts"] == "analyzed"
        db_node = next(node for node in statements["nodes"] if node["id"] == "s-db")
        assert db_node["entity_access_sites"] == db_call["entity_access_sites"]

    async def test_a_predating_graph_says_so_at_both_levels(self, database: WadiDatabase) -> None:
        snapshot, endpoint, method_id = await self._seed(database, predating=True)
        service = _offline_service(database)

        rollup = await service.endpoint_icfg(snapshot.id, endpoint.id)
        statements = await service.endpoint_icfg(snapshot.id, endpoint.id, "statements", method_id)
        for answer in (rollup, statements):
            assert answer["entity_facts"] == "predates-phase"
            assert "re-analyze" in answer["entity_facts_note"].lower()


class _Usage:
    """Two services. `orders` declares Order and Customer; `audit` declares an
    Order of its own (a different class with the same simple name) and makes
    one call whose entity could not be determined.

    Both report accounting. Since 1.27.0 only a reporting service's data
    models are listed (§5.2.17 hardening), so a non-reporting `audit` would
    have no Order row for the ambiguity tests to find.
    """

    def __init__(self) -> None:
        system = make_system("usage-shop")
        self.system = system
        self.snapshot = make_snapshot(system)
        self.orders = make_service(self.snapshot, "services/orders").model_copy(
            update={"entity_access_accounting": make_accounting(call_sites=3)}
        )
        self.audit = make_service(self.snapshot, "services/audit").model_copy(
            update={"entity_access_accounting": make_accounting(call_sites=1)}
        )
        self.order_model = make_data_model(self.snapshot, self.orders, _ORDER)
        self.customer_model = make_data_model(self.snapshot, self.orders, "com.acme.Customer")
        self.audit_order = make_data_model(self.snapshot, self.audit, "com.acme.audit.Order")
        order_id = self.order_model.id
        # R1-5: one save the analysis could not split, beside a create plus an
        # update. The first must never read as the second.
        self.unsplit = self._endpoint(
            self.orders, "/orders/import", [make_site(_CU, model_id=order_id)]
        )
        self.split = self._endpoint(
            self.orders,
            "/orders",
            [make_site(_C, model_id=order_id), make_site(_U, model_id=order_id)],
        )
        self.undetermined = self._endpoint(
            self.audit, "/audit", [make_site(EntityOperation.READ, entity=None)]
        )

    def _endpoint(
        self, boundary: ServiceBoundary, uri: str, sites: list[EntityAccessSite]
    ) -> Endpoint:
        return make_endpoint(self.snapshot, boundary, uri).model_copy(
            update={"entity_access": summarize_entity_access(sites)}
        )

    async def write(self, database: WadiDatabase) -> None:
        await SystemRepository(database).insert(self.system)
        await SnapshotRepository(database).insert(self.snapshot)
        artifacts = ArtifactRepository(database)
        await artifacts.write_service_boundaries([self.orders, self.audit])
        await artifacts.write_endpoints([self.unsplit, self.split, self.undetermined])
        await artifacts.write_data_models([self.order_model, self.customer_model, self.audit_order])


def _uris(row: dict[str, Any]) -> dict[str, list[str]]:
    return {
        usage["operation"]: [endpoint["full_uri"] for endpoint in usage["endpoints"]]
        for usage in row["operations"]
    }


@pytest.fixture
async def usage(database: WadiDatabase) -> _Usage:
    seed = _Usage()
    await seed.write(database)
    return seed


class TestEntityUsageTool:
    async def test_every_entity_of_the_snapshot_with_who_does_what(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        view = await _offline_service(database).entity_usage(usage.snapshot.id)
        assert view["analyzed"] is True
        assert "note" not in view
        assert {(row["service_id"], row["entity"]) for row in view["entities"]} == {
            (usage.orders.service_id, _ORDER),
            (usage.orders.service_id, "com.acme.Customer"),
            (usage.audit.service_id, "com.acme.audit.Order"),
            (usage.audit.service_id, None),
        }
        customer = next(r for r in view["entities"] if r["entity"] == "com.acme.Customer")
        # Q6: declared and reached by nothing is six empty lists, not a missing row.
        assert _uris(customer) == {op.value: [] for op in EntityOperation}
        accounting = {s["service_name"]: s["accounting"] for s in view["services"]}
        assert accounting["orders"]["call_sites"] == 3
        assert accounting["audit"]["call_sites"] == 1
        assert {s["service_name"]: s["status"] for s in view["services"]} == {
            "orders": "reporting",
            "audit": "reporting",
        }

    async def test_one_unsplit_save_never_reads_as_a_create_plus_an_update(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        """R1-5, the same check the `/entities` route makes."""
        view = await _offline_service(database).entity_usage(usage.snapshot.id, entity=_ORDER)
        [order] = view["entities"]
        assert _uris(order) == {
            "create": ["/orders"],
            "read": [],
            "update": ["/orders"],
            "delete": [],
            "create-or-update": ["/orders/import"],
            "unknown": [],
        }

    async def test_each_operation_counts_only_its_own_call_sites(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        """Review C1: `/orders` makes one create and one update, so 1 under each, never 2."""
        view = await _offline_service(database).entity_usage(usage.snapshot.id, entity=_ORDER)
        [order] = view["entities"]
        counts = {
            usage_row["operation"]: [
                (endpoint["full_uri"], endpoint["call_sites"])
                for endpoint in usage_row["endpoints"]
            ]
            for usage_row in order["operations"]
        }
        assert counts["create"] == [("/orders", 1)]
        assert counts["update"] == [("/orders", 1)]
        assert counts["create-or-update"] == [("/orders/import", 1)]
        endpoints = [e for usage_row in order["operations"] for e in usage_row["endpoints"]]
        assert all("call_sites_note" not in endpoint for endpoint in endpoints)

    async def test_a_count_a_summary_never_recorded_is_said_not_numbered(
        self, database: WadiDatabase
    ) -> None:
        """A summary written before 1.27.0 counted per entity only (review C1).

        Its per-operation count is `null`, and the entry says why in words, so
        an agent never reads the entity count, or zero, in its place.
        """
        snapshot, boundary = await _snapshot(database)
        boundary = boundary.model_copy(
            update={"entity_access_accounting": make_accounting(call_sites=2)}
        )
        await ArtifactRepository(database).write_service_boundaries([boundary])
        old_summary = [
            row.model_copy(update={"call_sites_by_operation": None})
            for row in summarize_entity_access(
                [make_site(EntityOperation.READ), make_site(EntityOperation.DELETE)]
            )
        ]
        endpoint = make_endpoint(snapshot, boundary, "/orders/{id}").model_copy(
            update={"entity_access": old_summary}
        )
        await ArtifactRepository(database).write_endpoints([endpoint])

        view = await _offline_service(database).entity_usage(snapshot.id, entity=_ORDER)
        [order] = view["entities"]
        listed = {u["operation"]: u["endpoints"] for u in order["operations"]}
        for operation in ("read", "delete"):
            [entry] = listed[operation]
            assert entry["call_sites"] is None
            assert entry["call_sites_note"] == (
                "count not recorded (summary predates 1.27.0; re-analyze)"
            )

    async def test_a_simple_name_that_names_one_entity_selects_it(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        view = await _offline_service(database).entity_usage(usage.snapshot.id, entity="Customer")
        assert [row["entity"] for row in view["entities"]] == ["com.acme.Customer"]
        assert [s["service_name"] for s in view["services"]] == ["orders"]

    async def test_a_simple_name_naming_two_entities_asks_which(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        with pytest.raises(ValueError, match=r"com\.acme\.Order.*com\.acme\.audit\.Order"):
            await _offline_service(database).entity_usage(usage.snapshot.id, entity="Order")

    async def test_the_service_filter_scopes_rows_and_accounting(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        view = await _offline_service(database).entity_usage(
            usage.snapshot.id, entity="Order", service_id=usage.audit.service_id
        )
        assert [row["entity"] for row in view["entities"]] == ["com.acme.audit.Order"]
        assert [s["service_id"] for s in view["services"]] == [usage.audit.service_id]

    async def test_the_undetermined_bucket_is_named_not_dropped(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        view = await _offline_service(database).entity_usage(
            usage.snapshot.id, service_id=usage.audit.service_id
        )
        bucket = next(row for row in view["entities"] if row["entity"] is None)
        assert bucket["name"] == "entity not determined"
        assert _uris(bucket)["read"] == ["/audit"]

    async def test_an_entity_the_snapshot_does_not_have_is_not_found(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        """Not an empty answer: "no endpoint touches it" would be a claim."""
        with pytest.raises(NotFoundError, match="entity_usage without"):
            await _offline_service(database).entity_usage(usage.snapshot.id, entity="Invoice")

    async def test_unknown_service_and_snapshot_point_at_the_listing_tools(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        service = _offline_service(database)
        with pytest.raises(NotFoundError, match="list_services"):
            await service.entity_usage(usage.snapshot.id, service_id="svc_" + "0" * 16)
        with pytest.raises(NotFoundError, match="list_snapshots"):
            await service.entity_usage("snap_" + "0" * 16)

    async def test_a_snapshot_predating_entity_facts_says_so_never_untouched(
        self, database: WadiDatabase
    ) -> None:
        """R1-6, for every way of asking, including about a declared entity."""
        snapshot, boundary = await _snapshot(database)
        await ArtifactRepository(database).write_data_models(
            [make_data_model(snapshot, boundary, _ORDER)]
        )
        await _write_predating(database, make_endpoint(snapshot, boundary, "/orders"))
        service = _offline_service(database)

        for view in (
            await service.entity_usage(snapshot.id),
            await service.entity_usage(snapshot.id, entity=_ORDER),
            await service.entity_usage(snapshot.id, entity="Order"),
        ):
            assert view["analyzed"] is False
            assert view["entities"] == []
            assert view["endpoints_predating"] == 1
            note: str = view["note"]
            assert "predates entity facts" in note
            assert "re-analyze" in note.lower()
            assert "no endpoint" not in note.lower()

    async def test_a_partly_reanalyzed_snapshot_says_how_much_predates(
        self, database: WadiDatabase, usage: _Usage
    ) -> None:
        await _write_predating(database, make_endpoint(usage.snapshot, usage.orders, "/legacy"))
        view = await _offline_service(database).entity_usage(usage.snapshot.id)
        assert view["analyzed"] is True
        assert view["endpoints_predating"] == 1
        assert "1 endpoint" in view["note"]


class _Statuses:
    """One service of each accounting status (1.27.0) in one snapshot.

    `gateway` reports and has no endpoints, the live `ts-gateway` shape
    (review C4). `billing` failed extraction and `legacy` predates the phase,
    so neither was examined (review C3). `common` is a library.
    """

    def __init__(self) -> None:
        self.system = make_system("status-shop")
        self.snapshot = make_snapshot(self.system)
        self.orders = make_service(self.snapshot, "services/orders").model_copy(
            update={"entity_access_accounting": make_accounting(call_sites=1)}
        )
        self.gateway = make_service(self.snapshot, "services/gateway").model_copy(
            update={"entity_access_accounting": make_accounting(call_sites=0)}
        )
        self.billing = make_service(self.snapshot, "services/billing").model_copy(
            update={"extraction_error": "RuntimeError: parse failed"}
        )
        self.legacy = make_service(self.snapshot, "services/legacy")
        self.common = make_service(self.snapshot, "libs/common").model_copy(
            update={"kind": ServiceKind.LIBRARY}
        )
        self.order_model = make_data_model(self.snapshot, self.orders, _ORDER)
        self.route_model = make_data_model(self.snapshot, self.gateway, "com.acme.gateway.Route")
        self.ledger_model = make_data_model(self.snapshot, self.legacy, "com.acme.legacy.Ledger")
        self.reader = make_endpoint(self.snapshot, self.orders, "/orders").model_copy(
            update={
                "entity_access": summarize_entity_access(
                    [make_site(EntityOperation.READ, model_id=self.order_model.id)]
                )
            }
        )

    async def write(self, database: WadiDatabase) -> None:
        await SystemRepository(database).insert(self.system)
        await SnapshotRepository(database).insert(self.snapshot)
        artifacts = ArtifactRepository(database)
        await artifacts.write_service_boundaries(
            [self.orders, self.gateway, self.billing, self.legacy, self.common]
        )
        await artifacts.write_endpoints([self.reader])
        await _write_predating(database, make_endpoint(self.snapshot, self.legacy, "/ledger"))
        await artifacts.write_data_models([self.order_model, self.route_model, self.ledger_model])


@pytest.fixture
async def statuses(database: WadiDatabase) -> _Statuses:
    seed = _Statuses()
    await seed.write(database)
    return seed


class TestEntityUsageSaysWhyAServiceHasNoAccounting:
    """Reviews C3, C4: the notes come from each service's status, never from endpoint counts.

    A failed service has no endpoint rows, so `endpoints_predating` is 0 for
    it, and arithmetic on that count said nothing about it at all.
    """

    async def test_each_service_that_was_not_examined_says_why(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        view = await _offline_service(database).entity_usage(statuses.snapshot.id)
        assert view["analyzed"] is True
        assert {s["service_name"]: s["status"] for s in view["services"]} == {
            "billing": "extraction-failed",
            "common": "library",
            "gateway": "reporting",
            "legacy": "predating",
            "orders": "reporting",
        }
        # A predating service's declared entities are not listed as six empty
        # lists: that would say "touched by nothing" about code nobody read.
        assert {(row["service_id"], row["entity"]) for row in view["entities"]} == {
            (statuses.orders.service_id, _ORDER),
            (statuses.gateway.service_id, "com.acme.gateway.Route"),
        }
        note: str = view["note"]
        assert "Extraction failed for service 'billing'" in note
        assert "never examined" in note
        assert "Service 'legacy' predates entity facts" in note
        assert "re-analyze" in note.lower()
        assert "Service 'common' is a library" in note
        assert "counted in each service that depends on it" in note
        assert "1 endpoint predates" in note

    async def test_a_failed_services_entity_is_never_said_to_be_absent(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        """Review C3: "no entity 'Invoice' is declared or touched here" is a
        claim about billing's code, which nobody examined."""
        service = _offline_service(database)
        for view in (
            await service.entity_usage(statuses.snapshot.id, entity="Invoice"),
            await service.entity_usage(
                statuses.snapshot.id, entity="Invoice", service_id=statuses.billing.service_id
            ),
            await service.entity_usage(
                statuses.snapshot.id, service_id=statuses.billing.service_id
            ),
        ):
            assert view["analyzed"] is False
            assert view["entities"] == []
            note: str = view["note"]
            assert "Extraction failed for service 'billing'" in note
            assert "never examined" in note
            assert "no entity" not in note.lower()
            assert "holds no endpoints" not in note
        across = await service.entity_usage(statuses.snapshot.id, entity="Invoice")
        assert across["note"].startswith(
            "'Invoice' is not an entity of any service that was examined"
        )
        # The answer names the services it could be in, and only those.
        assert {s["service_name"] for s in across["services"]} == {"billing", "legacy"}

    async def test_a_predating_services_entity_is_said_to_need_reanalysis(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        view = await _offline_service(database).entity_usage(
            statuses.snapshot.id, entity="com.acme.legacy.Ledger"
        )
        assert view["analyzed"] is False
        assert view["entities"] == []
        assert "Service 'legacy' predates entity facts" in view["note"]
        assert "re-analyze" in view["note"].lower()

    async def test_an_answer_about_one_entity_names_the_services_not_examined(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        """Found in `orders`, but `billing` and `legacy` might also touch an Order."""
        view = await _offline_service(database).entity_usage(statuses.snapshot.id, entity=_ORDER)
        assert view["analyzed"] is True
        assert [row["service_id"] for row in view["entities"]] == [statuses.orders.service_id]
        assert [s["service_name"] for s in view["services"]] == ["orders"]
        note: str = view["note"]
        assert "Extraction failed for service 'billing'" in note
        assert "Service 'legacy' predates entity facts" in note
        # The library has no entities of its own to be missing from this answer.
        assert "library" not in note

    async def test_a_reporting_service_with_no_endpoints_lists_its_entities(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        """Review C4, live on `ts-gateway`: it said "This snapshot holds no endpoints yet"."""
        view = await _offline_service(database).entity_usage(
            statuses.snapshot.id, service_id=statuses.gateway.service_id
        )
        assert view["analyzed"] is True
        assert view["endpoints_predating"] == 0
        [route] = view["entities"]
        assert route["entity"] == "com.acme.gateway.Route"
        assert _uris(route) == {op.value: [] for op in EntityOperation}
        assert [s["status"] for s in view["services"]] == ["reporting"]
        assert "note" not in view

    async def test_a_library_says_its_calls_count_in_its_dependents(
        self, database: WadiDatabase, statuses: _Statuses
    ) -> None:
        view = await _offline_service(database).entity_usage(
            statuses.snapshot.id, service_id=statuses.common.service_id
        )
        assert view["analyzed"] is False
        assert [s["status"] for s in view["services"]] == ["library"]
        note: str = view["note"]
        assert "Service 'common' is a library" in note
        assert "counted in each service that depends on it" in note
        assert "holds no endpoints" not in note

    async def test_only_a_snapshot_with_nothing_extracted_holds_no_endpoints(
        self, database: WadiDatabase
    ) -> None:
        system = make_system("empty")
        snapshot = make_snapshot(system)
        await SystemRepository(database).insert(system)
        await SnapshotRepository(database).insert(snapshot)

        view = await _offline_service(database).entity_usage(snapshot.id)
        assert view["analyzed"] is False
        assert view["services"] == []
        assert view["note"] == (
            "This snapshot holds no endpoints yet, so there are no entity facts to read."
        )
