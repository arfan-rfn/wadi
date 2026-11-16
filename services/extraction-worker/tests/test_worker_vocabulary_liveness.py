"""Worker-side vocabulary liveness (§7, recorded 2026-08-05).

The StrEnum conversion makes "producer emits a code the registry lacks" a
pyright error. These tests cover the other direction — a registered code no
producer emits — which pyright cannot see, and which is how the registry
quietly accumulates fiction.

The check lives in the *service*, not in wadi-contracts: contracts must not
import a service (P1), so the dependency has to point this way.
"""

import ast
import inspect

from wadi_contracts import EntityAccessBasis, EntityDeclaredBy, EntityOperation
from wadi_contracts.enums import AuthGapCode, CfgAnomalyCode, ClientLibrary
from wadi_testing.vocabulary import assert_registry_is_live, referenced_members
from wadi_worker import (
    assembler,
    auth_oracle,
    boundary,
    cfg_invariants,
    entity_access,
    query_reader,
)


def test_every_cfg_anomaly_code_is_emitted() -> None:
    assert_registry_is_live(CfgAnomalyCode, cfg_invariants)


def test_every_client_library_is_detected() -> None:
    assert_registry_is_live(ClientLibrary, boundary)


def test_every_auth_gap_code_is_emitted() -> None:
    assert_registry_is_live(AuthGapCode, auth_oracle)


# §5.2.17 E8: the entity vocabularies join the check, so an operation or basis
# the classifier never produces cannot sit in the contract looking measured.


GATED_TABLES = frozenset({"SAVE_SPLIT", "SHIPPED_GATE_FLAGS"})
"""Tables whose verbs reach `operation` only through an enabled gate flag."""


def _operations_published() -> set[str]:
    """The EntityOperation values the classifier and the query reader publish.

    Review B9: a verb named in a gated table is a candidate, not a published
    operation, while every shipped flag for it is off. Counting that mention
    let `create` and `update` read as live when the classifier could not
    publish either; the query reader, which does, was never scanned.
    """
    flagged_on = {f.operation.value for f in entity_access.SHIPPED_GATE_FLAGS if f.enabled}
    published = referenced_members(EntityOperation, query_reader)
    for statement in ast.parse(inspect.getsource(entity_access)).body:
        mentioned = {
            EntityOperation[node.attr].value
            for node in ast.walk(statement)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == EntityOperation.__name__
            and node.attr in EntityOperation.__members__
        }
        targets = {
            target.id
            for target in (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
                if isinstance(statement, ast.AnnAssign)
                else []
            )
            if isinstance(target, ast.Name)
        }
        published |= mentioned & flagged_on if targets & GATED_TABLES else mentioned
    return published


def test_every_entity_operation_is_produced() -> None:
    assert_registry_is_live(EntityOperation, entity_access, query_reader)
    assert _operations_published() == {operation.value for operation in EntityOperation}


def test_every_entity_access_basis_is_produced() -> None:
    assert_registry_is_live(EntityAccessBasis, entity_access)


def test_every_entity_declared_by_is_mapped() -> None:
    assert_registry_is_live(EntityDeclaredBy, assembler)
