"""Integration tests: system/snapshot/artifact repositories against real Mongo."""

import pytest

from wadi_contracts import SnapshotStatus
from wadi_storage import (
    ArtifactRepository,
    DuplicateSystemNameError,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration


class TestSystemRepository:
    async def test_roundtrip(self, database: WadiDatabase) -> None:
        repo = SystemRepository(database)
        system = make_system()
        await repo.insert(system)
        loaded = await repo.get(system.id)
        assert loaded == system  # full fidelity, including tz-aware created_at

    async def test_duplicate_name_rejected(self, database: WadiDatabase) -> None:
        repo = SystemRepository(database)
        await repo.insert(make_system("shop"))
        with pytest.raises(DuplicateSystemNameError):
            await repo.insert(make_system("shop"))

    async def test_get_by_name_and_list(self, database: WadiDatabase) -> None:
        repo = SystemRepository(database)
        a, b = make_system("alpha"), make_system("beta")
        await repo.insert(a)
        await repo.insert(b)
        assert await repo.get_by_name("alpha") == a
        assert await repo.get_by_name("missing") is None
        assert {s.id for s in await repo.list_all()} == {a.id, b.id}


class TestSnapshotRepository:
    async def test_roundtrip_and_listing_order(self, database: WadiDatabase) -> None:
        repo = SnapshotRepository(database)
        system = make_system()
        first, second = make_snapshot(system), make_snapshot(system)
        await repo.insert(first)
        await repo.insert(second)
        listed = await repo.list_for_system(system.id)
        assert [s.id for s in listed] == [second.id, first.id]  # newest first

    async def test_status_transitions_stamp_timestamps(self, database: WadiDatabase) -> None:
        repo = SnapshotRepository(database)
        snapshot = make_snapshot(make_system())
        await repo.insert(snapshot)

        await repo.set_status(snapshot.id, SnapshotStatus.RUNNING)
        running = await repo.get(snapshot.id)
        assert running is not None
        assert running.status is SnapshotStatus.RUNNING
        assert running.started_at is not None

        await repo.set_status(snapshot.id, SnapshotStatus.FAILED, error="boundary scan failed")
        failed = await repo.get(snapshot.id)
        assert failed is not None
        assert failed.status is SnapshotStatus.FAILED
        assert failed.finished_at is not None
        assert failed.error == "boundary scan failed"

    async def test_commits_are_never_rewritten(self, database: WadiDatabase) -> None:
        repo = SnapshotRepository(database)
        snapshot = make_snapshot(make_system())
        await repo.insert(snapshot)
        await repo.set_status(snapshot.id, SnapshotStatus.SUCCEEDED)
        reloaded = await repo.get(snapshot.id)
        assert reloaded is not None
        assert reloaded.commits == snapshot.commits


class TestArtifactRepository:
    async def test_boundary_and_endpoint_roundtrip(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)

        await artifacts.write_service_boundaries([boundary])
        await artifacts.write_endpoints([endpoint])

        assert await artifacts.list_service_boundaries(snapshot.id) == [boundary]
        assert await artifacts.get_service_boundary(snapshot.id, boundary.service_id) == boundary
        assert await artifacts.list_endpoints(snapshot.id, boundary.service_id) == [endpoint]
        assert await artifacts.get_endpoint(snapshot.id, endpoint.id) == endpoint

    async def test_writes_are_idempotent(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)

        for _ in range(3):  # a retried job must converge, not duplicate
            await artifacts.write_service_boundaries([boundary])
            await artifacts.write_endpoints([endpoint])

        assert len(await artifacts.list_service_boundaries(snapshot.id)) == 1
        assert len(await artifacts.list_endpoints(snapshot.id, boundary.service_id)) == 1

    async def test_empty_write_is_noop(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        await artifacts.write_endpoints([])  # must not raise

    async def test_snapshot_isolation(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        system = make_system()
        snap_a, snap_b = make_snapshot(system), make_snapshot(system)
        boundary_a = make_service(snap_a)
        await artifacts.write_service_boundaries([boundary_a])
        assert await artifacts.list_service_boundaries(snap_b.id) == []
