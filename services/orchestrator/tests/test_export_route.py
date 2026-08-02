"""Export route (§14): NDJSON stream, manifest trailer, status gating."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from wadi_contracts import (
    CONTRACT_MODELS,
    ExportManifest,
    JobType,
    Snapshot,
    SnapshotStatus,
)
from wadi_orchestrator.state import AppState
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_icfg,
    make_remote_call,
    make_service,
)

pytestmark = pytest.mark.integration


async def _succeeded_snapshot_with_artifacts(
    client: AsyncClient, sample_repo: Path, state: AppState
) -> Snapshot:
    """Register + analyze, materialize a small artifact set, mark succeeded."""
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

    caller = make_service(snapshot, "services/orders")
    callee = make_service(snapshot, "services/billing")
    endpoint = make_endpoint(snapshot, callee, uri="/invoices/{id}")
    call = make_remote_call(snapshot, caller, line=12)
    await state.artifacts.write_service_boundaries([caller, callee])
    await state.artifacts.write_endpoints([endpoint])
    await state.artifacts.write_icfg(make_icfg(snapshot, callee, endpoint))
    await state.artifacts.write_remote_calls([call])
    await state.stitch.replace_stitched_edges(snapshot.id, [make_analyzed_edge(call, endpoint)])
    await state.snapshots.set_status(snapshot.id, SnapshotStatus.SUCCEEDED)
    return snapshot


def _records(body: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in body.splitlines() if line.strip()]


class TestExportRoute:
    async def test_streams_every_artifact_with_manifest_trailer(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        snapshot = await _succeeded_snapshot_with_artifacts(client, sample_repo, app_state)
        response = await client.get(f"/api/v1/snapshots/{snapshot.id}/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")

        records = _records(response.text)
        kinds = [record["kind"] for record in records]
        assert kinds[0] == "system"
        assert kinds[1] == "snapshot"
        assert kinds[-1] == "manifest"

        # The trailer's counts are authoritative and match the stream.
        manifest = ExportManifest.model_validate(records[-1]["artifact"])
        received: dict[str, int] = {}
        for kind in kinds[:-1]:
            received[kind] = received.get(kind, 0) + 1
        assert manifest.artifact_counts == dict(sorted(received.items()))
        assert manifest.snapshot_id == snapshot.id
        assert manifest.artifact_counts["service_boundary"] == 2
        assert manifest.artifact_counts["endpoint"] == 1
        assert manifest.artifact_counts["icfg"] == 1
        assert manifest.artifact_counts["stitched_edge"] == 1

        # Every artifact record re-validates against its published contract.
        for record in records[:-1]:
            CONTRACT_MODELS[record["kind"]].model_validate(record["artifact"])

    async def test_unknown_snapshot_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/snapshots/snap_missing/export")
        assert response.status_code == 404

    async def test_non_succeeded_snapshot_409(
        self, client: AsyncClient, sample_repo: Path, app_state: AppState
    ) -> None:
        """A partial bundle is a misleading half-map — only succeeded exports."""
        response = await client.post(
            "/api/v1/systems",
            json={"name": "pending-shop", "repos": [{"source": str(sample_repo)}]},
        )
        analyze = await client.post(f"/api/v1/systems/{response.json()['id']}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        export = await client.get(f"/api/v1/snapshots/{snapshot_id}/export")
        assert export.status_code == 409
        assert "only succeeded" in export.json()["detail"]
