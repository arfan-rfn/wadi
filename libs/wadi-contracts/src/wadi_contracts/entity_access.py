"""Entity access: which entities an endpoint may touch, and how (§5.2.17).

The fact is per repository CALL SITE, and a claim is never stronger than its
basis. A site names the repository it called and why its operations were
decided (:class:`EntityAccessBasis`); each of its accesses names one entity
and one operation. The per-endpoint summary and the reverse view are folds of
those sites, computed by the two functions at the bottom of this module so the
fold exists exactly once (R1-22): the worker, the orchestrator and the MCP
server all call them, the way every reader of a wire shape calls
:func:`~wadi_contracts.endpoint.resolve_type_shape`.

Declaration order of every enum here is its display order everywhere.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import Field, model_validator

from wadi_contracts.base import WadiModel
from wadi_contracts.enums import HttpMethod

if TYPE_CHECKING:
    # DataModel's `declared_by` is typed by EntityDeclaredBy, defined here, so a
    # runtime import would be circular. Only the reverse view's signature
    # needs the name.
    from wadi_contracts.datamodel import DataModel

_DM_ID = r"^dm_[0-9a-f]{16}$"


class EntityOperation(StrEnum):
    """What an access may do to its entity (§5.2.17).

    "May" is the whole meaning: some path through the endpoint performs it,
    never that every path does (Q16). The vocabulary is CRUD because the
    reader is a developer; there is no ``write``.
    """

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    CREATE_OR_UPDATE = "create-or-update"
    """One value, never two verbs on one fact (R1-5).

    A save the analysis could not split. Publishing ``create`` AND ``update``
    instead would claim that both happen on some path, which is a stronger
    statement than the evidence makes. A demoted fact keeps the verb it would
    have claimed in ``candidate_operation``."""

    UNKNOWN = "unknown"
    """The verb could not be read (P10): an annotated query before the reader
    exists, a method name outside the verb table, or a repository method whose
    body is in the project — membership of a repository does not establish
    what a hand-written body does (C3)."""


_OPERATION_ORDER: dict[EntityOperation, int] = {op: i for i, op in enumerate(EntityOperation)}


class EntityAccessBasis(StrEnum):
    """Which evidence decided a site's operations (§5.2.17)."""

    METHOD_NAME = "method-name"
    """The Spring Data derived-method name, for a method Spring Data implements."""

    QUERY_TEXT = "query-text"
    """The method carries ``@Query``/``@Modifying`` or resolves to a named
    query. The method name never decides for such a method (R1-12)."""

    ARGUMENT_ORIGIN = "argument-origin"
    """A save split by where its argument came from: read, constructed, a
    parameter traced one caller hop. Gated (rule 5)."""

    EXISTENCE_GUARD = "existence-guard"
    """A save sitting directly in the found / not-found arm of an existence
    check on the same repository. Gated (rule 5)."""


class EntityDeclaredBy(StrEnum):
    """How an entity came to be one (Q1, Q15)."""

    ANNOTATION = "annotation"
    """``@Entity`` or ``@Document`` on the class."""

    REPOSITORY_ARGUMENT = "repository-argument"
    """A repository's type argument names it and the class carries no
    persistence annotation. The repository defines the entity; an annotation
    is not required for data to be stored under that type."""


class UnmeasuredEntityAccess(StrEnum):
    """Ways an endpoint touches data that this phase does not measure (Q2, Q17, Q4).

    Listed on every coverage section, so a count of entity operations is never
    read as the complete set of writes an endpoint performs.
    """

    CASCADED_OPERATIONS = "cascaded-operations"
    DIRTY_CHECKING_UPDATES = "dirty-checking-updates"
    OTHER_PERSISTENCE_MECHANISMS = "other-persistence-mechanisms"


class EntityAccess(WadiModel):
    """One entity one call site touches, with one operation (§5.2.17).

    ``candidate_operation`` is evidence, never a claim (R1-11): it is the verb
    a gated basis computed while its flag was off. The fact then publishes
    ``create-or-update``, and a reader that wants the claim reads
    ``operation`` only.
    """

    entity: str | None = Field(
        description="Qualified type name of the entity; None = the entity could not be "
        "determined (an unbindable repository chain or an unresolved query name)"
    )
    data_model_id: str | None = Field(
        pattern=_DM_ID,
        description="The entity's `dm_` id when the entity is in this service's data_models",
    )
    operation: EntityOperation
    candidate_operation: EntityOperation | None = Field(
        default=None,
        description="The verb a gated basis would have claimed (create | update); set only "
        "on a demoted fact, whose operation is then create-or-update",
    )

    @model_validator(mode="after")
    def _candidate_is_evidence_only(self) -> Self:
        """A candidate rides only on a demoted save, and only names a split verb.

        A candidate beside a published single verb would be a second claim the
        gate never earned, and a candidate of ``read`` or ``unknown`` names
        nothing the save split could have produced. Either is a writer bug that
        a reader would otherwise render as evidence.
        """
        candidate = self.candidate_operation
        if candidate is None:
            return self
        if self.operation is not EntityOperation.CREATE_OR_UPDATE:
            raise ValueError(
                "candidate_operation is evidence for a demoted save and requires "
                f"operation=create-or-update, got operation={self.operation.value}"
            )
        if candidate not in (EntityOperation.CREATE, EntityOperation.UPDATE):
            raise ValueError(f"candidate_operation must be create or update, got {candidate.value}")
        return self

    @model_validator(mode="after")
    def _model_id_names_an_entity(self) -> Self:
        if self.data_model_id is not None and self.entity is None:
            raise ValueError(
                "data_model_id requires an entity: an undetermined entity cannot "
                "name the model it is"
            )
        return self


class EntityAccessSite(WadiModel):
    """One repository call site and what it touches (§5.2.17, E1, C1).

    Carried on the ICFG node of the statement that makes the call, as a list,
    because one statement can make two repository calls (R1-2). Sites are
    counted as sites and accesses as accesses, never mixed: a query that
    deletes ``Invoice`` while reading ``Customer`` is ONE site with TWO
    accesses.
    """

    repository: str = Field(
        description="The receiver's declared repository type, qualified, e.g. "
        "'com.acme.pets.PetRepository'"
    )
    method_name: str = Field(description="The repository method called, e.g. 'findByStatus'")
    basis: EntityAccessBasis
    accesses: list[EntityAccess] = Field(min_length=1)
    entity_type_text: str | None = Field(
        default=None,
        description="The repository's entity type argument as written, kept as raw evidence "
        "when it could not be resolved to a type (R1-4)",
    )

    @model_validator(mode="after")
    def _only_a_query_names_several_entities(self) -> Self:
        """A derived method or a save acts on the repository's ONE entity.

        Only query text can name several (C1, rule 6), so a second access on
        any other basis is not something the analysis read.
        """
        if self.basis is not EntityAccessBasis.QUERY_TEXT and len(self.accesses) != 1:
            raise ValueError(
                f"a {self.basis.value} site has exactly one access; only a query-text "
                f"site names several entities, got {len(self.accesses)}"
            )
        return self


class EndpointEntityAccess(WadiModel):
    """One entity an endpoint may touch, and every operation it may perform (§5.2.17).

    The per-endpoint summary row, folded from the endpoint's sites by
    :func:`summarize_entity_access` and nowhere else (R1-22). ``operations``
    is a set written in :class:`EntityOperation` order, so ``create`` beside
    ``create-or-update`` stays two values: one save the analysis split and one
    it could not, which is a different statement from either alone.
    """

    entity: str | None = Field(
        description="Qualified type name; None = the row for accesses whose entity could "
        "not be determined"
    )
    data_model_id: str | None = Field(pattern=_DM_ID)
    operations: list[EntityOperation] = Field(
        min_length=1, description="Unique, in EntityOperation declaration order"
    )
    call_sites: int = Field(
        ge=1, description="Distinct repository call sites contributing to this row"
    )

    @model_validator(mode="after")
    def _operations_are_a_set_in_enum_order(self) -> Self:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("operations must be unique")
        if self.operations != sorted(self.operations, key=_OPERATION_ORDER.__getitem__):
            raise ValueError(
                "operations must be in EntityOperation enum order, got "
                f"{[op.value for op in self.operations]}"
            )
        return self


class EntityGateFlagState(WadiModel):
    """One (basis, verb) gate flag, as it was set when the worker ran (rule 5, E3).

    A gated basis publishes its candidate verb only while its flag is on, and
    a flag is only turned on after the basis met a precision bar on labeled
    saves. The stitcher cannot know how the worker was configured, so the
    worker records it here.
    """

    basis: EntityAccessBasis = Field(description="argument-origin | existence-guard")
    operation: EntityOperation = Field(description="create | update")
    enabled: bool
    scored_rules_version: str | None = Field(
        description="The rules version this flag was scored against; a flag on for a "
        "different version than `rules_version` is a stale score (E4)"
    )


def _keys_are_the_vocabulary(name: str, counts: dict[str, int], vocabulary: type[StrEnum]) -> None:
    expected = {member.value for member in vocabulary}
    if set(counts) != expected:
        missing = sorted(expected - set(counts))
        unknown = sorted(set(counts) - expected)
        raise ValueError(
            f"{name} keys must be exactly the {vocabulary.__name__} values "
            f"(missing {missing}, unknown {unknown}); a zero is written as 0, "
            "never left out (E8)"
        )


class EntityAccessAccounting(WadiModel):
    """Every repository call site of one service, accounted for (§5.2.17, R1-1).

    The unit is one repository call site: one distinct ``call_id`` among the
    export's ``db`` sink rows. The sites are partitioned twice, and each
    partition must sum to ``call_sites``, so no site can fall out of the
    report unseen (P10):

    1. **Flow membership** — whether the site lies in some endpoint's ICFG.
       A site in the export but in no endpoint flow (a call inside a lambda
       body, finding A1) is counted rather than lost.
    2. **Outcome** — the first of these that holds, in this order:
       ``flush`` (not an entity operation), ``implemented_in_project`` (a body
       the verb table does not read, C3), ``entity_undetermined``,
       ``unknown_operation``, ``create_or_update``, ``bound`` (every access has
       an entity and a single CRUD verb).

    ``accesses_by_operation`` counts ACCESSES (a two-entity query counts two)
    and ``sites_by_basis`` counts SITES; both list every vocabulary value, so
    a zero reads as measured rather than as missing (E8).

    A sibling of ``ServiceBoundary.analysis_coverage``, never part of it: that
    one is an in-CPG methods metric with its own invariant (E2).
    """

    call_sites: int = Field(ge=0, description="Distinct repository call sites in the export")
    in_endpoint_flow: int = Field(ge=0)
    in_no_endpoint_flow: int = Field(
        ge=0, description="In the export but in no endpoint ICFG (lambda bodies, A1)"
    )
    flush: int = Field(ge=0, description="flush() — not an entity operation")
    implemented_in_project: int = Field(
        ge=0, description="The called repository method has a body in the project (C3)"
    )
    entity_undetermined: int = Field(ge=0, description="Some access has no entity")
    unknown_operation: int = Field(ge=0, description="Some access has operation unknown")
    create_or_update: int = Field(ge=0, description="Some access has operation create-or-update")
    bound: int = Field(ge=0, description="Every access has an entity and a single CRUD verb")
    accesses_by_operation: dict[str, int] = Field(
        description="Accesses per EntityOperation value; every value present"
    )
    sites_by_basis: dict[str, int] = Field(
        description="Sites per EntityAccessBasis value; every value present"
    )
    rules_version: str = Field(description="The verb-table rules version (a hash) that ran")
    gate_flags: list[EntityGateFlagState] = Field(
        description="The (basis, verb) gate flags as they were set for this run (E3)"
    )

    @model_validator(mode="after")
    def _every_site_is_accounted_for(self) -> Self:
        flow = self.in_endpoint_flow + self.in_no_endpoint_flow
        if flow != self.call_sites:
            raise ValueError(
                f"in_endpoint_flow + in_no_endpoint_flow = {flow} must equal call_sites "
                f"{self.call_sites}: a site in neither is a silent gap (P10)"
            )
        outcomes = (
            self.flush
            + self.implemented_in_project
            + self.entity_undetermined
            + self.unknown_operation
            + self.create_or_update
            + self.bound
        )
        if outcomes != self.call_sites:
            raise ValueError(
                "flush + implemented_in_project + entity_undetermined + unknown_operation "
                f"+ create_or_update + bound = {outcomes} must equal call_sites "
                f"{self.call_sites}: every site has exactly one outcome"
            )
        _keys_are_the_vocabulary(
            "accesses_by_operation", self.accesses_by_operation, EntityOperation
        )
        _keys_are_the_vocabulary("sites_by_basis", self.sites_by_basis, EntityAccessBasis)
        return self


class ServiceEntityAccounting(WadiModel):
    """One service's accounting, named for the snapshot rollup."""

    service_id: str
    service_name: str
    accounting: EntityAccessAccounting


class EntityCoverageSection(WadiModel):
    """Snapshot rollup of entity access accounting (§5.2.17).

    Built by the stitcher the way :class:`~wadi_contracts.stitching.AuthCoverageSection`
    is: the sums over every boundary that reports accounting, and the count of
    boundaries that predate it, which are never folded into a zero. The
    unmeasured cases travel on every section so the operation counts are not
    read as every write the system performs (Q2, Q17, Q4).
    """

    services_reporting: int = Field(ge=0, description="Boundaries that carry accounting")
    services_predating: int = Field(
        ge=0,
        description=(
            "Service boundaries whose accounting is None: written before the phase, or "
            "extraction failed (the boundary's extraction_error tells them apart)"
        ),
    )
    call_sites: int = Field(ge=0)
    in_endpoint_flow: int = Field(ge=0)
    in_no_endpoint_flow: int = Field(ge=0)
    flush: int = Field(ge=0)
    implemented_in_project: int = Field(ge=0)
    entity_undetermined: int = Field(ge=0)
    unknown_operation: int = Field(ge=0)
    create_or_update: int = Field(ge=0)
    bound: int = Field(ge=0)
    accesses_by_operation: dict[str, int] = Field(
        description="Summed accesses per EntityOperation value"
    )
    sites_by_basis: dict[str, int] = Field(description="Summed sites per EntityAccessBasis value")
    by_service: list[ServiceEntityAccounting] = Field(
        default_factory=list[ServiceEntityAccounting], description="Sorted by service_name"
    )
    unmeasured: list[UnmeasuredEntityAccess] = Field(
        default_factory=lambda: list(UnmeasuredEntityAccess),
        description="Ways data is touched that this phase does not measure — always all of them",
    )
    unexercised_vocabulary: list[str] = Field(
        default_factory=list[str],
        description=(
            "'operation:<value>' / 'basis:<value>' entries with a zero count, "
            "sorted (E8). A zero is otherwise ambiguous: wadi may have looked "
            "and found none, or this corpus never exercises the case and the "
            "zero is evidence of nothing"
        ),
    )


class EndpointEntityAccessRow(WadiModel):
    """One endpoint's entity summary as the storage projection returns it (Part C).

    The reverse view's input: a projection of the endpoint documents, never a
    full :class:`~wadi_contracts.endpoint.Endpoint` read. ``entity_access`` is
    the endpoint's own field, ``None`` included (R1-6).
    """

    endpoint_id: str
    service_id: str
    http_method: HttpMethod
    full_uri: str
    entity_access: list[EndpointEntityAccess] | None


class EntityUsageEndpoint(WadiModel):
    """One endpoint that may perform one operation on one entity."""

    endpoint_id: str
    http_method: HttpMethod
    full_uri: str
    call_sites: int = Field(
        ge=1, description="The endpoint's call sites touching this entity (its summary row's)"
    )


class EntityOperationUsage(WadiModel):
    """The endpoints that may perform one operation on one entity."""

    operation: EntityOperation
    endpoints: list[EntityUsageEndpoint] = Field(description="Sorted by full_uri, then http_method")


class EntityUsageRow(WadiModel):
    """One entity of one service, and which endpoints may do what to it (§5.2.17).

    ``operations`` lists all six operations in enum order whether or not any
    endpoint performs them, so an empty list is a stated "no endpoint", and an
    entity no endpoint reaches is a row of six empty lists (Q6) rather than a
    missing row.
    """

    service_id: str
    entity: str | None = Field(
        description="Qualified type name; None = this service's undetermined-entity bucket"
    )
    name: str = Field(description="Simple name; 'entity not determined' for the None row")
    data_model_id: str | None = Field(pattern=_DM_ID)
    storage_name: str | None
    declared_by: EntityDeclaredBy | None = Field(
        description="None when no data model declares the entity (or the bucket row)"
    )
    operations: list[EntityOperationUsage] = Field(
        description="All six operations, in enum order; lists may be empty"
    )


class EntityUsageService(WadiModel):
    """One service as the reverse view lists it, with its accounting."""

    service_id: str
    service_name: str
    accounting: EntityAccessAccounting | None = Field(
        description="None = the service's boundary predates entity accounting"
    )


class EntityUsageView(WadiModel):
    """Which endpoints may create, read, update or delete each entity (§5.2.17).

    The reverse question, answered at read time by
    :func:`build_entity_usage_view` from a projection of the endpoint
    documents and one read of the snapshot's data models. Nothing is stored
    for it.

    ``analyzed=False`` means no endpoint of the snapshot carries entity facts:
    it predates the phase, and ``entities`` is empty because nothing was
    looked at, not because nothing is touched (R1-6).
    """

    snapshot_id: str
    analyzed: bool = Field(
        description="False when no endpoint row has entity_access — the snapshot predates it"
    )
    endpoints_predating: int = Field(ge=0, description="Endpoint rows whose entity_access is None")
    entities: list[EntityUsageRow] = Field(
        description="Sorted by service_id, then name; [] when analyzed is False"
    )
    services: list[EntityUsageService]


UNDETERMINED_ENTITY_NAME = "entity not determined"
"""The display name of a service's undetermined-entity row in the reverse view."""

_SIMPLE_NAME_SPLIT = re.compile(r"[.$]")


@dataclass
class _UsageRecord:
    """One EntityUsageRow while the fold is still adding endpoints to it."""

    service_id: str
    entity: str | None
    name: str
    data_model_id: str | None
    storage_name: str | None = None
    declared_by: EntityDeclaredBy | None = None
    endpoints: dict[EntityOperation, dict[str, EntityUsageEndpoint]] = field(
        default_factory=dict[EntityOperation, dict[str, EntityUsageEndpoint]]
    )

    def add(self, row: EndpointEntityAccessRow, summary: EndpointEntityAccess) -> None:
        for operation in summary.operations:
            listed = self.endpoints.setdefault(operation, {})
            prior = listed.get(row.endpoint_id)
            listed[row.endpoint_id] = EntityUsageEndpoint(
                endpoint_id=row.endpoint_id,
                http_method=row.http_method,
                full_uri=row.full_uri,
                call_sites=summary.call_sites + (prior.call_sites if prior else 0),
            )

    def build(self) -> EntityUsageRow:
        return EntityUsageRow(
            service_id=self.service_id,
            entity=self.entity,
            name=self.name,
            data_model_id=self.data_model_id,
            storage_name=self.storage_name,
            declared_by=self.declared_by,
            operations=[
                EntityOperationUsage(
                    operation=operation,
                    endpoints=sorted(
                        self.endpoints.get(operation, {}).values(),
                        key=lambda e: (e.full_uri, e.http_method.value, e.endpoint_id),
                    ),
                )
                for operation in EntityOperation
            ],
        )


def summarize_entity_access(sites: Iterable[EntityAccessSite]) -> list[EndpointEntityAccess]:
    """Fold an endpoint's call sites into its per-entity summary rows (§5.2.17).

    Accesses group by ``(entity, data_model_id)`` exactly as the sites wrote
    them; the fold never decides that two spellings are one entity. Each row's
    ``operations`` is the set of operations its accesses carry, in enum order,
    and ``call_sites`` counts the sites that contributed — a site touching one
    entity twice (a delete whose subquery reads the same table) counts once,
    because sites are counted as sites and accesses as accesses (R1-2).

    Every element of ``sites`` is one call site. An ICFG holds each statement
    once and each statement lists each of its calls once, so the caller passes
    the sites as the graph holds them; two identical calls on two lines are two
    sites, which is why nothing here de-duplicates by value.

    ``create-or-update`` is never merged into ``create`` or ``update``, and the
    two never merge into it (R1-5): each is a separate claim about separate
    saves. ``candidate_operation`` is evidence and never reaches a row (R1-11).

    Rows are sorted by entity with the undetermined row last, then by
    ``data_model_id`` with ``None`` last, so the result is deterministic. An
    endpoint with no sites folds to ``[]``: analyzed, no repository call found,
    which ``None`` on the endpoint must never be confused with (R1-6).
    """
    operations: dict[tuple[str | None, str | None], set[EntityOperation]] = {}
    site_counts: dict[tuple[str | None, str | None], int] = {}
    for site in sites:
        touched: set[tuple[str | None, str | None]] = set()
        for access in site.accesses:
            key = (access.entity, access.data_model_id)
            operations.setdefault(key, set()).add(access.operation)
            touched.add(key)
        for key in touched:
            site_counts[key] = site_counts.get(key, 0) + 1
    return [
        EndpointEntityAccess(
            entity=entity,
            data_model_id=model_id,
            operations=sorted(operations[(entity, model_id)], key=_OPERATION_ORDER.__getitem__),
            call_sites=site_counts[(entity, model_id)],
        )
        for entity, model_id in sorted(operations, key=_none_last_key)
    ]


def _none_last_key(key: tuple[str | None, str | None]) -> tuple[bool, str, bool, str]:
    entity, model_id = key
    return (entity is None, entity or "", model_id is None, model_id or "")


def build_entity_usage_view(
    snapshot_id: str,
    rows: Iterable[EndpointEntityAccessRow],
    data_models: "Iterable[DataModel]",
    services: Iterable[EntityUsageService],
) -> EntityUsageView:
    """Fold endpoint summaries into the per-entity reverse view (§5.2.17).

    The one composition of the reverse question (R1-22): the orchestrator's
    ``/entities`` route and the MCP ``entity_usage`` tool both call this, so
    "which endpoints may update ``Order``" cannot be counted two ways.

    An entity is scoped to its service. The rows are:

    * one per :class:`~wadi_contracts.datamodel.DataModel`, so a declared
      entity no endpoint reaches is a row of six empty lists (Q6). Its entity
      is the model's ``type_full_name``, or its simple ``entity`` name on a
      model written from a pre-2.14.0 export, the same fallback
      ``data_model_id`` takes;
    * one per entity an access names that no data model declares;
    * one ``entity=None`` row per service that has undetermined accesses.

    A summary row joins the data model whose id it carries, else the row of
    its own service and entity. An endpoint whose summary lands on one row
    twice (one type written with and without its model id) is listed once,
    with the call sites of both. Under each operation the endpoints sort by
    ``full_uri``, then ``http_method``.

    If every endpoint row's ``entity_access`` is ``None`` — or there are no
    rows — no endpoint was examined: ``analyzed`` is False and ``entities``
    is empty, because listing the data models as unreached would turn "not
    looked at" into "touched by nothing" (R1-6). ``endpoints_predating``
    counts the ``None`` rows either way, so a partly re-analyzed snapshot says
    how much of it predates the phase.
    """
    endpoint_rows = list(rows)
    listed_services = sorted(services, key=lambda s: (s.service_name, s.service_id))
    predating = sum(1 for row in endpoint_rows if row.entity_access is None)
    if predating == len(endpoint_rows):
        return EntityUsageView(
            snapshot_id=snapshot_id,
            analyzed=False,
            endpoints_predating=predating,
            entities=[],
            services=listed_services,
        )

    records: dict[tuple[str, str | None], _UsageRecord] = {}
    by_model_id: dict[str, tuple[str, str | None]] = {}
    for model in data_models:
        key = (model.service_id, model.type_full_name or model.entity)
        records.setdefault(
            key,
            _UsageRecord(
                service_id=model.service_id,
                entity=key[1],
                name=model.entity,
                data_model_id=model.id,
                storage_name=model.storage_name,
                declared_by=model.declared_by,
            ),
        )
        by_model_id.setdefault(model.id, key)

    for row in endpoint_rows:
        for summary in row.entity_access or []:
            key = by_model_id.get(summary.data_model_id or "") or (row.service_id, summary.entity)
            record = records.get(key)
            if record is None:
                record = records[key] = _UsageRecord(
                    service_id=key[0],
                    entity=key[1],
                    name=_simple_name(key[1]),
                    data_model_id=summary.data_model_id,
                )
            record.add(row, summary)

    return EntityUsageView(
        snapshot_id=snapshot_id,
        analyzed=True,
        endpoints_predating=predating,
        entities=[
            record.build()
            for record in sorted(
                records.values(),
                key=lambda r: (r.service_id, r.name, r.entity or "", r.data_model_id or ""),
            )
        ],
        services=listed_services,
    )


def _simple_name(entity: str | None) -> str:
    if entity is None:
        return UNDETERMINED_ENTITY_NAME
    return _SIMPLE_NAME_SPLIT.split(entity)[-1]
