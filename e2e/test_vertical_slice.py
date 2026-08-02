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
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from e2e_support import REPO_ROOT, make_fixture_repo, requires_joern_image
from httpx import ASGITransport, AsyncClient

from wadi_config import WadiSettings
from wadi_contracts import JobType
from wadi_joern_client import JoernClient
from wadi_orchestrator.app import create_app
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import RepoCache
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import GraphRepository, StitchRepository, WadiDatabase
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

FIXTURE = REPO_ROOT / "joern-platform" / "fixtures" / "spring-petstore-mini"
EXPECTED_ENDPOINTS = FIXTURE / "expected" / "endpoints.json"

pytestmark = pytest.mark.integration


@pytest.fixture
def fixture_repo(shared_dir: Path) -> Path:
    """The petstore fixture as a real git repo (what a user would analyze)."""
    return make_fixture_repo(FIXTURE, shared_dir)


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
