"""Older export documents must still parse (§5.2.10, §5.2.17).

Snapshots are immutable and permanent, and `wadi export` bundles are consumed
by third parties, so a 2.7.0 document written by an older build has to stay
readable by this one. The sentinels it carries inside ``pattern`` are the very
spelling 2.8.0 replaced, which makes this the one place in the codebase that
still knows the old convention existed.

The same holds one version back from the current reader: a 2.13.0 document
carries ``db`` sink rows with no ``db`` object and data models with none of
the entity-record fields, and must read as exactly that.
"""

from typing import Any

from wadi_joern_client.export import (
    CONFIG_PREFIX,
    UNRESOLVABLE_PATTERN,
    ExportDeclaredBy,
    ExportSecurityRule,
    GuardArm,
    RulePatternConfidence,
    SaveArgumentOrigin,
    ServiceExport,
)

_ANCHOR = {"file": "src/SecurityConfig.java", "line": 21}


def _legacy(pattern: str) -> ExportSecurityRule:
    """A rule exactly as a 2.7.0 exporter wrote it: no call_id, no confidence."""
    return ExportSecurityRule.model_validate(
        {
            "pattern": pattern,
            "http_method": "POST",
            "access": 'hasRole("ADMIN")',
            "kind": "filter-chain",
            "anchor": _ANCHOR,
            "evidence": 'antMatchers(...).hasRole("ADMIN")',
        }
    )


class TestLegacySentinelsNormalize:
    def test_a_readable_pattern_becomes_exact(self) -> None:
        rule = _legacy("/api/v1/orders/**")
        assert rule.pattern == "/api/v1/orders/**"
        assert rule.pattern_confidence is RulePatternConfidence.EXACT
        assert rule.resolvable is True

    def test_the_unresolvable_sentinel_becomes_a_null_pattern(self) -> None:
        rule = _legacy(UNRESOLVABLE_PATTERN)
        assert rule.pattern is None
        assert rule.pattern_confidence is RulePatternConfidence.NONE
        assert rule.resolvable is False

    def test_the_config_prefix_keeps_its_binding_and_is_marked_config(self) -> None:
        # `@app.security` still names the binding the worker correlates; only
        # the way it announces itself changed.
        rule = _legacy(f"{CONFIG_PREFIX}app.security")
        assert rule.pattern == "@app.security"
        assert rule.pattern_confidence is RulePatternConfidence.CONFIG
        assert rule.resolvable is False

    def test_a_legacy_rule_has_no_site_and_says_so(self) -> None:
        # 0 is "this document predates site identity", which the oracle must be
        # able to tell apart from a real site — never a valid CPG id.
        assert _legacy("/x").call_id == 0


class TestCurrentDocumentsAreUntouched:
    def test_an_explicit_confidence_is_never_overridden(self) -> None:
        # A 2.8.0 document carrying a literal pattern with NONE confidence is
        # stating that the scope is unread even though a string is present —
        # the config-expansion case where the effect was unreadable. Inferring
        # EXACT from the string would silently re-claim it.
        rule = ExportSecurityRule.model_validate(
            {
                "call_id": 42,
                "pattern": "/api/v1/thing",
                "pattern_confidence": "none",
                "access": "hasAnyRole(roles)",
                "kind": "filter-chain",
                "anchor": _ANCHOR,
                "evidence": "x",
            }
        )
        assert rule.pattern == "/api/v1/thing"
        assert rule.pattern_confidence is RulePatternConfidence.NONE
        assert rule.resolvable is False

    def test_a_null_pattern_round_trips(self) -> None:
        rule = ExportSecurityRule.model_validate(
            {
                "call_id": 7,
                "pattern": None,
                "pattern_confidence": "none",
                "access": "permitAll()",
                "kind": "filter-chain",
                "anchor": _ANCHOR,
                "evidence": "x",
            }
        )
        restored = ExportSecurityRule.model_validate(rule.model_dump())
        assert restored.pattern is None
        assert restored.pattern_confidence is RulePatternConfidence.NONE
        assert restored.call_id == 7


def _document(version: str, sink: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """A whole export with one repository call and one entity, as Scala writes it."""
    return {
        "export_schema_version": version,
        "language": "java",
        "methods": [],
        "cfgs": [],
        "endpoints": [],
        "sinks": [
            {
                "node_id": 11,
                "call_id": 12,
                "method_id": 3,
                "kind": "db",
                "value": None,
                "value_confidence": "none",
                "http_verb": None,
                "mechanism": None,
                "evidence": None,
                "auth_propagation": None,
                **sink,
            }
        ],
        "data_models": [
            {
                "entity": "Pet",
                "fields": [{"name": "tags", "type_name": "java.util.List"}],
                "persistence_framework": "spring-data-jpa",
                "storage_name": None,
                **model,
            }
        ],
    }


class TestEntityFactsAcrossVersions:
    def test_a_2_13_0_export_reads_with_no_entity_facts(self) -> None:
        export = ServiceExport.model_validate(_document("2.13.0", {}, {}))
        assert export.compatible_with_reader()
        assert export.sinks[0].db is None
        model = export.data_models[0]
        assert (model.type_full_name, model.jpql_name, model.declared_by) == (None, None, None)
        assert model.fields[0].declared_type is None

    def test_a_2_14_0_export_carries_the_db_object_and_the_entity_record(self) -> None:
        db = {
            "repository": "com.acme.pets.PetRepository",
            "method_name": "save",
            "entity_type_text": "Pet",
            "entity_type_full_name": "com.acme.pets.Pet",
            "repository_kind": "jpa",
            "implemented_in_project": False,
            "query": None,
            "save": {
                "argument_origin": "parameter",
                "lookup_same_repository": False,
                "guard_arm": "none",
                "caller_origins": ["read"],
            },
        }
        model = {
            "type_full_name": "com.acme.pets.Pet",
            "jpql_name": None,
            "storage_name": "pets",
            "declared_by": "annotation",
            "fields": [
                {"name": "tags", "type_name": "java.util.List", "declared_type": "List<Tag>"}
            ],
        }
        export = ServiceExport.model_validate(_document("2.14.0", {"db": db}, model))
        assert export.compatible_with_reader()
        facts = export.sinks[0].db
        assert facts is not None
        assert facts.entity_type_full_name == "com.acme.pets.Pet"
        assert facts.save is not None
        assert facts.save.guard_arm is GuardArm.NONE
        assert facts.save.caller_origins == [SaveArgumentOrigin.READ]
        record = export.data_models[0]
        assert record.declared_by is ExportDeclaredBy.ANNOTATION
        assert record.storage_name == "pets"
        assert record.fields[0].declared_type == "List<Tag>"
