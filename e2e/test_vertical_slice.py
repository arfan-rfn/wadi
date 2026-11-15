"""The Phase 1 conformance e2e (§11.8): the whole vertical slice, for real.

Register the spring-petstore-mini fixture as a system → analyze → the
extraction pipeline drives the REAL wadi-joern container over CPGQL → the
stitcher runs (Mongo truth + coverage + Neo4j) → the snapshot succeeds → the
public API serves endpoints (diffed against the fixture's expected JSON), the
ICFG, and pinned-SHA source.

Requirements: Docker + the ghcr.io/wadi-sh/joern image built at the version in
the VERSION file (`make joern-image`).
Runs via `make e2e`; skipped automatically when prerequisites are missing.

Everything except HTTP-serving runs in-process (orchestrator app via ASGI,
worker/stitcher pipelines driven directly through the same JobQueue they use
in production) — the compose stack adds process boundaries, not logic.

`test_entity_access_slice` runs the same slice over `spring-data-crud-matrix`
(§5.2.17, test plan critical path 1). Export 2.14.0's repository facts, as the
image's jar writes them, must reach every reader intact: the REST list, detail
and `/entities` routes, the coverage report, and the MCP tools an agent uses.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from e2e_support import REPO_ROOT, make_fixture_repo, requires_joern_image
from httpx import ASGITransport, AsyncClient

from wadi_config import WadiSettings
from wadi_contracts import JobType
from wadi_joern_client import JoernClient
from wadi_mcp.service import WadiMcpService
from wadi_orchestrator.app import create_app
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import RepoCache
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import GraphRepository, StitchRepository, WadiDatabase
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

FIXTURE = REPO_ROOT / "joern-platform" / "fixtures" / "spring-petstore-mini"
EXPECTED_ENDPOINTS = FIXTURE / "expected" / "endpoints.json"
CRUD_MATRIX = REPO_ROOT / "joern-platform" / "fixtures" / "spring-data-crud-matrix"

pytestmark = pytest.mark.integration


@pytest.fixture
def fixture_repo(shared_dir: Path) -> Path:
    """The petstore fixture as a real git repo (what a user would analyze)."""
    return make_fixture_repo(FIXTURE, shared_dir)


@pytest.fixture
def crud_matrix_repo(shared_dir: Path) -> Path:
    """The entity-access fixture: one endpoint per golden (R1-18)."""
    return make_fixture_repo(CRUD_MATRIX, shared_dir)


async def _analyze_and_stitch(
    http: AsyncClient,
    state: AppState,
    joern_url: str,
    database: WadiDatabase,
    graph: GraphRepository,
    *,
    name: str,
    repo: Path,
) -> str:
    """Register, extract through the real Joern, stitch; the snapshot id."""
    created = await http.post(
        "/api/v1/systems", json={"name": name, "repos": [{"source": str(repo)}]}
    )
    assert created.status_code == 201, created.text
    analyzed = await http.post(f"/api/v1/systems/{created.json()['id']}/analyze")
    assert analyzed.status_code == 202, analyzed.text
    snapshot_id: str = analyzed.json()["snapshot"]["id"]

    job = await state.jobs.claim("e2e-worker", types=[JobType.EXTRACT])
    assert job is not None
    joern = JoernClient(joern_url, request_timeout=120)
    try:
        await ExtractionPipeline(
            settings=state.settings,
            systems=state.systems,
            snapshots=state.snapshots,
            artifacts=state.artifacts,
            repo_cache=RepoCache(state.settings.repo_cache_dir),
            extractor=CpgqlJoernExtractor(joern),
        ).run(job)
    finally:
        joern.close()
    assert await state.jobs.complete(job.id, "e2e-worker")

    monitor = SnapshotMonitor(state)
    await monitor.tick()
    stitch = await state.jobs.claim("e2e-stitcher", types=[JobType.STITCH])
    assert stitch is not None
    await StitchPipeline(state.artifacts, StitchRepository(database), graph).run(snapshot_id)
    assert await state.jobs.complete(stitch.id, "e2e-stitcher")
    await monitor.tick()
    snapshot = await http.get(f"/api/v1/snapshots/{snapshot_id}")
    assert snapshot.json()["status"] == "succeeded"
    return snapshot_id


_CRUD = "com.acme.crud"
ORDER = f"{_CRUD}.domain.Order"
SHIPMENT = f"{_CRUD}.domain.Shipment"
AUDIT_ENTRY = f"{_CRUD}.domain.AuditEntry"
ENTITY_NAMES = (
    "AuditEntry",
    "Customer",
    "Invoice",
    "Issue",
    "Order",
    "OrderLine",
    "Pet",
    "Shipment",
    "Ticket",
    # The rigor review's hardening shapes (export 2.15.0).
    "AuditedOrder",
    "Coupon",
    "Note",
    "PetLog",
    "Trip",
)
OPERATIONS = ["create", "read", "update", "delete", "create-or-update", "unknown"]
"""`EntityOperation` in declaration order, which every reader displays in."""

ACCOUNTING_COUNTS = (
    "call_sites",
    "in_endpoint_flow",
    "in_no_endpoint_flow",
    "flush",
    "implemented_in_project",
    "entity_undetermined",
    "unknown_operation",
    "create_or_update",
    "bound",
)

ORDER_SAVE_ROUTES = [
    # Every endpoint whose flow saves an Order: all of them publish
    # create-or-update while both gate flags ship off (§5.2.17).
    ("PUT", "/crud/delete-then-save"),
    ("POST", "/crud/inherited-method-table"),
    ("PUT", "/crud/inherited-save-read-origin"),
    ("PUT", "/crud/repository-default-method"),
    ("POST", "/crud/save-constructed-no-lookup"),
    ("POST", "/crud/save-guard-early-return"),
    ("PUT", "/crud/save-guard-found-arm"),
    ("POST", "/crud/save-guard-not-found-arm"),
    ("PUT", "/crud/save-parameter-callers-agree"),
    ("PUT", "/crud/save-parameter-callers-disagree"),
    ("POST", "/crud/save-parameter-from-request-body"),
    ("PUT", "/crud/save-upsert-by-branch"),
    ("PUT", "/crud/save-via-helper-wrapper"),
    ("PUT", "/crud/two-calls-one-statement"),
]


def _by_operation(row: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    return {
        usage["operation"]: [(e["http_method"], e["full_uri"]) for e in usage["endpoints"]]
        for usage in row["operations"]
    }


def _endpoints_under(row: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    return next(
        usage["endpoints"] for usage in row["operations"] if usage["operation"] == operation
    )


@requires_joern_image
class TestVerticalSlice:
    @pytest.fixture
    async def stack(
        self, database: WadiDatabase, shared_dir: Path, joern_url: str
    ) -> AsyncIterator[tuple[AsyncClient, AppState, str]]:
        settings = WadiSettings(
            _env_file=None,  # type: ignore[call-arg]
            workspace_dir=shared_dir / "workspace",
            cpg_cache_dir=shared_dir / "cpg-cache",
            repo_cache_dir=shared_dir / "repo-cache",
            joern_url=joern_url,
        )
        app = create_app(settings, database=database, run_monitor=False)
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e") as http,
            app.router.lifespan_context(app),
        ):
            yield http, app.state.wadi, joern_url

    async def test_full_slice(
        self,
        stack: tuple[AsyncClient, AppState, str],
        fixture_repo: Path,
        database: WadiDatabase,
        graph_repository: GraphRepository,
    ) -> None:
        http, state, joern_url = stack

        # 1. Register + analyze through the public API.
        created = await http.post(
            "/api/v1/systems",
            json={"name": "petstore-e2e", "repos": [{"source": str(fixture_repo)}]},
        )
        assert created.status_code == 201, created.text
        system_id = created.json()["id"]
        analyzed = await http.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyzed.status_code == 202, analyzed.text
        snapshot_id = analyzed.json()["snapshot"]["id"]

        # 2. The worker claims the job and runs the REAL pipeline against Joern.
        job = await state.jobs.claim("e2e-worker", types=[JobType.EXTRACT])
        assert job is not None
        joern = JoernClient(joern_url, request_timeout=120)
        pipeline = ExtractionPipeline(
            settings=state.settings,
            systems=state.systems,
            snapshots=state.snapshots,
            artifacts=state.artifacts,
            repo_cache=RepoCache(state.settings.repo_cache_dir),
            extractor=CpgqlJoernExtractor(joern),
        )
        try:
            await pipeline.run(job)
        finally:
            joern.close()
        assert await state.jobs.complete(job.id, "e2e-worker")

        # 3. Monitor advances: stitch job → the REAL stitcher runs → succeeds.
        monitor = SnapshotMonitor(state)
        await monitor.tick()
        stitch = await state.jobs.claim("e2e-stitcher", types=[JobType.STITCH])
        assert stitch is not None
        summary = await StitchPipeline(
            state.artifacts, StitchRepository(database), graph_repository
        ).run(snapshot_id)
        assert summary.service_count == 1
        assert summary.endpoint_count == 3
        # The single-service fixture's outbound call resolves to a placeholder:
        # host 'inventory' is a bare name no config in this snapshot knows.
        assert summary.remote_call_count == 1
        assert summary.placeholder == 1
        assert await state.jobs.complete(stitch.id, "e2e-stitcher")
        await monitor.tick()
        snapshot = await http.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "succeeded"

        # 3b. The coverage report is served and honest about the placeholder.
        coverage = (await http.get(f"/api/v1/snapshots/{snapshot_id}/coverage")).json()
        assert coverage["totals"]["placeholder"] == 1
        assert [p["name"] for p in coverage["placeholders"]] == ["inventory"]
        # §5.4.3: the 3 unreached of 9 are Pet's serialization-only getters.
        section = coverage["analysis_coverage"]
        assert section["production_methods"] == 9
        assert section["reachable_methods"] == 6
        assert section["coverage_percent"] == 66.7

        # 4. Conformance diff: endpoints through the public API vs expected JSON.
        services = (await http.get(f"/api/v1/snapshots/{snapshot_id}/services")).json()
        assert len(services) == 1
        service = services[0]
        assert service["name"] == "petstore-mini"
        assert service["languages"] == ["java"]

        endpoints = (
            await http.get(
                f"/api/v1/snapshots/{snapshot_id}/services/{service['service_id']}/endpoints"
            )
        ).json()
        actual = sorted(
            (
                {
                    "http_method": e["http_method"],
                    "full_uri": e["full_uri"],
                    "simplified_uri": e["simplified_uri"],
                }
                for e in endpoints
            ),
            key=lambda e: (e["full_uri"], e["http_method"]),
        )
        expected = sorted(
            json.loads(EXPECTED_ENDPOINTS.read_text()),
            key=lambda e: (e["full_uri"], e["http_method"]),
        )
        assert actual == expected, "endpoint inventory diverged from the conformance fixture"

        # 5. The GET /pets/{id} ICFG crosses DI into the impl and marks sinks.
        get_pet = next(e for e in endpoints if e["simplified_uri"] == "/pets/{?}")
        icfg = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/endpoints/{get_pet['id']}/icfg")
        ).json()
        signatures = {n["method"]["signature"] for n in icfg["nodes"]}
        assert any("PetServiceImpl" in s for s in signatures)
        sink_kinds = {n["sink"] for n in icfg["nodes"] if n.get("sink")}
        assert sink_kinds == {"db", "http-client"}
        remote_marker = next(n for n in icfg["nodes"] if n.get("remote_call_id"))
        assert remote_marker["remote_call_id"].startswith("rc_")

        # 6. Source-on-demand serves the exact pinned text behind an anchor.
        # Joern anchors a method at its declaration INCLUDING annotations, so
        # the handler's window spans "@GetMapping(...)" plus the signature line.
        entry = next(n for n in icfg["nodes"] if n["id"] == icfg["entry_node_id"])
        source = await http.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{service['service_id']}/source",
            params={
                "file": entry["anchor"]["file"],
                "start_line": entry["anchor"]["start_line"],
                "end_line": entry["anchor"]["start_line"] + 1,
            },
        )
        assert source.status_code == 200, source.text
        content = source.json()["content"]
        assert "@GetMapping" in content
        assert "getPet(" in content

    async def test_entity_access_slice(
        self,
        stack: tuple[AsyncClient, AppState, str],
        crud_matrix_repo: Path,
        database: WadiDatabase,
        graph_repository: GraphRepository,
    ) -> None:
        http, state, joern_url = stack
        state.graph = graph_repository  # `/detail` reads the test Neo4j container
        snapshot_id = await _analyze_and_stitch(
            http,
            state,
            joern_url,
            database,
            graph_repository,
            name="crud-matrix-e2e",
            repo=crud_matrix_repo,
        )
        api = f"/api/v1/snapshots/{snapshot_id}"

        # 1. The service's accounting, as the image's jar produced it. The same
        # numbers the sbt-export golden pins (test_real_crud_matrix.py), so the
        # shipped image and the conformance run agree.
        (service,) = (await http.get(f"{api}/services")).json()
        service_id = service["service_id"]
        accounting = service["entity_access_accounting"]
        assert accounting is not None
        assert {key: accounting[key] for key in ACCOUNTING_COUNTS} == {
            "call_sites": 84,
            "in_endpoint_flow": 83,
            "in_no_endpoint_flow": 1,  # the lambda save (R1-1)
            "flush": 1,
            "implemented_in_project": 2,
            # Golden 30's unbindable chain and golden 38's `JpaRepository<E, ...>`.
            "entity_undetermined": 2,
            # M6 leaves the undeclared named query and the Mongo JSON query
            # unknown; the rigor review's six verbs nothing read decides join them.
            "unknown_operation": 8,
            # Every save; golden 34's insert is a create by its name now.
            "create_or_update": 17,
            "bound": 54,
        }

        # 2. The list route: every row was analyzed ([] or rows, never null).
        rows = (await http.get(f"{api}/services/{service_id}/endpoints")).json()
        assert len(rows) == 51  # the plan's 36 and the rigor review's 15
        assert [row["full_uri"] for row in rows if row["entity_access"] is None] == []
        by_route = {(row["http_method"], row["full_uri"]): row for row in rows}

        # 3. /entities: the reverse view, folded at read time (R1-8).
        usage = (await http.get(f"{api}/entities")).json()
        assert (usage["analyzed"], usage["endpoints_predating"]) == (True, 0)
        entities = {row["entity"]: row for row in usage["entities"]}
        # Every DataModel of the snapshot, plus the service's undetermined row.
        assert set(entities) == {
            *(f"{_CRUD}.domain.{name}" for name in ENTITY_NAMES),
            f"{_CRUD}.billing.Account",
            f"{_CRUD}.crm.Account",
            None,
        }
        order_dm = entities[ORDER]["data_model_id"]
        assert order_dm.startswith("dm_")
        # A declared entity no endpoint reaches is a row with six empty lists (Q6).
        shipment = entities[SHIPMENT]
        assert [op["operation"] for op in shipment["operations"]] == OPERATIONS
        assert all(op["endpoints"] == [] for op in shipment["operations"])
        # The repository-only entity: named by its repository alone (Q1).
        audit = entities[AUDIT_ENTRY]
        assert audit["declared_by"] == "repository-argument"
        assert _by_operation(audit)["read"] == [("GET", "/crud/repository-only-entity")]
        # The verb was read, the entity was not (golden 30, R1-25).
        undetermined = entities[None]
        assert undetermined["name"] == "entity not determined"
        assert _by_operation(undetermined)["read"] == [
            ("GET", "/crud/marker-receiver-unbound-entity"),
            ("GET", "/crud/unbindable-entity-chain"),
        ]
        assert [s["accounting"] for s in usage["services"]] == [accounting]
        assert [s["status"] for s in usage["services"]] == ["reporting"]
        # 1.27.0: under each operation, the endpoint's sites for that operation.
        # Golden 34 makes 11 calls on Order, three of them deletes (review C1).
        table = ("POST", "/crud/inherited-method-table")
        assert [
            (endpoint["full_uri"], endpoint["call_sites"])
            for endpoint in _endpoints_under(entities[ORDER], "delete")
            if (endpoint["http_method"], endpoint["full_uri"]) == table
        ] == [("/crud/inherited-method-table", 3)]

        find_row = by_route[("GET", "/crud/inherited-find-by-id")]
        assert find_row["entity_access"] == [
            {
                "entity": ORDER,
                "data_model_id": order_dm,
                "operations": ["read"],
                "call_sites": 1,
                "call_sites_by_operation": {"read": 1},
            }
        ]
        forwarding = by_route[("PUT", "/crud/forwarding-endpoint")]
        assert forwarding["entity_access"] == []

        # 4. The detail routes carry the same summary as the list row.
        detail = (await http.get(f"{api}/endpoints/{find_row['id']}")).json()
        assert detail["entity_access"] == find_row["entity_access"]
        view = (await http.get(f"{api}/endpoints/{forwarding['id']}/detail")).json()
        assert view["endpoint"]["entity_access"] == []
        assert view["stitched"] is True
        assert len(view["outbound"]) == 1

        # 5. The coverage report's entity section sums the boundary accounting.
        section = (await http.get(f"{api}/coverage")).json()["entity_coverage"]
        assert (section["services_reporting"], section["services_predating"]) == (1, 0)
        assert {key: section[key] for key in ACCOUNTING_COUNTS} == {
            key: accounting[key] for key in ACCOUNTING_COUNTS
        }
        assert section["accesses_by_operation"] == accounting["accesses_by_operation"]
        assert section["sites_by_basis"] == accounting["sites_by_basis"]
        assert [s["accounting"] for s in section["by_service"]] == [accounting]
        assert sorted(section["unmeasured"]) == [
            "cascaded-operations",
            "dirty-checking-updates",
            "other-persistence-mechanisms",
        ]
        # Every operation and basis is exercised: `create` by golden 34's insert
        # (by its name), `update` by golden 8's query text. Neither comes from a
        # save, which the shipped flags withhold: the section says so (C6).
        assert section["unexercised_vocabulary"] == []
        assert section["gated_operations"] == ["create", "update"]

        # 6. MCP, through the service object the server registers.
        mcp = WadiMcpService(database, graph_repository)

        # A forwarding endpoint: no repository call, and where the work went (Q26).
        forwarded = await mcp.endpoint_detail(snapshot_id, forwarding["id"])
        assert (forwarded["entity_access"], forwarded["entity_facts"]) == ([], "analyzed")
        assert forwarded["stitched"] is True
        assert len(forwarded["outbound"]) == 1
        assert "ts-station-service" in forwarded["outbound"][0]["url"]

        # endpoint_icfg: two repository calls in one statement are two sites
        # on one call row (R1-2), at the default detail level.
        two_calls = by_route[("PUT", "/crud/two-calls-one-statement")]
        icfg = await mcp.endpoint_icfg(snapshot_id, two_calls["id"])
        assert icfg["entity_facts"] == "analyzed"
        carrying = [
            call["entity_access_sites"]
            for method in icfg["methods"]
            for call in method["calls"]
            if "entity_access_sites" in call
        ]
        assert [sorted(site["method_name"] for site in sites) for sites in carrying] == [
            ["findById", "save"]
        ]
        save_site = next(site for site in carrying[0] if site["method_name"] == "save")
        assert save_site["basis"] == "argument-origin"
        assert save_site["accesses"] == [
            {
                "entity": ORDER,
                "data_model_id": order_dm,
                "operation": "create-or-update",
                "candidate_operation": "update",  # evidence, never a claim (R1-11)
                # ...and MCP says so in words, for an agent with no code to check.
                "candidate_note": "candidate (gated, not published): update",
            }
        ]

        # R1-5: one save that is create OR update reads as its own operation,
        # never as a create plus an update. Over MCP the endpoint's summary has
        # the one value, and the reverse view lists it in that column alone.
        constructed = ("POST", "/crud/save-constructed-no-lookup")
        summary = await mcp.endpoint_detail(snapshot_id, by_route[constructed]["id"])
        assert [
            (row["entity"], row["operations"], row["call_sites"])
            for row in summary["entity_access"]
        ] == [(ORDER, ["create-or-update"], 1)]
        order_usage = await mcp.entity_usage(snapshot_id, entity=ORDER)
        (order_row,) = order_usage["entities"]
        order_ops = _by_operation(order_row)
        assert list(order_ops) == OPERATIONS
        # No save publishes a single verb (R1-5). The one update is golden 8's
        # `update Order o set ...`, read from its query text (M6).
        assert order_ops["create"] == []
        assert order_ops["update"] == [("PUT", "/crud/query-jpql-update-modifying")]
        assert [op for op, routes in order_ops.items() if constructed in routes] == [
            "create-or-update"
        ]
        assert order_ops["create-or-update"] == ORDER_SAVE_ROUTES
        # A simple name answers when it names one entity, and refuses when it
        # names two (C2: billing.Account and crm.Account).
        shipment_usage = await mcp.entity_usage(snapshot_id, entity="Shipment")
        assert [row["entity"] for row in shipment_usage["entities"]] == [SHIPMENT]
        with pytest.raises(ValueError, match="names 2 entities"):
            await mcp.entity_usage(snapshot_id, entity="Account")
