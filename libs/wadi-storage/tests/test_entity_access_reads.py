"""Integration tests: the entity-access read paths against real Mongo (§5.2.17, R1-8).

The reverse view reads one projected row per endpoint of a snapshot and every
data model of it. Both reads are snapshot-wide, so their cost is the plan the
server picks, not the size of what comes back: each one is asserted to run as
an index scan that examines exactly the documents it returns, the bar §5.2.15
audited every other hot read against. The plan is read from Mongo's own
profiler for the query the repository method issued, so the test cannot pass
by explaining a query the code does not run.
"""

from typing import cast

import pytest

from wadi_contracts import (
    DataModel,
    EndpointEntityAccess,
    EntityAccess,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityAccessSite,
    EntityAccountingStatus,
    EntityDeclaredBy,
    EntityOperation,
    ServiceBoundary,
    ServiceKind,
    Snapshot,
    data_model_id,
    summarize_entity_access,
)
from wadi_storage import ArtifactRepository, WadiDatabase, entity_usage_view
from wadi_storage.codec import to_doc
from wadi_storage.mongo import DATA_MODELS, ENDPOINTS, MongoDocument
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration

_PET = "com.acme.pets.Pet"


def _summary(*operations: EntityOperation, entity: str = _PET) -> list[EndpointEntityAccess]:
    """An endpoint summary built the way the worker builds it: folded from sites."""
    return summarize_entity_access(
        EntityAccessSite(
            repository="com.acme.pets.PetRepository",
            method_name="save",
            basis=EntityAccessBasis.METHOD_NAME,
            accesses=[EntityAccess(entity=entity, data_model_id=None, operation=operation)],
        )
        for operation in operations
    )


def _model(snapshot: Snapshot, boundary: ServiceBoundary, entity: str) -> DataModel:
    simple = entity.rsplit(".", 1)[-1]
    return DataModel(
        snapshot_id=snapshot.id,
        service_id=boundary.service_id,
        id=data_model_id(boundary.service_id, entity),
        entity=simple,
        type_full_name=entity,
        persistence_framework="spring-data-jpa",
        storage_name=simple.lower(),
        declared_by=EntityDeclaredBy.ANNOTATION,
    )


async def _profiled_queries(database: WadiDatabase, collection: str) -> list[MongoDocument]:
    """The `find` operations the profiler recorded against one collection."""
    namespace = f"{database.db.name}.{collection}"
    cursor = database.collection("system.profile").find({"op": "query", "ns": namespace})
    return [doc async for doc in cursor]


def _assert_index_served(profile: MongoDocument) -> None:
    plan = str(profile.get("planSummary", ""))
    assert plan.startswith("IXSCAN"), f"expected an index scan, got {plan!r}"
    assert "COLLSCAN" not in plan
    # The whole point of the audit: an index that matches a prefix of the
    # filter still fetches and discards the rest. Equal means every document
    # read was one the caller asked for.
    assert profile["docsExamined"] == profile["nreturned"], profile


class TestEndpointEntityAccessProjection:
    async def _seed(self, database: WadiDatabase) -> tuple[Snapshot, list[str]]:
        """Two services in the snapshot under test, plus a second snapshot.

        The second snapshot and the second service are there so a scan that
        is not scoped by the index would examine documents it then drops.
        """
        repo = ArtifactRepository(database)
        system = make_system()
        snapshot, other_snapshot = make_snapshot(system), make_snapshot(system)
        orders = make_service(snapshot, "services/orders")
        pets = make_service(snapshot, "services/pets")
        analyzed = make_endpoint(snapshot, pets, "/pets").model_copy(
            update={"entity_access": _summary(EntityOperation.CREATE_OR_UPDATE)}
        )
        no_repository_call = make_endpoint(snapshot, orders, "/health").model_copy(
            update={"entity_access": []}
        )
        await repo.write_endpoints([analyzed, no_repository_call])
        await repo.write_endpoints(
            [make_endpoint(other_snapshot, make_service(other_snapshot), "/elsewhere")]
        )
        # A document written before the phase has no `entity_access` KEY at
        # all, which is not the same document as one carrying null.
        predating = make_endpoint(snapshot, orders, "/orders/{id}")
        legacy_doc = to_doc(predating)
        del legacy_doc["entity_access"]
        await database.collection(ENDPOINTS).insert_one(legacy_doc)
        return snapshot, [analyzed.id, no_repository_call.id, predating.id]

    async def test_rows_carry_the_endpoints_own_summary_none_included(
        self, database: WadiDatabase
    ) -> None:
        snapshot, (analyzed, no_call, predating) = await self._seed(database)
        rows = await ArtifactRepository(database).list_endpoint_entity_access(snapshot.id)

        by_id = {row.endpoint_id: row for row in rows}
        assert set(by_id) == {analyzed, no_call, predating}
        assert by_id[analyzed].full_uri == "/pets"
        assert by_id[analyzed].http_method.value == "GET"
        assert by_id[analyzed].entity_access == [
            EndpointEntityAccess(
                entity=_PET,
                data_model_id=None,
                operations=[EntityOperation.CREATE_OR_UPDATE],
                call_sites=1,
                call_sites_by_operation={"create-or-update": 1},
            )
        ]
        # R1-6: analyzed-and-empty and never-analyzed stay two answers.
        assert by_id[no_call].entity_access == []
        assert by_id[predating].entity_access is None

    async def test_runs_as_an_index_scan_reading_only_what_it_returns(
        self, database: WadiDatabase
    ) -> None:
        snapshot, endpoint_ids = await self._seed(database)
        await database.db.command("profile", 2)
        rows = await ArtifactRepository(database).list_endpoint_entity_access(snapshot.id)
        await database.db.command("profile", 0)

        [profile] = await _profiled_queries(database, ENDPOINTS)
        _assert_index_served(profile)
        assert profile["nreturned"] == len(rows) == len(endpoint_ids)

    async def test_reads_a_projection_never_the_whole_document(
        self, database: WadiDatabase
    ) -> None:
        """R1-8: the wire shapes are what made the list route 114 MB (§5.2.15)."""
        snapshot, _ = await self._seed(database)
        await database.db.command("profile", 2)
        await ArtifactRepository(database).list_endpoint_entity_access(snapshot.id)
        await database.db.command("profile", 0)

        [profile] = await _profiled_queries(database, ENDPOINTS)
        command = cast(MongoDocument, profile["command"])
        projection = cast(MongoDocument, command["projection"])
        assert set(projection) == {
            "_id",
            "id",
            "service_id",
            "http_method",
            "full_uri",
            "entity_access",
        }

    async def test_one_endpoints_summary_is_a_projected_index_read(
        self, database: WadiDatabase
    ) -> None:
        """The ICFG tools read one summary to say whether empty sites mean "none"."""
        snapshot, (analyzed, _, predating) = await self._seed(database)
        repo = ArtifactRepository(database)

        await database.db.command("profile", 2)
        row = await repo.get_endpoint_entity_access(snapshot.id, analyzed)
        await database.db.command("profile", 0)
        assert row is not None
        assert row.entity_access == _summary(EntityOperation.CREATE_OR_UPDATE)
        [profile] = await _profiled_queries(database, ENDPOINTS)
        _assert_index_served(profile)
        command = cast(MongoDocument, profile["command"])
        assert "entity_access" in cast(MongoDocument, command["projection"])
        assert "response_schema" not in cast(MongoDocument, command["projection"])

        legacy = await repo.get_endpoint_entity_access(snapshot.id, predating)
        assert legacy is not None
        assert legacy.entity_access is None
        assert await repo.get_endpoint_entity_access(snapshot.id, "ep_" + "0" * 16) is None

    async def test_the_list_rows_exclusion_projection_lets_the_summary_through(
        self, database: WadiDatabase
    ) -> None:
        """The list route drops only the wire shapes (§5.2.15), so the summary stays.

        `EndpointSummary.entity_access` exists so the list can show it without
        a fetch per row. An exclusion list that grew to cover it would make
        every row read as "predates the phase" with nothing failing.
        """
        snapshot, (analyzed, no_call, predating) = await self._seed(database)
        repo = ArtifactRepository(database)
        rows: dict[str, list[EndpointEntityAccess] | None] = {}
        for boundary_root in ("services/orders", "services/pets"):
            service = make_service(snapshot, boundary_root).service_id
            for summary in await repo.list_endpoint_summaries(snapshot.id, service):
                rows[summary.id] = summary.entity_access
        assert rows[analyzed] == _summary(EntityOperation.CREATE_OR_UPDATE)
        assert rows[no_call] == []
        assert rows[predating] is None


class TestDataModelsForSnapshot:
    async def test_every_services_models_in_one_index_served_query(
        self, database: WadiDatabase
    ) -> None:
        repo = ArtifactRepository(database)
        system = make_system()
        snapshot, other_snapshot = make_snapshot(system), make_snapshot(system)
        orders = make_service(snapshot, "services/orders")
        pets = make_service(snapshot, "services/pets")
        models = [
            _model(snapshot, orders, "com.acme.orders.Order"),
            _model(snapshot, pets, _PET),
            _model(snapshot, pets, "com.acme.pets.Owner"),
        ]
        await repo.write_data_models(models)
        await repo.write_data_models(
            [_model(other_snapshot, make_service(other_snapshot), "com.acme.other.Thing")]
        )

        await database.db.command("profile", 2)
        loaded = await repo.list_data_models_for_snapshot(snapshot.id)
        await database.db.command("profile", 0)

        assert sorted(model.id for model in loaded) == sorted(model.id for model in models)
        assert {model.id: model for model in loaded} == {model.id: model for model in models}
        [profile] = await _profiled_queries(database, DATA_MODELS)
        _assert_index_served(profile)
        assert profile["nreturned"] == len(models)


def _accounting(call_sites: int) -> EntityAccessAccounting:
    """``call_sites`` bound reads, one site and one access each."""
    return EntityAccessAccounting(
        call_sites=call_sites,
        in_endpoint_flow=call_sites,
        in_no_endpoint_flow=0,
        flush=0,
        implemented_in_project=0,
        entity_undetermined=0,
        unknown_operation=0,
        create_or_update=0,
        bound=call_sites,
        accesses_by_operation={
            op.value: call_sites if op is EntityOperation.READ else 0 for op in EntityOperation
        },
        sites_by_basis={
            basis.value: call_sites if basis is EntityAccessBasis.METHOD_NAME else 0
            for basis in EntityAccessBasis
        },
        rules_version="rules-test",
        gate_flags=[],
    )


_ROUTE = "com.acme.gateway.Route"
_LEDGER = "com.acme.legacy.Ledger"


class TestEntityUsageView:
    """The reverse view's one composition says why each service has accounting or not.

    1.27.0, reviews C3-C5: a library and a failed extraction both lack
    accounting, and readers that inferred "predating" from that alone showed
    libraries as stale and said nothing at all about a failed service.
    """

    async def _seed(self, database: WadiDatabase) -> tuple[Snapshot, dict[str, ServiceBoundary]]:
        """One boundary of each status. `gateway` reports and has no endpoints (C4)."""
        repo = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        pets = make_service(snapshot, "services/pets").model_copy(
            update={"entity_access_accounting": _accounting(call_sites=1)}
        )
        boundaries = {
            "pets": pets,
            "gateway": make_service(snapshot, "services/gateway").model_copy(
                update={"entity_access_accounting": _accounting(call_sites=0)}
            ),
            "billing": make_service(snapshot, "services/billing").model_copy(
                update={"extraction_error": "RuntimeError: parse failed"}
            ),
            "legacy": make_service(snapshot, "services/legacy"),
            "common": make_service(snapshot, "libs/common").model_copy(
                update={"kind": ServiceKind.LIBRARY}
            ),
        }
        await repo.write_service_boundaries(list(boundaries.values()))
        await repo.write_data_models(
            [
                _model(snapshot, pets, _PET),
                _model(snapshot, boundaries["gateway"], _ROUTE),
                _model(snapshot, boundaries["legacy"], _LEDGER),
            ]
        )
        await repo.write_endpoints(
            [
                make_endpoint(snapshot, pets, "/pets").model_copy(
                    update={"entity_access": _summary(EntityOperation.READ)}
                )
            ]
        )
        legacy_doc = to_doc(make_endpoint(snapshot, boundaries["legacy"], "/ledger"))
        del legacy_doc["entity_access"]
        await database.collection(ENDPOINTS).insert_one(legacy_doc)
        return snapshot, boundaries

    @pytest.mark.parametrize(
        ("name", "status"),
        [
            ("pets", EntityAccountingStatus.REPORTING),
            ("common", EntityAccountingStatus.LIBRARY),
            ("billing", EntityAccountingStatus.EXTRACTION_FAILED),
            ("legacy", EntityAccountingStatus.PREDATING),
        ],
    )
    async def test_each_boundary_carries_its_status_and_accounting_only_when_reporting(
        self, database: WadiDatabase, name: str, status: EntityAccountingStatus
    ) -> None:
        snapshot, boundaries = await self._seed(database)
        view = await entity_usage_view(ArtifactRepository(database), snapshot.id)

        [service] = [s for s in view.services if s.service_name == name]
        assert service.service_id == boundaries[name].service_id
        assert service.status is status
        if status is EntityAccountingStatus.REPORTING:
            assert service.accounting == boundaries[name].entity_access_accounting
        else:
            assert service.accounting is None

    async def test_a_reserved_kind_with_accounting_reports_like_a_service(
        self, database: WadiDatabase
    ) -> None:
        # Only `library` has no export of its own; a Phase 9 kind that was
        # analyzed is not one (F3 finding).
        repo = ArtifactRepository(database)
        snapshot = make_snapshot(make_system())
        worker = make_service(snapshot, "functions/thumbnail").model_copy(
            update={
                "kind": ServiceKind.FUNCTION,
                "entity_access_accounting": _accounting(call_sites=0),
            }
        )
        await repo.write_service_boundaries([worker])
        view = await entity_usage_view(repo, snapshot.id)
        [service] = view.services
        assert service.status is EntityAccountingStatus.REPORTING
        assert service.accounting == worker.entity_access_accounting

    async def test_only_reporting_services_list_their_declared_entities(
        self, database: WadiDatabase
    ) -> None:
        """A predating service's Ledger is not a row of six empty lists ("touched by nothing")."""
        snapshot, boundaries = await self._seed(database)
        view = await entity_usage_view(ArtifactRepository(database), snapshot.id)

        assert view.analyzed is True
        assert view.endpoints_predating == 1
        assert {(row.service_id, row.entity) for row in view.entities} == {
            (boundaries["pets"].service_id, _PET),
            (boundaries["gateway"].service_id, _ROUTE),
        }

    async def test_narrowed_to_a_reporting_service_with_no_endpoints_it_is_analyzed(
        self, database: WadiDatabase
    ) -> None:
        """Review C4: `ts-gateway` read `analyzed: false` because 0 predating == 0 rows."""
        snapshot, boundaries = await self._seed(database)
        gateway = boundaries["gateway"].service_id
        view = await entity_usage_view(
            ArtifactRepository(database), snapshot.id, service_id=gateway
        )

        assert view.analyzed is True
        assert view.endpoints_predating == 0
        [route] = view.entities
        assert (route.service_id, route.entity) == (gateway, _ROUTE)
        assert all(usage.endpoints == [] for usage in route.operations)
        assert [(s.service_id, s.status) for s in view.services] == [
            (gateway, EntityAccountingStatus.REPORTING)
        ]

    async def test_narrowed_to_a_service_nobody_examined_it_is_not_analyzed(
        self, database: WadiDatabase
    ) -> None:
        snapshot, boundaries = await self._seed(database)
        for name in ("billing", "legacy", "common"):
            view = await entity_usage_view(
                ArtifactRepository(database),
                snapshot.id,
                service_id=boundaries[name].service_id,
            )
            assert view.analyzed is False, name
            assert view.entities == [], name
            assert [s.service_name for s in view.services] == [name]
