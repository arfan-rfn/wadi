"""Vocabulary-registry liveness checking (architecture.md §7).

A registered value nothing emits is as much a defect as an emitted value
nothing registers. The second direction crashed a 20-service analysis on
2026-08-05 (``unlabeled-arm`` shipped in the producer, never reached
``CFG_ANOMALY_CODES``); the first is quieter but not harmless — for a P10 gap
registry, a consumer filtering for a never-emitted code cannot distinguish
"no such gaps" from "never implemented".

``StrEnum`` vocabularies make the *emitting* direction a type error once
producers reference enum members instead of string literals. This module
covers the other direction: it reads a producer module's source and reports
which members it actually references, so a test can assert registry ==
referenced in both directions.

Source inspection, not runtime tracing, is deliberate: a code path that only
fires on rare input (exactly the ``unlabeled-arm`` situation) would never be
observed by a runtime check, and "no fixture happened to produce it" is not
evidence that nothing emits it.
"""

import ast
import inspect
from enum import StrEnum
from types import ModuleType


def referenced_members(enum_cls: type[StrEnum], *modules: ModuleType) -> set[str]:
    """Enum member *values* referenced by attribute access in ``modules``.

    Matches ``EnumName.MEMBER`` anywhere in the module source — including
    inside dict literals and comprehensions — and maps each back to its value.
    Unknown attributes (``.value``, helper methods) are ignored, so a call like
    ``CfgAnomalyCode.BRANCH_ARITY.value`` still counts as a reference.
    """
    enum_name = enum_cls.__name__
    members: dict[str, str] = {member.name: member.value for member in enum_cls}
    found: set[str] = set()
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if isinstance(base, ast.Name) and base.id == enum_name and node.attr in members:
                found.add(members[node.attr])
    return found


def assert_registry_is_live(enum_cls: type[StrEnum], *modules: ModuleType) -> None:
    """Both-directions equality between a vocabulary and its producers (§7)."""
    registered: set[str] = {member.value for member in enum_cls}
    referenced = referenced_members(enum_cls, *modules)
    names = ", ".join(module.__name__ for module in modules)

    dead = registered - referenced
    assert not dead, (
        f"{enum_cls.__name__} registers {sorted(dead)} but no producer in {names} "
        "references them — emit them or record the removal (the host-unresolvable "
        "precedent, §5.4.2). A gap code nothing emits is indistinguishable from "
        "'no such gaps' to every consumer."
    )

    unregistered = referenced - registered
    assert not unregistered, (
        f"{names} references {sorted(unregistered)}, absent from "
        f"{enum_cls.__name__} — this is the 2026-08-05 drift shape (§7)."
    )
