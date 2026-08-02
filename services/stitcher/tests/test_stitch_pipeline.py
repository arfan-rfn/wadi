"""StitchPipeline integration tests: Mongo truth + coverage + Neo4j derived
view over a seeded two-service snapshot (§5.4)."""

import pytest

from wadi_contracts import (
    Confidence,
    NetworkIdentity,
    Provenance,
    ServiceBoundary,
    Snapshot,
    TargetKind,
)
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    StitchRepository,
    WadiDatabase,
)
from wadi_testing.builders import (
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


def _with_network(boundary: ServiceBoundary, **kwargs: object) -> ServiceBoundary:
    return boundary.model_copy(update={"network": NetworkIdentity.model_validate(kwargs)})


async def _seed_two_service_snapshot(
    artifacts: ArtifactRepository,
) -> Snapshot:
    """petstore calls inventory (resolvable), stripe (external), billing
    (bare hostname), and one runtime-only target (undetermined)."""
    snapshot = make_snapshot(make_system())
    petstore = make_service(snapshot, "services/petstore")
    inventory = _with_network(
        make_service(snapshot, "services/inventory"),
        hostnames=["inventory"],
        server_port=8081,
    )
    stock_endpoint = make_endpoint(snapshot, inventory, uri="/stock/{id}")
    calls = [
        make_remote_call(
            snapshot,
            petstore,
            line=27,
            url="http://inventory:8081/stock/{?}",
            confidence=Confidence.HIGH,
        ),
        make_remote_call(
            snapshot,
            petstore,
            line=30,
            url="https://api.stripe.com/v1/charges",
            confidence=Confidence.EXACT,
        ),
        make_remote_call(snapshot, petstore, line=33, url="http://billing/invoices"),
        make_remote_call(snapshot, petstore, line=36, url=None),
    ]
    await artifacts.write_service_boundaries([petstore, inventory])
    await artifacts.write_endpoints([stock_endpoint])
    await artifacts.write_remote_calls(calls)
    return snapshot


class TestStitchPipeline:
    async def test_full_run_writes_truth_coverage_and_graph(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = await _seed_two_service_snapshot(artifacts)
        pipeline = StitchPipeline(artifacts, stitch, graph_repository)

        summary = await pipeline.run(snapshot.id)

        assert summary.service_count == 2
        assert summary.remote_call_count == 4
        assert summary.edge_count == 4
        assert summary.analyzed == 1
        assert summary.external == 1
        assert summary.placeholder == 1
        assert summary.undetermined == 1

        # Tier-1 truth in Mongo.
        edges = await stitch.list_stitched_edges(snapshot.id)
        kinds = {e.target_kind for e in edges}
        assert kinds == set(TargetKind)
        analyzed = next(e for e in edges if e.target_kind is TargetKind.ANALYZED)
        assert analyzed.confidence is Confidence.HIGH  # min(HIGH url, EXACT res, EXACT path)
        assert analyzed.provenance is Provenance.CONFIG_RESOLVED

        # Coverage report (surfaced first, P10).
        report = await stitch.get_coverage_report(snapshot.id)
        assert report is not None
        assert report.totals.undetermined == 1
        [placeholder] = report.placeholders
        assert placeholder.name == "billing"
        [entry] = report.unresolved
        assert entry.reason_code == "url-undetermined"

        # Tier-2 derived view in Neo4j mirrors the truth.
        view = await graph_repository.remote_edges(snapshot.id, analyzed.service_id)
        assert {i.target_kind for i in view.outbound} == {
            TargetKind.ANALYZED,
            TargetKind.EXTERNAL,
            TargetKind.PLACEHOLDER,
        }
        analyzed_item = next(i for i in view.outbound if i.target_kind is TargetKind.ANALYZED)
        assert analyzed_item.target_simplified_uri == "/stock/{?}"

    async def test_rerun_converges_idempotently(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = await _seed_two_service_snapshot(artifacts)
        pipeline = StitchPipeline(artifacts, stitch, graph_repository)

        first = await pipeline.run(snapshot.id)
        first_edges = await stitch.list_stitched_edges(snapshot.id)
        second = await pipeline.run(snapshot.id)  # restitch: retry or explicit
        second_edges = await stitch.list_stitched_edges(snapshot.id)

        assert first == second
        assert [e.id for e in first_edges] == [e.id for e in second_edges]
        rows = await graph_repository._run(  # pyright: ignore[reportPrivateUsage]
            "MATCH ()-[e:INVOKES_REMOTE]->() RETURN count(e) AS n"
        )
        assert rows == [{"n": 3}]  # no duplicate edges after the rerun

    async def test_empty_snapshot_stitches_to_empty(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = make_snapshot(make_system())
        pipeline = StitchPipeline(artifacts, stitch, graph_repository)
        summary = await pipeline.run(snapshot.id)
        assert summary.edge_count == 0
        report = await stitch.get_coverage_report(snapshot.id)
        assert report is not None
        assert report.totals.call_sites == 0

    async def test_graph_failure_propagates(self, database: WadiDatabase) -> None:
        """A Tier-2 write failure fails the run (job → snapshot FAILED); Mongo
        truth is already written, so a restitch recovers without re-extraction."""

        class ExplodingGraph:
            async def replace_snapshot(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("neo4j is down")

        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = await _seed_two_service_snapshot(artifacts)
        pipeline = StitchPipeline(
            artifacts,
            stitch,
            ExplodingGraph(),  # pyright: ignore[reportArgumentType]
        )
        with pytest.raises(RuntimeError, match="neo4j is down"):
            await pipeline.run(snapshot.id)
        # Truth landed before the derived-view failure — recovery needs no re-extract.
        assert len(await stitch.list_stitched_edges(snapshot.id)) == 4
        assert await stitch.get_coverage_report(snapshot.id) is not None
