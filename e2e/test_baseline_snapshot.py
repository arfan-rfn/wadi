"""Standing benchmark-baseline harness (§5.4.3; introduced with Phase 2.5 M1).

Opt-in, never runs in CI: point ``WADI_BASELINE_REPO`` at a benchmark repo
(local path or git URL) and run

    WADI_BASELINE_REPO=~/repos/train-ticket uv run pytest e2e/test_baseline_snapshot.py -q -s

It analyzes the repo through the REAL wadi-joern container and the in-process
worker/stitcher (identical wiring to the conformance e2e), then prints the
snapshot's pinned commits, endpoint total, and the full analysis-coverage
section — the numbers recorded in commit messages and tranche issues, and the
before/after instrument for the T2/T3/T4 accuracy work.
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from e2e_support import requires_joern_image
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

BASELINE_REPO = os.environ.get("WADI_BASELINE_REPO", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not BASELINE_REPO,
        reason="baseline harness is opt-in — set WADI_BASELINE_REPO to a repo path/URL",
    ),
]


@requires_joern_image
class TestBaselineSnapshot:
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
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://baseline", timeout=60
            ) as http,
            app.router.lifespan_context(app),
        ):
            yield http, app.state.wadi, joern_url

    async def test_record_baseline(
        self,
        stack: tuple[AsyncClient, AppState, str],
        database: WadiDatabase,
        graph_repository: GraphRepository,
    ) -> None:
        http, state, joern_url = stack
        state.graph = graph_repository

        is_url = "://" in BASELINE_REPO
        source = BASELINE_REPO if is_url else str(Path(BASELINE_REPO).expanduser())
        name = source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        created = await http.post(
            "/api/v1/systems", json={"name": f"baseline-{name}", "repos": [{"source": source}]}
        )
        assert created.status_code == 201, created.text
        system_id = created.json()["id"]
        analyzed = await http.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyzed.status_code in (200, 202), analyzed.text
        snapshot_id = analyzed.json()["snapshot"]["id"]

        job = await state.jobs.claim("baseline-worker", types=[JobType.EXTRACT])
        assert job is not None
        # Benchmark services can be far larger than the fixtures — a generous
        # per-request budget, not the e2e's 120s.
        joern = JoernClient(joern_url, request_timeout=1800)
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
        assert await state.jobs.complete(job.id, "baseline-worker")

        monitor = SnapshotMonitor(state)
        await monitor.tick()
        stitch_job = await state.jobs.claim("baseline-stitcher", types=[JobType.STITCH])
        assert stitch_job is not None
        await StitchPipeline(state.artifacts, StitchRepository(database), graph_repository).run(
            snapshot_id
        )
        assert await state.jobs.complete(stitch_job.id, "baseline-stitcher")
        await monitor.tick()

        snapshot = (await http.get(f"/api/v1/snapshots/{snapshot_id}")).json()
        assert snapshot["status"] == "succeeded", snapshot.get("error")

        boundaries = (await http.get(f"/api/v1/snapshots/{snapshot_id}/services")).json()
        endpoint_total = 0
        for service in boundaries:
            if service["kind"] != "service":
                continue
            endpoints = (
                await http.get(
                    f"/api/v1/snapshots/{snapshot_id}/services/{service['service_id']}/endpoints"
                )
            ).json()
            endpoint_total += len(endpoints)
        coverage = (await http.get(f"/api/v1/snapshots/{snapshot_id}/coverage")).json()

        print(f"\n=== baseline: {name} ===")
        print(f"commits: {snapshot['commits']}")
        services = [s for s in boundaries if s["kind"] == "service"]
        libraries = [s["name"] for s in boundaries if s["kind"] == "library"]
        print(f"services: {len(services)}   libraries: {sorted(libraries)}")
        print(f"endpoints: {endpoint_total}")
        print(f"totals: {json.dumps(coverage['totals'])}")
        print("analysis_coverage:")
        section = coverage["analysis_coverage"]
        print(
            f"  snapshot: {section['reachable_methods']}/{section['production_methods']}"
            f" ({section['coverage_percent']}%)"
        )
        for entry in section["services"]:
            if entry["production_methods"] is None:
                print(f"  - {entry['name']}: unknown")
            else:
                print(
                    f"  - {entry['name']}: {entry['reachable_methods']}/"
                    f"{entry['production_methods']} ({entry['coverage_percent']}%)"
                )

        # §5.2.8 M2: the per-release CFG-fidelity number — anomaly totals per
        # code plus who was never checked. "the weird code lives in real repos."
        anomalies = coverage.get("cfg_anomalies")
        if anomalies is None:
            print("cfg_anomalies: unknown (report predates the invariants)")
        else:
            totals = anomalies["total_by_code"]
            print(f"cfg_anomalies: {json.dumps(totals) if totals else 'none'}")
            unchecked = [s["name"] for s in anomalies["services"] if not s["checked"]]
            if unchecked:
                print(f"  never checked: {', '.join(sorted(unchecked))}")

        # §5.2.7 spot-check: one recovered response schema, for hand-verification
        # against the target repo's source.
        def _shape_summary(shape: dict[str, Any], depth: int = 0) -> str:
            if shape is None:
                return "-"
            kind = shape.get("kind")
            if kind == "object" and depth < 2:
                inner = ", ".join(
                    f["name"] + ":" + _shape_summary(f["shape"], depth + 1)
                    for f in shape.get("fields", [])[:8]
                )
                return f"{shape['type_name']}{{{inner}}}"
            if kind == "array":
                return f"[{_shape_summary(shape.get('element') or {}, depth + 1)}]"
            return f"{shape.get('type_name')}<{kind}>"

        # The shapes are NOT on a list row since §5.2.15 — they arrive with the
        # per-endpoint detail. Reading them off the list still "worked" here:
        # `next(..., None)` found nothing and the spot-check printed nothing,
        # silently, which is the failure mode this repo treats as worse than a
        # red test. Walk a bounded prefix of each service's endpoints instead.
        found_shape = False
        for service in boundaries:
            if service["kind"] != "service" or found_shape:
                continue
            endpoints = (
                await http.get(
                    f"/api/v1/snapshots/{snapshot_id}/services/{service['service_id']}/endpoints"
                )
            ).json()
            for row in endpoints[:25]:
                detail = (
                    await http.get(f"/api/v1/snapshots/{snapshot_id}/endpoints/{row['id']}/detail")
                ).json()
                shape = detail["endpoint"].get("response_schema") or {}
                if shape.get("kind") != "object":
                    continue
                print(
                    f"schema spot-check: {service['name']} {row['http_method']} "
                    f"{row['full_uri']} -> {_shape_summary(shape)}"
                )
                found_shape = True
                break
        if not found_shape:
            # A baseline that stops reporting a fact must say so, or the next
            # reader takes silence for "this corpus has no object shapes".
            print("schema spot-check: no object response shape in the sampled prefix")
