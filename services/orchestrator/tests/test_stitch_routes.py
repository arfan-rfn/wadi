"""Stitched-graph routes: coverage, remote-edges, restitch state machine."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from wadi_contracts import (
    CoverageReport,
    CoverageTotals,
    JobStatus,
    JobType,
    Snapshot,
    SnapshotStatus,
)
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_storage import GraphRepository
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_remote_call,
    make_service,
)

pytestmark = pytest.mark.integration


async def _analyzed_snapshot(client: AsyncClient, sample_repo: Path, state: AppState) -> Snapshot:
    """Register + analyze + drive the extract job to success via the queue."""
    response = await client.post(
        "/api/v1/systems",
        json={"name": "shop", "repos": [{"source": str(sample_repo), "branch": "main"}]},
    )
    system_id = response.json()["id"]
    analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
    snapshot = Snapshot.model_validate(analyze.json()["snapshot"])
    job = await state.jobs.claim("test-worker", types=[JobType.EXTRACT])
    assert job is not None
    await state.jobs.complete(job.id, "test-worker")
    return snapshot


def _empty_report(snapshot_id: str) -> CoverageReport:
    return CoverageReport(
        snapshot_id=snapshot_id,
        totals=CoverageTotals(
            call_sites=0, edges=0, analyzed=0, external=0, placeholder=0, undetermined=0
        ),
    )


class TestCoverageRoute:
    async def test_404_before_stitch(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        response = await client.get(f"/api/v1/snapshots/{snapshot.id}/coverage")
        assert response.status_code == 404
        assert "not stitched" in response.json()["detail"]

    async def test_404_unknown_snapshot(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/snapshots/snap_missing/coverage")
        assert response.status_code == 404

    async def test_returns_report(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        await app_state.stitch.write_coverage_report(_empty_report(snapshot.id))
        response = await client.get(f"/api/v1/snapshots/{snapshot.id}/coverage")
        assert response.status_code == 200
        assert response.json()["totals"]["call_sites"] == 0


class TestRemoteEdgesRoute:
    async def test_view_from_graph(
        self,
        client: AsyncClient,
        sample_repo: Path,
        app_state: AppState,
        graph_repository: GraphRepository,
    ) -> None:
        app_state.graph = graph_repository  # point the app at the test Neo4j
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        call = make_remote_call(snapshot, caller)
        edge = make_analyzed_edge(call, target)
        await app_state.artifacts.write_service_boundaries([caller, callee])
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[target],
            remote_calls=[call],
            edges=[edge],
        )
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{caller.service_id}/remote-edges"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["outbound"]) == 1
        assert body["outbound"][0]["target_kind"] == "analyzed"
        assert body["inbound"] == []

    async def test_unknown_service_404(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/svc_{'0' * 16}/remote-edges"
        )
        assert response.status_code == 404


class TestRestitch:
    async def test_restitch_after_failure_recovers(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        monitor = SnapshotMonitor(app_state)
        await monitor.tick()  # enqueue the stitch job
        stitch_job = await app_state.jobs.claim("stitcher", types=[JobType.STITCH])
        assert stitch_job is not None
        await app_state.jobs.fail(stitch_job.id, "stitcher", "neo4j is down")
        # exhaust retries so the job is permanently failed
        for _ in range(2):
            retry = await app_state.jobs.claim("stitcher", types=[JobType.STITCH])
            assert retry is not None
            await app_state.jobs.fail(retry.id, "stitcher", "neo4j is down")
        await monitor.tick()
        failed = await app_state.snapshots.get(snapshot.id)
        assert failed is not None
        assert failed.status is SnapshotStatus.FAILED

        # Recovery: restitch enqueues a fresh stitch job over stored artifacts.
        response = await client.post(f"/api/v1/snapshots/{snapshot.id}/restitch")
        assert response.status_code == 202, response.text
        recovering = await app_state.snapshots.get(snapshot.id)
        assert recovering is not None
        assert recovering.status is SnapshotStatus.RUNNING

        # The old FAILED stitch job is superseded — the monitor must not
        # re-fail the snapshot while the new job is pending.
        await monitor.tick()
        still_running = await app_state.snapshots.get(snapshot.id)
        assert still_running is not None
        assert still_running.status is SnapshotStatus.RUNNING

        new_job = await app_state.jobs.claim("stitcher", types=[JobType.STITCH])
        assert new_job is not None
        await app_state.jobs.complete(new_job.id, "stitcher")
        await monitor.tick()
        recovered = await app_state.snapshots.get(snapshot.id)
        assert recovered is not None
        assert recovered.status is SnapshotStatus.SUCCEEDED

    async def test_restitch_conflicts_with_active_jobs(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={"name": "busy", "repos": [{"source": str(sample_repo), "branch": "main"}]},
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        # extract job still pending
        restitch = await client.post(f"/api/v1/snapshots/{snapshot_id}/restitch")
        assert restitch.status_code == 409
        assert "active jobs" in restitch.json()["detail"]

    async def test_restitch_requires_successful_extraction(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={"name": "broken", "repos": [{"source": str(sample_repo), "branch": "main"}]},
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        for _ in range(3):  # exhaust extract attempts
            job = await app_state.jobs.claim("worker", types=[JobType.EXTRACT])
            assert job is not None
            await app_state.jobs.fail(job.id, "worker", "boom")
        restitch = await client.post(f"/api/v1/snapshots/{snapshot_id}/restitch")
        assert restitch.status_code == 409
        assert "no successful extraction" in restitch.json()["detail"]

    async def test_restitch_unknown_snapshot_404(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/snapshots/snap_missing/restitch")
        assert response.status_code == 404

    async def test_restitch_succeeded_snapshot_rebuilds(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        """Re-stitch of a healthy snapshot is first-class (Tier-2 rebuild, §6)."""
        snapshot = await _analyzed_snapshot(client, sample_repo, app_state)
        monitor = SnapshotMonitor(app_state)
        await monitor.tick()
        stitch_job = await app_state.jobs.claim("stitcher", types=[JobType.STITCH])
        assert stitch_job is not None
        await app_state.jobs.complete(stitch_job.id, "stitcher")
        await monitor.tick()
        response = await client.post(f"/api/v1/snapshots/{snapshot.id}/restitch")
        assert response.status_code == 202
        jobs = await app_state.jobs.list_for_snapshot(snapshot.id)
        stitch_jobs = [j for j in jobs if j.type is JobType.STITCH]
        assert len(stitch_jobs) == 2
        assert any(j.status is JobStatus.PENDING for j in stitch_jobs)
