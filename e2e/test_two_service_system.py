"""The Phase 2 conformance e2e: cross-service stitching, for real (§11.2).

Analyzes the petstore-system fixture (two Maven modules + compose +
application.yml) through the REAL wadi-joern container, runs the REAL
stitcher (phone book → matcher → Mongo truth → coverage → Neo4j), and
verifies through the public API only: stitched edges with confidence and
provenance, the coverage report's honest unknowns, structured endpoint auth,
declared params, and restitch convergence.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from e2e_support import REPO_ROOT, make_fixture_repo, requires_joern_image
from httpx import ASGITransport, AsyncClient

from wadi_config import WadiSettings
from wadi_contracts import CONTRACT_MODELS, ExportManifest, JobType
from wadi_joern_client import JoernClient
from wadi_orchestrator.app import create_app
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import RepoCache
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import GraphRepository, StitchRepository, WadiDatabase
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

FIXTURE = REPO_ROOT / "joern-platform" / "fixtures" / "petstore-system"
EXPECTED_DIR = FIXTURE / "expected"

pytestmark = pytest.mark.integration


@pytest.fixture
def system_repo(shared_dir: Path) -> Path:
    return make_fixture_repo(FIXTURE, shared_dir)


@requires_joern_image
class TestTwoServiceSystem:
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

    async def _run_stitch(
        self,
        state: AppState,
        database: WadiDatabase,
        graph: GraphRepository,
        snapshot_id: str,
        worker: str,
    ) -> None:
        stitch = await state.jobs.claim(worker, types=[JobType.STITCH])
        assert stitch is not None
        await StitchPipeline(state.artifacts, StitchRepository(database), graph).run(snapshot_id)
        assert await state.jobs.complete(stitch.id, worker)

    async def test_cross_service_stitching(
        self,
        stack: tuple[AsyncClient, AppState, str],
        system_repo: Path,
        database: WadiDatabase,
        graph_repository: GraphRepository,
    ) -> None:
        http, state, joern_url = stack
        state.graph = graph_repository  # the app reads the test Neo4j container

        # 1. Register + analyze: one repo, two discovered services.
        created = await http.post(
            "/api/v1/systems",
            json={"name": "petstore-system-e2e", "repos": [{"source": str(system_repo)}]},
        )
        assert created.status_code == 201, created.text
        system_id = created.json()["id"]
        analyzed = await http.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyzed.json()["snapshot"]["id"]

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
        await self._run_stitch(state, database, graph_repository, snapshot_id, "e2e-stitcher")
        await monitor.tick()
        assert (await http.get(f"/api/v1/snapshots/{snapshot_id}")).json()["status"] == "succeeded"

        # 2. Both services discovered with their compose/application identities,
        # and the shared module classified as a LIBRARY boundary (§5.2.6) —
        # queryable, never analyzed as a service.
        all_boundaries = (await http.get(f"/api/v1/snapshots/{snapshot_id}/services")).json()
        assert {s["name"]: s["kind"] for s in all_boundaries} == {
            "petstore": "service",
            "inventory": "service",
            "petstore-common": "library",
        }
        by_name = {s["name"]: s for s in all_boundaries if s["kind"] == "service"}
        assert by_name["inventory"]["network"]["hostnames"] == ["inventory"]
        assert by_name["inventory"]["network"]["application_name"] == "inventory"
        assert by_name["petstore"]["network"]["env"]["inventory.url"] == "http://inventory:8081"
        # The staged source union is recorded on the dependent service.
        assert by_name["petstore"]["library_roots"] == ["common"]
        assert by_name["petstore"]["extraction_error"] is None

        # 3. Endpoint inventories diff against the fixture's expected JSON.
        for name, service in by_name.items():
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
                json.loads((EXPECTED_DIR / name / "endpoints.json").read_text()),
                key=lambda e: (e["full_uri"], e["http_method"]),
            )
            assert actual == expected, f"{name} endpoint inventory diverged"

        # 4. Coverage FIRST (P10): the report states exactly what is unknown.
        coverage = (await http.get(f"/api/v1/snapshots/{snapshot_id}/coverage")).json()
        totals = coverage["totals"]
        # T1 set + the full T2 idiom set: RestClient (x2 incl. base-bound),
        # UriComponentsBuilder, RequestEntity, feign inherited/method=/
        # constant-name/url=${key}, ternary, StringBuilder, join, MessageFormat,
        # member map, ctor @Value
        assert totals["analyzed"] == 20
        # audit.example.com: branch candidate + the hierarchy-chain report sink
        assert totals["external"] == 3  # audit branch + hierarchy sink + @HttpExchange feed
        assert totals["undetermined"] == 3  # no-endpoint-match + getenv idiom + base-undetermined
        assert totals["placeholder"] == 2  # billing + backup-inventory (ternary branch)
        # T1 honesty inventory (§5.2.5): excluded from the map, counted here.
        assert totals["unreachable_call_sites"] == 1  # OrphanedAuditNotifier
        assert totals["suspected_call_sites"] == 1  # LegacyBillingBridge (unresolved receiver)
        assert [e["host"] for e in coverage["external_apis"]] == ["audit.example.com"]
        assert coverage["external_apis"][0]["call_count"] == 3
        assert {(p["name"], p["resolved_via"]) for p in coverage["placeholders"]} == {
            ("billing", "bare-hostname"),
            ("backup-inventory", "bare-hostname"),
        }
        reasons = sorted(entry["reason_code"] for entry in coverage["unresolved"])
        # T2: named causes — the DB-row trap now says getenv, the injected
        # WebClient's relative path says base-undetermined.
        assert reasons == ["base-undetermined", "no-endpoint-match", "unsupported-idiom:getenv"]
        # §5.4.2 census: the fixture's JDK-HttpClient probe is an unmodelled
        # mechanism — present and SAID to be present, never a silent zero.
        unmodelled = [
            (m["mechanism"], len(m["service_ids"])) for m in coverage["unmodelled_mechanisms"]
        ]
        assert unmodelled == [("jdk-httpclient", 1)]
        # §5.4.3 analysis coverage: production-vs-reachable methods per service.
        # Petstore's 5 unreached = the T1 unreachable-inventory classes +
        # framework-invoked roots; inventory's 1 = SecurityConfig.filterChain.
        # Staged common-library sources (wadi-libs/) count in NO denominator,
        # and the library itself never gets an entry (§5.2.6).
        section = coverage["analysis_coverage"]
        per_service = {e["name"]: e for e in section["services"]}
        assert set(per_service) == {"petstore", "inventory"}
        assert per_service["petstore"]["production_methods"] == 35
        assert per_service["petstore"]["reachable_methods"] == 30
        assert per_service["inventory"]["production_methods"] == 9
        assert per_service["inventory"]["reachable_methods"] == 8
        assert section["production_methods"] == 44
        assert section["reachable_methods"] == 38
        assert section["coverage_percent"] == 86.4

        # 5. Stitched edges through the public API, with confidence + provenance.
        petstore_id = by_name["petstore"]["service_id"]
        inventory_id = by_name["inventory"]["service_id"]
        outbound = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/services/{petstore_id}/remote-edges")
        ).json()["outbound"]
        analyzed_edges = [e for e in outbound if e["target_kind"] == "analyzed"]
        assert len(analyzed_edges) == 20
        # §5.2.6: the shared-module DTO resolved through the staged union — the
        # DI signature matched exactly and the call stitched to the inventory.
        summary_edge = next(
            e for e in analyzed_edges if e["url"] == "http://inventory:8081/stock/{?}"
        )
        assert summary_edge["target_simplified_uri"] == "/stock/{?}"
        assert summary_edge["http_verb"] == "GET"
        by_url = {e["url"]: e for e in analyzed_edges}
        rest_edge = by_url["${inventory.url}/stock/{?}"]
        assert rest_edge["target_simplified_uri"] == "/stock/{?}"
        assert rest_edge["confidence"] == "high"
        assert rest_edge["provenance"] == "config-resolved"
        feign_edge = next(e for e in analyzed_edges if e["mechanism"] == "feign")
        assert feign_edge["target_simplified_uri"] == "/api/v1/inventory/stock/{?}"
        assert feign_edge["confidence"] == "high"
        # The service-registry idiom (DI interface -> constant map) stitched too.
        registry_edge = by_url["http://inventory/stock/{?}"]
        assert registry_edge["target_simplified_uri"] == "/stock/{?}"
        assert registry_edge["confidence"] == "high"
        # T1: the long-concat exchange() carries its argument verb end to end.
        reserve_edge = by_url["http://inventory/stock/reserve/{?}/{?}"]
        assert reserve_edge["http_verb"] == "PUT"
        assert reserve_edge["target_simplified_uri"] == "/stock/reserve/{?}/{?}"
        assert reserve_edge["confidence"] == "high"
        # T1: the WebClient fluent chain stitches with its own mechanism label.
        webclient_edge = by_url["http://inventory:8081/admin/restock"]
        assert webclient_edge["mechanism"] == "webclient"
        assert webclient_edge["http_verb"] == "POST"
        assert webclient_edge["target_simplified_uri"] == "/admin/restock"
        # T2: the RestClient fluent chain — the yas idiom, now a first-class edge.
        restclient_edge = by_url["${inventory.api.url}/api/v1/inventory/stock/{?}"]
        assert restclient_edge["mechanism"] == "restclient"
        assert restclient_edge["http_verb"] == "GET"
        assert restclient_edge["target_simplified_uri"] == "/api/v1/inventory/stock/{?}"
        assert restclient_edge["confidence"] == "high"
        assert restclient_edge["provenance"] == "config-resolved"
        # T2: the UriComponentsBuilder chain — base + path steps, query skipped.
        ucb_edge = by_url["${inventory.api.url}/stock/{?}"]
        assert ucb_edge["target_simplified_uri"] == "/stock/{?}"
        assert ucb_edge["http_verb"] == "GET"
        assert ucb_edge["confidence"] == "high"
        # T2: RequestEntity-form exchange — verb + URI.create URL off-call-site;
        # the literal "/1" segment is absorbed by the {count} template.
        entity_edge = by_url["${inventory.api.url}/stock/reserve/{?}/1"]
        assert entity_edge["target_simplified_uri"] == "/stock/reserve/{?}/{?}"
        assert entity_edge["http_verb"] == "PUT"
        assert entity_edge["confidence"] == "high"
        # T2 feign completeness: inherited contract + constant-name clients.
        inherited_edge = by_url["http://inventory/api/v1/inventory/reserved/{id}"]
        assert inherited_edge["mechanism"] == "feign"
        assert inherited_edge["target_simplified_uri"] == "/api/v1/inventory/reserved/{?}"
        named_edge = by_url["http://inventory/api/v1/inventory/audit/{id}"]
        assert named_edge["target_simplified_uri"] == "/api/v1/inventory/audit/{?}"
        # T2 base recovery: RestClient.create(base) + relative uri stitches HIGH.
        bound_edge = next(
            e
            for e in analyzed_edges
            if e["mechanism"] == "restclient" and e["url"] == "${inventory.api.url}/stock/{?}"
        )
        assert bound_edge["confidence"] == "high"
        # T2 declarative @HttpExchange: an external edge with its own mechanism.
        feed_edge = next(e for e in outbound if e["mechanism"] == "http-interface")
        assert feed_edge["target_kind"] == "external"
        assert feed_edge["external_host"] == "audit.example.com"

        inbound = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/services/{inventory_id}/remote-edges")
        ).json()["inbound"]
        assert len(inbound) == 20  # every analyzed idiom lands on inventory

        # 6. Structured auth arrived on the wire (goal 9).
        inventory_endpoints = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/services/{inventory_id}/endpoints")
        ).json()
        by_uri = {e["simplified_uri"]: e for e in inventory_endpoints}
        restock_auth = by_uri["/admin/restock"]["auth"]
        assert restock_auth["authenticated"] is True
        assert restock_auth["roles"] == ["ADMIN"]
        assert {ev["kind"] for ev in restock_auth["evidence"]} == {
            "annotation",
            "security-dsl",
        }
        assert by_uri["/stock/{?}"]["auth"]["authenticated"] is False  # permitAll, evidenced

        # 7. Declared params survived to the public API.
        petstore_endpoints = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/services/{petstore_id}/endpoints")
        ).json()
        pets_by_uri = {e["simplified_uri"]: e for e in petstore_endpoints}
        assert pets_by_uri["/pets/{?}"]["params"] == [
            {"name": "id", "location": "path", "type_name": "java.lang.String", "required": True}
        ]

        # 8. Recovery: restitch converges to the identical edge set.
        edges_before = sorted(e["edge_id"] for e in outbound)
        restitched = await http.post(f"/api/v1/snapshots/{snapshot_id}/restitch")
        assert restitched.status_code == 202, restitched.text
        await self._run_stitch(state, database, graph_repository, snapshot_id, "e2e-restitcher")
        await monitor.tick()
        assert (await http.get(f"/api/v1/snapshots/{snapshot_id}")).json()["status"] == "succeeded"
        outbound_after = (
            await http.get(f"/api/v1/snapshots/{snapshot_id}/services/{petstore_id}/remote-edges")
        ).json()["outbound"]
        assert sorted(e["edge_id"] for e in outbound_after) == edges_before

        # 9. Export (§14): every record re-validates against its published
        # contract, the manifest trailer's counts are authoritative, and two
        # exports differ ONLY in the manifest's produced_at (determinism rule).
        first = await http.get(f"/api/v1/snapshots/{snapshot_id}/export")
        assert first.status_code == 200, first.text
        first_lines = [line for line in first.text.splitlines() if line.strip()]
        records = [json.loads(line) for line in first_lines]
        assert records[0]["kind"] == "system"
        assert records[-1]["kind"] == "manifest"
        manifest = ExportManifest.model_validate(records[-1]["artifact"])
        received: dict[str, int] = {}
        for record in records[:-1]:
            received[record["kind"]] = received.get(record["kind"], 0) + 1
            CONTRACT_MODELS[record["kind"]].model_validate(record["artifact"])
        assert manifest.artifact_counts == dict(sorted(received.items()))
        # The bundle mirrors the API's own answers.
        assert received["service_boundary"] == 3  # petstore + inventory + the library
        assert received["endpoint"] == 14
        assert received["icfg"] == 14
        assert received["stitched_edge"] == coverage["totals"]["edges"]
        assert received["coverage_report"] == 1

        second = await http.get(f"/api/v1/snapshots/{snapshot_id}/export")
        second_lines = [line for line in second.text.splitlines() if line.strip()]
        assert first_lines[:-1] == second_lines[:-1]  # byte-identical artifacts
        first_manifest = json.loads(first_lines[-1])["artifact"]
        second_manifest = json.loads(second_lines[-1])["artifact"]
        assert first_manifest.pop("produced_at") != ""
        assert second_manifest.pop("produced_at") != ""
        assert first_manifest == second_manifest
