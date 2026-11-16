"""MCP `endpoint_detail` without the stitched graph (§5.2.17, pre-landing review #6).

The tool is an agent's only route to an endpoint's request and response
contract (§5.2.16). The outbound join is the one part of its answer that
Neo4j holds, and a graph read that failed used to fail the whole call: the
contract was lost for want of the edges. Each test here has a stitched
snapshot whose flow makes a remote call, so the graph IS read, and a graph
that fails or never answers.
"""

import asyncio
from typing import Any

import pytest
from mcp_support import make_two_method_icfg

from wadi_contracts import (
    CoverageReport,
    CoverageTotals,
    RemoteEdgesView,
    TypeShape,
)
from wadi_mcp.service import WadiMcpService
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    GraphStore,
    GraphStoreError,
    SnapshotRepository,
    StitchRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration


class _FailingGraph(GraphRepository):
    """Refuses as an unreachable Neo4j does once the driver gives up."""

    def __init__(self) -> None:
        super().__init__(GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused"))

    async def remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        raise GraphStoreError("ServiceUnavailable: Unable to retrieve routing information")


class _SilentGraph(GraphRepository):
    """Never answers; the real driver retries for about a minute first."""

    def __init__(self) -> None:
        super().__init__(GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused"))

    async def remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the event is never set")


async def _stitched_endpoint_with_a_remote_call(database: WadiDatabase) -> tuple[str, str]:
    system = make_system("degrade-shop")
    snapshot = make_snapshot(system)
    boundary = make_service(snapshot)
    endpoint = make_endpoint(snapshot, boundary).model_copy(
        update={
            "entity_access": [],
            "response_schema": TypeShape.model_validate(
                {"kind": "object", "type_name": "com.acme.Order", "fields": []}
            ),
        }
    )
    icfg = make_two_method_icfg(snapshot, boundary, endpoint)
    # The marker as the current worker writes it, list and legacy field both.
    icfg = icfg.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"remote_call_ids": [node.remote_call_id]})
                if node.remote_call_id is not None
                else node
                for node in icfg.nodes
            ]
        }
    )
    await SystemRepository(database).insert(system)
    await SnapshotRepository(database).insert(snapshot)
    artifacts = ArtifactRepository(database)
    await artifacts.write_service_boundaries([boundary])
    await artifacts.write_endpoints([endpoint])
    await artifacts.write_icfg(icfg)
    await StitchRepository(database).write_coverage_report(
        CoverageReport(
            snapshot_id=snapshot.id,
            totals=CoverageTotals(
                call_sites=1, edges=1, analyzed=1, external=0, placeholder=0, undetermined=0
            ),
        )
    )
    return snapshot.id, endpoint.id


def _assert_contract_without_edges(detail: dict[str, Any], endpoint_id: str) -> None:
    # The contract arrives whole.
    assert detail["id"] == endpoint_id
    assert detail["response_schema"]["type_name"] == "com.acme.Order"
    assert "request_schema" in detail
    assert detail["entity_facts"] == "analyzed"
    # The edges are unknown: null, never [] ("calls nothing"), and stitching
    # did run, so `stitched` stays true rather than reading "not yet".
    assert detail["outbound"] is None
    assert detail["stitched"] is True
    note: str = detail["outbound_note"]
    assert "outbound is null, not empty" in note
    assert "\n" not in note


class TestEndpointDetailDegrades:
    async def test_a_failing_graph_costs_the_edges_not_the_contract(
        self, database: WadiDatabase
    ) -> None:
        snapshot_id, endpoint_id = await _stitched_endpoint_with_a_remote_call(database)

        detail = await WadiMcpService(database, _FailingGraph()).endpoint_detail(
            snapshot_id, endpoint_id
        )
        _assert_contract_without_edges(detail, endpoint_id)
        assert "ServiceUnavailable" in detail["outbound_note"]

    async def test_a_graph_that_never_answers_is_given_up_on(self, database: WadiDatabase) -> None:
        snapshot_id, endpoint_id = await _stitched_endpoint_with_a_remote_call(database)

        service = WadiMcpService(database, _SilentGraph(), graph_timeout_seconds=0.05)
        detail = await service.endpoint_detail(snapshot_id, endpoint_id)
        _assert_contract_without_edges(detail, endpoint_id)
        assert "did not answer within 0.05 s" in detail["outbound_note"]

    async def test_shared_shapes_survive_too(self, database: WadiDatabase) -> None:
        """Both shape forms are the contract; neither depends on the graph."""
        snapshot_id, endpoint_id = await _stitched_endpoint_with_a_remote_call(database)

        detail = await WadiMcpService(database, _FailingGraph()).endpoint_detail(
            snapshot_id, endpoint_id, resolve_shapes=False
        )
        _assert_contract_without_edges(detail, endpoint_id)
        assert "type_defs" in detail
