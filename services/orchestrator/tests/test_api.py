"""Orchestrator API integration tests (real Mongo, real git, ASGI client)."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from wadi_orchestrator.state import AppState
from wadi_testing.builders import make_endpoint, make_icfg, make_service, make_snapshot

pytestmark = pytest.mark.integration


async def _register_system(client: AsyncClient, sample_repo: Path, name: str = "shop") -> str:
    response = await client.post(
        "/api/v1/systems",
        json={"name": name, "repos": [{"source": str(sample_repo), "branch": "main"}]},
    )
    assert response.status_code == 201, response.text
    system_id: str = response.json()["id"]
    return system_id


class TestHealth:
    async def test_healthz(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestSystems:
    async def test_create_and_get(self, client: AsyncClient, sample_repo: Path) -> None:
        system_id = await _register_system(client, sample_repo)
        assert system_id.startswith("sys_")
        fetched = await client.get(f"/api/v1/systems/{system_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "shop"

    async def test_duplicate_name_conflict(self, client: AsyncClient, sample_repo: Path) -> None:
        await _register_system(client, sample_repo)
        response = await client.post(
            "/api/v1/systems",
            json={"name": "shop", "repos": [{"source": str(sample_repo)}]},
        )
        assert response.status_code == 409

    async def test_validation_rejects_empty_repos(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/systems", json={"name": "x", "repos": []})
        assert response.status_code == 422

    async def test_missing_system_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/systems/sys_" + "0" * 32)
        assert response.status_code == 404

    async def test_list(self, client: AsyncClient, sample_repo: Path) -> None:
        await _register_system(client, sample_repo, "a-system")
        listed = await client.get("/api/v1/systems")
        assert listed.status_code == 200
        assert [s["name"] for s in listed.json()] == ["a-system"]


class TestAnalyze:
    async def test_analyze_pins_sha_and_creates_job(
        self, client: AsyncClient, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        response = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert response.status_code == 202, response.text
        body = response.json()
        snapshot = body["snapshot"]
        assert snapshot["status"] == "running"
        (sha,) = snapshot["commits"].values()
        assert len(sha) == 40
        assert len(body["job_ids"]) == 1

        jobs = await client.get(f"/api/v1/snapshots/{snapshot['id']}/jobs")
        assert jobs.status_code == 200
        assert jobs.json()[0]["type"] == "extract"
        assert jobs.json()[0]["status"] == "pending"

    async def test_analyze_unknown_branch_400(self, client: AsyncClient, sample_repo: Path) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={
                "name": "badbranch",
                "repos": [{"source": str(sample_repo), "branch": "no-such-branch"}],
            },
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyze.status_code == 400
        assert "no-such-branch" in analyze.json()["detail"]

    async def test_analyze_unreachable_repo_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={"name": "ghost", "repos": [{"source": "/nonexistent/path/repo"}]},
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyze.status_code == 400

    async def test_snapshots_listing(self, client: AsyncClient, sample_repo: Path) -> None:
        system_id = await _register_system(client, sample_repo)
        await client.post(f"/api/v1/systems/{system_id}/analyze")
        await client.post(f"/api/v1/systems/{system_id}/analyze")
        listed = await client.get(f"/api/v1/systems/{system_id}/snapshots")
        assert listed.status_code == 200
        assert len(listed.json()) == 2


class TestReadApi:
    async def test_artifact_flow(self, client: AsyncClient, app_state: AppState) -> None:
        """Seed artifacts as the worker would, then read them through the API."""
        from wadi_testing.builders import make_system

        system = make_system("seeded")
        await app_state.systems.insert(system)
        snapshot = make_snapshot(system)
        await app_state.snapshots.insert(snapshot)
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)
        icfg = make_icfg(snapshot, boundary, endpoint)
        await app_state.artifacts.write_service_boundaries([boundary])
        await app_state.artifacts.write_endpoints([endpoint])
        await app_state.artifacts.write_icfg(icfg)

        services = await client.get(f"/api/v1/snapshots/{snapshot.id}/services")
        assert services.status_code == 200
        assert services.json()[0]["service_id"] == boundary.service_id
        assert services.json()[0]["endpoint_count"] == 1  # derived view field (§7 views)

        endpoints = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{boundary.service_id}/endpoints"
        )
        assert endpoints.status_code == 200
        assert endpoints.json()[0]["id"] == endpoint.id

        single = await client.get(f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}")
        assert single.status_code == 200

        graph = await client.get(f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/icfg")
        assert graph.status_code == 200
        assert len(graph.json()["nodes"]) == len(icfg.nodes)

    async def test_404s(self, client: AsyncClient) -> None:
        missing_snap = "snap_" + "0" * 32
        assert (await client.get(f"/api/v1/snapshots/{missing_snap}")).status_code == 404
        assert (await client.get(f"/api/v1/snapshots/{missing_snap}/services")).status_code == 404
        assert (
            await client.get(f"/api/v1/snapshots/{missing_snap}/endpoints/ep_{'0' * 16}")
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/snapshots/{missing_snap}/endpoints/ep_{'0' * 16}/icfg")
        ).status_code == 404


class TestSourceOnDemand:
    async def test_reads_pinned_source(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]

        # Seed the boundary the worker would discover (build root at repo root).
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        snapshot = await app_state.snapshots.get(snapshot_id)
        assert snapshot is not None
        repo_key = normalize_repo_source(str(sample_repo))
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=repo_key,
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])

        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{boundary.service_id}/source",
            params={"file": "src/App.java", "start_line": 2, "end_line": 3},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "  int x;\n  int y;\n"
        assert body["variant"] == "original"

    async def test_missing_file_404(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{boundary.service_id}/source",
            params={"file": "src/Ghost.java"},
        )
        assert response.status_code == 404

    async def _seed_boundary(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> tuple[str, str]:
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])
        return snapshot_id, boundary.service_id

    async def test_whole_file_when_end_line_omitted(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """§11 Phase 2.7: on-demand whole-file serving with an honest length."""
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src/App.java"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "class App {\n  int x;\n  int y;\n}\n"
        assert body["start_line"] == 1
        assert body["end_line"] == 4
        assert body["total_lines"] == 4
        assert body["truncated"] is False

    async def test_window_beyond_cap_is_truncated_honestly(
        self,
        client: AsyncClient,
        app_state: AppState,
        sample_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A window larger than the server cap is cut and SAID to be cut."""
        import wadi_orchestrator.app as app_module

        monkeypatch.setattr(app_module, "SOURCE_MAX_LINES", 2)
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src/App.java"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "class App {\n  int x;\n"
        assert body["end_line"] == 2
        assert body["total_lines"] == 4
        assert body["truncated"] is True

    async def test_directory_path_is_400_not_content(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """A tree path must never be served as file content."""
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src"},
        )
        assert response.status_code == 400
        assert "not a file" in response.json()["detail"]


class TestMonitor:
    async def test_full_lifecycle_via_monitor_ticks(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """extract succeeds → stitch enqueued → stitch succeeds → snapshot SUCCEEDED."""
        from wadi_orchestrator.monitor import SnapshotMonitor

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        monitor = SnapshotMonitor(app_state)

        # Simulate the worker completing the extract job.
        extract = await app_state.jobs.claim("test-worker")
        assert extract is not None
        assert await app_state.jobs.complete(extract.id, "test-worker")

        await monitor.tick()  # sees extraction done → enqueues stitch
        jobs = await app_state.jobs.list_for_snapshot(snapshot_id)
        assert [j.type.value for j in jobs] == ["extract", "stitch"]

        stitch = await app_state.jobs.claim("stitch-worker")
        assert stitch is not None
        assert await app_state.jobs.complete(stitch.id, "stitch-worker")

        await monitor.tick()  # sees stitch done → snapshot succeeded
        snapshot = await client.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "succeeded"

    async def test_failed_job_fails_snapshot_loudly(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        from wadi_orchestrator.monitor import SnapshotMonitor

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]

        job = await app_state.jobs.claim("w")
        assert job is not None
        # Exhaust all attempts so the failure is permanent.
        for attempt in range(job.max_attempts):
            await app_state.jobs.fail(job.id, "w", f"boom {attempt}")
            reclaimed = await app_state.jobs.claim("w")
            if reclaimed is None:
                break

        await SnapshotMonitor(app_state).tick()
        snapshot = await client.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "failed"
        assert "boom" in snapshot.json()["error"]


class TestAuth:
    async def test_token_enforced_when_configured(self, database: object, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient
        from orchestrator_support import make_settings
        from pydantic import SecretStr

        from wadi_orchestrator.app import create_app
        from wadi_storage import WadiDatabase

        assert isinstance(database, WadiDatabase)
        settings = make_settings(tmp_path, api_token=SecretStr("s3cret"))
        app = create_app(settings, database=database, run_monitor=False)
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as http,
            app.router.lifespan_context(app),
        ):
            # /healthz stays open for platform probes.
            assert (await http.get("/healthz")).status_code == 200
            # API requires the bearer token.
            assert (await http.get("/api/v1/systems")).status_code == 401
            wrong = await http.get("/api/v1/systems", headers={"Authorization": "Bearer nope"})
            assert wrong.status_code == 401
            right = await http.get("/api/v1/systems", headers={"Authorization": "Bearer s3cret"})
            assert right.status_code == 200


class TestSystemGraph:
    async def test_prestitch_graph_lists_services_with_honest_stitched_flag(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """§11 Phase 2.7 M4: before stitching, services render and the empty
        edge list is 'not yet' (stitched=False), never 'none'."""
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])

        response = await client.get(f"/api/v1/snapshots/{snapshot_id}/graph")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stitched"] is False
        assert body["edges"] == []
        assert [s["name"] for s in body["services"]] == ["sample"]
        service = body["services"][0]
        assert service["endpoint_count"] == 0
        assert service["gateway"] is False
        # cfg_anomalies=None on the boundary → unknown, never zero (P10).
        assert service["cfg_anomaly_count"] is None

    async def test_missing_snapshot_404(self, client: AsyncClient) -> None:
        missing = "snap_" + "0" * 32
        assert (await client.get(f"/api/v1/snapshots/{missing}/graph")).status_code == 404
