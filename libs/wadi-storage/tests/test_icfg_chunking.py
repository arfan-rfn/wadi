"""Integration tests: ICFG storage including the >16MB chunking path."""

from typing import NamedTuple

import pytest

from wadi_contracts import Endpoint, Icfg, ServiceBoundary, Snapshot
from wadi_storage import ArtifactRepository, WadiDatabase
from wadi_storage.mongo import ICFG_PARTS, ICFGS
from wadi_testing.builders import make_endpoint, make_icfg, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration


class BigIcfgSetup(NamedTuple):
    snapshot: Snapshot
    boundary: ServiceBoundary
    endpoint: Endpoint
    icfg: Icfg


class TestSmallIcfg:
    async def test_roundtrip_unchunked(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)
        icfg = make_icfg(snapshot, boundary, endpoint)

        await artifacts.write_icfg(icfg)
        loaded = await artifacts.get_icfg(snapshot.id, endpoint.id)
        assert loaded == icfg
        assert await database.collection(ICFG_PARTS).count_documents({}) == 0

    async def test_missing_returns_none(self, database: WadiDatabase) -> None:
        artifacts = ArtifactRepository(database)
        assert await artifacts.get_icfg("snap_none", "ep_" + "0" * 16) is None


class TestChunkedIcfg:
    @pytest.fixture
    def big_icfg_setup(self) -> BigIcfgSetup:
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)
        # ~2,000 statements x ~10KB source text = ~20MB > 16MB Mongo limit.
        icfg = make_icfg(
            snapshot,
            boundary,
            endpoint,
            statement_count=2_000,
            statement_text="x" * 10_000,
        )
        return BigIcfgSetup(snapshot, boundary, endpoint, icfg)

    async def test_oversized_roundtrip(
        self, database: WadiDatabase, big_icfg_setup: BigIcfgSetup
    ) -> None:
        snapshot, _, endpoint, icfg = big_icfg_setup
        artifacts = ArtifactRepository(database)
        await artifacts.write_icfg(icfg)  # must not hit the 16MB write error

        manifest = await database.collection(ICFGS).find_one(
            {"snapshot_id": snapshot.id, "endpoint_id": endpoint.id}
        )
        assert manifest is not None
        assert manifest["chunked"] is True
        assert int(str(manifest["part_count"])) >= 2
        parts = await database.collection(ICFG_PARTS).count_documents(
            {"snapshot_id": snapshot.id, "endpoint_id": endpoint.id}
        )
        assert parts == manifest["part_count"]

        loaded = await artifacts.get_icfg(snapshot.id, endpoint.id)
        assert loaded == icfg  # exact logical equality across the chunk boundary

    async def test_rewrite_shrinks_cleanly(
        self, database: WadiDatabase, big_icfg_setup: BigIcfgSetup
    ) -> None:
        snapshot, boundary, endpoint, big = big_icfg_setup
        artifacts = ArtifactRepository(database)
        await artifacts.write_icfg(big)
        small = make_icfg(snapshot, boundary, endpoint)
        await artifacts.write_icfg(small)  # retry/re-extract with a smaller graph

        assert await artifacts.get_icfg(snapshot.id, endpoint.id) == small
        stale_parts = await database.collection(ICFG_PARTS).count_documents(
            {"snapshot_id": snapshot.id, "endpoint_id": endpoint.id}
        )
        assert stale_parts == 0  # no orphaned chunks

    async def test_missing_part_fails_loudly(
        self, database: WadiDatabase, big_icfg_setup: BigIcfgSetup
    ) -> None:
        snapshot, _, endpoint, icfg = big_icfg_setup
        artifacts = ArtifactRepository(database)
        await artifacts.write_icfg(icfg)
        await database.collection(ICFG_PARTS).delete_one(
            {"snapshot_id": snapshot.id, "endpoint_id": endpoint.id, "part": 0}
        )
        with pytest.raises(RuntimeError, match="incomplete"):
            await artifacts.get_icfg(snapshot.id, endpoint.id)
