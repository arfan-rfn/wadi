"""The repository-call classifier (§5.2.17, plan "Classification rules").

Table tests over the one public seam, :func:`classify_db_access`: raw facts
of one repository call in, one :class:`EntityAccessSite` (or none, for
``flush``) out. Every save rule runs under both gate states, because the
published operation is a function of the flag and the candidate is only ever
evidence (R1-11).
"""

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
)
from wadi_worker.entity_access import (
    NAME_PREFIXES,
    RULES_VERSION,
    SAVE_SPLIT,
    SHIPPED_GATE_FLAGS,
    NameRoute,
    classify_db_access,
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

# (origin, lookup_same_repository, guard_arm, caller_origins) -> (candidate, basis).
# A None candidate is a save the split cannot decide: create-or-update in
# either gate state, with nothing to publish.
SAVE_SPLIT_CASES: list[
    tuple[
        str,
        SaveArgumentOrigin,
        bool,
        GuardArm,
        list[SaveArgumentOrigin],
        EntityOperation | None,
        EntityAccessBasis,
    ]
] = [
    ("read-is-update", _READ, False, GuardArm.NONE, [], _UPDATE, _ORIGIN),
    # The guard is consulted only for a constructed argument (rule 3): a read
    # object saved in a found arm is decided by its origin.
    ("read-in-found-arm", _READ, True, GuardArm.FOUND, [], _UPDATE, _ORIGIN),
    ("constructed-no-lookup", _NEW, False, GuardArm.NONE, [], _CREATE, _ORIGIN),
    ("constructed-not-found-arm", _NEW, True, GuardArm.NOT_FOUND, [], _CREATE, _GUARD),
    ("constructed-found-arm", _NEW, True, GuardArm.FOUND, [], _UPDATE, _GUARD),
    ("constructed-lookup-no-arm", _NEW, True, GuardArm.NONE, [], None, _ORIGIN),
    ("mixed", _MIXED, False, GuardArm.NONE, [], None, _ORIGIN),
    ("other", _OTHER, True, GuardArm.FOUND, [], None, _ORIGIN),
    (
        "parameter-callers-agree-read",
        _PARAM,
        False,
        GuardArm.NONE,
        [_READ, _READ],
        _UPDATE,
        _ORIGIN,
    ),
    ("parameter-one-caller-constructed", _PARAM, False, GuardArm.NONE, [_NEW], _CREATE, _ORIGIN),
    (
        "parameter-constructed-in-not-found-arm",
        _PARAM,
        True,
        GuardArm.NOT_FOUND,
        [_NEW, _NEW],
        _CREATE,
        _GUARD,
    ),
    ("parameter-callers-disagree", _PARAM, False, GuardArm.NONE, [_READ, _NEW], None, _ORIGIN),
    ("parameter-still-a-parameter", _PARAM, False, GuardArm.NONE, [_PARAM, _PARAM], None, _ORIGIN),
    ("parameter-callers-mixed", _PARAM, False, GuardArm.NONE, [_MIXED], None, _ORIGIN),
    ("parameter-no-caller", _PARAM, False, GuardArm.NONE, [], None, _ORIGIN),
]


def _save(
    origin: SaveArgumentOrigin,
    lookup: bool,
    arm: GuardArm,
    callers: list[SaveArgumentOrigin],
    method_name: str = "save",
) -> ExportDbAccess:
    return _db(
        method_name,
        save=ExportDbSave(
            argument_origin=origin,
            lookup_same_repository=lookup,
            guard_arm=arm,
            caller_origins=callers,
        ),
    )


class TestSaveSplit:
    """Rules 3 and 4 under the gate (rule 5), both flag states."""

    @pytest.mark.parametrize(
        ("origin", "lookup", "arm", "callers", "candidate", "basis"),
        [case[1:] for case in SAVE_SPLIT_CASES],
        ids=[case[0] for case in SAVE_SPLIT_CASES],
    )
    def test_flags_off_publish_create_or_update_and_keep_the_candidate(
        self,
        origin: SaveArgumentOrigin,
        lookup: bool,
        arm: GuardArm,
        callers: list[SaveArgumentOrigin],
        candidate: EntityOperation | None,
        basis: EntityAccessBasis,
    ) -> None:
        site = classify_db_access(_save(origin, lookup, arm, callers), entities=PETS)

        assert site is not None
        assert site.basis is basis
        assert [(a.entity, a.operation, a.candidate_operation) for a in site.accesses] == [
            (PET, EntityOperation.CREATE_OR_UPDATE, candidate)
        ]

    @pytest.mark.parametrize(
        ("origin", "lookup", "arm", "callers", "candidate", "basis"),
        [case[1:] for case in SAVE_SPLIT_CASES],
        ids=[case[0] for case in SAVE_SPLIT_CASES],
    )
    def test_flags_on_publish_the_candidate_as_the_operation(
        self,
        origin: SaveArgumentOrigin,
        lookup: bool,
        arm: GuardArm,
        callers: list[SaveArgumentOrigin],
        candidate: EntityOperation | None,
        basis: EntityAccessBasis,
    ) -> None:
        site = classify_db_access(
            _save(origin, lookup, arm, callers),
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

    def test_insert_and_save_all_go_through_the_split(self) -> None:
        for name in ("insert", "saveAll", "saveAllAndFlush"):
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
        assert published(_save(_NEW, True, GuardArm.FOUND, [])) == (
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
    "MongoRepository": {"insert": _S, "saveAll": _S, "findAll": _R},
}


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
    def test_it_is_a_stable_16_hex_digest(self) -> None:
        assert len(RULES_VERSION) == 16
        assert int(RULES_VERSION, 16) >= 0
        assert rules_version() == RULES_VERSION

    def test_it_moves_with_the_verb_table(self) -> None:
        assert rules_version(name_prefixes=(*NAME_PREFIXES, ("fetch", NameRoute.READ))) != (
            RULES_VERSION
        )

    def test_it_moves_with_the_save_split(self) -> None:
        assert rules_version(save_split=SAVE_SPLIT[1:]) != RULES_VERSION

    def test_it_moves_with_the_facts_read(self) -> None:
        assert rules_version(raw_fact_fields=("db.method_name",)) != RULES_VERSION
