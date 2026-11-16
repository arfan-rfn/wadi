"""Integration tests: the read compositions shared by the orchestrator and MCP (C5).

The orchestrator's endpoint detail and the MCP `endpoint_detail` tool answer
"what does this endpoint call?" from one function, so the two surfaces cannot
drift into different answers. P1 forbids the MCP server importing the
orchestrator, which is why the join lives in the storage seam.
"""

import asyncio

import pytest

from wadi_contracts import (
    CoverageReport,
    CoverageTotals,
    Icfg,
    IcfgEdge,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    RemoteCall,
    RemoteEdgesView,
    ServiceBoundary,
    Snapshot,
    SourceAnchor,
)
from wadi_storage import (
    EndpointOutbound,
    GraphRepository,
    GraphStore,
    GraphStoreError,
    OutboundUnavailable,
    StitchRepository,
    WadiDatabase,
    endpoint_outbound,
    endpoint_outbound_or_unavailable,
)
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


def _unreachable_graph() -> GraphRepository:
    """A graph whose driver connects lazily to nothing.

    Any read through it raises, so a test using it proves the code path never
    touched Neo4j.
    """
    return GraphRepository(GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused"))


def _icfg_calling(snapshot: Snapshot, caller: ServiceBoundary, call: RemoteCall) -> Icfg:
    endpoint = make_endpoint(snapshot, caller)
    icfg = make_icfg(snapshot, caller, endpoint)
    icfg.nodes.append(
        IcfgNode(
            id="call0",
            kind=IcfgNodeKind.CALL,
            anchor=SourceAnchor(file="src/A.java", start_line=3, end_line=3),
            source_text="inventoryClient.stock(id);",
            method=endpoint.handler,
            remote_call_id=call.id,
            remote_call_ids=[call.id],
        )
    )
    icfg.edges.append(IcfgEdge(source="s2", target="call0", kind=IcfgEdgeKind.FLOW))
    return icfg


async def _mark_stitched(database: WadiDatabase, snapshot: Snapshot) -> None:
    await StitchRepository(database).write_coverage_report(
        CoverageReport(
            snapshot_id=snapshot.id,
            totals=CoverageTotals(
                call_sites=2, edges=2, analyzed=2, external=0, placeholder=0, undetermined=0
            ),
        )
    )


class TestEndpointOutbound:
    async def test_before_stitching_it_is_not_yet_and_the_graph_is_never_read(
        self, database: WadiDatabase
    ) -> None:
        """Pre-stitch, outbound is 'not yet', never 'none' (P10)."""
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)
        icfg = _icfg_calling(snapshot, caller, make_remote_call(snapshot, caller))

        result = await endpoint_outbound(
            StitchRepository(database),
            _unreachable_graph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            icfg=icfg,
        )
        assert result.stitched is False
        assert result.outbound == []

    async def test_a_stitched_endpoint_without_a_graph_reports_stitched_and_no_calls(
        self, database: WadiDatabase
    ) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)
        await _mark_stitched(database, snapshot)

        result = await endpoint_outbound(
            StitchRepository(database),
            _unreachable_graph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            icfg=None,
        )
        assert result.stitched is True
        assert result.outbound == []

    async def test_only_the_edges_this_endpoints_flow_reaches(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        """The service-wide edge set stays behind /remote-edges."""
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/orders")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        in_flow = make_remote_call(snapshot, caller, line=27)
        elsewhere = make_remote_call(snapshot, caller, line=99, url="http://billing:8082/x")
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[target],
            remote_calls=[in_flow, elsewhere],
            edges=[make_analyzed_edge(in_flow, target), make_analyzed_edge(elsewhere, target)],
        )
        await _mark_stitched(database, snapshot)

        outbound, stitched = await endpoint_outbound(
            StitchRepository(database),
            graph_repository,
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            icfg=_icfg_calling(snapshot, caller, in_flow),
        )
        assert stitched is True
        assert [edge.remote_call_id for edge in outbound] == [in_flow.id]
        assert outbound[0].target_endpoint_id == target.id


class _FailingGraph(GraphRepository):
    """A graph store that refuses, the way an unreachable Neo4j does once the
    driver has given up (GraphRepository translates the driver's error)."""

    def __init__(self) -> None:
        super().__init__(GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused"))

    async def remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        raise GraphStoreError("ServiceUnavailable: Unable to retrieve routing information")


class _SilentGraph(GraphRepository):
    """A graph store that never answers. The real driver retries an unreachable
    server for about a minute before it raises (measured: 57 s)."""

    def __init__(self) -> None:
        super().__init__(GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused"))

    async def remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the event is never set")


class TestEndpointOutboundOrUnavailable:
    """The join MCP `endpoint_detail` reads (§5.2.17, pre-landing review #6).

    The tool is an agent's only route to an endpoint's request and response
    contract (§5.2.16), so a graph that cannot be read must cost the agent the
    edges, never the contract. Unknown is its own answer: neither `[]`, which
    reads as "calls nothing", nor "not stitched", which is false.
    """

    async def test_a_graph_that_fails_leaves_outbound_unknown(self, database: WadiDatabase) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)
        await _mark_stitched(database, snapshot)

        result = await endpoint_outbound_or_unavailable(
            StitchRepository(database),
            _FailingGraph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_ids={"rc_" + "a" * 16},
        )
        assert isinstance(result, OutboundUnavailable)
        assert "ServiceUnavailable" in result.reason

    async def test_a_graph_that_does_not_answer_in_time_leaves_it_unknown(
        self, database: WadiDatabase
    ) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)
        await _mark_stitched(database, snapshot)

        result = await endpoint_outbound_or_unavailable(
            StitchRepository(database),
            _SilentGraph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_ids={"rc_" + "a" * 16},
            timeout_seconds=0.05,
        )
        assert isinstance(result, OutboundUnavailable)
        assert "did not answer within 0.05 s" in result.reason

    async def test_before_stitching_the_graph_is_never_read(self, database: WadiDatabase) -> None:
        """'Not yet' needs no graph, so a failing one cannot make it unknown."""
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)

        result = await endpoint_outbound_or_unavailable(
            StitchRepository(database),
            _FailingGraph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_ids={"rc_" + "a" * 16},
        )
        assert result == EndpointOutbound(outbound=[], stitched=False)

    async def test_a_flow_with_no_remote_call_never_reads_the_graph(
        self, database: WadiDatabase
    ) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot)
        await _mark_stitched(database, snapshot)

        result = await endpoint_outbound_or_unavailable(
            StitchRepository(database),
            _FailingGraph(),
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_ids=set(),
        )
        assert result == EndpointOutbound(outbound=[], stitched=True)

    async def test_a_readable_graph_gives_the_workspace_answer(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        """C5: given the ids the ICFG carries, the same edges as `/detail` reads."""
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/orders")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        in_flow = make_remote_call(snapshot, caller, line=27)
        elsewhere = make_remote_call(snapshot, caller, line=99, url="http://billing:8082/x")
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[target],
            remote_calls=[in_flow, elsewhere],
            edges=[make_analyzed_edge(in_flow, target), make_analyzed_edge(elsewhere, target)],
        )
        await _mark_stitched(database, snapshot)
        stitch = StitchRepository(database)

        from_ids = await endpoint_outbound_or_unavailable(
            stitch,
            graph_repository,
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_ids={in_flow.id},
        )
        from_icfg = await endpoint_outbound(
            stitch,
            graph_repository,
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            icfg=_icfg_calling(snapshot, caller, in_flow),
        )
        assert from_ids == from_icfg
        assert [edge.remote_call_id for edge in from_icfg.outbound] == [in_flow.id]
