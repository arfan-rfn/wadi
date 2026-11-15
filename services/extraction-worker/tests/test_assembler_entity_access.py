"""Entity access through the assembler (§5.2.17): sites, summaries, records, accounting.

The export below is shaped the way the 2.14.0 Scala pass writes it: one
``kind=db`` sink row per repository CALL, rows sharing a ``node_id`` when one
statement makes two calls (R1-2), each carrying its ``db`` raw facts. One of
its methods is a lambda body, which the export carries and no endpoint ICFG
contains (finding A1), so the accounting has a site in no endpoint flow.
"""

from dataclasses import replace

import pytest

from wadi_contracts import (
    EndpointEntityAccess,
    EntityAccessBasis,
    EntityDeclaredBy,
    EntityOperation,
    IcfgNode,
    data_model_id,
)
from wadi_joern_client.export import (
    CfgNodeKind,
    ExportCall,
    ExportCfg,
    ExportCfgNode,
    ExportDataModel,
    ExportDbAccess,
    ExportDbQuery,
    ExportDbSave,
    ExportDeclaredBy,
    ExportEndpoint,
    ExportMethod,
    ExportParam,
    ExportSink,
    GuardArm,
    RepositoryKind,
    SaveArgumentOrigin,
    ServiceExport,
)
from wadi_worker.assembler import AssembledArtifacts, Assembler
from wadi_worker.entity_access import RULES_VERSION, SHIPPED_GATE_FLAGS

SNAP = "snap_" + "a" * 16
SVC = "svc_" + "b" * 16

PET = "com.acme.pets.Pet"
AUDIT = "com.acme.audit.AuditEntry"
PET_REPO = "com.acme.pets.PetRepository"
AUDIT_REPO = "com.acme.audit.AuditRepository"

CONTROLLER = 100
SERVICE = 200
LAMBDA = 300
# cfg node ids in SERVICE / LAMBDA
TWO_CALLS = 201
FLUSH = 202
SAVE_NEW = 203
SAVE_READ = 204
IN_LAMBDA = 301

ALL_FLAGS_ON = tuple(
    replace(flag, enabled=True, scored_rules_version=RULES_VERSION) for flag in SHIPPED_GATE_FLAGS
)


def _method(method_id: int, name: str, line: int) -> ExportMethod:
    return ExportMethod(
        id=method_id,
        full_name=f"com.acme.pets.PetService.{name}:void()",
        signature=f"{name}()",
        filename="src/main/java/com/acme/pets/PetService.java",
        line=line,
        line_end=line + 9,
        code=f"void {name}() {{",
    )


def _statement(node_id: int, code: str, line: int) -> ExportCfgNode:
    return ExportCfgNode(
        id=node_id, kind=CfgNodeKind.STATEMENT, code=code, line=line, line_end=line
    )


def _db(
    repository: str,
    method_name: str,
    entity: str | None,
    *,
    save: ExportDbSave | None = None,
) -> ExportDbAccess:
    return ExportDbAccess(
        repository=repository,
        method_name=method_name,
        entity_type_text=entity.rsplit(".", 1)[-1] if entity else None,
        entity_type_full_name=entity,
        repository_kind=RepositoryKind.JPA,
        implemented_in_project=False,
        save=save,
    )


def _sink(node_id: int, call_id: int, method_id: int, db: ExportDbAccess | None) -> ExportSink:
    return ExportSink(node_id=node_id, call_id=call_id, method_id=method_id, kind="db", db=db)


def _save_facts(origin: SaveArgumentOrigin) -> ExportDbSave:
    return ExportDbSave(
        argument_origin=origin, lookup_same_repository=False, guard_arm=GuardArm.NONE
    )


def crud_export(version: str = "2.14.0") -> ServiceExport:
    """POST /pets: controller -> PetService.adopt, which makes five repository
    calls on four statements; PetService.<lambda>0 makes a sixth."""
    controller = ExportMethod(
        id=CONTROLLER,
        full_name="com.acme.pets.PetController.adopt:void()",
        signature="adopt()",
        filename="src/main/java/com/acme/pets/PetController.java",
        line=10,
        line_end=12,
        code="public void adopt() {",
        tags=["endpoint=POST /pets"],
    )
    return ServiceExport(
        export_schema_version=version,
        language="java",
        methods=[controller, _method(SERVICE, "adopt", 20), _method(LAMBDA, "lambda$adopt$0", 40)],
        cfgs=[
            ExportCfg(
                method_id=CONTROLLER,
                nodes=[
                    ExportCfgNode(
                        id=101,
                        kind=CfgNodeKind.CALL,
                        code="petService.adopt();",
                        line=11,
                        line_end=11,
                        call=ExportCall(
                            callee_full_name="com.acme.pets.PetService.adopt:void()",
                            callee_id=SERVICE,
                            resolved=True,
                        ),
                    )
                ],
                edges=[],
            ),
            ExportCfg(
                method_id=SERVICE,
                nodes=[
                    _statement(
                        TWO_CALLS, "auditRepository.save(petRepository.findById(id).get());", 21
                    ),
                    _statement(FLUSH, "petRepository.flush();", 22),
                    _statement(SAVE_NEW, "petRepository.save(new Pet());", 23),
                    _statement(SAVE_READ, "petRepository.save(pet);", 24),
                ],
                edges=[],
            ),
            ExportCfg(
                method_id=LAMBDA,
                nodes=[_statement(IN_LAMBDA, "petRepository.deleteById(id);", 41)],
                edges=[],
            ),
        ],
        endpoints=[ExportEndpoint(method_id=CONTROLLER, http_method="POST", uri="/pets")],
        sinks=[
            _sink(TWO_CALLS, 3201, SERVICE, _db(PET_REPO, "findById", PET)),
            _sink(
                TWO_CALLS,
                3202,
                SERVICE,
                _db(AUDIT_REPO, "save", AUDIT, save=_save_facts(SaveArgumentOrigin.OTHER)),
            ),
            _sink(FLUSH, 3203, SERVICE, _db(PET_REPO, "flush", PET)),
            _sink(
                SAVE_NEW,
                3204,
                SERVICE,
                _db(PET_REPO, "save", PET, save=_save_facts(SaveArgumentOrigin.CONSTRUCTED)),
            ),
            _sink(
                SAVE_READ,
                3205,
                SERVICE,
                _db(PET_REPO, "save", PET, save=_save_facts(SaveArgumentOrigin.READ)),
            ),
            _sink(IN_LAMBDA, 3301, LAMBDA, _db(PET_REPO, "deleteById", PET)),
        ],
        data_models=[
            ExportDataModel(
                entity="Pet",
                type_full_name=PET,
                fields=[
                    ExportParam(name="id", type_name="java.lang.Long", declared_type="Long"),
                    ExportParam(name="tags", type_name="java.util.List", declared_type="List<Tag>"),
                ],
                persistence_framework="spring-data-jpa",
                storage_name="pets",
                declared_by=ExportDeclaredBy.ANNOTATION,
            ),
            # Q1: a repository binds it and it carries no @Entity.
            ExportDataModel(
                entity="AuditEntry",
                type_full_name=AUDIT,
                persistence_framework="spring-data-jpa",
                declared_by=ExportDeclaredBy.REPOSITORY_ARGUMENT,
            ),
        ],
    )


def _node(artifacts: AssembledArtifacts, method: int, node: int) -> IcfgNode:
    return next(n for n in artifacts.icfgs[0].nodes if n.id == f"m{method}:n{node}")


@pytest.fixture
def assembled() -> AssembledArtifacts:
    return Assembler(snapshot_id=SNAP, service_id=SVC).assemble(crud_export())


class TestSites:
    def test_two_repository_calls_in_one_statement_are_two_sites(
        self, assembled: AssembledArtifacts
    ) -> None:
        sites = _node(assembled, SERVICE, TWO_CALLS).entity_access_sites

        assert [(s.repository, s.method_name) for s in sites] == [
            (PET_REPO, "findById"),
            (AUDIT_REPO, "save"),
        ]
        assert [[a.entity for a in s.accesses] for s in sites] == [[PET], [AUDIT]]

    def test_each_site_has_one_access_carrying_the_entity_model_id(
        self, assembled: AssembledArtifacts
    ) -> None:
        pet_id = data_model_id(SVC, PET)
        save_new = _node(assembled, SERVICE, SAVE_NEW).entity_access_sites

        assert len(save_new) == 1
        assert save_new[0].basis is EntityAccessBasis.ARGUMENT_ORIGIN
        assert [
            (a.data_model_id, a.operation, a.candidate_operation) for a in save_new[0].accesses
        ] == [(pet_id, EntityOperation.CREATE_OR_UPDATE, EntityOperation.CREATE)]

    def test_flush_marks_the_node_db_but_carries_no_site(
        self, assembled: AssembledArtifacts
    ) -> None:
        node = _node(assembled, SERVICE, FLUSH)

        assert node.sink is not None
        assert node.entity_access_sites == []

    def test_nodes_without_a_repository_call_carry_no_sites(
        self, assembled: AssembledArtifacts
    ) -> None:
        controller_call = _node(assembled, CONTROLLER, 101)

        assert controller_call.entity_access_sites == []


class TestEndpointSummary:
    def test_the_summary_folds_every_site_in_the_endpoint_graph(
        self, assembled: AssembledArtifacts
    ) -> None:
        # Pet: findById (read) and two saves the gate demoted; Audit: one save
        # whose origin the split cannot read. flush adds nothing, and the
        # lambda's deleteById is in no endpoint graph (A1).
        assert assembled.endpoints[0].entity_access == [
            EndpointEntityAccess(
                entity=AUDIT,
                data_model_id=data_model_id(SVC, AUDIT),
                operations=[EntityOperation.CREATE_OR_UPDATE],
                call_sites=1,
            ),
            EndpointEntityAccess(
                entity=PET,
                data_model_id=data_model_id(SVC, PET),
                operations=[EntityOperation.READ, EntityOperation.CREATE_OR_UPDATE],
                call_sites=3,
            ),
        ]

    def test_with_flags_on_the_split_saves_publish_their_verbs(self) -> None:
        artifacts = Assembler(snapshot_id=SNAP, service_id=SVC, gate_flags=ALL_FLAGS_ON).assemble(
            crud_export()
        )

        pet = next(row for row in artifacts.endpoints[0].entity_access or [] if row.entity == PET)
        assert pet.operations == [
            EntityOperation.CREATE,
            EntityOperation.READ,
            EntityOperation.UPDATE,
        ]

    def test_one_undecided_save_reads_differently_from_a_create_and_an_update(self) -> None:
        # R1-5: `create-or-update` is its own claim. One save the split cannot
        # decide must not read as "this endpoint creates and updates".
        export = crud_export()
        undecided = export.model_copy(
            update={
                "sinks": [
                    _sink(
                        SAVE_NEW,
                        3204,
                        SERVICE,
                        _db(PET_REPO, "save", PET, save=_save_facts(SaveArgumentOrigin.MIXED)),
                    )
                ]
            }
        )
        split = export.model_copy(
            update={"sinks": [s for s in export.sinks if s.call_id in (3204, 3205)]}
        )
        flags_on = Assembler(snapshot_id=SNAP, service_id=SVC, gate_flags=ALL_FLAGS_ON)

        one_undecided = flags_on.assemble(undecided).endpoints[0].entity_access
        create_and_update = flags_on.assemble(split).endpoints[0].entity_access

        assert one_undecided is not None
        assert create_and_update is not None
        assert [(r.operations, r.call_sites) for r in one_undecided] == [
            ([EntityOperation.CREATE_OR_UPDATE], 1)
        ]
        assert [(r.operations, r.call_sites) for r in create_and_update] == [
            ([EntityOperation.CREATE, EntityOperation.UPDATE], 2)
        ]

    def test_an_endpoint_with_no_repository_call_is_analyzed_and_empty(self) -> None:
        export = crud_export().model_copy(update={"sinks": []})

        endpoint = Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export).endpoints[0]

        assert endpoint.entity_access == []

    def test_a_lambda_hosted_call_is_in_no_summary(self, assembled: AssembledArtifacts) -> None:
        rows = assembled.endpoints[0].entity_access or []

        assert EntityOperation.DELETE not in {op for row in rows for op in row.operations}


class TestEntityRecords:
    def test_model_ids_derive_from_the_qualified_name(self, assembled: AssembledArtifacts) -> None:
        assert {m.type_full_name: m.id for m in assembled.data_models} == {
            PET: data_model_id(SVC, PET),
            AUDIT: data_model_id(SVC, AUDIT),
        }

    def test_two_entities_sharing_a_simple_name_get_two_ids(self) -> None:
        # C2: com.acme.a.Item and com.acme.b.Item are two entities, and each
        # access names the one its repository binds.
        export = crud_export()
        items = [
            ExportDataModel(
                entity="Item",
                type_full_name=f"com.acme.{pkg}.Item",
                persistence_framework="spring-data-jpa",
                declared_by=ExportDeclaredBy.ANNOTATION,
            )
            for pkg in ("a", "b")
        ]
        export = export.model_copy(
            update={
                "data_models": items,
                "sinks": [
                    _sink(
                        SAVE_NEW,
                        3204,
                        SERVICE,
                        _db("com.acme.a.ItemRepository", "findAll", "com.acme.a.Item"),
                    ),
                    _sink(
                        SAVE_READ,
                        3205,
                        SERVICE,
                        _db("com.acme.b.ItemRepository", "findAll", "com.acme.b.Item"),
                    ),
                ],
            }
        )

        artifacts = Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export)

        ids = [m.id for m in artifacts.data_models]
        assert len(set(ids)) == 2
        assert [
            (r.entity, r.data_model_id) for r in artifacts.endpoints[0].entity_access or []
        ] == [
            ("com.acme.a.Item", data_model_id(SVC, "com.acme.a.Item")),
            ("com.acme.b.Item", data_model_id(SVC, "com.acme.b.Item")),
        ]

    def test_the_record_carries_every_entity_name_and_how_it_was_declared(self) -> None:
        export = crud_export()
        export.data_models[0].jpql_name = "PetEntity"
        pet = next(
            m
            for m in Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export).data_models
            if m.type_full_name == PET
        )

        assert (pet.entity, pet.jpql_name, pet.storage_name, pet.declared_by) == (
            "Pet",
            "PetEntity",
            "pets",
            EntityDeclaredBy.ANNOTATION,
        )
        assert [(f.name, f.type_name, f.declared_type) for f in pet.fields] == [
            ("id", "java.lang.Long", "Long"),
            ("tags", "java.util.List", "List<Tag>"),
        ]

    def test_a_repository_only_entity_is_a_record_declared_by_its_repository(
        self, assembled: AssembledArtifacts
    ) -> None:
        audit = next(m for m in assembled.data_models if m.type_full_name == AUDIT)

        assert audit.declared_by is EntityDeclaredBy.REPOSITORY_ARGUMENT
        assert audit.storage_name is None


def _zero_operations(**counts: int) -> dict[str, int]:
    return {op.value: counts.get(op.value.replace("-", "_"), 0) for op in EntityOperation}


def _zero_bases(**counts: int) -> dict[str, int]:
    return {
        basis.value: counts.get(basis.value.replace("-", "_"), 0) for basis in EntityAccessBasis
    }


class TestAccounting:
    def test_every_call_site_is_counted_once_in_each_partition(
        self, assembled: AssembledArtifacts
    ) -> None:
        accounting = assembled.entity_access_accounting

        assert accounting is not None
        # Six distinct call ids: two share a statement (R1-2), one is flush,
        # one is in the lambda body.
        assert accounting.call_sites == 6
        assert (accounting.in_endpoint_flow, accounting.in_no_endpoint_flow) == (5, 1)
        assert (
            accounting.flush,
            accounting.implemented_in_project,
            accounting.entity_undetermined,
            accounting.unknown_operation,
            accounting.create_or_update,
            accounting.bound,
        ) == (1, 0, 0, 0, 3, 2)
        # Accesses, not sites: flush has none; the lambda's delete counts.
        assert accounting.accesses_by_operation == _zero_operations(
            read=1, delete=1, create_or_update=3
        )
        assert accounting.sites_by_basis == _zero_bases(method_name=2, argument_origin=3)

    def test_it_records_the_rules_version_and_the_flags_as_they_ran(
        self, assembled: AssembledArtifacts
    ) -> None:
        accounting = assembled.entity_access_accounting

        assert accounting is not None
        assert accounting.rules_version == RULES_VERSION
        assert [
            (f.basis, f.operation, f.enabled, f.scored_rules_version) for f in accounting.gate_flags
        ] == [(f.basis, f.operation, False, None) for f in SHIPPED_GATE_FLAGS]

    def test_with_flags_on_split_saves_count_as_bound(self) -> None:
        artifacts = Assembler(snapshot_id=SNAP, service_id=SVC, gate_flags=ALL_FLAGS_ON).assemble(
            crud_export()
        )
        accounting = artifacts.entity_access_accounting

        assert accounting is not None
        assert (accounting.create_or_update, accounting.bound) == (1, 4)
        assert accounting.accesses_by_operation == _zero_operations(
            create=1, read=1, update=1, delete=1, create_or_update=1
        )
        assert all(f.enabled for f in accounting.gate_flags)

    def test_outcomes_take_the_first_bucket_that_holds(self) -> None:
        export = crud_export()
        undetermined_query = _db(PET_REPO, "findActive", None).model_copy(
            update={"query": ExportDbQuery(text=None, native=False, modifying=False)}
        )
        export = export.model_copy(
            update={
                "sinks": [
                    # implemented in the project AND no entity: C3 comes first.
                    _sink(
                        TWO_CALLS,
                        3201,
                        SERVICE,
                        _db(PET_REPO, "findOrCreate", None).model_copy(
                            update={"implemented_in_project": True}
                        ),
                    ),
                    # an unknown verb AND no entity: the entity comes first.
                    _sink(TWO_CALLS, 3202, SERVICE, undetermined_query),
                    _sink(FLUSH, 3203, SERVICE, _db(PET_REPO, "purgeStale", PET)),
                    # a row the pass did not describe: no entity anyone read.
                    _sink(SAVE_NEW, 3204, SERVICE, None),
                ]
            }
        )

        accounting = (
            Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export).entity_access_accounting
        )

        assert accounting is not None
        assert (
            accounting.call_sites,
            accounting.implemented_in_project,
            accounting.entity_undetermined,
            accounting.unknown_operation,
        ) == (4, 1, 2, 1)
        assert accounting.sites_by_basis == _zero_bases(method_name=2, query_text=1)
        assert accounting.accesses_by_operation == _zero_operations(unknown=3)

    def test_an_export_without_repository_calls_accounts_for_zero(self) -> None:
        export = crud_export().model_copy(update={"sinks": []})

        accounting = (
            Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export).entity_access_accounting
        )

        assert accounting is not None
        assert accounting.call_sites == 0


def _predating(export: ServiceExport) -> ServiceExport:
    """The same export as a 2.13.0 writer produced it: no db facts, no entity records."""
    return export.model_copy(
        update={
            "export_schema_version": "2.13.0",
            "sinks": [s.model_copy(update={"db": None}) for s in export.sinks],
            "data_models": [
                m.model_copy(
                    update={
                        "type_full_name": None,
                        "jpql_name": None,
                        "declared_by": None,
                        "fields": [f.model_copy(update={"declared_type": None}) for f in m.fields],
                    }
                )
                for m in export.data_models
            ],
        }
    )


class TestPredatingExport:
    def test_it_states_no_entity_facts(self) -> None:
        artifacts = Assembler(snapshot_id=SNAP, service_id=SVC).assemble(_predating(crud_export()))

        assert [e.entity_access for e in artifacts.endpoints] == [None]
        assert all(n.entity_access_sites == [] for i in artifacts.icfgs for n in i.nodes)
        assert artifacts.entity_access_accounting is None

    def test_its_model_ids_stay_on_the_simple_name(self) -> None:
        artifacts = Assembler(snapshot_id=SNAP, service_id=SVC).assemble(_predating(crud_export()))

        assert [m.id for m in artifacts.data_models] == [
            data_model_id(SVC, "Pet"),
            data_model_id(SVC, "AuditEntry"),
        ]
        assert [m.declared_by for m in artifacts.data_models] == [None, None]

    def test_nothing_but_the_entity_facts_changes(self) -> None:
        assembler = Assembler(snapshot_id=SNAP, service_id=SVC)
        before = assembler.assemble(_predating(crud_export()))
        after = assembler.assemble(crud_export())

        def endpoints(a: AssembledArtifacts) -> list[dict[str, object]]:
            return [e.model_dump(exclude={"created_at", "entity_access"}) for e in a.endpoints]

        def graphs(a: AssembledArtifacts) -> list[dict[str, object]]:
            return [
                i.model_dump(
                    exclude={"created_at": True, "nodes": {"__all__": {"entity_access_sites"}}}
                )
                for i in a.icfgs
            ]

        assert endpoints(before) == endpoints(after)
        assert graphs(before) == graphs(after)
        assert before.remote_calls == after.remote_calls
        assert before.mq_interactions == after.mq_interactions
        assert before.cfg_anomalies == after.cfg_anomalies
