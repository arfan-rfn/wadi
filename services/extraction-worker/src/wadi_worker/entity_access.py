"""Entity access classification: raw repository-call facts to claims (§5.2.17).

The Scala pass describes each repository call and stops there (P6): which
repository, which method, the bound entity, whether the method carries a
query, and for a save where its argument came from. Deciding what that call
DOES to its entity is this module's job, and the decision is a table rather
than branching code (plan "Classification rules"), so a rule change is a data
change whose hash moves, and a gate flag scored against the old table stops
publishing (E4).
"""

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from wadi_contracts import (
    EntityAccess,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityAccessSite,
    EntityGateFlagState,
    EntityOperation,
)
from wadi_joern_client.export import (
    ExportDbAccess,
    ExportDbSave,
    ExportSink,
    GuardArm,
    SaveArgumentOrigin,
    ServiceExport,
)
from wadi_worker.query_reader import EntityCatalog, read_repository_query

logger = logging.getLogger(__name__)

ENTITY_FACTS_SINCE = (2, 14)
"""The export minor that first carries ``db`` raw facts (§5.2.17). An older
export's endpoints get ``entity_access=None``, meaning the snapshot predates
the phase. Never ``[]``, which would claim they were looked at and found
nothing (R1-6)."""

_MAJOR_MINOR = re.compile(r"^(\d+)\.(\d+)")


class NameRoute(StrEnum):
    """Where a Spring Data method name sends a call (rule 2)."""

    READ = "read"
    DELETE = "delete"
    SAVE = "save"
    """Rule 3: the save split decides, from the argument's origin."""

    FLUSH = "flush"
    """Not an entity operation: counted on its own, and no site (rule 2)."""


EXACT_NAMES: Mapping[str, NameRoute] = {"flush": NameRoute.FLUSH}
"""Method names matched whole, before any prefix. ``flush`` is exact because
``saveAndFlush`` is a save, not a flush."""

NAME_PREFIXES: tuple[tuple[str, NameRoute], ...] = (
    ("find", NameRoute.READ),
    ("get", NameRoute.READ),
    ("read", NameRoute.READ),
    ("query", NameRoute.READ),
    ("search", NameRoute.READ),
    ("count", NameRoute.READ),
    ("exists", NameRoute.READ),
    ("stream", NameRoute.READ),
    ("delete", NameRoute.DELETE),
    ("remove", NameRoute.DELETE),
    ("save", NameRoute.SAVE),
    ("insert", NameRoute.SAVE),
)
"""Rule 2's verb table: Spring Data's derived-query subject prefixes. No
prefix is a prefix of another, so the order does not decide anything. A name
outside the table is ``unknown``. It is never guessed from a word that looks
like a verb (P10)."""

_NAME_OPERATION: Mapping[NameRoute, EntityOperation] = {
    NameRoute.READ: EntityOperation.READ,
    NameRoute.DELETE: EntityOperation.DELETE,
}


@dataclass(frozen=True)
class SaveRule:
    """One row of the save split (rules 3 and 4). ``None`` matches anything.

    ``candidate`` is the verb the evidence supports, or None when it supports
    neither; ``basis`` names the evidence that decided, so the guard arm is
    the basis only where it was consulted.
    """

    origin: SaveArgumentOrigin
    lookup_same_repository: bool | None
    guard_arm: GuardArm | None
    candidate: EntityOperation | None
    basis: EntityAccessBasis


SAVE_SPLIT: tuple[SaveRule, ...] = (
    # An object a repository returned is already stored: saving it updates.
    SaveRule(
        SaveArgumentOrigin.READ,
        None,
        None,
        EntityOperation.UPDATE,
        EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    # A `new` with no lookup on the same repository creates.
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        False,
        None,
        EntityOperation.CREATE,
        EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    # A `new` beside a lookup: only the arm of the existence check says which
    # (the train-ticket shape §5.2.17 names, and the 2023 paper's miss).
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        True,
        GuardArm.NOT_FOUND,
        EntityOperation.CREATE,
        EntityAccessBasis.EXISTENCE_GUARD,
    ),
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        True,
        GuardArm.FOUND,
        EntityOperation.UPDATE,
        EntityAccessBasis.EXISTENCE_GUARD,
    ),
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        True,
        GuardArm.NONE,
        None,
        EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    SaveRule(SaveArgumentOrigin.MIXED, None, None, None, EntityAccessBasis.ARGUMENT_ORIGIN),
    SaveRule(SaveArgumentOrigin.OTHER, None, None, None, EntityAccessBasis.ARGUMENT_ORIGIN),
    # A parameter that one caller hop did not resolve (R1-27).
    SaveRule(SaveArgumentOrigin.PARAMETER, None, None, None, EntityAccessBasis.ARGUMENT_ORIGIN),
)
"""Rule 3's table, first matching row wins. A parameter is first replaced by
its callers' common origin (rule 4, :func:`_effective_origin`), so the
PARAMETER row only ever sees one that stayed unresolved."""

RAW_FACT_FIELDS: tuple[str, ...] = (
    "db.repository",
    "db.method_name",
    "db.entity_type_text",
    "db.entity_type_full_name",
    "db.implemented_in_project",
    "db.query",
    "db.save.argument_origin",
    "db.save.lookup_same_repository",
    "db.save.guard_arm",
    "db.save.caller_origins",
)
"""The export facts the classifier reads. Part of the rules version: a rule
that starts reading another fact is a different rule (E4)."""


@dataclass(frozen=True)
class GateFlag:
    """One (basis, verb) gate flag (rule 5).

    A gated basis publishes its candidate verb only while the flag is on, and
    a flag is only turned on after the basis met the precision bar on labeled
    saves, measured against ``scored_rules_version``. A flag on for any other
    version publishes nothing (E4).
    """

    basis: EntityAccessBasis
    operation: EntityOperation
    enabled: bool
    scored_rules_version: str | None


SHIPPED_GATE_FLAGS: tuple[GateFlag, ...] = (
    GateFlag(EntityAccessBasis.ARGUMENT_ORIGIN, EntityOperation.CREATE, False, None),
    GateFlag(EntityAccessBasis.ARGUMENT_ORIGIN, EntityOperation.UPDATE, False, None),
    GateFlag(EntityAccessBasis.EXISTENCE_GUARD, EntityOperation.CREATE, False, None),
    GateFlag(EntityAccessBasis.EXISTENCE_GUARD, EntityOperation.UPDATE, False, None),
)
"""Both bases ship off (§5.2.17): no basis has been scored yet (M5)."""


def rules_version(
    *,
    exact_names: Mapping[str, NameRoute] = EXACT_NAMES,
    name_prefixes: Sequence[tuple[str, NameRoute]] = NAME_PREFIXES,
    save_split: Sequence[SaveRule] = SAVE_SPLIT,
    raw_fact_fields: Sequence[str] = RAW_FACT_FIELDS,
) -> str:
    """A stable hash of the verb table and the facts it reads (rule 5, E4).

    Canonical JSON rather than ``hash()``, which is salted per process: the
    version is compared across runs, and against a number a person recorded
    when they scored a flag.

    The query reader (M6) is not hashed in. It publishes on the
    ``query-text`` basis, which no flag gates, and it cannot change what a
    gated basis computes, so a change to it must not void a save score.
    """
    canonical = json.dumps(
        {
            "exact_names": sorted([name, route.value] for name, route in exact_names.items()),
            "name_prefixes": [[prefix, route.value] for prefix, route in name_prefixes],
            "name_operations": sorted(
                [route.value, operation.value] for route, operation in _NAME_OPERATION.items()
            ),
            "save_split": [
                [
                    rule.origin.value,
                    rule.lookup_same_repository,
                    rule.guard_arm.value if rule.guard_arm else None,
                    rule.candidate.value if rule.candidate else None,
                    rule.basis.value,
                ]
                for rule in save_split
            ],
            "raw_fact_fields": list(raw_fact_fields),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


RULES_VERSION = rules_version()
"""The rules version that runs. Recorded on every service's accounting."""


def name_route(method_name: str) -> NameRoute | None:
    """The verb table's answer for one method name; None = not in the table."""
    exact = EXACT_NAMES.get(method_name)
    if exact is not None:
        return exact
    for prefix, route in NAME_PREFIXES:
        if method_name.startswith(prefix):
            return route
    return None


def classify_db_access(
    db: ExportDbAccess,
    *,
    entities: EntityCatalog,
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
) -> EntityAccessSite | None:
    """Classify one repository call into its site; None for ``flush``.

    The rules apply in the plan's order, first match wins:

    * ``flush`` is not an entity operation (rule 2): no site.
    * A method carrying a query (rule 1) is decided by the query, never by
      its name (R1-12). :func:`read_query` is where that happens.
    * A method with a body in the project is ``unknown`` (C3).
    * Otherwise the name decides (rule 2), and a save goes to the split.
    """
    route = name_route(db.method_name)
    if route is NameRoute.FLUSH:
        return None
    entity = db.entity_type_full_name
    repository_entity = EntityAccess(
        entity=entity,
        data_model_id=entities.model_id(entity),
        operation=EntityOperation.UNKNOWN,
    )
    # R1-4: the type argument as written is evidence only while it is
    # unresolved; once resolved, `entity` already says it.
    entity_type_text = db.entity_type_text if entity is None else None
    if db.query is not None:
        basis = EntityAccessBasis.QUERY_TEXT
        accesses, entity_type_text = read_query(db, repository_entity, entities)
    elif db.implemented_in_project:
        basis = EntityAccessBasis.METHOD_NAME
        accesses = [repository_entity]
    elif route is NameRoute.SAVE:
        candidate, basis = split_save(db.save)
        published = _gate(candidate, basis, gate_flags)
        accesses = [
            repository_entity.model_copy(
                update={
                    "operation": published,
                    "candidate_operation": candidate if published != candidate else None,
                }
            )
        ]
    else:
        basis = EntityAccessBasis.METHOD_NAME
        operation = (
            _NAME_OPERATION.get(route, EntityOperation.UNKNOWN)
            if route is not None
            else EntityOperation.UNKNOWN
        )
        accesses = [repository_entity.model_copy(update={"operation": operation})]
    return EntityAccessSite(
        repository=db.repository,
        method_name=db.method_name,
        basis=basis,
        accesses=accesses,
        entity_type_text=entity_type_text,
    )


def split_save(save: ExportDbSave | None) -> tuple[EntityOperation | None, EntityAccessBasis]:
    """The save split's candidate and its basis (rules 3 and 4), before the gate.

    A save without split facts (an export before T3's save facts, or a row
    the pass did not describe) has no input: no candidate.
    """
    if save is None:
        return None, EntityAccessBasis.ARGUMENT_ORIGIN
    origin = _effective_origin(save)
    for rule in SAVE_SPLIT:
        if (
            rule.origin is origin
            and rule.lookup_same_repository in (None, save.lookup_same_repository)
            and rule.guard_arm in (None, save.guard_arm)
        ):
            return rule.candidate, rule.basis
    # The table covers every origin; a combination it does not is undecided.
    return None, EntityAccessBasis.ARGUMENT_ORIGIN


def _effective_origin(save: ExportDbSave) -> SaveArgumentOrigin:
    """A parameter takes its callers' origin when every caller agrees (rule 4, R1-27).

    One hop only. Callers that disagree, no caller at all, or an origin that
    is still a parameter after the hop leave it a parameter, which the split
    table reads as undecided.
    """
    if save.argument_origin is not SaveArgumentOrigin.PARAMETER:
        return save.argument_origin
    callers = set(save.caller_origins)
    if len(callers) == 1:
        return callers.pop()
    return SaveArgumentOrigin.PARAMETER


def _gate(
    candidate: EntityOperation | None,
    basis: EntityAccessBasis,
    gate_flags: Sequence[GateFlag],
) -> EntityOperation:
    """Rule 5: a candidate is published only through an on, current flag."""
    if candidate is None:
        return EntityOperation.CREATE_OR_UPDATE
    for flag in gate_flags:
        if (
            flag.basis is basis
            and flag.operation is candidate
            and flag.enabled
            and flag.scored_rules_version == RULES_VERSION
        ):
            return candidate
    return EntityOperation.CREATE_OR_UPDATE


def read_query(
    db: ExportDbAccess, repository_entity: EntityAccess, entities: EntityCatalog
) -> tuple[list[EntityAccess], str | None]:
    """The accesses an annotated query performs, and the site's unresolved text.

    The query reader (M6, :mod:`wadi_worker.query_reader`) reads the text and
    may return several accesses, one per entity the query names, each with
    its own verb (rule 6, C1). That is why the site's validator allows several
    only on the ``query-text`` basis. A query it does not read (no text, a
    Mongo JSON query, a verb it cannot follow) keeps the pre-M6 answer: one
    ``unknown`` access on the repository's own entity, because the method is
    known to touch data and what it does is not read.

    The text returned is the site's ``entity_type_text``: the names as written
    when no access resolved to an entity, and None as soon as one did.
    """
    reading = read_repository_query(db, entities)
    if reading is None:
        unread_text = db.entity_type_text if repository_entity.entity is None else None
        return [repository_entity], unread_text
    accesses = [
        EntityAccess(entity=entity, data_model_id=entities.model_id(entity), operation=operation)
        for entity, operation in reading.accesses
    ]
    resolved = any(access.entity is not None for access in accesses)
    return accesses, None if resolved or not reading.unresolved else ", ".join(reading.unresolved)


class SiteOutcome(StrEnum):
    """One repository call site's accounting outcome (B5), first match wins.

    Values are the ``EntityAccessAccounting`` field names they count into.
    """

    FLUSH = "flush"
    IMPLEMENTED_IN_PROJECT = "implemented_in_project"
    ENTITY_UNDETERMINED = "entity_undetermined"
    UNKNOWN_OPERATION = "unknown_operation"
    CREATE_OR_UPDATE = "create_or_update"
    BOUND = "bound"


@dataclass(frozen=True)
class DbCallSite:
    """One repository call site of the export, classified.

    The accounting unit: one distinct ``call_id`` among the ``kind=db`` sink
    rows (B5). ``site`` is None for ``flush``, which is not an entity
    operation, and for a row the pass did not describe.
    """

    call_id: int
    method_id: int
    node_id: int
    outcome: SiteOutcome
    site: EntityAccessSite | None


def carries_entity_facts(export: ServiceExport) -> bool:
    """Whether the export is new enough to state entity facts (2.14.0+).

    An unreadable minor reads as too old: "not looked at" is the claim that
    cannot turn out false.
    """
    match = _MAJOR_MINOR.match(export.export_schema_version)
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= ENTITY_FACTS_SINCE


def classify_db_sinks(
    sinks: Iterable[ExportSink],
    *,
    entities: EntityCatalog,
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
) -> list[DbCallSite]:
    """Every repository call site of an export, classified once, in export order.

    One record per distinct ``call_id``: two calls in one statement are two
    sites (R1-2), and the rows a call site would repeat per candidate value
    (§5.2 over-approximation) are one. ``entities`` is the service's entity
    records, which give an access its ``dm_`` id and the query reader its
    names (M6).
    """
    rows: dict[int, ExportSink] = {}
    for sink in sinks:
        if sink.kind != "db":
            continue
        prior = rows.get(sink.call_id)
        if prior is None or (prior.db is None and sink.db is not None):
            rows[sink.call_id] = sink
    calls: list[DbCallSite] = []
    for call_id, sink in rows.items():
        if sink.db is None:
            # Every kind=db row of a 2.14.0 export carries its facts. One
            # without is a call the pass saw and did not describe. It cannot
            # be a site, because a site names its repository and method, so it
            # is counted as a call whose entity nobody determined rather than
            # left out of the accounting (P10).
            logger.warning(
                "db sink call %d (node %d) carries no repository facts; counted "
                "entity_undetermined, no site",
                call_id,
                sink.node_id,
            )
            outcome, site = SiteOutcome.ENTITY_UNDETERMINED, None
        else:
            site = classify_db_access(sink.db, entities=entities, gate_flags=gate_flags)
            outcome = _outcome(sink.db, site)
        calls.append(
            DbCallSite(
                call_id=call_id,
                method_id=sink.method_id,
                node_id=sink.node_id,
                outcome=outcome,
                site=site,
            )
        )
    return calls


def _outcome(db: ExportDbAccess, site: EntityAccessSite | None) -> SiteOutcome:
    """The first accounting bucket that holds for one described site (B5)."""
    if site is None:
        return SiteOutcome.FLUSH
    if db.implemented_in_project:
        return SiteOutcome.IMPLEMENTED_IN_PROJECT
    operations = {access.operation for access in site.accesses}
    if any(access.entity is None for access in site.accesses):
        return SiteOutcome.ENTITY_UNDETERMINED
    if EntityOperation.UNKNOWN in operations:
        return SiteOutcome.UNKNOWN_OPERATION
    if EntityOperation.CREATE_OR_UPDATE in operations:
        return SiteOutcome.CREATE_OR_UPDATE
    return SiteOutcome.BOUND


def account_entity_access(
    calls: Sequence[DbCallSite],
    *,
    in_endpoint_flow: set[int],
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
) -> EntityAccessAccounting:
    """Every repository call site of one service, partitioned twice (B5, R1-1).

    ``in_endpoint_flow`` holds the call ids some endpoint ICFG contains. Every
    other site is in the export and in no endpoint flow: a lambda body (A1),
    code only an async root reaches, or a handler the assembler could not
    place. Both partitions cover every call, so the contract's sum validators
    hold by construction. The flags are recorded as configured: a flag on for
    a stale rules version is visible as one, and published nothing (E4).
    """
    outcomes = dict.fromkeys(SiteOutcome, 0)
    accesses = dict.fromkeys((operation.value for operation in EntityOperation), 0)
    bases = dict.fromkeys((basis.value for basis in EntityAccessBasis), 0)
    for call in calls:
        outcomes[call.outcome] += 1
        if call.site is None:
            continue
        bases[call.site.basis.value] += 1
        for access in call.site.accesses:
            accesses[access.operation.value] += 1
    in_flow = sum(1 for call in calls if call.call_id in in_endpoint_flow)
    return EntityAccessAccounting(
        call_sites=len(calls),
        in_endpoint_flow=in_flow,
        in_no_endpoint_flow=len(calls) - in_flow,
        flush=outcomes[SiteOutcome.FLUSH],
        implemented_in_project=outcomes[SiteOutcome.IMPLEMENTED_IN_PROJECT],
        entity_undetermined=outcomes[SiteOutcome.ENTITY_UNDETERMINED],
        unknown_operation=outcomes[SiteOutcome.UNKNOWN_OPERATION],
        create_or_update=outcomes[SiteOutcome.CREATE_OR_UPDATE],
        bound=outcomes[SiteOutcome.BOUND],
        accesses_by_operation=accesses,
        sites_by_basis=bases,
        rules_version=RULES_VERSION,
        gate_flags=[
            EntityGateFlagState(
                basis=flag.basis,
                operation=flag.operation,
                enabled=flag.enabled,
                scored_rules_version=flag.scored_rules_version,
            )
            for flag in gate_flags
        ],
    )
