"""Stitcher skeleton tests: the read path works over real artifacts."""

import pytest

from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import ArtifactRepository, WadiDatabase
from wadi_testing.builders import (
    make_endpoint,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


class TestStitchSkeleton:
    async def test_counts_snapshot_artifacts(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary_a = make_service(snapshot, "services/orders")
        boundary_b = make_service(snapshot, "services/billing")
        await artifacts.write_service_boundaries([boundary_a, boundary_b])
        await artifacts.write_endpoints(
            [
                make_endpoint(snapshot, boundary_a, "/orders"),
                make_endpoint(snapshot, boundary_a, "/orders/{id}"),
                make_endpoint(snapshot, boundary_b, "/invoices"),
            ]
        )

        summary = await StitchPipeline(artifacts).run(snapshot.id)
        assert summary.service_count == 2
        assert summary.endpoint_count == 3
        assert summary.remote_call_count == 0
        assert summary.mq_interaction_count == 0

    async def test_empty_snapshot(self, database: WadiDatabase) -> None:
        summary = await StitchPipeline(ArtifactRepository(database)).run("snap_empty")
        assert summary.service_count == 0
