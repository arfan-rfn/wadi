"""Export 2.14.0 entity facts (§5.2.17): the raw repository-call facts the
Scala pass nests on ``db`` sink rows, and the entity-record fields on
``data_models``. The reader validates shape only; classifying a call into an
operation is the worker's job (P6).
"""

from typing import Any

import pytest
from pydantic import ValidationError

from wadi_joern_client.export import (
    EXPORT_SCHEMA_VERSION,
    ExportDataModel,
    ExportDeclaredBy,
    ExportMethod,
    ExportSink,
    GuardArm,
    RepositoryKind,
    SaveArgumentOrigin,
)


def _db_sink(db: dict[str, Any] | None) -> dict[str, Any]:
    row: dict[str, Any] = {"node_id": 11, "call_id": 12, "method_id": 3, "kind": "db"}
    if db is not None:
        row["db"] = db
    return row


def _db(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "repository": "com.acme.pets.PetRepository",
        "method_name": "save",
        "entity_type_text": "Pet",
        "entity_type_full_name": "com.acme.pets.Pet",
        "repository_kind": "jpa",
        "implemented_in_project": False,
        "query": None,
        "save": {
            "argument_origin": "constructed",
            "lookup_same_repository": True,
            "guard_arm": "not-found",
            "caller_origins": [],
        },
    }
    base.update(overrides)
    return base


class TestDbFactsOnSinkRows:
    def test_a_save_carries_its_rule_three_inputs(self) -> None:
        sink = ExportSink.model_validate(_db_sink(_db()))
        assert sink.db is not None
        assert sink.db.repository == "com.acme.pets.PetRepository"
        assert sink.db.repository_kind is RepositoryKind.JPA
        assert sink.db.save is not None
        assert sink.db.save.argument_origin is SaveArgumentOrigin.CONSTRUCTED
        assert sink.db.save.guard_arm is GuardArm.NOT_FOUND
        assert sink.db.save.lookup_same_repository is True
        assert sink.db.query is None

    def test_a_parameter_save_lists_the_origin_at_each_caller(self) -> None:
        save = {
            "argument_origin": "parameter",
            "lookup_same_repository": False,
            "guard_arm": "none",
            "caller_origins": ["read", "constructed"],
        }
        sink = ExportSink.model_validate(_db_sink(_db(save=save)))
        assert sink.db is not None
        assert sink.db.save is not None
        assert sink.db.save.caller_origins == [
            SaveArgumentOrigin.READ,
            SaveArgumentOrigin.CONSTRUCTED,
        ]

    def test_an_annotated_query_method_carries_its_query(self) -> None:
        query = {"text": None, "native": False, "named_ref": "Pet.findStale", "modifying": True}
        sink = ExportSink.model_validate(
            _db_sink(_db(method_name="findStale", save=None, query=query))
        )
        assert sink.db is not None
        assert sink.db.query is not None
        assert sink.db.query.named_ref == "Pet.findStale"
        assert sink.db.query.modifying is True
        assert sink.db.query.text is None

    def test_an_unbound_chain_reports_no_entity(self) -> None:
        # R1-4: null is "the extends chain could not be bound", never omitted.
        sink = ExportSink.model_validate(
            _db_sink(
                _db(
                    method_name="findAll",
                    entity_type_text=None,
                    entity_type_full_name=None,
                    repository_kind="other",
                    save=None,
                )
            )
        )
        assert sink.db is not None
        assert sink.db.entity_type_text is None
        assert sink.db.repository_kind is RepositoryKind.OTHER

    def test_a_db_row_without_the_object_still_reads(self) -> None:
        assert ExportSink.model_validate(_db_sink(None)).db is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [("argument_origin", "copied"), ("guard_arm", "maybe")],
    )
    def test_an_unregistered_save_value_fails_loudly(self, field: str, value: str) -> None:
        save: dict[str, Any] = {
            "argument_origin": "read",
            "lookup_same_repository": False,
            "guard_arm": "none",
            "caller_origins": [],
            field: value,
        }
        with pytest.raises(ValidationError, match=field):
            ExportSink.model_validate(_db_sink(_db(save=save)))

    def test_an_unknown_db_field_fails_loudly(self) -> None:
        with pytest.raises(ValidationError, match="verb"):
            ExportSink.model_validate(_db_sink(_db(verb="create")))


class TestDataModelRows:
    def test_an_entity_record_carries_its_names(self) -> None:
        model = ExportDataModel.model_validate(
            {
                "entity": "Pet",
                "type_full_name": "com.acme.pets.Pet",
                "jpql_name": "PetEntity",
                "storage_name": "pets",
                "declared_by": "annotation",
                "persistence_framework": "spring-data-jpa",
                "fields": [
                    {"name": "tags", "type_name": "java.util.List", "declared_type": "List<Tag>"}
                ],
            }
        )
        assert model.declared_by is ExportDeclaredBy.ANNOTATION
        assert model.type_full_name == "com.acme.pets.Pet"
        assert model.fields[0].declared_type == "List<Tag>"
        assert model.fields[0].type_name == "java.util.List"

    def test_a_type_only_a_repository_names_is_its_own_row(self) -> None:
        # Q1: no @Entity, but a repository's chain binds it.
        model = ExportDataModel.model_validate(
            {
                "entity": "AuditEntry",
                "type_full_name": "com.acme.audit.AuditEntry",
                "declared_by": "repository-argument",
                "persistence_framework": "spring-data-mongodb",
            }
        )
        assert model.declared_by is ExportDeclaredBy.REPOSITORY_ARGUMENT

    def test_a_pre_2_14_row_reads_with_nothing_new(self) -> None:
        model = ExportDataModel.model_validate(
            {
                "entity": "Pet",
                "persistence_framework": "spring-data-jpa",
                "storage_name": None,
                "fields": [{"name": "id", "type_name": "java.lang.String"}],
            }
        )
        assert (model.type_full_name, model.jpql_name, model.declared_by) == (None, None, None)
        assert model.fields[0].declared_type is None

    def test_method_params_are_unchanged(self) -> None:
        method = ExportMethod.model_validate(
            {
                "id": 1,
                "full_name": "A.b:void(java.lang.String)",
                "signature": "void(java.lang.String)",
                "filename": "A.java",
                "line": 1,
                "line_end": 2,
                "code": "void b(String s)",
                "params": [{"name": "s", "type_name": "java.lang.String"}],
            }
        )
        assert method.params[0].declared_type is None


def test_the_reader_is_at_2_14_0() -> None:
    assert EXPORT_SCHEMA_VERSION == "2.14.0"
