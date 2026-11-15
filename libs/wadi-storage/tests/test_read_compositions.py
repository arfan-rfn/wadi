"""Integration tests: the read compositions shared by the orchestrator and MCP (C5).

The orchestrator's endpoint detail and the MCP `endpoint_detail` tool answer
"what does this endpoint call?" from one function, so the two surfaces cannot
drift into different answers. P1 forbids the MCP server importing the
orchestrator, which is why the join lives in the storage seam.
"""

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
    ServiceBoundary,
    Snapshot,
    SourceAnchor,
)
from wadi_storage import (
    GraphRepository,
    GraphStore,
    StitchRepository,
    WadiDatabase,
    endpoint_outbound,
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
