"""StitchPipeline integration tests: Mongo truth + coverage + Neo4j derived
view over a seeded two-service snapshot (§5.4)."""

import pytest

from wadi_contracts import (
    AnalysisCoverage,
    Confidence,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityGateFlagState,
    EntityOperation,
    NetworkIdentity,
    Provenance,
    ServiceBoundary,
    ServiceKind,
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
    petstore = make_service(snapshot, "services/petstore").model_copy(
        update={"analysis_coverage": AnalysisCoverage(production_methods=24, reachable_methods=19)}
    )
    # Inventory deliberately carries no coverage fact — the report must show
    # it as unknown, not zero (§5.4.3, P10).
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

        # Analysis coverage (§5.4.3): known counts roll up; the service
        # without the fact stays visible as unknown.
        assert report.analysis_coverage is not None
        assert report.analysis_coverage.production_methods == 24
        assert report.analysis_coverage.reachable_methods == 19
        assert report.analysis_coverage.coverage_percent == 79.2
        by_name = {e.name: e for e in report.analysis_coverage.services}
        assert by_name["petstore"].coverage_percent == 79.2
        assert by_name["inventory"].production_methods is None
        assert by_name["inventory"].coverage_percent is None

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

    async def test_a_call_that_misses_on_two_candidates_is_stitched(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        """Issue #26: two services answer to one hostname and neither serves the
        path. The run must store one undetermined edge per candidate."""
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = make_snapshot(make_system())
        petstore = make_service(snapshot, "services/petstore")
        orders_a = _with_network(make_service(snapshot, "services/orders-a"), hostnames=["orders"])
        orders_b = _with_network(make_service(snapshot, "services/orders-b"), hostnames=["orders"])
        call = make_remote_call(snapshot, petstore, url="http://orders/no/such/path")
        await artifacts.write_service_boundaries([petstore, orders_a, orders_b])
        await artifacts.write_endpoints(
            [make_endpoint(snapshot, orders_a), make_endpoint(snapshot, orders_b)]
        )
        await artifacts.write_remote_calls([call])

        summary = await StitchPipeline(artifacts, stitch, graph_repository).run(snapshot.id)

        assert summary.undetermined == 2
        stored = await stitch.list_stitched_edges(snapshot.id)
        assert [e.remote_call_id for e in stored] == [call.id, call.id]
        assert [e.target_kind for e in stored] == [TargetKind.UNDETERMINED] * 2
        assert len({e.id for e in stored}) == 2
        report = await stitch.get_coverage_report(snapshot.id)
        assert report is not None
        assert [u.reason_code for u in report.unresolved] == ["no-endpoint-match"] * 2

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

    async def test_entity_coverage_survives_the_stored_report(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        """§5.2.17: the section is read back from Mongo as written, gate flags
        included (E3), and a pre-phase service stays a count, never zeros."""
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = make_snapshot(make_system())
        accounting = EntityAccessAccounting(
            call_sites=3,
            in_endpoint_flow=2,
            in_no_endpoint_flow=1,
            flush=0,
            implemented_in_project=0,
            entity_undetermined=0,
            unknown_operation=0,
            create_or_update=1,
            bound=2,
            accesses_by_operation={
                "create": 0,
                "read": 2,
                "update": 0,
                "delete": 0,
                "create-or-update": 1,
                "unknown": 0,
            },
            sites_by_basis={
                "method-name": 2,
                "query-text": 0,
                "argument-origin": 1,
                "existence-guard": 0,
            },
            rules_version="rules-1",
            gate_flags=[
                EntityGateFlagState(
                    basis=EntityAccessBasis.ARGUMENT_ORIGIN,
                    operation=EntityOperation.CREATE,
                    enabled=True,
                    scored_rules_version="rules-1",
                ),
                EntityGateFlagState(
                    basis=EntityAccessBasis.ARGUMENT_ORIGIN,
                    operation=EntityOperation.UPDATE,
                    enabled=False,
                    scored_rules_version=None,
                ),
            ],
        )
        petstore = make_service(snapshot, "services/petstore").model_copy(
            update={"entity_access_accounting": accounting}
        )
        legacy = make_service(snapshot, "services/legacy")
        library = make_service(snapshot, "libs/common").model_copy(
            update={"kind": ServiceKind.LIBRARY}
        )
        await artifacts.write_service_boundaries([petstore, legacy, library])

        await StitchPipeline(artifacts, stitch, graph_repository).run(snapshot.id)
        report = await stitch.get_coverage_report(snapshot.id)

        assert report is not None
        section = report.entity_coverage
        assert section is not None
        assert (section.services_reporting, section.services_predating) == (1, 1)
        assert (section.call_sites, section.create_or_update, section.bound) == (3, 1, 2)
        assert section.in_no_endpoint_flow == 1
        [row] = section.by_service
        assert (row.service_id, row.service_name) == (petstore.service_id, "petstore")
        assert row.accounting == accounting
        assert section.unexercised_vocabulary == [
            "basis:existence-guard",
            "basis:query-text",
            "operation:create",
            "operation:delete",
            "operation:unknown",
            "operation:update",
        ]
        assert [case.value for case in section.unmeasured] == [
            "cascaded-operations",
            "dirty-checking-updates",
            "other-persistence-mechanisms",
        ]

    async def test_a_snapshot_from_before_the_phase_stores_no_entity_section(
        self, database: WadiDatabase, graph_repository: GraphRepository
    ) -> None:
        artifacts = ArtifactRepository(database)
        stitch = StitchRepository(database)
        snapshot = await _seed_two_service_snapshot(artifacts)

        await StitchPipeline(artifacts, stitch, graph_repository).run(snapshot.id)
        report = await stitch.get_coverage_report(snapshot.id)

        assert report is not None
        assert report.entity_coverage is None

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
