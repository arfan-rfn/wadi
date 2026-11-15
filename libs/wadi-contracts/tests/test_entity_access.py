"""Entity-access contract tests (§5.2.17, Phase 2.10).

The validators here are the claim rules: a demoted save publishes
``create-or-update`` and keeps its candidate as evidence only (R1-11), a
derived method has exactly one access, and an id never names a model the
fact does not. Each one is pinned by an input it must reject.
"""

import json
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from wadi_contracts.datamodel import DataModel, DataModelField
from wadi_contracts.endpoint import Endpoint
from wadi_contracts.entity_access import (
    EndpointEntityAccess,
    EndpointEntityAccessRow,
    EntityAccess,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityAccessSite,
    EntityAccountingStatus,
    EntityCoverageSection,
    EntityDeclaredBy,
    EntityGateFlagState,
    EntityOperation,
    EntityOperationUsage,
    EntityUsageEndpoint,
    EntityUsageRow,
    EntityUsageService,
    ServiceEntityAccounting,
    UnmeasuredEntityAccess,
    build_entity_usage_view,
    summarize_entity_access,
)
from wadi_contracts.enums import HttpMethod, IcfgNodeKind, SinkKind
from wadi_contracts.icfg import IcfgNode
from wadi_contracts.source import MethodRef, SourceAnchor
from wadi_contracts.stitching import CoverageReport, CoverageTotals
from wadi_contracts.views import EndpointSummary
from wadi_testing.builders import make_service, make_snapshot, make_system

_DM = "dm_0123456789abcdef"
_DM_OWNER = "dm_fedcba9876543210"
_REPO = "com.acme.pets.PetRepository"


def _access(
    entity: str | None = "com.acme.Pet",
    operation: EntityOperation = EntityOperation.READ,
    data_model_id: str | None = None,
) -> EntityAccess:
    return EntityAccess(entity=entity, data_model_id=data_model_id, operation=operation)


def _site(
    *accesses: EntityAccess,
    basis: EntityAccessBasis = EntityAccessBasis.METHOD_NAME,
    method_name: str = "findById",
) -> EntityAccessSite:
    return EntityAccessSite(
        repository=_REPO,
        method_name=method_name,
        basis=basis,
        accesses=list(accesses) or [_access()],
    )


class TestEntityAccess:
    def test_a_single_verb_with_no_candidate_is_a_claim(self) -> None:
        access = EntityAccess(
            entity="com.acme.Pet", data_model_id=_DM, operation=EntityOperation.READ
        )
        assert access.operation is EntityOperation.READ
        assert access.candidate_operation is None

    def test_a_demoted_save_keeps_its_candidate_as_evidence(self) -> None:
        access = EntityAccess(
            entity="com.acme.Pet",
            data_model_id=_DM,
            operation=EntityOperation.CREATE_OR_UPDATE,
            candidate_operation=EntityOperation.CREATE,
        )
        assert access.candidate_operation is EntityOperation.CREATE

    def test_a_candidate_beside_a_published_verb_is_rejected(self) -> None:
        # R1-11: a candidate on a fact that already publishes a single verb
        # would be a second, unearned claim riding on the first.
        with pytest.raises(ValidationError, match="candidate_operation"):
            EntityAccess(
                entity="com.acme.Pet",
                data_model_id=None,
                operation=EntityOperation.UPDATE,
                candidate_operation=EntityOperation.UPDATE,
            )

    @pytest.mark.parametrize(
        "candidate",
        [
            EntityOperation.READ,
            EntityOperation.DELETE,
            EntityOperation.CREATE_OR_UPDATE,
            EntityOperation.UNKNOWN,
        ],
    )
    def test_a_candidate_is_only_ever_create_or_update(self, candidate: EntityOperation) -> None:
        with pytest.raises(ValidationError, match="candidate_operation"):
            EntityAccess(
                entity="com.acme.Pet",
                data_model_id=None,
                operation=EntityOperation.CREATE_OR_UPDATE,
                candidate_operation=candidate,
            )

    def test_an_undetermined_entity_cannot_name_a_data_model(self) -> None:
        with pytest.raises(ValidationError, match="data_model_id"):
            EntityAccess(entity=None, data_model_id=_DM, operation=EntityOperation.READ)

    def test_an_undetermined_entity_without_a_model_is_honest(self) -> None:
        access = EntityAccess(entity=None, data_model_id=None, operation=EntityOperation.DELETE)
        assert access.entity is None

    def test_a_data_model_id_must_be_a_dm_id(self) -> None:
        with pytest.raises(ValidationError, match="data_model_id"):
            EntityAccess(entity="com.acme.Pet", data_model_id="Pet", operation=EntityOperation.READ)

    def test_operation_vocabulary_is_in_display_order(self) -> None:
        assert [op.value for op in EntityOperation] == [
            "create",
            "read",
            "update",
            "delete",
            "create-or-update",
            "unknown",
        ]


class TestEntityAccessSite:
    def test_a_derived_method_has_one_access(self) -> None:
        site = _site(_access())
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert site.entity_type_text is None

    def test_a_site_touches_at_least_one_entity(self) -> None:
        with pytest.raises(ValidationError, match="accesses"):
            EntityAccessSite(
                repository=_REPO,
                method_name="findById",
                basis=EntityAccessBasis.METHOD_NAME,
                accesses=[],
            )

    @pytest.mark.parametrize(
        "basis",
        [
            EntityAccessBasis.METHOD_NAME,
            EntityAccessBasis.ARGUMENT_ORIGIN,
            EntityAccessBasis.EXISTENCE_GUARD,
        ],
    )
    def test_only_a_query_names_several_entities(self, basis: EntityAccessBasis) -> None:
        # A derived method or a save acts on the repository's one entity;
        # two accesses there would be invented, not read (C1).
        with pytest.raises(ValidationError, match="query-text"):
            _site(_access(), _access("com.acme.Owner"), basis=basis)

    def test_a_query_that_deletes_one_entity_and_reads_another_is_one_site(self) -> None:
        site = _site(
            _access("com.acme.Invoice", EntityOperation.DELETE),
            _access("com.acme.Customer", EntityOperation.READ),
            basis=EntityAccessBasis.QUERY_TEXT,
            method_name="purgeForCustomer",
        )
        assert [a.operation for a in site.accesses] == [
            EntityOperation.DELETE,
            EntityOperation.READ,
        ]

    def test_raw_type_text_survives_an_unresolved_entity(self) -> None:
        site = EntityAccessSite(
            repository=_REPO,
            method_name="findAll",
            basis=EntityAccessBasis.METHOD_NAME,
            accesses=[_access(entity=None)],
            entity_type_text="T",
        )
        assert site.entity_type_text == "T"


def _node(kind: IcfgNodeKind, sites: list[EntityAccessSite]) -> IcfgNode:
    sig = "com.acme.PetService.get(java.lang.String)"
    return IcfgNode(
        id="n1",
        kind=kind,
        anchor=SourceAnchor(file="src/A.java", start_line=3, end_line=3),
        source_text="return repo.findById(id);",
        method=MethodRef(id="m_0123456789abcdef", signature=sig),
        entity_access_sites=sites,
    )


class TestIcfgNodeSites:
    def test_sites_default_to_empty(self) -> None:
        node = IcfgNode(
            id="n1",
            kind=IcfgNodeKind.CALL,
            anchor=SourceAnchor(file="src/A.java", start_line=3, end_line=3),
            source_text="repo.flush();",
            method=MethodRef(id="m_0123456789abcdef", signature="A.b()"),
            sink=SinkKind.DB,
        )
        assert node.entity_access_sites == []

    @pytest.mark.parametrize("kind", [IcfgNodeKind.CALL, IcfgNodeKind.RETURN])
    def test_a_statement_carries_its_sites(self, kind: IcfgNodeKind) -> None:
        # R1-2: one statement can hold two repository calls, so two sites.
        two = [_site(), _site(method_name="existsById")]
        assert len(_node(kind, two).entity_access_sites) == 2

    @pytest.mark.parametrize("kind", [IcfgNodeKind.ENTRY, IcfgNodeKind.EXIT])
    def test_a_synthetic_node_cannot_carry_a_site(self, kind: IcfgNodeKind) -> None:
        with pytest.raises(ValidationError, match="entity_access_sites"):
            _node(kind, [_site()])


class TestEndpointEntityAccess:
    def test_operations_in_enum_order_are_accepted(self) -> None:
        row = EndpointEntityAccess(
            entity="com.acme.Pet",
            data_model_id=_DM,
            operations=[EntityOperation.READ, EntityOperation.CREATE_OR_UPDATE],
            call_sites=2,
        )
        assert row.call_sites == 2

    def test_operations_out_of_enum_order_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="enum order"):
            EndpointEntityAccess(
                entity="com.acme.Pet",
                data_model_id=None,
                operations=[EntityOperation.UPDATE, EntityOperation.READ],
                call_sites=1,
            )

    def test_a_repeated_operation_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            EndpointEntityAccess(
                entity="com.acme.Pet",
                data_model_id=None,
                operations=[EntityOperation.READ, EntityOperation.READ],
                call_sites=2,
            )

    def test_a_row_names_at_least_one_operation(self) -> None:
        with pytest.raises(ValidationError, match="operations"):
            EndpointEntityAccess(
                entity="com.acme.Pet", data_model_id=None, operations=[], call_sites=1
            )

    def test_a_row_comes_from_at_least_one_site(self) -> None:
        with pytest.raises(ValidationError, match="call_sites"):
            EndpointEntityAccess(
                entity="com.acme.Pet",
                data_model_id=None,
                operations=[EntityOperation.READ],
                call_sites=0,
            )


class TestSummarizeEntityAccess:
    def test_no_sites_is_an_empty_summary(self) -> None:
        # R1-6: [] is "analyzed, no repository call found" — the worker's
        # answer for an endpoint that touches nothing, never None.
        assert summarize_entity_access([]) == []

    def test_two_sites_on_one_entity_fold_into_one_row(self) -> None:
        rows = summarize_entity_access(
            [
                _site(_access(operation=EntityOperation.READ, data_model_id=_DM)),
                _site(
                    _access(operation=EntityOperation.DELETE, data_model_id=_DM),
                    method_name="deleteById",
                ),
            ]
        )
        assert rows == [
            EndpointEntityAccess(
                entity="com.acme.Pet",
                data_model_id=_DM,
                operations=[EntityOperation.READ, EntityOperation.DELETE],
                call_sites=2,
                # One read site and one delete site, never "2" under each.
                call_sites_by_operation={"read": 1, "delete": 1},
            )
        ]

    def test_operations_come_out_in_enum_order_whatever_the_site_order(self) -> None:
        rows = summarize_entity_access(
            [
                _site(_access(operation=EntityOperation.UNKNOWN)),
                _site(_access(operation=EntityOperation.DELETE)),
                _site(_access(operation=EntityOperation.CREATE)),
                _site(_access(operation=EntityOperation.DELETE)),
            ]
        )
        assert rows[0].operations == [
            EntityOperation.CREATE,
            EntityOperation.DELETE,
            EntityOperation.UNKNOWN,
        ]
        assert rows[0].call_sites == 4

    def test_a_two_entity_query_site_counts_once_for_each_entity(self) -> None:
        query = _site(
            _access("com.acme.Invoice", EntityOperation.DELETE),
            _access("com.acme.Customer", EntityOperation.READ),
            basis=EntityAccessBasis.QUERY_TEXT,
        )
        rows = summarize_entity_access([query])
        assert [(r.entity, r.operations, r.call_sites) for r in rows] == [
            ("com.acme.Customer", [EntityOperation.READ], 1),
            ("com.acme.Invoice", [EntityOperation.DELETE], 1),
        ]

    def test_two_accesses_to_one_entity_at_one_site_count_one_site(self) -> None:
        # Distinct-site counting: a delete-with-subquery touches Invoice twice
        # at ONE call site. call_sites counts sites, never accesses.
        query = _site(
            _access("com.acme.Invoice", EntityOperation.DELETE),
            _access("com.acme.Invoice", EntityOperation.READ),
            basis=EntityAccessBasis.QUERY_TEXT,
        )
        rows = summarize_entity_access([query, _site(_access("com.acme.Invoice"))])
        assert rows == [
            EndpointEntityAccess(
                entity="com.acme.Invoice",
                data_model_id=None,
                operations=[EntityOperation.READ, EntityOperation.DELETE],
                call_sites=2,
                # The query site reads and deletes Invoice, so it counts once
                # under each; the plain read site adds one read.
                call_sites_by_operation={"read": 2, "delete": 1},
            )
        ]

    def test_create_or_update_is_never_merged_into_create_or_update_verbs(self) -> None:
        # R1-5: one undecided save beside a decided create still reads as
        # both — collapsing either way would change what the endpoint claims.
        save = EntityOperation.CREATE_OR_UPDATE
        rows = summarize_entity_access(
            [
                _site(_access(operation=save), basis=EntityAccessBasis.ARGUMENT_ORIGIN),
                _site(
                    _access(operation=EntityOperation.CREATE),
                    basis=EntityAccessBasis.ARGUMENT_ORIGIN,
                ),
            ]
        )
        assert rows[0].operations == [EntityOperation.CREATE, save]

    def test_a_create_and_an_update_never_become_create_or_update(self) -> None:
        rows = summarize_entity_access(
            [
                _site(_access(operation=EntityOperation.CREATE)),
                _site(_access(operation=EntityOperation.UPDATE)),
            ]
        )
        assert rows[0].operations == [EntityOperation.CREATE, EntityOperation.UPDATE]

    def test_a_candidate_is_never_summarized_as_a_claim(self) -> None:
        demoted = EntityAccess(
            entity="com.acme.Pet",
            data_model_id=None,
            operation=EntityOperation.CREATE_OR_UPDATE,
            candidate_operation=EntityOperation.UPDATE,
        )
        rows = summarize_entity_access([_site(demoted, basis=EntityAccessBasis.EXISTENCE_GUARD)])
        assert rows[0].operations == [EntityOperation.CREATE_OR_UPDATE]

    def test_the_undetermined_entity_row_sorts_last(self) -> None:
        rows = summarize_entity_access(
            [
                _site(_access(entity=None)),
                _site(_access("com.acme.Zebra")),
                _site(_access("com.acme.Aardvark")),
            ]
        )
        assert [r.entity for r in rows] == ["com.acme.Aardvark", "com.acme.Zebra", None]

    def test_one_type_with_two_model_ids_stays_two_rows(self) -> None:
        # Grouping is by (entity, data_model_id) exactly as written; the fold
        # does not decide which id is the right one.
        rows = summarize_entity_access(
            [
                _site(_access(data_model_id=_DM_OWNER)),
                _site(_access(data_model_id=_DM)),
            ]
        )
        assert [r.data_model_id for r in rows] == [_DM, _DM_OWNER]


class TestEndpointCarriesTheSummary:
    def _endpoint(self, handler_ref: MethodRef, svc_id: str) -> Endpoint:
        return Endpoint.create(
            snapshot_id="snap-1",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/pets/{id}",
            handler=handler_ref,
        )

    def test_an_endpoint_predating_the_phase_says_none(
        self, handler_ref: MethodRef, svc_id: str
    ) -> None:
        assert self._endpoint(handler_ref, svc_id).entity_access is None

    def test_none_and_empty_survive_a_round_trip_apart(
        self, handler_ref: MethodRef, svc_id: str
    ) -> None:
        # R1-6: "predates the phase" and "analyzed, nothing found" are two
        # answers; JSON must not fold them into one.
        old = self._endpoint(handler_ref, svc_id)
        analyzed = old.model_copy(update={"entity_access": []})
        assert Endpoint.model_validate_json(old.model_dump_json()).entity_access is None
        assert Endpoint.model_validate_json(analyzed.model_dump_json()).entity_access == []

    def test_create_takes_the_summary(self, handler_ref: MethodRef, svc_id: str) -> None:
        row = EndpointEntityAccess(
            entity="com.acme.Pet",
            data_model_id=None,
            operations=[EntityOperation.READ],
            call_sites=1,
        )
        endpoint = Endpoint.create(
            snapshot_id="snap-1",
            service_id=svc_id,
            http_method=HttpMethod.GET,
            full_uri="/pets/{id}",
            handler=handler_ref,
            entity_access=[row],
        )
        assert endpoint.entity_access == [row]

    def test_the_list_row_carries_the_summary(self, handler_ref: MethodRef, svc_id: str) -> None:
        endpoint = self._endpoint(handler_ref, svc_id).model_copy(update={"entity_access": []})
        summary = EndpointSummary.model_validate(
            endpoint.model_dump(exclude={"request_schema", "response_schema", "type_defs"})
        )
        assert summary.entity_access == []


class TestDataModelIsTheEntityRecord:
    def test_a_pre_phase_document_still_reads(self, svc_id: str) -> None:
        # Written by 1.25.0: none of the entity-record fields exist yet.
        legacy = {
            "schema_version": "1.25.0",
            "snapshot_id": "snap-1",
            "service_id": svc_id,
            "created_at": "2026-11-01T00:00:00Z",
            "id": _DM,
            "entity": "Pet",
            "fields": [{"name": "tags", "type_name": "java.util.List"}],
            "persistence_framework": "spring-data-jpa",
        }
        model = DataModel.model_validate(legacy)
        assert model.declared_by is None
        assert model.type_full_name is None
        assert model.jpql_name is None
        assert model.fields[0].declared_type is None

    def test_the_entity_record_carries_its_names_and_origin(self, svc_id: str) -> None:
        model = DataModel(
            snapshot_id="snap-1",
            service_id=svc_id,
            id=_DM,
            entity="Pet",
            type_full_name="com.acme.pets.Pet",
            jpql_name="PetEntity",
            storage_name="pets",
            declared_by=EntityDeclaredBy.REPOSITORY_ARGUMENT,
            fields=[
                DataModelField(name="tags", type_name="java.util.List", declared_type="List<Tag>")
            ],
            persistence_framework="spring-data-jpa",
        )
        restored = DataModel.model_validate_json(model.model_dump_json())
        assert restored.declared_by is EntityDeclaredBy.REPOSITORY_ARGUMENT
        assert restored.fields[0].declared_type == "List<Tag>"
        assert restored.jpql_name == "PetEntity"


def _accounting(**overrides: Any) -> dict[str, Any]:
    """Ten sites, every partition consistent; tests break one thing at a time."""
    base: dict[str, Any] = {
        "call_sites": 10,
        "in_endpoint_flow": 8,
        "in_no_endpoint_flow": 2,
        "flush": 1,
        "implemented_in_project": 1,
        "entity_undetermined": 2,
        "unknown_operation": 1,
        "create_or_update": 2,
        "bound": 3,
        # Nine non-flush sites: one basis each, at least one access each, and
        # at least as many create-or-update and unknown accesses as the
        # buckets that count them.
        "accesses_by_operation": {
            "create": 1,
            "read": 2,
            "update": 1,
            "delete": 1,
            "create-or-update": 2,
            "unknown": 2,
        },
        "sites_by_basis": {
            "method-name": 3,
            "query-text": 2,
            "argument-origin": 2,
            "existence-guard": 2,
        },
        "rules_version": "r-0123abcd",
        "gate_flags": [
            {
                "basis": "argument-origin",
                "operation": "create",
                "enabled": False,
                "scored_rules_version": None,
            }
        ],
    }
    base.update(overrides)
    return base


class TestEntityAccessAccounting:
    def test_a_consistent_accounting_is_accepted(self) -> None:
        accounting = EntityAccessAccounting.model_validate(_accounting())
        assert accounting.gate_flags == [
            EntityGateFlagState(
                basis=EntityAccessBasis.ARGUMENT_ORIGIN,
                operation=EntityOperation.CREATE,
                enabled=False,
                scored_rules_version=None,
            )
        ]

    def test_flow_membership_must_account_for_every_site(self) -> None:
        with pytest.raises(ValidationError, match="in_endpoint_flow"):
            EntityAccessAccounting.model_validate(_accounting(in_no_endpoint_flow=1))

    def test_outcomes_must_account_for_every_site(self) -> None:
        with pytest.raises(ValidationError, match="bound"):
            EntityAccessAccounting.model_validate(_accounting(bound=4))

    @pytest.mark.parametrize("field", ["accesses_by_operation", "sites_by_basis"])
    def test_a_missing_vocabulary_key_is_rejected(self, field: str) -> None:
        # A zero must be written as a zero: an absent key would read the same
        # as "never measured" (E8).
        counts = dict(_accounting()[field])
        counts.pop(next(iter(counts)))
        with pytest.raises(ValidationError, match=field):
            EntityAccessAccounting.model_validate(_accounting(**{field: counts}))

    @pytest.mark.parametrize("field", ["accesses_by_operation", "sites_by_basis"])
    def test_an_unknown_vocabulary_key_is_rejected(self, field: str) -> None:
        counts = {**_accounting()[field], "write": 0}
        with pytest.raises(ValidationError, match=field):
            EntityAccessAccounting.model_validate(_accounting(**{field: counts}))

    def test_the_bases_count_every_site_but_the_flushes(self) -> None:
        # 1.27.0: `bound=10` beside all-zero dicts used to pass.
        bases = {**_accounting()["sites_by_basis"], "method-name": 2}
        with pytest.raises(ValidationError, match="sites_by_basis sums to 8"):
            EntityAccessAccounting.model_validate(_accounting(sites_by_basis=bases))

    def test_every_site_has_at_least_one_access(self) -> None:
        accesses = dict.fromkeys(_accounting()["accesses_by_operation"], 0)
        accesses["create-or-update"] = 2
        accesses["unknown"] = 1
        with pytest.raises(ValidationError, match="fewer than the 9 sites"):
            EntityAccessAccounting.model_validate(_accounting(accesses_by_operation=accesses))

    def test_a_bucket_needs_accesses_with_its_operation(self) -> None:
        accesses = {**_accounting()["accesses_by_operation"], "create-or-update": 1, "read": 3}
        with pytest.raises(ValidationError, match="counted under create-or-update"):
            EntityAccessAccounting.model_validate(_accounting(accesses_by_operation=accesses))

    def test_a_negative_count_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="flush"):
            EntityAccessAccounting.model_validate(_accounting(flush=-1, bound=5))

    def test_the_boundary_carries_it_beside_analysis_coverage(self) -> None:
        # E2: a sibling of analysis_coverage, never inside it — None on a
        # boundary written before the phase.
        boundary = make_service(make_snapshot(make_system()), "services/pets")
        assert boundary.entity_access_accounting is None
        counted = boundary.model_copy(
            update={
                "entity_access_accounting": EntityAccessAccounting.model_validate(_accounting())
            }
        )
        restored = type(boundary).model_validate(json.loads(counted.model_dump_json()))
        assert restored.entity_access_accounting is not None
        assert restored.entity_access_accounting.call_sites == 10


_TOTALS = CoverageTotals(
    call_sites=0, edges=0, analyzed=0, external=0, placeholder=0, undetermined=0
)


class TestEntityCoverageSection:
    def _section(self) -> EntityCoverageSection:
        accounting = EntityAccessAccounting.model_validate(_accounting())
        return EntityCoverageSection(
            services_reporting=1,
            services_predating=1,
            call_sites=10,
            in_endpoint_flow=8,
            in_no_endpoint_flow=2,
            flush=1,
            implemented_in_project=1,
            entity_undetermined=2,
            unknown_operation=1,
            create_or_update=2,
            bound=3,
            accesses_by_operation=accounting.accesses_by_operation,
            sites_by_basis=accounting.sites_by_basis,
            by_service=[
                ServiceEntityAccounting(
                    service_id="svc-pets", service_name="pets", accounting=accounting
                )
            ],
        )

    def test_every_unmeasured_case_is_always_named(self) -> None:
        # Q2/Q17/Q4: a reader of the counts is told what they leave out on
        # every report, not only when someone thinks to ask.
        assert self._section().unmeasured == list(UnmeasuredEntityAccess)

    def test_the_report_predating_the_phase_has_no_section(self) -> None:
        report = CoverageReport(snapshot_id="snap-1", totals=_TOTALS)
        assert report.entity_coverage is None

    def test_the_section_round_trips_on_the_report(self) -> None:
        report = CoverageReport(
            snapshot_id="snap-1", totals=_TOTALS, entity_coverage=self._section()
        )
        restored = CoverageReport.model_validate_json(report.model_dump_json())
        assert restored.entity_coverage is not None
        assert restored.entity_coverage.by_service[0].accounting.call_sites == 10
        assert restored.entity_coverage.unexercised_vocabulary == []


_PETS = "svc-pets"
_OWNERS = "svc-owners"


def _model(service_id: str, name: str, model_id: str, **extra: Any) -> DataModel:
    return DataModel(
        snapshot_id="snap-1",
        service_id=service_id,
        id=model_id,
        entity=name,
        type_full_name=f"com.acme.{name}",
        persistence_framework="spring-data-jpa",
        declared_by=EntityDeclaredBy.ANNOTATION,
        **extra,
    )


def _row(
    endpoint_id: str,
    full_uri: str,
    access: list[EndpointEntityAccess] | None,
    *,
    service_id: str = _PETS,
    method: HttpMethod = HttpMethod.GET,
) -> EndpointEntityAccessRow:
    return EndpointEntityAccessRow(
        endpoint_id=endpoint_id,
        service_id=service_id,
        http_method=method,
        full_uri=full_uri,
        entity_access=access,
    )


def _summary(
    entity: str | None,
    *ops: EntityOperation,
    model_id: str | None = None,
    sites: int = 1,
    by_operation: dict[str, int] | None | Literal["all"] = "all",
) -> EndpointEntityAccess:
    """A summary row; by default every operation was performed by every site."""
    return EndpointEntityAccess(
        entity=entity,
        data_model_id=model_id,
        operations=list(ops),
        call_sites=sites,
        call_sites_by_operation=(
            {op.value: sites for op in ops} if by_operation == "all" else by_operation
        ),
    )


def _usage(row: EntityUsageRow) -> dict[EntityOperation, list[str]]:
    return {usage.operation: [e.endpoint_id for e in usage.endpoints] for usage in row.operations}


def _reporting(service_id: str, name: str) -> EntityUsageService:
    return EntityUsageService(
        service_id=service_id,
        service_name=name,
        status=EntityAccountingStatus.REPORTING,
        accounting=EntityAccessAccounting.model_validate(_accounting()),
    )


def _not_reporting(
    service_id: str, name: str, status: EntityAccountingStatus = EntityAccountingStatus.PREDATING
) -> EntityUsageService:
    return EntityUsageService(
        service_id=service_id, service_name=name, status=status, accounting=None
    )


_SERVICES = [_reporting(_PETS, "pets"), _reporting(_OWNERS, "owners")]
_PREDATING = [_not_reporting(_PETS, "pets"), _not_reporting(_OWNERS, "owners")]


class TestBuildEntityUsageView:
    def test_a_declared_entity_no_endpoint_reaches_has_six_empty_lists(self) -> None:
        # Q6: an entity is a row because it exists, not because it is reached.
        view = build_entity_usage_view(
            "snap-1",
            [_row("ep_1", "/pets", [])],
            [_model(_PETS, "Pet", _DM, storage_name="pets")],
            _SERVICES,
        )
        assert view.analyzed is True
        [row] = view.entities
        assert (row.entity, row.name, row.data_model_id) == ("com.acme.Pet", "Pet", _DM)
        assert (row.storage_name, row.declared_by) == ("pets", EntityDeclaredBy.ANNOTATION)
        assert [u.operation for u in row.operations] == list(EntityOperation)
        assert all(u.endpoints == [] for u in row.operations)

    def test_endpoints_land_under_each_operation_they_may_perform(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [
                _row(
                    "ep_get",
                    "/pets/{id}",
                    [_summary("com.acme.Pet", EntityOperation.READ, model_id=_DM, sites=2)],
                ),
                _row(
                    "ep_put",
                    "/pets/{id}",
                    [
                        _summary(
                            "com.acme.Pet",
                            EntityOperation.READ,
                            EntityOperation.CREATE_OR_UPDATE,
                            model_id=_DM,
                        )
                    ],
                    method=HttpMethod.PUT,
                ),
            ],
            [_model(_PETS, "Pet", _DM)],
            _SERVICES,
        )
        [row] = view.entities
        usage = _usage(row)
        assert usage[EntityOperation.READ] == ["ep_get", "ep_put"]
        assert usage[EntityOperation.CREATE_OR_UPDATE] == ["ep_put"]
        # One undecided save is not a create plus an update (R1-5).
        assert usage[EntityOperation.CREATE] == []
        assert usage[EntityOperation.UPDATE] == []
        read = next(u for u in row.operations if u.operation is EntityOperation.READ)
        assert read.endpoints[0] == EntityUsageEndpoint(
            endpoint_id="ep_get", http_method=HttpMethod.GET, full_uri="/pets/{id}", call_sites=2
        )

    def test_endpoints_sort_by_uri_then_method(self) -> None:
        read = [_summary("com.acme.Pet", EntityOperation.READ, model_id=_DM)]
        view = build_entity_usage_view(
            "snap-1",
            [
                _row("ep_b_put", "/b", read, method=HttpMethod.PUT),
                _row("ep_b_get", "/b", read, method=HttpMethod.GET),
                _row("ep_a", "/a", read, method=HttpMethod.POST),
            ],
            [_model(_PETS, "Pet", _DM)],
            _SERVICES,
        )
        assert _usage(view.entities[0])[EntityOperation.READ] == ["ep_a", "ep_b_get", "ep_b_put"]

    def test_an_entity_only_an_access_names_still_gets_a_row(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [
                _row(
                    "ep_1",
                    "/audit",
                    [_summary("com.acme.audit.AuditEntry", EntityOperation.CREATE)],
                )
            ],
            [],
            _SERVICES,
        )
        [row] = view.entities
        assert (row.entity, row.name, row.data_model_id) == (
            "com.acme.audit.AuditEntry",
            "AuditEntry",
            None,
        )
        assert (row.storage_name, row.declared_by) == (None, None)
        assert _usage(row)[EntityOperation.CREATE] == ["ep_1"]

    def test_undetermined_accesses_get_one_row_per_service(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [
                _row("ep_p1", "/p1", [_summary(None, EntityOperation.READ)]),
                _row("ep_p2", "/p2", [_summary(None, EntityOperation.DELETE)]),
                _row("ep_o1", "/o1", [_summary(None, EntityOperation.UNKNOWN)], service_id=_OWNERS),
            ],
            [_model(_PETS, "Pet", _DM)],
            _SERVICES,
        )
        undetermined = [r for r in view.entities if r.entity is None]
        assert [(r.service_id, r.name) for r in undetermined] == [
            (_OWNERS, "entity not determined"),
            (_PETS, "entity not determined"),
        ]
        pets = next(r for r in undetermined if r.service_id == _PETS)
        assert _usage(pets)[EntityOperation.READ] == ["ep_p1"]
        assert _usage(pets)[EntityOperation.DELETE] == ["ep_p2"]
        assert pets.data_model_id is None

    def test_a_service_with_no_undetermined_access_has_no_such_row(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [_row("ep_1", "/pets", [_summary("com.acme.Pet", EntityOperation.READ, model_id=_DM)])],
            [_model(_PETS, "Pet", _DM)],
            _SERVICES,
        )
        assert [r.entity for r in view.entities] == ["com.acme.Pet"]

    def test_an_entity_is_scoped_to_its_service(self) -> None:
        # Two services each with their own `Pet`: two rows, never one.
        other = "dm_1111111111111111"
        view = build_entity_usage_view(
            "snap-1",
            [
                _row("ep_p", "/p", [_summary("com.acme.Pet", EntityOperation.READ, model_id=_DM)]),
                _row(
                    "ep_o",
                    "/o",
                    [_summary("com.acme.Pet", EntityOperation.DELETE, model_id=other)],
                    service_id=_OWNERS,
                ),
            ],
            [_model(_PETS, "Pet", _DM), _model(_OWNERS, "Pet", other)],
            _SERVICES,
        )
        assert [(r.service_id, _usage(r)[EntityOperation.READ]) for r in view.entities] == [
            (_OWNERS, []),
            (_PETS, ["ep_p"]),
        ]

    def test_rows_sort_by_service_then_name(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [_row("ep_1", "/x", [])],
            [
                _model(_PETS, "Visit", "dm_2222222222222222"),
                _model(_OWNERS, "Owner", "dm_3333333333333333"),
                _model(_PETS, "Pet", _DM),
            ],
            _SERVICES,
        )
        assert [(r.service_id, r.name) for r in view.entities] == [
            (_OWNERS, "Owner"),
            (_PETS, "Pet"),
            (_PETS, "Visit"),
        ]

    def test_a_snapshot_predating_the_phase_is_not_analyzed(self) -> None:
        # R1-6: every row None means no endpoint was ever examined. Listing the
        # data models as unreached would turn "not looked" into "nothing".
        view = build_entity_usage_view(
            "snap-1",
            [_row("ep_1", "/a", None), _row("ep_2", "/b", None)],
            [_model(_PETS, "Pet", _DM)],
            _PREDATING,
        )
        assert view.analyzed is False
        assert view.entities == []
        assert view.endpoints_predating == 2
        assert [s.service_id for s in view.services] == [_OWNERS, _PETS]

    def test_a_reporting_service_with_no_endpoints_is_analyzed(self) -> None:
        # The service_id filter on a queue consumer or a gateway: no endpoint
        # rows, measured accounting. "Holds no endpoints yet" was false.
        view = build_entity_usage_view(
            "snap-1", [], [_model(_PETS, "Pet", _DM)], [_reporting(_PETS, "pets")]
        )
        assert view.analyzed is True
        [row] = view.entities
        assert all(u.endpoints == [] for u in row.operations)

    def test_a_predating_service_lists_no_entities_in_an_analyzed_snapshot(self) -> None:
        # Its six empty lists would read as "touched by nothing" when nothing
        # was looked at; its status says why it has no rows.
        view = build_entity_usage_view(
            "snap-1",
            [
                _row("ep_p", "/p", [_summary("com.acme.Pet", EntityOperation.READ, model_id=_DM)]),
                _row("ep_o", "/o", None, service_id=_OWNERS),
            ],
            [_model(_PETS, "Pet", _DM), _model(_OWNERS, "Owner", "dm_3333333333333333")],
            [_reporting(_PETS, "pets"), _not_reporting(_OWNERS, "owners")],
        )
        assert [(r.service_id, r.name) for r in view.entities] == [(_PETS, "Pet")]
        assert view.endpoints_predating == 1

    def test_a_model_of_a_non_reporting_service_joins_when_an_access_names_it(self) -> None:
        # A library's entity, named by a dependent's access through its model id.
        library = "svc-lib"
        lib_model = "dm_4444444444444444"
        view = build_entity_usage_view(
            "snap-1",
            [
                _row(
                    "ep_p",
                    "/p",
                    [_summary("com.acme.Tag", EntityOperation.READ, model_id=lib_model)],
                )
            ],
            [_model(library, "Tag", lib_model, storage_name="tags")],
            [
                _reporting(_PETS, "pets"),
                _not_reporting(library, "lib", EntityAccountingStatus.LIBRARY),
            ],
        )
        [row] = view.entities
        assert (row.service_id, row.storage_name) == (library, "tags")
        assert _usage(row)[EntityOperation.READ] == ["ep_p"]

    def test_a_count_under_an_operation_counts_that_operation(self) -> None:
        # The live defect: 11 sites on Order, 3 of them deletes, read "11 calls"
        # under delete.
        summary = _summary(
            "com.acme.Order",
            EntityOperation.READ,
            EntityOperation.DELETE,
            EntityOperation.CREATE_OR_UPDATE,
            sites=11,
            by_operation={"read": 5, "delete": 3, "create-or-update": 3},
        )
        view = build_entity_usage_view(
            "snap-1", [_row("ep_t", "/crud/inherited-method-table", [summary])], [], _SERVICES
        )
        [row] = view.entities
        counts = {u.operation: [e.call_sites for e in u.endpoints] for u in row.operations}
        assert counts[EntityOperation.READ] == [5]
        assert counts[EntityOperation.DELETE] == [3]
        assert counts[EntityOperation.CREATE_OR_UPDATE] == [3]

    def test_a_summary_without_per_operation_counts_has_no_count(self) -> None:
        # Written before 1.27.0: the entity count is not reused as an
        # operation count, which is the defect this field fixes.
        summary = _summary(
            "com.acme.Pet", EntityOperation.READ, model_id=_DM, sites=4, by_operation=None
        )
        view = build_entity_usage_view(
            "snap-1", [_row("ep_1", "/p", [summary])], [_model(_PETS, "Pet", _DM)], _SERVICES
        )
        read = next(u for u in view.entities[0].operations if u.operation is EntityOperation.READ)
        assert read.endpoints[0].call_sites is None

    def test_endpoints_predating_counts_only_none_rows(self) -> None:
        view = build_entity_usage_view(
            "snap-1",
            [
                _row("ep_1", "/a", None),
                _row("ep_2", "/b", []),
                _row("ep_3", "/c", [_summary("com.acme.Pet", EntityOperation.READ)]),
            ],
            [],
            _SERVICES,
        )
        assert view.analyzed is True
        assert view.endpoints_predating == 1
        assert view.snapshot_id == "snap-1"


class TestReverseViewShapes:
    def test_a_service_carries_accounting_exactly_when_reporting(self) -> None:
        with pytest.raises(ValidationError, match="accounting is present exactly"):
            EntityUsageService(
                service_id=_PETS,
                service_name="pets",
                status=EntityAccountingStatus.REPORTING,
                accounting=None,
            )
        with pytest.raises(ValidationError, match="accounting is present exactly"):
            EntityUsageService(
                service_id=_PETS,
                service_name="pets",
                status=EntityAccountingStatus.EXTRACTION_FAILED,
                accounting=EntityAccessAccounting.model_validate(_accounting()),
            )

    def test_a_usage_row_lists_all_six_operations(self) -> None:
        with pytest.raises(ValidationError, match="every EntityOperation once"):
            EntityUsageRow(
                service_id=_PETS,
                entity="com.acme.Pet",
                name="Pet",
                data_model_id=None,
                storage_name=None,
                declared_by=None,
                operations=[
                    EntityOperationUsage(operation=op, endpoints=[])
                    for op in list(EntityOperation)[:5]
                ],
            )

    def test_per_operation_counts_must_match_the_operations(self) -> None:
        with pytest.raises(ValidationError, match="must be exactly the row's operations"):
            _summary("com.acme.Pet", EntityOperation.READ, by_operation={"delete": 1})
        with pytest.raises(ValidationError, match="between 1 and call_sites 2"):
            _summary("com.acme.Pet", EntityOperation.READ, sites=2, by_operation={"read": 3})

    def test_the_undetermined_row_names_no_model(self) -> None:
        with pytest.raises(ValidationError, match="data_model_id requires an entity"):
            _summary(None, EntityOperation.READ, model_id=_DM)


class TestPublishedSurface:
    def test_the_package_exports_the_fold_and_its_shapes(self) -> None:
        # R1-22: the worker, orchestrator and MCP server import the fold from
        # the package root; a missing re-export pushes each into a private path.
        import wadi_contracts

        for name in (
            "EntityAccess",
            "EntityAccessSite",
            "EndpointEntityAccess",
            "EntityAccessAccounting",
            "EntityCoverageSection",
            "EntityUsageView",
            "EndpointEntityAccessRow",
            "summarize_entity_access",
            "build_entity_usage_view",
        ):
            assert name in wadi_contracts.__all__
            assert getattr(wadi_contracts, name) is not None

    def test_the_reverse_view_publishes_a_schema(self) -> None:
        # The frontend's types are generated from schemas/, so a view that is
        # not registered has no TypeScript type and gets a hand-written one.
        from wadi_contracts.entity_access import EntityUsageView
        from wadi_contracts.registry import CONTRACT_MODELS

        assert CONTRACT_MODELS["entity_usage"] is EntityUsageView
