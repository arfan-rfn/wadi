"""`GET /snapshots/{id}/entities` and the entity summary on the endpoint routes (§5.2.17).

The documents are built with the contract models, the way the worker writes
them: sites on a call, folded by `summarize_entity_access`. A snapshot written
before the phase is seeded as a raw document with no `entity_access` key,
because that is what one is, and a null would be a different document.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from wadi_contracts import (
    DataModel,
    Endpoint,
    EntityAccess,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityAccessSite,
    EntityDeclaredBy,
    EntityOperation,
    HttpMethod,
    ServiceBoundary,
    Snapshot,
    data_model_id,
    summarize_entity_access,
)
from wadi_orchestrator.state import AppState
from wadi_storage.codec import to_doc
from wadi_storage.mongo import ENDPOINTS
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system

pytestmark = pytest.mark.integration

_PET = "com.acme.pets.Pet"
_OWNER = "com.acme.pets.Owner"
_REPOSITORY = "com.acme.pets.PetRepository"
_C, _R, _U, _D = (
    EntityOperation.CREATE,
    EntityOperation.READ,
    EntityOperation.UPDATE,
    EntityOperation.DELETE,
)
_CU = EntityOperation.CREATE_OR_UPDATE


def _save(operation: EntityOperation, model_id: str | None) -> EntityAccessSite:
    """One `save` call site, as the worker classifies it."""
    candidate = EntityOperation.CREATE if operation is _CU else None
    return EntityAccessSite(
        repository=_REPOSITORY,
        method_name="save",
        basis=EntityAccessBasis.ARGUMENT_ORIGIN,
        accesses=[
            EntityAccess(
                entity=_PET,
                data_model_id=model_id,
                operation=operation,
                candidate_operation=candidate,
            )
        ],
    )


def _accounting(call_sites: int) -> EntityAccessAccounting:
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
        accesses_by_operation={op.value: 0 for op in EntityOperation},
        sites_by_basis={basis.value: 0 for basis in EntityAccessBasis},
        rules_version="rules-test",
        gate_flags=[],
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


def _endpoint(
    snapshot: Snapshot,
    boundary: ServiceBoundary,
    uri: str,
    sites: list[EntityAccessSite],
    method: HttpMethod = HttpMethod.POST,
) -> Endpoint:
    endpoint = make_endpoint(snapshot, boundary, uri)
    return Endpoint.create(
        snapshot_id=snapshot.id,
        service_id=boundary.service_id,
        http_method=method,
        full_uri=uri,
        handler=endpoint.handler,
        entity_access=summarize_entity_access(sites),
    )


class _Fresh:
    """A snapshot analyzed with entity facts: one service, two entities."""

    def __init__(self, app_state: AppState) -> None:
        system = make_system("entities")
        self.snapshot = make_snapshot(system)
        self.pets = make_service(self.snapshot, "services/pets").model_copy(
            update={"entity_access_accounting": _accounting(call_sites=3)}
        )
        self.pet_model = _model(self.snapshot, self.pets, _PET)
        self.owner_model = _model(self.snapshot, self.pets, _OWNER)
        model_id = self.pet_model.id
        # R1-5: one save the analysis could not split, and a create beside an
        # update. The two endpoints must read differently.
        self.unsplit = _endpoint(self.snapshot, self.pets, "/pets/import", [_save(_CU, model_id)])
        self.split = _endpoint(
            self.snapshot, self.pets, "/pets", [_save(_C, model_id), _save(_U, model_id)]
        )
        self.forwarder = _endpoint(self.snapshot, self.pets, "/pets/sync", [])
        self.app_state = app_state
        self.system = system

    async def write(self) -> None:
        await self.app_state.systems.insert(self.system)
        await self.app_state.snapshots.insert(self.snapshot)
        await self.app_state.artifacts.write_service_boundaries([self.pets])
        await self.app_state.artifacts.write_endpoints([self.unsplit, self.split, self.forwarder])
        await self.app_state.artifacts.write_data_models([self.pet_model, self.owner_model])


def _by_operation(row: dict[str, Any]) -> dict[str, list[str]]:
    return {
        usage["operation"]: [endpoint["full_uri"] for endpoint in usage["endpoints"]]
        for usage in row["operations"]
    }


class TestEntitiesRoute:
    async def test_a_fresh_snapshot_lists_each_entity_with_who_does_what(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        seed = _Fresh(app_state)
        await seed.write()

        response = await client.get(f"/api/v1/snapshots/{seed.snapshot.id}/entities")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["snapshot_id"] == seed.snapshot.id
        assert body["analyzed"] is True
        assert body["endpoints_predating"] == 0
        assert [(row["name"], row["entity"]) for row in body["entities"]] == [
            ("Owner", _OWNER),
            ("Pet", _PET),
        ]
        owner, pet = body["entities"]
        # Q6: a declared entity no endpoint reaches is a row of six empty
        # lists, a stated "no endpoint", never a missing row.
        assert _by_operation(owner) == {op.value: [] for op in EntityOperation}
        assert pet["storage_name"] == "pet"
        assert pet["declared_by"] == "annotation"
        assert pet["data_model_id"] == seed.pet_model.id
        [service] = body["services"]
        assert service["service_name"] == "pets"
        assert service["accounting"]["call_sites"] == 3

    async def test_one_unsplit_save_never_reads_as_a_create_plus_an_update(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """R1-5: `create-or-update` is its own claim, never merged into either verb."""
        seed = _Fresh(app_state)
        await seed.write()

        body = (await client.get(f"/api/v1/snapshots/{seed.snapshot.id}/entities")).json()
        pet = next(row for row in body["entities"] if row["entity"] == _PET)
        assert _by_operation(pet) == {
            "create": ["/pets"],
            "read": [],
            "update": ["/pets"],
            "delete": [],
            "create-or-update": ["/pets/import"],
            "unknown": [],
        }
        create = next(usage for usage in pet["operations"] if usage["operation"] == "create")
        assert create["endpoints"] == [
            {
                "endpoint_id": seed.split.id,
                "http_method": "POST",
                "full_uri": "/pets",
                "call_sites": 2,
            }
        ]

    async def test_a_snapshot_predating_entity_facts_says_so_and_lists_nothing(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """R1-6: listing its data models as unreached would turn "not looked
        at" into "touched by nothing"."""
        system = make_system("old")
        snapshot = make_snapshot(system)
        boundary = make_service(snapshot)
        await app_state.systems.insert(system)
        await app_state.snapshots.insert(snapshot)
        await app_state.artifacts.write_service_boundaries([boundary])
        await app_state.artifacts.write_data_models([_model(snapshot, boundary, _PET)])
        for uri in ("/pets", "/pets/{id}"):
            document = to_doc(make_endpoint(snapshot, boundary, uri))
            del document["entity_access"]
            await app_state.database.collection(ENDPOINTS).insert_one(document)

        response = await client.get(f"/api/v1/snapshots/{snapshot.id}/entities")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["analyzed"] is False
        assert body["endpoints_predating"] == 2
        assert body["entities"] == []
        assert body["services"] == [
            {"service_id": boundary.service_id, "service_name": "orders", "accounting": None}
        ]

    async def test_unknown_snapshot_404(self, client: AsyncClient) -> None:
        missing = "snap_" + "0" * 32
        response = await client.get(f"/api/v1/snapshots/{missing}/entities")
        assert response.status_code == 404
        # The route's own 404, worded as /auth words it, not FastAPI's "no route".
        assert response.json()["detail"] == f"snapshot {missing} not found"


class TestEndpointRoutesCarryTheSummary:
    """`EndpointSummary` and `Endpoint` carry `entity_access` on the existing routes."""

    async def test_list_and_detail_return_the_summary_and_keep_empty_apart_from_none(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        seed = _Fresh(app_state)
        await seed.write()
        predating = make_endpoint(seed.snapshot, seed.pets, "/legacy")
        document = to_doc(predating)
        del document["entity_access"]
        await app_state.database.collection(ENDPOINTS).insert_one(document)

        listed = await client.get(
            f"/api/v1/snapshots/{seed.snapshot.id}/services/{seed.pets.service_id}/endpoints"
        )
        assert listed.status_code == 200, listed.text
        rows = {row["full_uri"]: row["entity_access"] for row in listed.json()}
        assert rows["/pets/import"] == [
            {
                "entity": _PET,
                "data_model_id": seed.pet_model.id,
                "operations": ["create-or-update"],
                "call_sites": 1,
            }
        ]
        assert rows["/pets"][0]["operations"] == ["create", "update"]
        assert rows["/pets/sync"] == []
        assert rows["/legacy"] is None

        detail = await client.get(
            f"/api/v1/snapshots/{seed.snapshot.id}/endpoints/{seed.split.id}/detail"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["endpoint"]["entity_access"] == rows["/pets"]

        single = await client.get(f"/api/v1/snapshots/{seed.snapshot.id}/endpoints/{predating.id}")
        assert single.json()["entity_access"] is None
