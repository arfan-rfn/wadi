"""Integration tests for the MCP tool logic against real Mongo."""

import pytest
from mcp_support import make_two_method_icfg

from wadi_mcp.server import create_server
from wadi_mcp.service import NotFoundError, WadiMcpService
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    GraphStore,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded(database: WadiDatabase) -> dict[str, str]:
    """A system → snapshot → service → endpoint → ICFG chain in storage."""
    system = make_system("mcp-shop")
    snapshot = make_snapshot(system)
    boundary = make_service(snapshot)
    endpoint = make_endpoint(snapshot, boundary)
    icfg = make_two_method_icfg(snapshot, boundary, endpoint)

    await SystemRepository(database).insert(system)
    await SnapshotRepository(database).insert(snapshot)
    artifacts = ArtifactRepository(database)
    await artifacts.write_service_boundaries([boundary])
    await artifacts.write_endpoints([endpoint])
    await artifacts.write_icfg(icfg)
    return {
        "system_id": system.id,
        "snapshot_id": snapshot.id,
        "service_id": boundary.service_id,
        "endpoint_id": endpoint.id,
    }


class TestListingTools:
    async def test_full_navigation_chain(
        self, database: WadiDatabase, seeded: dict[str, str]
    ) -> None:
        service = _service(database)

        systems = await service.list_systems()
        assert [s["name"] for s in systems] == ["mcp-shop"]

        snapshots = await service.list_snapshots(seeded["system_id"])
        assert snapshots[0]["id"] == seeded["snapshot_id"]

        services = await service.list_services(seeded["snapshot_id"])
        assert services[0]["service_id"] == seeded["service_id"]

        endpoints = await service.list_endpoints(seeded["snapshot_id"], seeded["service_id"])
        assert endpoints[0]["id"] == seeded["endpoint_id"]
        assert endpoints[0]["auth"]["authenticated"] is None  # honest unknown (P10)

    async def test_not_found_errors_guide_the_agent(self, database: WadiDatabase) -> None:
        service = _service(database)
        with pytest.raises(NotFoundError, match="list_systems"):
            await service.list_snapshots("sys_" + "0" * 16)
        with pytest.raises(NotFoundError, match="list_snapshots"):
            await service.list_services("snap_" + "0" * 16)


class TestEndpointIcfgTool:
    async def test_method_rollup_default(
        self, database: WadiDatabase, seeded: dict[str, str]
    ) -> None:
        service = _service(database)
        rollup = await service.endpoint_icfg(seeded["snapshot_id"], seeded["endpoint_id"])
        assert rollup["detail"] == "methods"
        assert len(rollup["methods"]) >= 2

    async def test_statement_drilldown(
        self, database: WadiDatabase, seeded: dict[str, str]
    ) -> None:
        service = _service(database)
        rollup = await service.endpoint_icfg(seeded["snapshot_id"], seeded["endpoint_id"])
        target = rollup["root_method_id"]
        detail = await service.endpoint_icfg(
            seeded["snapshot_id"], seeded["endpoint_id"], "statements", target
        )
        assert detail["method_id"] == target
        assert detail["nodes"]

    async def test_statements_without_method_id_rejected(
        self, database: WadiDatabase, seeded: dict[str, str]
    ) -> None:
        service = _service(database)
        with pytest.raises(ValueError, match="method_id"):
            await service.endpoint_icfg(seeded["snapshot_id"], seeded["endpoint_id"], "statements")

    async def test_missing_icfg_not_found(
        self, database: WadiDatabase, seeded: dict[str, str]
    ) -> None:
        service = _service(database)
        with pytest.raises(NotFoundError, match="list_endpoints"):
            await service.endpoint_icfg(seeded["snapshot_id"], "ep_" + "0" * 16)


def _service(database: "WadiDatabase") -> WadiMcpService:
    """Service with a lazily-connected graph — these tests never touch Neo4j."""
    store = GraphStore("neo4j://127.0.0.1:1", "neo4j", "unused")
    return WadiMcpService(database, GraphRepository(store))


class TestServerRegistration:
    async def test_all_phase1_tools_registered(self, database: WadiDatabase) -> None:
        server = create_server(_service(database))
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "list_systems",
            "list_snapshots",
            "list_services",
            "list_endpoints",
            "endpoint_icfg",
            "coverage_report",
            "remote_edges",
        }
        # Every tool ships an agent-facing description (the docstring).
        assert all(tool.description for tool in tools)
