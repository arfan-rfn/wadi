"""MCP stitched-graph tools: coverage_report, remote_edges, cross-service ICFG."""

import pytest
from mcp_support import make_two_method_icfg

from wadi_contracts import (
    Confidence,
    CoverageReport,
    CoverageTotals,
    Endpoint,
    Provenance,
    ServiceBoundary,
    Snapshot,
    StitchedEdge,
    TargetKind,
    remote_call_id,
)
from wadi_mcp.service import NotFoundError, WadiMcpService
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_testing.builders import (
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


class _Seed:
    def __init__(
        self,
        snapshot: Snapshot,
        caller: ServiceBoundary,
        callee: ServiceBoundary,
        target: Endpoint,
        caller_endpoint: Endpoint,
        rc_id: str,
    ) -> None:
        self.snapshot = snapshot
        self.caller = caller
        self.callee = callee
        self.target = target
        self.caller_endpoint = caller_endpoint
        self.rc_id = rc_id


@pytest.fixture
async def seed(database: WadiDatabase, graph_repository: GraphRepository) -> _Seed:
    """Mongo + Neo4j seeded: caller's ICFG has one stitched call to callee."""
    system = make_system("stitched-shop")
    snapshot = make_snapshot(system)
    caller = make_service(snapshot, "services/orders")
    callee = make_service(snapshot, "services/billing")
    caller_endpoint = make_endpoint(snapshot, caller, uri="/orders/{id}")
    target = make_endpoint(snapshot, callee, uri="/invoices/{id}")
    icfg = make_two_method_icfg(snapshot, caller, caller_endpoint)
    # The support ICFG's call fact (must match its baked-in site/url).
    rc_id = remote_call_id(
        caller.service_id, "src/OrderService.java", 25, "http://billing/invoices/{id}"
    )
    call = make_remote_call(
        snapshot,
        caller,
        url="http://billing/invoices/{id}",
        file="src/OrderService.java",
        line=25,
    )
    assert call.id == rc_id  # the ICFG marker and the fact agree by construction
    edge = StitchedEdge.create(
        snapshot_id=snapshot.id,
        service_id=caller.service_id,
        remote_call_id=rc_id,
        mechanism="resttemplate",
        url=call.url,
        target_kind=TargetKind.ANALYZED,
        target_service_id=callee.service_id,
        target_endpoint_id=target.id,
        confidence=Confidence.HIGH,
        provenance=Provenance.CONFIG_RESOLVED,
    )

    await SystemRepository(database).insert(system)
    await SnapshotRepository(database).insert(snapshot)
    artifacts = ArtifactRepository(database)
    await artifacts.write_service_boundaries([caller, callee])
    await artifacts.write_endpoints([caller_endpoint, target])
    await artifacts.write_icfg(icfg)
    await artifacts.write_remote_calls([call])
    await graph_repository.replace_snapshot(
        snapshot.id,
        boundaries=[caller, callee],
        endpoints=[caller_endpoint, target],
        remote_calls=[call],
        edges=[edge],
    )
    from wadi_storage import StitchRepository

    stitch = StitchRepository(database)
    await stitch.replace_stitched_edges(snapshot.id, [edge])
    await stitch.write_coverage_report(
        CoverageReport(
            snapshot_id=snapshot.id,
            totals=CoverageTotals(
                call_sites=1, edges=1, analyzed=1, external=0, placeholder=0, undetermined=0
            ),
        )
    )
    return _Seed(snapshot, caller, callee, target, caller_endpoint, rc_id)


class TestCoverageTool:
    async def test_returns_report(
        self, database: WadiDatabase, graph_repository: GraphRepository, seed: _Seed
    ) -> None:
        service = WadiMcpService(database, graph_repository)
        report = await service.coverage_report(seed.snapshot.id)
        assert report["totals"]["analyzed"] == 1

    async def test_unstitched_snapshot_guides_agent(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        system = make_system("bare")
        snapshot = make_snapshot(system)
        await SystemRepository(database).insert(system)
        await SnapshotRepository(database).insert(snapshot)
        service = WadiMcpService(database, graph_repository)
        with pytest.raises(NotFoundError, match="not stitched"):
            await service.coverage_report(snapshot.id)


class TestRemoteEdgesTool:
    async def test_outbound_and_inbound(
        self, database: WadiDatabase, graph_repository: GraphRepository, seed: _Seed
    ) -> None:
        service = WadiMcpService(database, graph_repository)
        outbound_view = await service.remote_edges(seed.snapshot.id, seed.caller.service_id)
        assert len(outbound_view["outbound"]) == 1
        assert outbound_view["outbound"][0]["target_kind"] == "analyzed"
        inbound_view = await service.remote_edges(seed.snapshot.id, seed.callee.service_id)
        assert len(inbound_view["inbound"]) == 1

    async def test_unknown_service_guides_agent(
        self, database: WadiDatabase, graph_repository: GraphRepository, seed: _Seed
    ) -> None:
        service = WadiMcpService(database, graph_repository)
        with pytest.raises(NotFoundError, match="list_services"):
            await service.remote_edges(seed.snapshot.id, "svc_" + "0" * 16)


class TestCrossServiceIcfg:
    async def test_rollup_gains_targets_and_downstream(
        self, database: WadiDatabase, graph_repository: GraphRepository, seed: _Seed
    ) -> None:
        service = WadiMcpService(database, graph_repository)
        rollup = await service.endpoint_icfg(
            seed.snapshot.id, seed.caller_endpoint.id, cross_service=True
        )
        [target_item] = rollup["remote_targets"]
        assert target_item["remote_call_id"] == seed.rc_id
        assert target_item["target_endpoint_id"] == seed.target.id
        assert target_item["confidence"] == "high"
        [downstream] = rollup["downstream"]
        assert downstream["endpoint_id"] == seed.target.id
        assert downstream["service_id"] == seed.callee.service_id
        assert downstream["simplified_uri"] == "/invoices/{?}"

    async def test_default_rollup_unchanged(
        self, database: WadiDatabase, graph_repository: GraphRepository, seed: _Seed
    ) -> None:
        service = WadiMcpService(database, graph_repository)
        rollup = await service.endpoint_icfg(seed.snapshot.id, seed.caller_endpoint.id)
        assert "remote_targets" not in rollup
        assert "downstream" not in rollup
