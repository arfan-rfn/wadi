"""GraphRepository integration tests (Neo4j): schema, rebuild, reads (§5.4.3)."""

from typing import NamedTuple

import pytest

from wadi_contracts import (
    Confidence,
    Endpoint,
    PlaceholderEntry,
    Provenance,
    RemoteCall,
    ServiceBoundary,
    Snapshot,
    StitchedEdge,
    TargetKind,
    placeholder_service_id,
)
from wadi_storage import GraphRepository
from wadi_testing.builders import (
    make_analyzed_edge,
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


def _snapshot() -> Snapshot:
    return make_snapshot(make_system())


class _Seeded(NamedTuple):
    caller: ServiceBoundary
    callee: ServiceBoundary
    target: Endpoint
    call: RemoteCall
    edge: StitchedEdge


async def _seed_analyzed(repo: GraphRepository, snapshot: Snapshot) -> _Seeded:
    caller = make_service(snapshot, "services/petstore")
    callee = make_service(snapshot, "services/inventory")
    target = make_endpoint(snapshot, callee, uri="/stock/{id}")
    call = make_remote_call(snapshot, caller)
    edge = make_analyzed_edge(call, target)
    await repo.replace_snapshot(
        snapshot.id,
        boundaries=[caller, callee],
        endpoints=[target],
        remote_calls=[call],
        edges=[edge],
    )
    return _Seeded(caller, callee, target, call, edge)


class TestSchema:
    async def test_ensure_schema_idempotent(self, graph_repository: GraphRepository) -> None:
        await graph_repository.ensure_schema()
        await graph_repository.ensure_schema()  # second run must not raise


class TestReplaceSnapshot:
    async def test_analyzed_edge_with_return(self, graph_repository: GraphRepository) -> None:
        snapshot = _snapshot()
        seeded = await _seed_analyzed(graph_repository, snapshot)
        rows = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH (rc:RemoteCall {snapshot_id: $s})-[e:INVOKES_REMOTE]->(ep:Endpoint) "
            "OPTIONAL MATCH (ep)-[r:RETURNS_TO]->(rc) "
            "RETURN e.confidence AS confidence, e.provenance AS provenance, "
            "       r IS NOT NULL AS has_return",
            {"s": snapshot.id},
        )
        assert rows == [
            {"confidence": "exact", "provenance": "config-resolved", "has_return": True}
        ]
        view = await graph_repository.remote_edges(snapshot.id, seeded.caller.service_id)
        assert len(view.outbound) == 1

    async def test_external_and_placeholder_have_no_return_edge(
        self, graph_repository: GraphRepository
    ) -> None:
        snapshot = _snapshot()
        caller = make_service(snapshot, "services/petstore")
        stripe_call = make_remote_call(
            snapshot, caller, line=40, url="https://api.stripe.com/v1/charges"
        )
        billing_call = make_remote_call(snapshot, caller, line=41, url="http://billing/invoices")
        ph = placeholder_service_id("billing")
        edges = [
            StitchedEdge.create(
                snapshot_id=snapshot.id,
                service_id=caller.service_id,
                remote_call_id=stripe_call.id,
                mechanism="resttemplate",
                url=stripe_call.url,
                target_kind=TargetKind.EXTERNAL,
                external_host="api.stripe.com",
                confidence=Confidence.EXACT,
                provenance=Provenance.MACHINE_PROVEN,
            ),
            StitchedEdge.create(
                snapshot_id=snapshot.id,
                service_id=caller.service_id,
                remote_call_id=billing_call.id,
                mechanism="resttemplate",
                url=billing_call.url,
                target_kind=TargetKind.PLACEHOLDER,
                target_service_id=ph,
                confidence=Confidence.HEURISTIC,
                provenance=Provenance.HEURISTIC,
            ),
        ]
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller],
            endpoints=[],
            remote_calls=[stripe_call, billing_call],
            edges=edges,
            placeholders=[
                PlaceholderEntry(
                    placeholder_id=ph,
                    name="billing",
                    resolved_via="bare-hostname",
                    call_count=1,
                    caller_service_ids=[caller.service_id],
                )
            ],
        )
        returns = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH ()-[r:RETURNS_TO]->() WHERE r.edge_id IS NOT NULL RETURN count(r) AS n"
        )
        assert returns == [{"n": 0}]
        view = await graph_repository.remote_edges(snapshot.id, caller.service_id)
        kinds = {item.target_kind for item in view.outbound}
        assert kinds == {TargetKind.EXTERNAL, TargetKind.PLACEHOLDER}
        placeholder_item = next(i for i in view.outbound if i.target_kind is TargetKind.PLACEHOLDER)
        assert placeholder_item.target_service_name == "billing"

    async def test_undetermined_is_dangling_call_site(
        self, graph_repository: GraphRepository
    ) -> None:
        snapshot = _snapshot()
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
        )
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller],
            endpoints=[],
            remote_calls=[call],
            edges=[edge],
        )
        rows = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH (rc:RemoteCall {snapshot_id: $s}) "
            "OPTIONAL MATCH (rc)-[e:INVOKES_REMOTE]->() "
            "RETURN rc.remote_call_id AS id, count(e) AS edges",
            {"s": snapshot.id},
        )
        assert rows == [{"id": call.id, "edges": 0}]  # visible honesty (P10)

    async def test_rebuild_removes_stale_and_converges(
        self, graph_repository: GraphRepository
    ) -> None:
        snapshot = _snapshot()
        await _seed_analyzed(graph_repository, snapshot)
        caller = make_service(snapshot, "services/petstore")
        # Second stitch: the analyzed edge disappeared (input changed).
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller],
            endpoints=[],
            remote_calls=[],
            edges=[],
        )
        rows = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH (n {snapshot_id: $s}) RETURN labels(n)[0] AS label, count(n) AS n "
            "ORDER BY label",
            {"s": snapshot.id},
        )
        assert rows == [{"label": "Service", "n": 1}]

    async def test_cross_snapshot_isolation(self, graph_repository: GraphRepository) -> None:
        snap_a, snap_b = _snapshot(), _snapshot()
        await _seed_analyzed(graph_repository, snap_a)
        await _seed_analyzed(graph_repository, snap_b)
        await graph_repository.delete_snapshot(snap_a.id)
        remaining = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH (n) RETURN DISTINCT n.snapshot_id AS s"
        )
        assert remaining == [{"s": snap_b.id}]

    async def test_batching_writes_all_rows(self, graph_repository: GraphRepository) -> None:
        small_batch = GraphRepository(graph_repository._store, batch_size=3)  # pyright: ignore[reportPrivateUsage]
        snapshot = _snapshot()
        caller = make_service(snapshot, "services/petstore")
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        calls = [
            make_remote_call(snapshot, caller, line=10 + i, url=f"http://inventory:8081/x/{i}")
            for i in range(10)
        ]
        edges = [make_analyzed_edge(c, target) for c in calls]
        await small_batch.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[target],
            remote_calls=calls,
            edges=edges,
        )
        rows = await small_batch._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH ()-[e:INVOKES_REMOTE]->() WHERE e.edge_id IS NOT NULL RETURN count(e) AS n"
        )
        assert rows == [{"n": 10}]


class TestReads:
    async def test_remote_edges_inbound_outbound(self, graph_repository: GraphRepository) -> None:
        snapshot = _snapshot()
        seeded = await _seed_analyzed(graph_repository, snapshot)
        outbound_view = await graph_repository.remote_edges(snapshot.id, seeded.caller.service_id)
        inbound_view = await graph_repository.remote_edges(snapshot.id, seeded.callee.service_id)
        assert len(outbound_view.outbound) == 1
        assert outbound_view.inbound == []
        assert len(inbound_view.inbound) == 1
        assert inbound_view.outbound == []
        item = outbound_view.outbound[0]
        assert item.target_simplified_uri == "/stock/{?}"
        assert item.caller_service_name == "petstore"
        assert item.target_service_name == "inventory"
        assert item.confidence is Confidence.EXACT
        assert item.provenance is Provenance.CONFIG_RESOLVED

    async def test_resolve_call_targets(self, graph_repository: GraphRepository) -> None:
        snapshot = _snapshot()
        seeded = await _seed_analyzed(graph_repository, snapshot)
        items = await graph_repository.resolve_call_targets(snapshot.id, [seeded.call.id])
        assert len(items) == 1
        assert items[0].target_kind is TargetKind.ANALYZED
        assert await graph_repository.resolve_call_targets(snapshot.id, []) == []
