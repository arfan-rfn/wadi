"""The Phase 1 conformance e2e (§11.8): the whole vertical slice, for real.

Register the spring-petstore-mini fixture as a system → analyze → the
extraction pipeline drives the REAL wadi-joern container over CPGQL → the
stitcher skeleton runs → the snapshot succeeds → the public API serves
endpoints (diffed against the fixture's expected JSON), the ICFG, and
pinned-SHA source.

Requirements: Docker + the ghcr.io/wadi-sh/joern image built at the version in
the VERSION file (`make joern-image`).
Runs via `make e2e`; skipped automatically when prerequisites are missing.

Everything except HTTP-serving runs in-process (orchestrator app via ASGI,
worker/stitcher pipelines driven directly through the same JobQueue they use
in production) — the compose stack adds process boundaries, not logic.
"""

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from wadi_config import WadiSettings
from wadi_contracts import JobType
from wadi_joern_client import JoernClient
from wadi_orchestrator.app import create_app
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import RepoCache
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import WadiDatabase
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
# The image tag tracks the VERSION file, same as the compose pins (§13) and
# the tag CI builds for this test.
JOERN_IMAGE = f"ghcr.io/wadi-sh/joern:{(REPO_ROOT / 'VERSION').read_text().strip()}"
FIXTURE = REPO_ROOT / "joern-platform" / "fixtures" / "spring-petstore-mini"
EXPECTED_ENDPOINTS = FIXTURE / "expected" / "endpoints.json"

pytestmark = pytest.mark.integration


def _docker_image_present() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", JOERN_IMAGE], capture_output=True, check=False
    )
    return probe.returncode == 0


requires_joern_image = pytest.mark.skipif(
    not _docker_image_present(),
    reason=f"{JOERN_IMAGE} not built — run: docker build -t {JOERN_IMAGE} joern-platform/",
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "E2E",
            "GIT_AUTHOR_EMAIL": "e2e@wadi.test",
            "GIT_COMMITTER_NAME": "E2E",
            "GIT_COMMITTER_EMAIL": "e2e@wadi.test",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
        },
    )


@pytest.fixture(scope="module")
def shared_dir() -> Iterator[Path]:
    """Host dir mounted at the SAME path inside the Joern container (§13 topology)."""
    path = Path(tempfile.mkdtemp(prefix="wadi-e2e-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def joern_url(shared_dir: Path) -> Iterator[str]:
    container = f"wadi-e2e-joern-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1:0:8080",
            "--volume",
            f"{shared_dir}:{shared_dir}",
            JOERN_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        port_line = subprocess.run(
            ["docker", "port", container, "8080/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
        url = f"http://127.0.0.1:{port_line.rsplit(':', 1)[1].strip()}"
        client = JoernClient(url, request_timeout=60)
        deadline = time.monotonic() + 180
        while not client.is_ready():
            if time.monotonic() > deadline:
                raise RuntimeError("wadi-joern container never became ready")
            time.sleep(2)
        client.close()
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


@pytest.fixture
def fixture_repo(shared_dir: Path) -> Path:
    """The petstore fixture as a real git repo (what a user would analyze)."""
    repo = shared_dir / f"petstore-{uuid.uuid4().hex[:8]}"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("expected"))
    _git("init", "--initial-branch=main", cwd=repo)
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "petstore fixture", cwd=repo)
    return repo


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
        self, stack: tuple[AsyncClient, AppState, str], fixture_repo: Path
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

        # 3. Monitor advances: stitch job → stitcher runs → snapshot succeeds.
        monitor = SnapshotMonitor(state)
        await monitor.tick()
        stitch = await state.jobs.claim("e2e-stitcher", types=[JobType.STITCH])
        assert stitch is not None
        summary = await StitchPipeline(state.artifacts).run(snapshot_id)
        assert summary.service_count == 1
        assert summary.endpoint_count == 3
        assert await state.jobs.complete(stitch.id, "e2e-stitcher")
        await monitor.tick()
        snapshot = await http.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "succeeded"

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
