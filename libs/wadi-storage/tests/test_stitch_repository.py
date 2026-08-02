"""StitchRepository integration tests (Mongo): replace semantics + reads."""

import pytest

from wadi_contracts import (
    Confidence,
    CoverageReport,
    CoverageTotals,
    Provenance,
    StitchedEdge,
    TargetKind,
)
from wadi_storage import StitchRepository, WadiDatabase
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(database: WadiDatabase) -> StitchRepository:
    return StitchRepository(database)


def _totals(**overrides: int) -> CoverageTotals:
    base: dict[str, int] = {
        "call_sites": 1,
        "edges": 1,
        "analyzed": 1,
        "external": 0,
        "placeholder": 0,
        "undetermined": 0,
    }
    base.update(overrides)
    return CoverageTotals.model_validate(base)


class TestStitchedEdges:
    async def test_replace_and_list_sorted(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        calls = [
            make_remote_call(snapshot, caller, line=27),
            make_remote_call(snapshot, caller, line=31, url="http://inventory:8081/admin"),
        ]
        edges = [make_analyzed_edge(call, target) for call in calls]

        await repo.replace_stitched_edges(snapshot.id, edges)
        stored = await repo.list_stitched_edges(snapshot.id)
        assert [e.id for e in stored] == sorted(e.id for e in edges)
        assert stored == sorted(edges, key=lambda e: e.id)  # round-trips exactly (P9)

    async def test_replace_removes_stale_rows(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        old_call = make_remote_call(snapshot, caller, line=27)
        new_call = make_remote_call(snapshot, caller, line=99, url="http://inventory:8081/new")

        await repo.replace_stitched_edges(snapshot.id, [make_analyzed_edge(old_call, target)])
        await repo.replace_stitched_edges(snapshot.id, [make_analyzed_edge(new_call, target)])

        stored = await repo.list_stitched_edges(snapshot.id)
        assert len(stored) == 1
        assert stored[0].remote_call_id == new_call.id

    async def test_replace_is_idempotent(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        edge = make_analyzed_edge(
            make_remote_call(snapshot, caller), make_endpoint(snapshot, callee, uri="/stock/{id}")
        )
        await repo.replace_stitched_edges(snapshot.id, [edge])
        await repo.replace_stitched_edges(snapshot.id, [edge])  # retry converges
        assert len(await repo.list_stitched_edges(snapshot.id)) == 1

    async def test_snapshot_isolation(self, repo: StitchRepository) -> None:
        system = make_system()
        snap_a, snap_b = make_snapshot(system), make_snapshot(system)
        for snap in (snap_a, snap_b):
            caller = make_service(snap, "services/petstore")
            callee = make_service(snap, "services/inventory")
            edge = make_analyzed_edge(
                make_remote_call(snap, caller), make_endpoint(snap, callee, uri="/stock/{id}")
            )
            await repo.replace_stitched_edges(snap.id, [edge])

        await repo.replace_stitched_edges(snap_a.id, [])
        assert await repo.list_stitched_edges(snap_a.id) == []
        assert len(await repo.list_stitched_edges(snap_b.id)) == 1

    async def test_direction_queries(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        edge = make_analyzed_edge(make_remote_call(snapshot, caller), target)
        await repo.replace_stitched_edges(snapshot.id, [edge])

        outbound = await repo.list_stitched_edges(snapshot.id, caller.service_id)
        inbound = await repo.list_stitched_edges(
            snapshot.id, callee.service_id, direction="inbound"
        )
        assert [e.id for e in outbound] == [edge.id]
        assert [e.id for e in inbound] == [edge.id]
        assert await repo.list_stitched_edges(snapshot.id, callee.service_id) == []
        with pytest.raises(ValueError, match="direction"):
            await repo.list_stitched_edges(snapshot.id, direction="sideways")

    async def test_edges_for_remote_calls(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        call = make_remote_call(snapshot, caller)
        other = make_remote_call(snapshot, caller, line=50, url="http://inventory:8081/x")
        await repo.replace_stitched_edges(
            snapshot.id,
            [make_analyzed_edge(call, target), make_analyzed_edge(other, target)],
        )
        found = await repo.list_edges_for_remote_calls(snapshot.id, [call.id])
        assert [e.remote_call_id for e in found] == [call.id]
        assert await repo.list_edges_for_remote_calls(snapshot.id, []) == []

    async def test_undetermined_edge_round_trips(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        caller = make_service(snapshot, "services/petstore")
        call = make_remote_call(snapshot, caller, url=None)
        edge = StitchedEdge.create(
            snapshot_id=snapshot.id,
            service_id=caller.service_id,
            remote_call_id=call.id,
            mechanism=call.mechanism,
            target_kind=TargetKind.UNDETERMINED,
            confidence=Confidence.NONE,
            provenance=Provenance.MACHINE_PROVEN,
            evidence="url recovered from DB row — runtime-only",
        )
        await repo.replace_stitched_edges(snapshot.id, [edge])
        assert (await repo.list_stitched_edges(snapshot.id)) == [edge]


class TestCoverageReport:
    async def test_upsert_and_get(self, repo: StitchRepository) -> None:
        system = make_system()
        snapshot = make_snapshot(system)
        report = CoverageReport(snapshot_id=snapshot.id, totals=_totals())
        await repo.write_coverage_report(report)
        assert await repo.get_coverage_report(snapshot.id) == report

        updated = CoverageReport(
            snapshot_id=snapshot.id, totals=_totals(edges=2, external=1, call_sites=2)
        )
        await repo.write_coverage_report(updated)  # re-stitch overwrites
        assert await repo.get_coverage_report(snapshot.id) == updated

    async def test_missing_report_is_none(self, repo: StitchRepository) -> None:
        assert await repo.get_coverage_report("snap_missing") is None
