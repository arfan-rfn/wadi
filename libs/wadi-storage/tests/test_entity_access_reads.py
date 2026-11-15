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
    EntityAccessBasis,
    EntityAccessSite,
    EntityDeclaredBy,
    EntityOperation,
    ServiceBoundary,
    Snapshot,
    data_model_id,
    summarize_entity_access,
)
from wadi_storage import ArtifactRepository, WadiDatabase
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
