"""The repository-call classifier (§5.2.17, plan "Classification rules").

Table tests over the one public seam, :func:`classify_db_access`: raw facts
of one repository call in, one :class:`EntityAccessSite` (or none, for
``flush``) out. Every save rule runs under both gate states, because the
published operation is a function of the flag and the candidate is only ever
evidence (R1-11).
"""

import inspect
from collections.abc import Callable
from dataclasses import replace

import pytest

from wadi_contracts import DataModel, EntityAccessBasis, EntityOperation
from wadi_joern_client.export import (
    ExportDbAccess,
    ExportDbQuery,
    ExportDbSave,
    GuardArm,
    RepositoryKind,
    SaveArgumentOrigin,
    ServiceExport,
)
from wadi_worker.entity_access import (
    GATED_FUNCTIONS,
    NAME_PREFIXES,
    PERSISTENCE_PACKAGES,
    RULES_VERSION,
    SAVE_SPLIT,
    SHIPPED_GATE_FLAGS,
    VERB_CHANGING_SIMPLE_NAMES,
    VERB_NEUTRAL_ANNOTATIONS,
    NameRoute,
    classify_db_access,
    export_rules_version,
    rules_version,
)
from wadi_worker.query_reader import EntityCatalog

PET = "com.acme.pets.Pet"
PET_REPOSITORY = "com.acme.pets.PetRepository"
PET_MODEL_ID = "dm_" + "1" * 16
PETS = EntityCatalog(
    [
        DataModel(
            snapshot_id="snap_" + "a" * 16,
            service_id="svc_" + "b" * 16,
            id=PET_MODEL_ID,
            entity="Pet",
            type_full_name=PET,
            persistence_framework="spring-data",
        )
    ]
)
STORED_PETS = EntityCatalog(
    [
        DataModel(
            snapshot_id="snap_" + "a" * 16,
            service_id="svc_" + "b" * 16,
            id=PET_MODEL_ID,
            entity="Pet",
            type_full_name=PET,
            storage_name="pets",
            persistence_framework="spring-data",
        )
    ]
)
NO_ENTITIES = EntityCatalog()


def _db(method_name: str, **facts: object) -> ExportDbAccess:
    fields: dict[str, object] = {
        "repository": PET_REPOSITORY,
        "method_name": method_name,
        "entity_type_text": "Pet",
        "entity_type_full_name": PET,
        "repository_kind": RepositoryKind.JPA,
        "implemented_in_project": False,
    }
    fields.update(facts)
    return ExportDbAccess.model_validate(fields)


class TestMethodName:
    def test_a_derived_read_is_one_read_access_on_the_repository_entity(self) -> None:
        site = classify_db_access(_db("findByStatus"), entities=PETS)

        assert site is not None
        assert site.repository == PET_REPOSITORY
        assert site.method_name == "findByStatus"
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.entity, a.data_model_id, a.operation) for a in site.accesses] == [
            (PET, PET_MODEL_ID, EntityOperation.READ)
        ]
        assert site.accesses[0].candidate_operation is None
        assert site.entity_type_text is None

    def test_flush_is_not_an_entity_operation_and_yields_no_site(self) -> None:
        assert classify_db_access(_db("flush"), entities=NO_ENTITIES) is None

    def test_save_and_flush_is_a_save_not_a_flush(self) -> None:
        site = classify_db_access(_db("saveAndFlush"), entities=NO_ENTITIES)

        assert site is not None
        assert site.accesses[0].operation is EntityOperation.CREATE_OR_UPDATE

    def test_a_name_outside_the_verb_table_is_unknown(self) -> None:
        site = classify_db_access(_db("purgeStale"), entities=NO_ENTITIES)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert site.accesses[0].operation is EntityOperation.UNKNOWN

    def test_an_entity_absent_from_data_models_has_no_model_id(self) -> None:
        site = classify_db_access(_db("deleteById"), entities=NO_ENTITIES)

        assert site is not None
        assert site.accesses[0].entity == PET
        assert site.accesses[0].data_model_id is None
        assert site.accesses[0].operation is EntityOperation.DELETE

    def test_an_unresolved_entity_is_undetermined_and_keeps_its_text(self) -> None:
        # R1-4: the chain bound a type argument the export could not resolve
        # to a project type. The text is evidence; the entity is not claimed.
        site = classify_db_access(
            _db("findAll", entity_type_full_name=None, entity_type_text="T"),
            entities=PETS,
        )

        assert site is not None
        assert site.accesses[0].entity is None
        assert site.accesses[0].data_model_id is None
        assert site.accesses[0].operation is EntityOperation.READ
        assert site.entity_type_text == "T"

    def test_an_unbindable_chain_is_undetermined_with_no_text(self) -> None:
        site = classify_db_access(
            _db("findAll", entity_type_full_name=None, entity_type_text=None),
            entities=NO_ENTITIES,
        )

        assert site is not None
        assert site.accesses[0].entity is None
        assert site.entity_type_text is None


class TestQueryAndProjectBodies:
    """Rule 1 and C3: two cases where the method name must not decide."""

    def test_an_annotated_query_is_decided_by_its_text_not_its_name(self) -> None:
        # R1-12: `findActive` reads like a read, but its @Query decides, and
        # since the query reader (M6) that decision is the text's own verb.
        site = classify_db_access(
            _db(
                "findActive",
                query=ExportDbQuery(
                    text="delete from Pet p where p.active = false", native=False, modifying=True
                ),
            ),
            entities=PETS,
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.QUERY_TEXT
        assert [(a.entity, a.data_model_id, a.operation) for a in site.accesses] == [
            (PET, PET_MODEL_ID, EntityOperation.DELETE)
        ]

    def test_a_modifying_query_named_like_a_save_is_still_query_text(self) -> None:
        site = classify_db_access(
            _db(
                "saveStatus",
                query=ExportDbQuery(text=None, native=True, modifying=True),
            ),
            entities=NO_ENTITIES,
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.QUERY_TEXT
        assert site.accesses[0].operation is EntityOperation.UNKNOWN
        assert site.accesses[0].candidate_operation is None

    def test_a_project_implemented_method_is_unknown_whatever_its_name(self) -> None:
        # C3: membership of a repository does not establish what a
        # hand-written `default` body or custom fragment does.
        site = classify_db_access(_db("findOrCreate", implemented_in_project=True), entities=PETS)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.entity, a.operation) for a in site.accesses] == [(PET, EntityOperation.UNKNOWN)]


MONGO = "org.springframework.data.mongodb.repository"
JPA = "org.springframework.data.jpa.repository"


class TestAnnotationsTheExportDoesNotRead:
    """Review B1: an annotation that changes what the method does, and that
    nothing here reads, leaves the verb unknown instead of letting the name
    decide."""

    @pytest.mark.parametrize(
        ("method_name", "annotation"),
        [
            # Spring Data MongoDB's documented example: an update named `find`.
            ("findAndIncrementVisitsByLastname", f"{MONGO}.Update"),
            ("findTotalsByStatus", f"{MONGO}.Aggregation"),
            ("findStale", f"{MONGO}.DeleteQuery"),
            ("findByStatus", f"{MONGO}.CountQuery"),
            ("findByName", f"{MONGO}.ExistsQuery"),
            ("deleteArchived", f"{JPA}.query.Procedure"),
            ("getTotal", f"{JPA}.query.Procedure"),
            # Any persistence package, any name outside the neutral list.
            ("findByStatus", "org.hibernate.annotations.SQLSelect"),
            ("findByStatus", "jakarta.persistence.NamedStoredProcedureQuery"),
            ("findByStatus", "javax.persistence.SqlResultSetMapping"),
            # The export could not resolve the name: a known verb-changing one
            # still counts.
            ("findAndIncrementVisitsByLastname", "Update"),
            ("deleteArchived", "Procedure"),
            ("findTotals", "Aggregation"),
            ("findStale", "DeleteQuery"),
            ("countStale", "CountQuery"),
            ("existsStale", "ExistsQuery"),
            ("findByStatus", "NativeQuery"),
            # A NativeQuery whose text the export did not carry is unread.
            ("findByStatus", f"{JPA}.NativeQuery"),
            # A Query on a project annotation: its text is not in the export.
            ("findActive", f"{JPA}.Query"),
        ],
    )
    def test_an_unread_persistence_annotation_makes_the_verb_unknown(
        self, method_name: str, annotation: str
    ) -> None:
        site = classify_db_access(_db(method_name, method_annotations=[annotation]), entities=PETS)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.entity, a.data_model_id, a.operation) for a in site.accesses] == [
            (PET, PET_MODEL_ID, EntityOperation.UNKNOWN)
        ]

    def test_a_meta_annotation_is_judged_by_the_annotation_it_carries(self) -> None:
        increments = classify_db_access(
            _db(
                "findByLastname",
                method_annotations=[
                    "com.acme.IncrementVisits",
                    f"com.acme.IncrementVisits>{MONGO}.Update",
                ],
            ),
            entities=PETS,
        )
        locked = classify_db_access(
            _db(
                "findByLastname",
                method_annotations=["com.acme.ReadLocked", f"com.acme.ReadLocked>{JPA}.Lock"],
            ),
            entities=PETS,
        )

        assert increments is not None
        assert increments.accesses[0].operation is EntityOperation.UNKNOWN
        assert locked is not None
        assert locked.accesses[0].operation is EntityOperation.READ

    @pytest.mark.parametrize(
        "annotation",
        [
            f"{JPA}.Lock",
            f"{JPA}.QueryHints",
            f"{JPA}.EntityGraph",
            f"{MONGO}.Meta",
            f"{MONGO}.Hint",
            f"{MONGO}.ReadPreference",
            f"{MONGO}.Tailable",
            "org.springframework.data.mongodb.core.annotation.Collation",
            "org.springframework.data.rest.core.annotation.RestResource",
            "org.springframework.data.repository.query.Param",
            "org.springframework.transaction.annotation.Transactional",
            "jakarta.transaction.Transactional",
            "org.springframework.lang.Nullable",
            "org.springframework.lang.NonNull",
            # Outside the persistence packages: nothing acts on a repository
            # method there that could change its statement.
            "com.acme.Audited",
            "io.micrometer.core.annotation.Timed",
            "org.springframework.cache.annotation.Cacheable",
            # Unresolved, and not a known verb-changing name.
            "Timed",
            "Lock",
        ],
    )
    def test_a_verb_neutral_annotation_leaves_the_name_to_decide(self, annotation: str) -> None:
        site = classify_db_access(
            _db("findByStatus", method_annotations=[annotation]), entities=PETS
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert site.accesses[0].operation is EntityOperation.READ, annotation

    def test_an_unread_annotation_keeps_a_save_out_of_the_split(self) -> None:
        # The split's candidate is a gated verb: an annotation that replaces
        # the statement removes the save's input, so no candidate is kept.
        site = classify_db_access(
            _db(
                "save",
                method_annotations=[f"{JPA}.query.Procedure"],
                save=ExportDbSave(
                    argument_origin=SaveArgumentOrigin.CONSTRUCTED,
                    lookup_same_repository=False,
                    guard_arm=GuardArm.NONE,
                ),
            ),
            entities=PETS,
            gate_flags=ALL_FLAGS_ON,
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.operation, a.candidate_operation) for a in site.accesses] == [
            (EntityOperation.UNKNOWN, None)
        ]

    def test_beside_a_query_an_unread_annotation_is_unknown_on_the_query_basis(self) -> None:
        site = classify_db_access(
            _db(
                "findArchived",
                method_annotations=[f"{JPA}.Query", f"{JPA}.query.Procedure"],
                query=ExportDbQuery(text="select p from Pet p", native=False, modifying=False),
            ),
            entities=PETS,
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.QUERY_TEXT
        assert [(a.entity, a.operation) for a in site.accesses] == [(PET, EntityOperation.UNKNOWN)]

    def test_a_carried_query_annotation_leaves_the_text_to_decide(self) -> None:
        for annotations, native, text in (
            ([f"{JPA}.Query", f"{JPA}.Modifying"], False, "delete from Pet p where p.id = ?1"),
            ([f"{JPA}.NativeQuery"], True, "delete from pets where id = ?1"),
            (["NativeQuery"], True, "delete from pets where id = ?1"),
        ):
            site = classify_db_access(
                _db(
                    "findStale",
                    method_annotations=annotations,
                    query=ExportDbQuery(text=text, native=native, modifying=not native),
                ),
                entities=STORED_PETS,
            )

            assert site is not None
            assert site.basis is EntityAccessBasis.QUERY_TEXT
            assert [(a.entity, a.operation) for a in site.accesses] == [
                (PET, EntityOperation.DELETE)
            ], annotations


def _soft_deleted(rewritten_by: str) -> EntityCatalog:
    return EntityCatalog(
        [
            DataModel(
                snapshot_id="snap_" + "a" * 16,
                service_id="svc_" + "b" * 16,
                id=PET_MODEL_ID,
                entity="Pet",
                type_full_name=PET,
                storage_name="pets",
                delete_rewritten_by=rewritten_by,
                persistence_framework="spring-data",
            )
        ]
    )


class TestRewrittenDelete:
    """Review B1: Hibernate's `@SQLDelete` or `@SoftDelete` on the entity
    replaces the DELETE a repository delete would run, usually with an
    UPDATE, so the name no longer says what happens."""

    @pytest.mark.parametrize(
        "rewritten_by",
        [
            "org.hibernate.annotations.SQLDelete",
            "org.hibernate.annotations.SoftDelete",
            "SQLDelete",
        ],
    )
    def test_a_delete_by_name_is_unknown(self, rewritten_by: str) -> None:
        for method_name in ("deleteById", "delete", "deleteAllInBatch", "removeByStatus"):
            site = classify_db_access(_db(method_name), entities=_soft_deleted(rewritten_by))

            assert site is not None
            assert site.basis is EntityAccessBasis.METHOD_NAME
            assert [(a.entity, a.operation) for a in site.accesses] == [
                (PET, EntityOperation.UNKNOWN)
            ], method_name

    def test_a_read_of_the_same_entity_is_still_a_read(self) -> None:
        site = classify_db_access(
            _db("findById"), entities=_soft_deleted("org.hibernate.annotations.SQLDelete")
        )

        assert site is not None
        assert site.accesses[0].operation is EntityOperation.READ

    def test_a_jpql_delete_of_the_entity_is_unknown(self) -> None:
        # The JPA provider turns a JPQL delete of a soft-deleted entity into
        # its rewrite as well; which one it runs is not read, so no verb.
        site = classify_db_access(
            _db(
                "purge",
                query=ExportDbQuery(
                    text="delete from Pet p where p.id = ?1", native=False, modifying=True
                ),
            ),
            entities=_soft_deleted("org.hibernate.annotations.SoftDelete"),
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.QUERY_TEXT
        assert [(a.entity, a.operation) for a in site.accesses] == [(PET, EntityOperation.UNKNOWN)]

    def test_a_native_delete_runs_its_own_sql_and_stays_a_delete(self) -> None:
        site = classify_db_access(
            _db(
                "purge",
                query=ExportDbQuery(
                    text="delete from pets where id = ?1", native=True, modifying=True
                ),
            ),
            entities=_soft_deleted("org.hibernate.annotations.SQLDelete"),
        )

        assert site is not None
        assert [(a.entity, a.operation) for a in site.accesses] == [(PET, EntityOperation.DELETE)]


class TestUnresolvedDeclaration:
    """§5.2.17: a project interface declares the name but no declaration
    matched the call's arity, so the method's annotations were not read."""

    def test_a_derived_name_is_unknown(self) -> None:
        site = classify_db_access(_db("findAll", declaration_resolved=False), entities=PETS)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.entity, a.operation) for a in site.accesses] == [(PET, EntityOperation.UNKNOWN)]

    def test_a_save_is_unknown_with_no_candidate(self) -> None:
        site = classify_db_access(
            _save(_NEW, False, GuardArm.NONE, []).model_copy(
                update={"declaration_resolved": False}
            ),
            entities=PETS,
            gate_flags=ALL_FLAGS_ON,
        )

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert [(a.operation, a.candidate_operation) for a in site.accesses] == [
            (EntityOperation.UNKNOWN, None)
        ]

    def test_flush_is_a_site_when_its_declaration_was_not_resolved(self) -> None:
        # The project overloads `flush`, so which one runs was not read: the
        # call is not known to be JpaRepository.flush().
        site = classify_db_access(_db("flush", declaration_resolved=False), entities=PETS)

        assert site is not None
        assert site.accesses[0].operation is EntityOperation.UNKNOWN


_READ = SaveArgumentOrigin.READ
_NEW = SaveArgumentOrigin.CONSTRUCTED
_PARAM = SaveArgumentOrigin.PARAMETER
_MIXED = SaveArgumentOrigin.MIXED
_OTHER = SaveArgumentOrigin.OTHER
_ORIGIN = EntityAccessBasis.ARGUMENT_ORIGIN
_GUARD = EntityAccessBasis.EXISTENCE_GUARD
_CREATE = EntityOperation.CREATE
_UPDATE = EntityOperation.UPDATE

ALL_FLAGS_ON = tuple(
    replace(flag, enabled=True, scored_rules_version=RULES_VERSION) for flag in SHIPPED_GATE_FLAGS
)

# (origin, lookup_same_repository, guard_arm, caller_origins, guard_lookup_method)
# -> (candidate, basis). A None candidate is a save the split cannot decide:
# create-or-update in either gate state, with nothing to publish.
SAVE_SPLIT_CASES: list[
    tuple[
        str,
        SaveArgumentOrigin,
        bool,
        GuardArm,
        list[SaveArgumentOrigin],
        str | None,
        EntityOperation | None,
        EntityAccessBasis,
    ]
] = [
    ("read-is-update", _READ, False, GuardArm.NONE, [], None, _UPDATE, _ORIGIN),
    # The guard is consulted only for a constructed argument (rule 3): a read
    # object saved in a found arm is decided by its origin.
    ("read-in-found-arm", _READ, True, GuardArm.FOUND, [], "findByName", _UPDATE, _ORIGIN),
    ("constructed-no-lookup", _NEW, False, GuardArm.NONE, [], None, _CREATE, _ORIGIN),
    ("constructed-not-found-arm", _NEW, True, GuardArm.NOT_FOUND, [], None, _CREATE, _GUARD),
    # Review B5: the not-found row needs no identity lookup. Nothing matched,
    # so a new object saved there is an insert whatever the lookup tested.
    (
        "constructed-not-found-arm-by-a-field",
        _NEW,
        True,
        GuardArm.NOT_FOUND,
        [],
        "findByUserId",
        _CREATE,
        _GUARD,
    ),
    ("constructed-found-arm", _NEW, True, GuardArm.FOUND, [], "findById", _UPDATE, _GUARD),
    # Review B5: a found arm says "this row exists" only when the lookup was
    # by identity. ts-delivery-service saves a new UUID-keyed ledger row while
    # `findByUserId` matches some other row: that is an insert.
    *(
        (
            f"constructed-found-arm-by-{lookup}",
            _NEW,
            True,
            GuardArm.FOUND,
            [],
            lookup,
            _UPDATE,
            _GUARD,
        )
        for lookup in ("getById", "getReferenceById", "existsById")
    ),
    (
        "constructed-found-arm-by-a-field",
        _NEW,
        True,
        GuardArm.FOUND,
        [],
        "findByUserId",
        None,
        _ORIGIN,
    ),
    # An export before 2.15.0 does not say which lookup the guard tested.
    ("constructed-found-arm-lookup-unknown", _NEW, True, GuardArm.FOUND, [], None, None, _ORIGIN),
    ("constructed-lookup-no-arm", _NEW, True, GuardArm.NONE, [], None, None, _ORIGIN),
    ("mixed", _MIXED, False, GuardArm.NONE, [], None, None, _ORIGIN),
    ("other", _OTHER, True, GuardArm.FOUND, [], "findById", None, _ORIGIN),
    (
        "parameter-callers-agree-read",
        _PARAM,
        False,
        GuardArm.NONE,
        [_READ, _READ],
        None,
        _UPDATE,
        _ORIGIN,
    ),
    (
        "parameter-one-caller-constructed",
        _PARAM,
        False,
        GuardArm.NONE,
        [_NEW],
        None,
        _CREATE,
        _ORIGIN,
    ),
    (
        "parameter-constructed-in-not-found-arm",
        _PARAM,
        True,
        GuardArm.NOT_FOUND,
        [_NEW, _NEW],
        None,
        _CREATE,
        _GUARD,
    ),
    (
        "parameter-callers-disagree",
        _PARAM,
        False,
        GuardArm.NONE,
        [_READ, _NEW],
        None,
        None,
        _ORIGIN,
    ),
    (
        "parameter-still-a-parameter",
        _PARAM,
        False,
        GuardArm.NONE,
        [_PARAM, _PARAM],
        None,
        None,
        _ORIGIN,
    ),
    ("parameter-callers-mixed", _PARAM, False, GuardArm.NONE, [_MIXED], None, None, _ORIGIN),
    ("parameter-no-caller", _PARAM, False, GuardArm.NONE, [], None, None, _ORIGIN),
]


def _save(
    origin: SaveArgumentOrigin,
    lookup: bool,
    arm: GuardArm,
    callers: list[SaveArgumentOrigin],
    method_name: str = "save",
    guard_lookup: str | None = None,
) -> ExportDbAccess:
    return _db(
        method_name,
        save=ExportDbSave(
            argument_origin=origin,
            lookup_same_repository=lookup,
            guard_arm=arm,
            guard_lookup_method=guard_lookup,
            caller_origins=callers,
        ),
    )


class TestSaveSplit:
    """Rules 3 and 4 under the gate (rule 5), both flag states."""

    @pytest.mark.parametrize(
        ("origin", "lookup", "arm", "callers", "guard_lookup", "candidate", "basis"),
        [case[1:] for case in SAVE_SPLIT_CASES],
        ids=[case[0] for case in SAVE_SPLIT_CASES],
    )
    def test_flags_off_publish_create_or_update_and_keep_the_candidate(
        self,
        origin: SaveArgumentOrigin,
        lookup: bool,
        arm: GuardArm,
        callers: list[SaveArgumentOrigin],
        guard_lookup: str | None,
        candidate: EntityOperation | None,
        basis: EntityAccessBasis,
    ) -> None:
        site = classify_db_access(
            _save(origin, lookup, arm, callers, guard_lookup=guard_lookup), entities=PETS
        )

        assert site is not None
        assert site.basis is basis
        assert [(a.entity, a.operation, a.candidate_operation) for a in site.accesses] == [
            (PET, EntityOperation.CREATE_OR_UPDATE, candidate)
        ]

    @pytest.mark.parametrize(
        ("origin", "lookup", "arm", "callers", "guard_lookup", "candidate", "basis"),
        [case[1:] for case in SAVE_SPLIT_CASES],
        ids=[case[0] for case in SAVE_SPLIT_CASES],
    )
    def test_flags_on_publish_the_candidate_as_the_operation(
        self,
        origin: SaveArgumentOrigin,
        lookup: bool,
        arm: GuardArm,
        callers: list[SaveArgumentOrigin],
        guard_lookup: str | None,
        candidate: EntityOperation | None,
        basis: EntityAccessBasis,
    ) -> None:
        site = classify_db_access(
            _save(origin, lookup, arm, callers, guard_lookup=guard_lookup),
            entities=PETS,
            gate_flags=ALL_FLAGS_ON,
        )

        assert site is not None
        assert site.basis is basis
        published = candidate or EntityOperation.CREATE_OR_UPDATE
        assert [(a.entity, a.operation, a.candidate_operation) for a in site.accesses] == [
            (PET, published, None)
        ]

    def test_a_save_without_split_facts_is_create_or_update_on_argument_origin(self) -> None:
        # Before T3's save facts (or on a row the pass did not describe) the
        # split has no input: no candidate in either gate state.
        for flags in (SHIPPED_GATE_FLAGS, ALL_FLAGS_ON):
            site = classify_db_access(_db("save"), entities=NO_ENTITIES, gate_flags=flags)

            assert site is not None
            assert site.basis is _ORIGIN
            assert site.accesses[0].operation is EntityOperation.CREATE_OR_UPDATE
            assert site.accesses[0].candidate_operation is None

    def test_save_all_goes_through_the_split(self) -> None:
        # `insert` left the split (review B8): it is pinned in TestVerbTable.
        for name in ("saveAll", "saveAllAndFlush"):
            site = classify_db_access(
                _save(_NEW, False, GuardArm.NONE, [], method_name=name),
                entities=NO_ENTITIES,
                gate_flags=ALL_FLAGS_ON,
            )

            assert site is not None
            assert site.accesses[0].operation is _CREATE, name

    def test_one_flag_on_publishes_only_its_basis_and_verb(self) -> None:
        only_guard_create = tuple(
            replace(flag, enabled=True, scored_rules_version=RULES_VERSION)
            if (flag.basis, flag.operation) == (_GUARD, _CREATE)
            else flag
            for flag in SHIPPED_GATE_FLAGS
        )

        def published(save: ExportDbAccess) -> tuple[EntityOperation, EntityOperation | None]:
            site = classify_db_access(save, entities=NO_ENTITIES, gate_flags=only_guard_create)
            assert site is not None
            return site.accesses[0].operation, site.accesses[0].candidate_operation

        assert published(_save(_NEW, True, GuardArm.NOT_FOUND, [])) == (_CREATE, None)
        assert published(_save(_NEW, True, GuardArm.FOUND, [], guard_lookup="findById")) == (
            EntityOperation.CREATE_OR_UPDATE,
            _UPDATE,
        )
        assert published(_save(_NEW, False, GuardArm.NONE, [])) == (
            EntityOperation.CREATE_OR_UPDATE,
            _CREATE,
        )

    def test_a_flag_scored_against_another_rules_version_publishes_nothing(self) -> None:
        # E4 at run time: a stale score is not a score. The build-time test
        # below keeps such a flag from shipping; this keeps an override from
        # publishing on one.
        stale = tuple(
            replace(flag, enabled=True, scored_rules_version="0" * 16)
            for flag in SHIPPED_GATE_FLAGS
        )
        site = classify_db_access(
            _save(_NEW, False, GuardArm.NONE, []), entities=NO_ENTITIES, gate_flags=stale
        )

        assert site is not None
        assert site.accesses[0].operation is EntityOperation.CREATE_OR_UPDATE
        assert site.accesses[0].candidate_operation is _CREATE


class TestGateFlags:
    def test_the_four_basis_verb_flags_ship_and_all_ship_off(self) -> None:
        assert sorted((f.basis.value, f.operation.value) for f in SHIPPED_GATE_FLAGS) == [
            ("argument-origin", "create"),
            ("argument-origin", "update"),
            ("existence-guard", "create"),
            ("existence-guard", "update"),
        ]
        assert [f.enabled for f in SHIPPED_GATE_FLAGS] == [False] * 4

    def test_no_shipped_flag_is_on_for_a_stale_rules_version(self) -> None:
        # E4: the build fails when a flag is on for rules other than the ones
        # it was scored against, so a rule change cannot keep publishing on an
        # old precision measurement. Turning a flag on means re-scoring it.
        stale = [
            (f.basis.value, f.operation.value, f.scored_rules_version)
            for f in SHIPPED_GATE_FLAGS
            if f.enabled and f.scored_rules_version != RULES_VERSION
        ]
        assert stale == [], f"gate flags on for a stale rules version (now {RULES_VERSION})"


_C = EntityOperation.CREATE
_R = EntityOperation.READ
_D = EntityOperation.DELETE
_S = EntityOperation.CREATE_OR_UPDATE  # a save with no split facts, flags as shipped
_FLUSH = None  # no site

# E5: every method a repository inherits from the Spring Data base interfaces,
# by declaring interface, as the Spring Data Commons 3.x, JPA 3.x and MongoDB
# 4.x APIs list them (overloads collapse to one name; deprecated methods kept
# because older code still calls them). Pinned so a verb-table edit that
# reclassifies an inherited method fails here, by name.
INHERITED_METHODS: dict[str, dict[str, EntityOperation | None]] = {
    "CrudRepository": {
        "save": _S,
        "saveAll": _S,
        "findById": _R,
        "existsById": _R,
        "findAll": _R,
        "findAllById": _R,
        "count": _R,
        "deleteById": _D,
        "delete": _D,
        "deleteAllById": _D,
        "deleteAll": _D,
    },
    "ListCrudRepository": {"saveAll": _S, "findAll": _R, "findAllById": _R},
    "PagingAndSortingRepository": {"findAll": _R},
    "JpaRepository": {
        "flush": _FLUSH,
        "saveAndFlush": _S,
        "saveAllAndFlush": _S,
        "deleteInBatch": _D,
        "deleteAllInBatch": _D,
        "deleteAllByIdInBatch": _D,
        "getOne": _R,
        "getById": _R,
        "getReferenceById": _R,
        "findAll": _R,
    },
    "QueryByExampleExecutor": {
        "findOne": _R,
        "findAll": _R,
        "count": _R,
        "exists": _R,
        "findBy": _R,
    },
    # `insert` never updates (review B8): a create by its name, not a save.
    "MongoRepository": {"insert": _C, "saveAll": _S, "findAll": _R},
}


class TestVerbTable:
    """Rule 2 reads a name the way Spring Data's own parser does (review B8)."""

    @pytest.mark.parametrize(
        ("method_name", "expected"),
        [
            # A prefix is a verb only where the name ends or goes on with an
            # uppercase letter: Spring Data reads `deleted(boolean)` as a find
            # by the `deleted` property, so it is not a delete.
            ("deleted", EntityOperation.UNKNOWN),
            ("finder", EntityOperation.UNKNOWN),
            ("getter", EntityOperation.UNKNOWN),
            ("counter", EntityOperation.UNKNOWN),
            ("streamer", EntityOperation.UNKNOWN),
            ("removed", EntityOperation.UNKNOWN),
            ("existsall", EntityOperation.UNKNOWN),
            ("find_by_status", EntityOperation.UNKNOWN),
            ("findAll", EntityOperation.READ),
            ("count", EntityOperation.READ),
            ("exists", EntityOperation.READ),
            ("existsById", EntityOperation.READ),
            ("findTop3ByStatus", EntityOperation.READ),
            ("deleteAllInBatch", EntityOperation.DELETE),
            ("removeByStatus", EntityOperation.DELETE),
        ],
    )
    def test_a_prefix_counts_only_at_a_word_boundary(
        self, method_name: str, expected: EntityOperation
    ) -> None:
        site = classify_db_access(_db(method_name), entities=NO_ENTITIES)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert site.accesses[0].operation is expected, method_name

    def test_a_save_prefix_without_a_boundary_is_not_a_save(self) -> None:
        site = classify_db_access(_db("saved"), entities=NO_ENTITIES, gate_flags=ALL_FLAGS_ON)

        assert site is not None
        assert site.basis is EntityAccessBasis.METHOD_NAME
        assert site.accesses[0].operation is EntityOperation.UNKNOWN

    def test_insert_is_a_create_by_its_name_whatever_its_save_facts_say(self) -> None:
        # `MongoRepository.insert` never updates, so a read argument (which
        # the split would call an update) does not make it one, and the verb
        # needs no gate: the name alone says it.
        for flags in (SHIPPED_GATE_FLAGS, ALL_FLAGS_ON):
            site = classify_db_access(
                _save(_READ, True, GuardArm.FOUND, [], method_name="insert"),
                entities=PETS,
                gate_flags=flags,
            )

            assert site is not None
            assert site.basis is EntityAccessBasis.METHOD_NAME
            assert [(a.entity, a.operation, a.candidate_operation) for a in site.accesses] == [
                (PET, EntityOperation.CREATE, None)
            ]

    def test_only_insert_by_that_exact_name_is_a_create(self) -> None:
        for name in ("insertAll", "inserted"):
            site = classify_db_access(_db(name), entities=NO_ENTITIES)

            assert site is not None
            assert site.basis is EntityAccessBasis.METHOD_NAME
            assert site.accesses[0].operation is EntityOperation.UNKNOWN, name


class TestInheritedMethodTable:
    @pytest.mark.parametrize(
        ("interface", "method_name", "expected"),
        [
            (interface, name, verb)
            for interface, methods in INHERITED_METHODS.items()
            for name, verb in methods.items()
        ],
        ids=[f"{i}.{n}" for i, methods in INHERITED_METHODS.items() for n in methods],
    )
    def test_every_inherited_method_has_its_pinned_verb(
        self, interface: str, method_name: str, expected: EntityOperation | None
    ) -> None:
        site = classify_db_access(_db(method_name), entities=NO_ENTITIES)

        if expected is None:
            assert site is None, f"{interface}.{method_name} must not be an entity access"
        else:
            assert site is not None
            assert site.basis is (
                _ORIGIN
                if expected is EntityOperation.CREATE_OR_UPDATE
                else EntityAccessBasis.METHOD_NAME
            )
            assert site.accesses[0].operation is expected, f"{interface}.{method_name}"


class TestRulesVersion:
    """Review B4, B9: the version covers every input to a gated verb, so no
    edit to how a candidate is computed can keep a flag's score."""

    def test_it_is_a_stable_16_hex_digest(self) -> None:
        assert len(RULES_VERSION) == 16
        assert int(RULES_VERSION, 16) >= 0
        assert rules_version(save_origin_rules=None) == RULES_VERSION
        assert rules_version(save_origin_rules="ab12") == rules_version(save_origin_rules="ab12")

    def test_it_moves_with_the_verb_table(self) -> None:
        assert rules_version(
            save_origin_rules=None, name_prefixes=(*NAME_PREFIXES, ("fetch", NameRoute.READ))
        ) != (RULES_VERSION)
        assert (
            rules_version(save_origin_rules=None, exact_names={"flush": NameRoute.FLUSH})
            != RULES_VERSION
        )

    def test_it_moves_with_the_save_split(self) -> None:
        assert rules_version(save_origin_rules=None, save_split=SAVE_SPLIT[1:]) != RULES_VERSION
        # The identity-lookup column is part of a row (review B5).
        widened = tuple(
            replace(rule, guard_lookups=rule.guard_lookups | {"findByUserId"})
            if rule.guard_lookups is not None
            else rule
            for rule in SAVE_SPLIT
        )
        assert rules_version(save_origin_rules=None, save_split=widened) != RULES_VERSION

    def test_it_moves_with_the_facts_read(self) -> None:
        assert (
            rules_version(save_origin_rules=None, raw_fact_fields=("db.method_name",))
            != RULES_VERSION
        )

    def test_it_moves_with_the_annotation_tables(self) -> None:
        # An annotation decides whether a save reaches the split at all.
        assert (
            rules_version(save_origin_rules=None, verb_neutral=VERB_NEUTRAL_ANNOTATIONS[1:])
            != RULES_VERSION
        )
        assert (
            rules_version(save_origin_rules=None, persistence_packages=PERSISTENCE_PACKAGES[1:])
            != RULES_VERSION
        )
        assert (
            rules_version(
                save_origin_rules=None,
                verb_changing_names=VERB_CHANGING_SIMPLE_NAMES - {"Procedure"},
            )
            != RULES_VERSION
        )

    def test_the_hashed_functions_are_the_gated_path(self) -> None:
        # Rule 4, the rule order and the gate are code, not tables (review B4).
        assert {f.__name__ for f in GATED_FUNCTIONS} >= {
            "classify_db_access",
            "name_route",
            "split_save",
            "_effective_origin",
            "_gate",
            "_is_unread",
            "_changes_the_verb",
        }

    @pytest.mark.parametrize("function", GATED_FUNCTIONS, ids=lambda f: f.__name__)
    def test_it_moves_with_the_source_of_each_hashed_function(
        self, function: Callable[..., object]
    ) -> None:
        def edited(candidate: Callable[..., object]) -> str:
            source = inspect.getsource(candidate)
            return source + "    # reformatted\n" if candidate is function else source

        assert rules_version(save_origin_rules=None, source_of=edited) != RULES_VERSION

    def test_it_moves_with_the_scala_rules_that_derive_the_save_facts(self) -> None:
        versions = {
            rules_version(save_origin_rules=rules)
            for rules in (None, "", "null", "a" * 64, "b" * 64)
        }
        # None is an export before 2.15.0, and differs from every present value.
        assert len(versions) == 5

    def test_an_export_runs_under_the_version_of_its_own_save_origin_rules(self) -> None:
        def export(rules: str | None) -> ServiceExport:
            return ServiceExport(
                export_schema_version="2.15.0",
                language="java",
                methods=[],
                cfgs=[],
                endpoints=[],
                sinks=[],
                save_origin_rules=rules,
            )

        assert export_rules_version(export(None)) == RULES_VERSION
        assert export_rules_version(export("c" * 64)) == rules_version(save_origin_rules="c" * 64)
        assert export_rules_version(export("c" * 64)) != RULES_VERSION

    def test_a_flag_scored_against_one_version_publishes_nothing_under_another(self) -> None:
        # E4 per export: the score names the export's version, so an export
        # whose Scala rules moved runs a different version and the flag is stale.
        scored = rules_version(save_origin_rules="a" * 64)
        flags = tuple(
            replace(flag, enabled=True, scored_rules_version=scored) for flag in SHIPPED_GATE_FLAGS
        )
        save = _save(_NEW, False, GuardArm.NONE, [])

        current = classify_db_access(save, entities=PETS, gate_flags=flags, rules_version=scored)
        moved = classify_db_access(
            save,
            entities=PETS,
            gate_flags=flags,
            rules_version=rules_version(save_origin_rules="b" * 64),
        )

        assert current is not None
        assert moved is not None
        assert [(a.operation, a.candidate_operation) for a in current.accesses] == [(_CREATE, None)]
        assert [(a.operation, a.candidate_operation) for a in moved.accesses] == [
            (EntityOperation.CREATE_OR_UPDATE, _CREATE)
        ]
