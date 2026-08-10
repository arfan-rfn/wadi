"""Integration tests: system/snapshot/artifact repositories against real Mongo."""

from typing import cast

import pytest

from wadi_contracts import Icfg, ShapeKind, SnapshotStatus, TypeShape
from wadi_storage import (
    ArtifactRepository,
    DuplicateSystemNameError,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_testing.builders import (
    make_endpoint,
    make_icfg,
    make_service,
    make_snapshot,
    make_system,
)

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

    async def test_summaries_exclude_the_shapes_in_the_query(self, database: WadiDatabase) -> None:
        """The projection is what makes the list route fast (§5.2.15).

        Trimming the response alone moved ICPC `contest` from 114.5 MB to
        2.4 MB and the clock from ~11 s only to ~11 s: the cost was reading
        and validating 124 MB of wire shapes, not sending them. Excluding
        them in the find() took it to ~0.09 s. A future refactor that
        projects in Python instead would restore the payload win and silently
        lose the whole speed-up, so the exclusion is pinned here rather than
        only at the route.
        """
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary).model_copy(
            update={
                "request_schema": TypeShape(kind=ShapeKind.OBJECT, type_name="com.acme.Req"),
                "response_schema": TypeShape(kind=ShapeKind.OBJECT, type_name="com.acme.Res"),
            }
        )
        await artifacts.write_service_boundaries([boundary])
        await artifacts.write_endpoints([endpoint])

        # The document really does hold them — otherwise this proves nothing.
        stored = await database.collection("endpoints").find_one({"id": endpoint.id})
        assert stored is not None
        response_schema = cast(dict[str, object], stored["response_schema"])
        assert response_schema["type_name"] == "com.acme.Res"

        rows = await artifacts.list_endpoint_summaries(snapshot.id, boundary.service_id)
        assert [row.id for row in rows] == [endpoint.id]
        assert not hasattr(rows[0], "response_schema")
        assert not hasattr(rows[0], "request_schema")
        # The envelope survives: a row reports the contract that WROTE it.
        assert rows[0].schema_version == endpoint.schema_version
        assert rows[0].auth == endpoint.auth
        assert rows[0].handler == endpoint.handler

    async def test_remote_call_ids_come_from_the_aggregation_not_the_graphs(
        self, database: WadiDatabase
    ) -> None:
        """The endpoint-dependencies join, without loading a single ICFG.

        It used to be one `get_icfg` per endpoint — 804 graphs on ICPC
        `contest`, reassembled from their chunks and validated — to answer in
        125 bytes, and it took ~4.4 s against 5-8 ms for every other read on
        that page. Measured after: 0.07 s, byte-identical payload.

        Correctness is what this pins, not speed: the union has to be exact,
        deduped, and it has to cover CHUNKED graphs, whose nodes live in
        `icfg_parts` and leave nothing on the manifest to aggregate over.
        """
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)

        plain = make_endpoint(snapshot, boundary, "/orders/{id}")
        empty = make_endpoint(snapshot, boundary, "/health")
        await artifacts.write_endpoints([plain, empty])

        def with_calls(icfg: Icfg, by_node: dict[str, list[str]]) -> Icfg:
            nodes = [
                node.model_copy(update={"remote_call_ids": by_node.get(node.id, [])})
                for node in icfg.nodes
            ]
            return icfg.model_copy(update={"nodes": nodes})

        # Two nodes naming the same call plus a second call — the union must
        # dedupe across nodes rather than concatenating them.
        await artifacts.write_icfg(
            with_calls(
                make_icfg(snapshot, boundary, plain),
                {"s0": ["rc_aaa", "rc_bbb"], "s1": ["rc_aaa"]},
            )
        )
        # An endpoint whose flow reaches nothing must be ABSENT, not present
        # with an empty set: the view reads "no key" as "calls nothing".
        await artifacts.write_icfg(make_icfg(snapshot, boundary, empty))

        found = await artifacts.remote_call_ids_by_endpoint(snapshot.id, boundary.service_id)
        assert found == {plain.id: {"rc_aaa", "rc_bbb"}}

    async def test_remote_call_ids_cover_chunked_graphs(self, database: WadiDatabase) -> None:
        """A chunked ICFG keeps its nodes in `icfg_parts` (§6).

        The manifest it leaves behind has no `nodes` at all, so a single
        aggregation over `icfgs` returns an empty union for it — silently, and
        only for the largest graphs in a snapshot, which is the worst possible
        shape for a bug. The parts collection is aggregated too and merged.
        """
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary, "/bulk")
        await artifacts.write_endpoints([endpoint])

        # Past SAFE_PART_BYTES (12 MB), so write_icfg takes the chunked path.
        big = make_icfg(
            snapshot, boundary, endpoint, statement_count=200, statement_text="x" * 70_000
        )
        nodes = [
            node.model_copy(update={"remote_call_ids": ["rc_chunked"] if node.id == "s7" else []})
            for node in big.nodes
        ]
        await artifacts.write_icfg(big.model_copy(update={"nodes": nodes}))

        manifest = await database.collection("icfgs").find_one({"endpoint_id": endpoint.id})
        assert manifest is not None
        assert manifest["chunked"] is True, "fixture must exercise the chunked path"

        found = await artifacts.remote_call_ids_by_endpoint(snapshot.id, boundary.service_id)
        assert found == {endpoint.id: {"rc_chunked"}}

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
