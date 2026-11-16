"""Entity access classification: raw repository-call facts to claims (§5.2.17).

The Scala pass describes each repository call and stops there (P6): which
repository, which method, the bound entity, whether the method carries a
query, and for a save where its argument came from. Deciding what that call
DOES to its entity is this module's job, and the decision is a table rather
than branching code (plan "Classification rules"), so a rule change is a data
change whose hash moves, and a gate flag scored against the old table stops
publishing (E4). The hash also covers the code that applies the tables and
the export's own Scala save rules (:func:`rules_version`, review B4).
"""

import hashlib
import inspect
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
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
    CREATE = "create"
    """``insert`` only: ``MongoRepository.insert`` never updates (review B8)."""
    SAVE = "save"
    """Rule 3: the save split decides, from the argument's origin."""

    FLUSH = "flush"
    """Not an entity operation: counted on its own, and no site (rule 2)."""


EXACT_NAMES: Mapping[str, NameRoute] = {"flush": NameRoute.FLUSH, "insert": NameRoute.CREATE}
"""Method names matched whole, before any prefix. ``flush`` is exact because
``saveAndFlush`` is a save, not a flush. ``insert`` is exact because only
``MongoRepository.insert`` has that name, and it never updates, so it is a
``create`` by its name and never enters the save split (review B8)."""

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
)
"""Rule 2's verb table: Spring Data's derived-query subject prefixes. A
prefix counts only where the name ends or goes on with an uppercase letter,
the way Spring Data's own parser splits a name, so ``deleted(boolean)`` is a
find by a property, not a delete (review B8). No prefix is a prefix of
another, so the order does not decide anything. A name outside the table is
``unknown``. It is never guessed from a word that looks like a verb (P10)."""

_NAME_OPERATION: Mapping[NameRoute, EntityOperation] = {
    NameRoute.READ: EntityOperation.READ,
    NameRoute.DELETE: EntityOperation.DELETE,
    NameRoute.CREATE: EntityOperation.CREATE,
}


IDENTITY_LOOKUPS: frozenset[str] = frozenset(
    {"findById", "getById", "getReferenceById", "existsById"}
)
"""The lookups that test whether THE row exists, by its key (review B5).

A lookup by any other field (``findByUserId``) says some row matches that
field. A new object saved while one does is still an insert: train-ticket's
``ts-delivery-service`` saves a new UUID-keyed ledger row inside
``if (findByUserId(id) != null)``. So the found arm decides only after one of
these."""


@dataclass(frozen=True)
class SaveRule:
    """One row of the save split (rules 3 and 4). ``None`` matches anything.

    ``guard_lookups`` is the set the guard's lookup method must be in; a
    column rather than a branch, so a change to it moves the rules version.
    ``candidate`` is the verb the evidence supports, or None when it supports
    neither; ``basis`` names the evidence that decided, so the guard arm is
    the basis only where it was consulted and decided.
    """

    origin: SaveArgumentOrigin
    lookup_same_repository: bool | None
    guard_arm: GuardArm | None
    guard_lookups: frozenset[str] | None
    candidate: EntityOperation | None
    basis: EntityAccessBasis


SAVE_SPLIT: tuple[SaveRule, ...] = (
    # An object a repository returned is already stored: saving it updates.
    SaveRule(
        SaveArgumentOrigin.READ,
        lookup_same_repository=None,
        guard_arm=None,
        guard_lookups=None,
        candidate=EntityOperation.UPDATE,
        basis=EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    # A `new` with no lookup on the same repository creates.
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        lookup_same_repository=False,
        guard_arm=None,
        guard_lookups=None,
        candidate=EntityOperation.CREATE,
        basis=EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    # A `new` beside a lookup: only the arm of the existence check says which
    # (the train-ticket shape §5.2.17 names, and the 2023 paper's miss).
    # Nothing matched in the not-found arm, whatever the lookup tested.
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        lookup_same_repository=True,
        guard_arm=GuardArm.NOT_FOUND,
        guard_lookups=None,
        candidate=EntityOperation.CREATE,
        basis=EntityAccessBasis.EXISTENCE_GUARD,
    ),
    # The found arm is an update only when the lookup was by identity
    # (review B5); after any other lookup, the next row says nothing.
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        lookup_same_repository=True,
        guard_arm=GuardArm.FOUND,
        guard_lookups=IDENTITY_LOOKUPS,
        candidate=EntityOperation.UPDATE,
        basis=EntityAccessBasis.EXISTENCE_GUARD,
    ),
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        lookup_same_repository=True,
        guard_arm=GuardArm.FOUND,
        guard_lookups=None,
        candidate=None,
        basis=EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    SaveRule(
        SaveArgumentOrigin.CONSTRUCTED,
        lookup_same_repository=True,
        guard_arm=GuardArm.NONE,
        guard_lookups=None,
        candidate=None,
        basis=EntityAccessBasis.ARGUMENT_ORIGIN,
    ),
    *(
        SaveRule(
            origin,
            lookup_same_repository=None,
            guard_arm=None,
            guard_lookups=None,
            candidate=None,
            basis=EntityAccessBasis.ARGUMENT_ORIGIN,
        )
        # PARAMETER: one that one caller hop did not resolve (R1-27).
        for origin in (
            SaveArgumentOrigin.MIXED,
            SaveArgumentOrigin.OTHER,
            SaveArgumentOrigin.PARAMETER,
        )
    ),
)
"""Rule 3's table, first matching row wins. A parameter is first replaced by
its callers' common origin (rule 4, :func:`_effective_origin`), so the
PARAMETER row only ever sees one that stayed unresolved."""

PERSISTENCE_PACKAGES: tuple[str, ...] = (
    "org.springframework.data.",
    "org.hibernate.",
    "jakarta.persistence.",
    "javax.persistence.",
)
"""Where an annotation that changes a repository method's statement lives.
Only Spring Data and the JPA provider act on a repository method, so an
annotation from any other package leaves the verb to the name (review B1)."""

VERB_CHANGING_SIMPLE_NAMES: frozenset[str] = frozenset(
    {
        "Update",
        "Procedure",
        "Aggregation",
        "DeleteQuery",
        "CountQuery",
        "ExistsQuery",
        "NativeQuery",
    }
)
"""An annotation the export could not resolve is written by its simple name
alone. It counts as a persistence annotation under one of these names, the
Spring Data annotations known to replace a method's statement, and under the
name of one the query path reads (:data:`VERB_NEUTRAL_ANNOTATIONS` with
``needs_query``), so an unresolved ``@Query`` whose text the export did not
carry is unread too."""


@dataclass(frozen=True)
class NeutralAnnotation:
    """A persistence annotation that does not change which verb a method performs."""

    name: str
    """Simple name: the package is already known to be a persistence one."""
    needs_query: bool
    """Neutral only when the export carries the method's query, because the
    query path is what reads it; without the text it decides nothing."""
    reason: str


VERB_NEUTRAL_ANNOTATIONS: tuple[NeutralAnnotation, ...] = (
    NeutralAnnotation("Query", True, "the query path reads its text"),
    NeutralAnnotation("Modifying", True, "marks a @Query as a write; the query path reads it"),
    NeutralAnnotation("NativeQuery", True, "read as a native @Query once its text is carried"),
    NeutralAnnotation("Transactional", False, "sets the transaction, not the statement"),
    NeutralAnnotation("Lock", False, "adds a row lock to the same statement"),
    NeutralAnnotation("QueryHints", False, "passes provider hints to the same statement"),
    NeutralAnnotation("EntityGraph", False, "chooses what a read fetches, not whether it reads"),
    NeutralAnnotation("Meta", False, "attaches Mongo query metadata such as a comment"),
    NeutralAnnotation("Hint", False, "chooses the index a Mongo query uses"),
    NeutralAnnotation("ReadPreference", False, "chooses the replica a Mongo read goes to"),
    NeutralAnnotation("Collation", False, "sets how a query compares strings"),
    NeutralAnnotation("Tailable", False, "keeps a Mongo cursor open; it still reads"),
    NeutralAnnotation("RestResource", False, "configures Spring Data REST's export of the method"),
    NeutralAnnotation("Param", False, "names a query parameter"),
    NeutralAnnotation("Nullable", False, "a null-safety contract on the result"),
    NeutralAnnotation("NonNull", False, "a null-safety contract on the result"),
)
"""Persistence annotations that leave the verb to the name or the query
(review B1). Any other annotation from a persistence package makes the
operation ``unknown``: ``@Update``, ``@Aggregation``, ``@DeleteQuery``,
``@CountQuery``, ``@ExistsQuery``, ``@Procedure`` and the ones nobody listed
yet. Data rather than a branch, so a change to it moves the rules version."""

_NEUTRAL_BY_NAME: Mapping[str, NeutralAnnotation] = {a.name: a for a in VERB_NEUTRAL_ANNOTATIONS}

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
    "db.save.guard_lookup_method",
    "db.save.caller_origins",
    "db.method_annotations",
    "db.declaration_resolved",
    "data_model.delete_rewritten_by",
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


def name_route(method_name: str) -> NameRoute | None:
    """The verb table's answer for one method name; None = not in the table."""
    exact = EXACT_NAMES.get(method_name)
    if exact is not None:
        return exact
    for prefix, route in NAME_PREFIXES:
        rest = method_name.removeprefix(prefix)
        if rest != method_name and (not rest or rest[0].isupper()):
            return route
    return None


def classify_db_access(
    db: ExportDbAccess,
    *,
    entities: EntityCatalog,
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
    rules_version: str | None = None,
) -> EntityAccessSite | None:
    """Classify one repository call into its site; None for ``flush``.

    ``rules_version`` is the version of the export the call came from
    (:func:`export_rules_version`), which a flag's score must name for the
    flag to publish; None stands for an export that carries no
    ``save_origin_rules``, :data:`RULES_VERSION`.

    The rules apply in the plan's order, first match wins:

    * A method whose declaration the export did not resolve, or that carries
      a persistence annotation nothing here reads, is ``unknown``: what it
      does was not read, so neither its name nor the save split decides
      (review B1). The basis is the query's when it carries one.
    * ``flush`` is not an entity operation (rule 2): no site.
    * A method carrying a query (rule 1) is decided by the query, never by
      its name (R1-12). :func:`read_query` is where that happens.
    * A method with a body in the project is ``unknown`` (C3).
    * Otherwise the name decides (rule 2), and a save goes to the split.
    """
    unread = _is_unread(db)
    route = name_route(db.method_name)
    if route is NameRoute.FLUSH and not unread:
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
    if unread:
        basis = (
            EntityAccessBasis.QUERY_TEXT if db.query is not None else EntityAccessBasis.METHOD_NAME
        )
        accesses = [repository_entity]
    elif db.query is not None:
        basis = EntityAccessBasis.QUERY_TEXT
        accesses, entity_type_text = read_query(db, repository_entity, entities)
    elif db.implemented_in_project:
        basis = EntityAccessBasis.METHOD_NAME
        accesses = [repository_entity]
    elif route is NameRoute.SAVE:
        candidate, basis = split_save(db.save)
        published = _gate(candidate, basis, gate_flags, rules_version or RULES_VERSION)
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
        accesses = [
            repository_entity.model_copy(
                update={"operation": _unless_rewritten(operation, entity, entities)}
            )
        ]
    return EntityAccessSite(
        repository=db.repository,
        method_name=db.method_name,
        basis=basis,
        accesses=accesses,
        entity_type_text=entity_type_text,
    )


def _is_unread(db: ExportDbAccess) -> bool:
    """Whether what the method does was not read: its declaration did not
    resolve, or one of its annotations may change its verb (review B1)."""
    if not db.declaration_resolved:
        return True
    return any(
        _changes_the_verb(entry.rsplit(">", 1)[-1], query_carried=db.query is not None)
        for entry in db.method_annotations
    )


def _changes_the_verb(annotation: str, *, query_carried: bool) -> bool:
    """One annotation's test. A meta-annotation entry (``a>b``) is passed as
    ``b``, the annotation the project's own one carries."""
    package, _, name = annotation.rpartition(".")
    neutral = _NEUTRAL_BY_NAME.get(name)
    if package:
        persistence = annotation.startswith(PERSISTENCE_PACKAGES)
    else:
        persistence = name in VERB_CHANGING_SIMPLE_NAMES or (
            neutral is not None and neutral.needs_query
        )
    if not persistence:
        return False
    return neutral is None or (neutral.needs_query and not query_carried)


def _unless_rewritten(
    operation: EntityOperation, entity: str | None, entities: EntityCatalog
) -> EntityOperation:
    """A delete of an entity carrying Hibernate ``@SQLDelete``/``@SoftDelete``
    runs that statement instead, usually an update, so the verb is not the
    name's (review B1, ``DataModel.delete_rewritten_by``)."""
    if operation is EntityOperation.DELETE and entities.delete_rewritten_by(entity):
        return EntityOperation.UNKNOWN
    return operation


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
            and (rule.guard_lookups is None or save.guard_lookup_method in rule.guard_lookups)
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
    rules_version: str,
) -> EntityOperation:
    """Rule 5: a candidate is published only through an on flag scored
    against the rules this export runs under (E4)."""
    if candidate is None:
        return EntityOperation.CREATE_OR_UPDATE
    for flag in gate_flags:
        if (
            flag.basis is basis
            and flag.operation is candidate
            and flag.enabled
            and flag.scored_rules_version == rules_version
        ):
            return candidate
    return EntityOperation.CREATE_OR_UPDATE


GATED_FUNCTIONS: tuple[Callable[..., object], ...] = (
    classify_db_access,
    name_route,
    _is_unread,
    _changes_the_verb,
    split_save,
    _effective_origin,
    _gate,
)
"""Every function on the path from a call's facts to a gated candidate: the
rule order, rule 4 and the gate are code, so their source is part of the
rules version (review B4). The query reader is not on it: it publishes on
the ``query-text`` basis, which no flag gates, and it cannot change what a
gated basis computes, so a change to it must not void a save score."""


def rules_version(
    *,
    save_origin_rules: str | None,
    exact_names: Mapping[str, NameRoute] = EXACT_NAMES,
    name_prefixes: Sequence[tuple[str, NameRoute]] = NAME_PREFIXES,
    save_split: Sequence[SaveRule] = SAVE_SPLIT,
    raw_fact_fields: Sequence[str] = RAW_FACT_FIELDS,
    persistence_packages: Sequence[str] = PERSISTENCE_PACKAGES,
    verb_changing_names: frozenset[str] = VERB_CHANGING_SIMPLE_NAMES,
    verb_neutral: Sequence[NeutralAnnotation] = VERB_NEUTRAL_ANNOTATIONS,
    functions: Sequence[Callable[..., object]] = GATED_FUNCTIONS,
    source_of: Callable[[Callable[..., object]], str] = inspect.getsource,
) -> str:
    """A stable hash of every input to a gated verb (rule 5, E4, review B4).

    The tables, the source of :data:`GATED_FUNCTIONS`, and the export's
    ``save_origin_rules``: a hash the sbt build computes from the Scala
    sources that derive the save facts (None on an export before 2.15.0,
    which hashes differently from any value). A formatting change moves it
    too, which costs a re-score and can never keep a stale one. The M5
    scorer calls this with the export it scored, and records the result as
    the flag's ``scored_rules_version``.

    Canonical JSON rather than ``hash()``, which is salted per process: the
    version is compared across runs, and against a number a person recorded
    when they scored a flag.
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
                    sorted(rule.guard_lookups) if rule.guard_lookups is not None else None,
                    rule.candidate.value if rule.candidate else None,
                    rule.basis.value,
                ]
                for rule in save_split
            ],
            "raw_fact_fields": list(raw_fact_fields),
            "persistence_packages": list(persistence_packages),
            "verb_changing_names": sorted(verb_changing_names),
            "verb_neutral": [[a.name, a.needs_query, a.reason] for a in verb_neutral],
            "functions": [source_of(function) for function in functions],
            "save_origin_rules": save_origin_rules,
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


RULES_VERSION = rules_version(save_origin_rules=None)
"""The version for an export that carries no ``save_origin_rules`` (one
written before 2.15.0). Any other export runs under
:func:`export_rules_version`, which is what its accounting records."""


def export_rules_version(export: ServiceExport) -> str:
    """The rules version one export is classified under (review B4)."""
    return rules_version(save_origin_rules=export.save_origin_rules)


def read_query(
    db: ExportDbAccess, repository_entity: EntityAccess, entities: EntityCatalog
) -> tuple[list[EntityAccess], str | None]:
    """The accesses an annotated query performs, and the site's unresolved text.

    The query reader (M6, :mod:`wadi_worker.query_reader`) reads the text and
    may return several accesses, one per entity the query names, each with
    its own verb (rule 6, C1). That is why the site's validator allows several
    only on the ``query-text`` basis. A query it does not read (no text, a
    Mongo JSON query, a verb it cannot follow, text its lexer cannot split, a
    select that only calls a function) keeps the pre-M6 answer: one
    ``unknown`` access on the repository's own entity, because the method is
    known to touch data and what it does is not read. A JPQL delete of an
    entity whose delete Hibernate rewrites is ``unknown`` too (review B1).

    The text returned is the site's ``entity_type_text``: the names as written
    when no access resolved to an entity, and None as soon as one did.
    """
    reading = read_repository_query(db, entities)
    if reading is None:
        unread_text = db.entity_type_text if repository_entity.entity is None else None
        return [repository_entity], unread_text
    # A JPQL delete goes through the provider, which applies the entity's
    # delete rewrite; native SQL runs the statement as written.
    native = db.query is not None and db.query.native
    accesses = [
        EntityAccess(
            entity=entity,
            data_model_id=entities.model_id(entity),
            operation=operation if native else _unless_rewritten(operation, entity, entities),
        )
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
    rows (B5). ``site`` is None only for ``flush``, which is not an entity
    operation.
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
    rules_version: str,
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
) -> list[DbCallSite]:
    """Every repository call site of an export, classified once, in export order.

    One record per distinct ``call_id``: two calls in one statement are two
    sites (R1-2), and the rows a call site would repeat per candidate value
    (§5.2 over-approximation) are one. ``entities`` is the service's entity
    records, which give an access its ``dm_`` id and the query reader its
    names (M6); ``rules_version`` is the export's own
    (:func:`export_rules_version`), the one a flag's score must name.
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
            # without is a call the pass saw and did not describe. It is still
            # a repository call, so it gets a site whose entity nobody
            # determined (review C8): its endpoint then reads "undetermined"
            # instead of "no repository call found", and the basis counts
            # still cover every non-flush site (P10).
            logger.warning(
                "db sink call %d (node %d) carries no repository facts; counted "
                "entity_undetermined",
                call_id,
                sink.node_id,
            )
            outcome, site = SiteOutcome.ENTITY_UNDETERMINED, _undescribed_site()
        else:
            site = classify_db_access(
                sink.db, entities=entities, gate_flags=gate_flags, rules_version=rules_version
            )
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


UNDESCRIBED_CALL = "unknown"
"""The repository and method name of a call the pass did not describe.

Neither the row nor its ICFG node says which call it is: the node's ``call``
is the statement's primary call, which for ``repo.findById(id).get()`` is
``Optional.get``, and the row carries no callee. Borrowing the node's name
could name another call, so the site says it does not know (review C8)."""


def _undescribed_site() -> EntityAccessSite:
    return EntityAccessSite(
        repository=UNDESCRIBED_CALL,
        method_name=UNDESCRIBED_CALL,
        basis=EntityAccessBasis.METHOD_NAME,
        accesses=[EntityAccess(entity=None, data_model_id=None, operation=EntityOperation.UNKNOWN)],
    )


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
    rules_version: str,
    gate_flags: Sequence[GateFlag] = SHIPPED_GATE_FLAGS,
) -> EntityAccessAccounting:
    """Every repository call site of one service, partitioned twice (B5, R1-1).

    ``in_endpoint_flow`` holds the call ids some endpoint ICFG contains. Every
    other site is in the export and in no endpoint flow: a lambda body (A1),
    code only an async root reaches, or a handler the assembler could not
    place. Both partitions cover every call, so the contract's sum validators
    hold by construction. The flags are recorded as configured, beside the
    export's own ``rules_version``: a flag on for a stale rules version is
    visible as one, and published nothing (E4).
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
        rules_version=rules_version,
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
