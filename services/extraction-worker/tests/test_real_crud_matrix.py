"""Cross-language golden for entity access per endpoint (§5.2.17).

Consumes the REAL sbt-produced `spring-data-crud-matrix` and `save-origin-mini`
exports and assembles them with the worker's `Assembler`, proving the chain end
to end: the Scala pass describes each repository call (export 2.15.0 `db`
rows), and the worker turns that into per-node sites, a per-endpoint summary
and a per-service accounting.

The unit tests in `test_entity_classification.py` and
`test_assembler_entity_access.py` pin the rules against synthetic rows. This
pins them against what Joern actually produces from Java source, one golden
per endpoint: the plan's 36 (R1-18), the rigor review's 15 hardening shapes
(37-51) and the pre-landing review's two statements that make a repository
call and an HTTP call (52, 53), so a golden that drifts names itself in the
test id.

Both gate states run (rule 5): the shipped table, where every save publishes
`create-or-update` and keeps its candidate as evidence (R1-11), and all four
flags on and scored against the export's own rules version, where the candidate
is what publishes. Goldens 7-13 and 31 carry a query, and the query reader
(M6) publishes what its text states on the `query-text` basis, which no flag
gates. A query it does not read (Mongo JSON, a named query that did not
resolve) stays `unknown` on the repository's own entity.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest

from wadi_contracts import (
    DataModel,
    Endpoint,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityDeclaredBy,
    EntityOperation,
    HttpMethod,
    Icfg,
    IcfgNode,
    SinkKind,
)
from wadi_joern_client.export import ExportSink, ServiceExport
from wadi_worker.assembler import AssembledArtifacts, Assembler
from wadi_worker.entity_access import SHIPPED_GATE_FLAGS, GateFlag, export_rules_version

TARGET = Path(__file__).resolve().parents[3] / "joern-platform" / "target"
CRUD_MATRIX_EXPORT = TARGET / "spring-data-crud-matrix-export" / "export.json"
SAVE_ORIGIN_EXPORT = TARGET / "save-origin-mini-export" / "export.json"

requires_crud_matrix = pytest.mark.skipif(
    not CRUD_MATRIX_EXPORT.exists(),
    reason="spring-data-crud-matrix export not present — run `sbt test` in joern-platform first",
)
requires_save_origin = pytest.mark.skipif(
    not SAVE_ORIGIN_EXPORT.exists(),
    reason="save-origin-mini export not present — run `sbt test` in joern-platform first",
)

# Table shorthands: the operations in enum order, and the two save bases.
C, R, U, D = (
    EntityOperation.CREATE,
    EntityOperation.READ,
    EntityOperation.UPDATE,
    EntityOperation.DELETE,
)
CU, UNK = EntityOperation.CREATE_OR_UPDATE, EntityOperation.UNKNOWN
AO, EG = EntityAccessBasis.ARGUMENT_ORIGIN, EntityAccessBasis.EXISTENCE_GUARD

_SPLIT_FLAGS = ((AO, C), (AO, U), (EG, C), (EG, U))


def flags_on_scored_at(version: str) -> tuple[GateFlag, ...]:
    """Every (basis, verb) flag on, scored against ``version``.

    Since export 2.15.0 the rules version is per export: it hashes the
    export's ``save_origin_rules`` (review B4). A flag scored against the
    rules that run is scored against that export's version.
    """
    return tuple(GateFlag(basis, operation, True, version) for basis, operation in _SPLIT_FLAGS)


STALE_RULES_VERSION = "0000000000000000"
FLAGS_ON_STALE = flags_on_scored_at(STALE_RULES_VERSION)
"""The same four flags on, scored against rules that no longer run (E4)."""

_ACME = "com.acme.crud"
ORDER = f"{_ACME}.domain.Order"
ORDER_LINE = f"{_ACME}.domain.OrderLine"
PET = f"{_ACME}.domain.Pet"
ISSUE = f"{_ACME}.domain.Issue"
TICKET = f"{_ACME}.domain.Ticket"
CUSTOMER = f"{_ACME}.domain.Customer"
INVOICE = f"{_ACME}.domain.Invoice"
AUDIT_ENTRY = f"{_ACME}.domain.AuditEntry"
SHIPMENT = f"{_ACME}.domain.Shipment"
BILLING_ACCOUNT = f"{_ACME}.billing.Account"
CRM_ACCOUNT = f"{_ACME}.crm.Account"
TRIP = f"{_ACME}.domain.Trip"
PET_LOG = f"{_ACME}.domain.PetLog"
NOTE = f"{_ACME}.domain.Note"
AUDITED_ORDER = f"{_ACME}.domain.AuditedOrder"
COUPON = f"{_ACME}.domain.Coupon"

ORDER_REPO = f"{_ACME}.repo.OrderRepository"
ORDER_LINE_REPO = f"{_ACME}.repo.OrderLineRepository"
PET_REPO = f"{_ACME}.repo.PetRepository"
ISSUE_REPO = f"{_ACME}.repo.IssueRepository"
TICKET_REPO = f"{_ACME}.repo.TicketRepository"
CUSTOMER_REPO = f"{_ACME}.repo.CustomerRepository"
INVOICE_REPO = f"{_ACME}.repo.InvoiceRepository"
AUDIT_REPO = f"{_ACME}.repo.AuditEntryRepository"
BASE_REPO = f"{_ACME}.repo.BaseRepository"
BILLING_REPO = f"{_ACME}.billing.AccountRepository"
CRM_REPO = f"{_ACME}.repo.CrmAccountRepository"
TRIP_REPO = f"{_ACME}.repo.TripRepository"
PET_LOG_REPO = f"{_ACME}.repo.PetLogRepository"
NOTE_REPO = f"{_ACME}.repo.NoteRepository"
AUDITED_ORDER_REPO = f"{_ACME}.repo.AuditedOrderRepository"
COUPON_REPO = f"{_ACME}.repo.CouponRepository"
CRUD_REPOSITORY = "org.springframework.data.repository.CrudRepository"
JPA_REPOSITORY = "org.springframework.data.jpa.repository.JpaRepository"


# --- expectation shapes --------------------------------------------------------


class Access(NamedTuple):
    entity: str | None
    operation: EntityOperation
    candidate: EntityOperation | None = None


class Site(NamedTuple):
    """One `EntityAccessSite`, with the method it sits in.

    ``owner`` is `Class.method` for a call in a callee the ICFG inlines, and
    None for a call in the endpoint's own handler.
    """

    repository: str
    method: str
    basis: EntityAccessBasis
    accesses: tuple[Access, ...]
    entity_type_text: str | None = None
    owner: str | None = None


class Row(NamedTuple):
    """One `EndpointEntityAccess` row; its `data_model_id` is checked by join."""

    entity: str | None
    operations: tuple[EntityOperation, ...]
    call_sites: int


def named(
    operation: EntityOperation,
    method: str,
    entity: str | None = ORDER,
    repository: str = ORDER_REPO,
    *,
    owner: str | None = None,
) -> Site:
    """A site whose verb the method-name table decided (rule 2), or C3's
    `unknown` for a method with a body in the project."""
    basis = EntityAccessBasis.METHOD_NAME
    return Site(repository, method, basis, (Access(entity, operation),), owner=owner)


def saved(
    candidate: EntityOperation | None,
    method: str = "save",
    *,
    basis: EntityAccessBasis = AO,
    entity: str = ORDER,
    repository: str = ORDER_REPO,
    owner: str | None = None,
) -> Site:
    """A save as the shipped gate publishes it: `create-or-update`, with the
    split's candidate kept as evidence (rules 3-5)."""
    return Site(repository, method, basis, (Access(entity, CU, candidate),), owner=owner)


def queried(
    method: str, *accesses: Access, repository: str = ORDER_REPO, unread: str | None = None
) -> Site:
    """An annotated query method: its text decides and the name never does
    (R1-12). ``unread`` names the repository entity of a query the reader
    does not read, which stays `unknown` on it."""
    if unread is not None:
        accesses = (Access(unread, UNK),)
    return Site(repository, method, EntityAccessBasis.QUERY_TEXT, accesses)


def published_with_flags_on(site: Site) -> Site:
    """Rule 5 with every flag on and current: a candidate is what publishes."""
    return site._replace(
        accesses=tuple(
            Access(access.entity, access.candidate) if access.candidate is not None else access
            for access in site.accesses
        )
    )


@dataclass(frozen=True)
class Golden:
    number: int
    name: str
    verb: str
    sites: tuple[Site, ...]
    summary: tuple[Row, ...]
    summary_flags_on: tuple[Row, ...] | None = None
    """None: no gated candidate, so the flags change nothing here."""

    @property
    def route(self) -> tuple[str, str]:
        return (self.verb, f"/crud/{self.name}")

    @property
    def id(self) -> str:
        return f"{self.number:02d}-{self.name}"


GOLDENS: tuple[Golden, ...] = (
    Golden(1, "inherited-find-by-id", "GET", (named(R, "findById"),), (Row(ORDER, (R,), 1),)),
    Golden(
        2,
        "inherited-save-read-origin",
        "PUT",
        # Saving what the repository returned updates it (rule 3: read).
        (named(R, "findById"), saved(U)),
        (Row(ORDER, (R, CU), 2),),
        (Row(ORDER, (R, U), 2),),
    ),
    Golden(3, "inherited-delete", "DELETE", (named(D, "deleteById"),), (Row(ORDER, (D,), 1),)),
    Golden(4, "derived-find-by-status", "GET", (named(R, "findByStatus"),), (Row(ORDER, (R,), 1),)),
    Golden(5, "derived-delete-by", "DELETE", (named(D, "deleteByStatus"),), (Row(ORDER, (D,), 1),)),
    Golden(
        6,
        "derived-count-exists",
        "GET",
        (named(R, "countByStatus"), named(R, "existsByStatus")),
        (Row(ORDER, (R,), 2),),
    ),
    # Goldens 7-13 and 31: the query reader (M6) publishes the verb the text
    # states, and 9 and 31 name a second entity, each with its own operation
    # (rule 6, C1). Each expectation was checked against QUERY_FACTS below.
    Golden(
        7,
        "query-jpql-select",
        "GET",
        # select l from OrderLine l where l.sku = ?1
        (queried("findBySkuText", Access(ORDER_LINE, R), repository=ORDER_LINE_REPO),),
        (Row(ORDER_LINE, (R,), 1),),
    ),
    Golden(
        8,
        "query-jpql-update-modifying",
        "PUT",
        # update Order o set o.status = ?2 where o.id = ?1
        (queried("updateStatus", Access(ORDER, U)),),
        (Row(ORDER, (U,), 1),),
    ),
    Golden(
        9,
        "query-jpql-join-association",
        "GET",
        # select o from Order o join o.lines l: `lines` is List<OrderLine>.
        (queried("findContainingSku", Access(ORDER, R), Access(ORDER_LINE, R)),),
        (Row(ORDER, (R,), 1), Row(ORDER_LINE, (R,), 1)),
    ),
    Golden(
        10,
        "query-jpql-keyword-entity",
        "GET",
        # select o from Order o where ...: `Order` by position, not a keyword.
        (queried("findInStatus", Access(ORDER, R)),),
        (Row(ORDER, (R,), 1),),
    ),
    Golden(
        11,
        "query-native-table",
        "GET",
        # select * from orders ...: the table Order's @Table names.
        (
            queried("findNativeByStatus", Access(ORDER, R)),
            queried("findNativeConcatenated", Access(ORDER, R)),
        ),
        (Row(ORDER, (R,), 2),),
    ),
    Golden(
        12,
        "query-named",
        "GET",
        (
            queried("shipped", Access(ORDER, R)),
            queried("findOpen", Access(ISSUE, R), repository=ISSUE_REPO),
            # `Client` is Customer's @Entity(name=).
            queried("findVip", Access(CUSTOMER, R), repository=CUSTOMER_REPO),
            # A named NATIVE query on the `invoices` table.
            queried("sumOpen", Access(INVOICE, R), repository=INVOICE_REPO),
            # A name nothing declares: no text, so not read (P10).
            queried("undeclaredNamed", unread=ORDER),
        ),
        (
            Row(CUSTOMER, (R,), 1),
            Row(INVOICE, (R,), 1),
            Row(ISSUE, (R,), 1),
            Row(ORDER, (R, UNK), 2),
        ),
    ),
    Golden(
        13,
        "query-mongo-json",
        "GET",
        # A Mongo query is JSON: not read (R1-24).
        (queried("findByStatusJson", unread=PET, repository=PET_REPO),),
        (Row(PET, (UNK,), 1),),
    ),
    Golden(
        14,
        "base-interface-repository",
        "POST",
        # A repository only through a project base interface (Q10), and a
        # base that binds its entity by position, not by name.
        (
            named(R, "findById", ISSUE, ISSUE_REPO),
            named(R, "findAllByIdIn", ISSUE, ISSUE_REPO),
            named(R, "findById", TICKET, TICKET_REPO),
        ),
        (Row(ISSUE, (R,), 2), Row(TICKET, (R,), 1)),
    ),
    Golden(
        15,
        "save-constructed-no-lookup",
        "POST",
        (saved(C),),
        (Row(ORDER, (CU,), 1),),
        (Row(ORDER, (C,), 1),),
    ),
    Golden(
        16,
        "save-guard-not-found-arm",
        "POST",
        (named(R, "existsById"), saved(C, basis=EG)),
        (Row(ORDER, (R, CU), 2),),
        (Row(ORDER, (C, R), 2),),
    ),
    Golden(
        17,
        "save-guard-found-arm",
        "PUT",
        (named(R, "existsById"), saved(U, basis=EG)),
        (Row(ORDER, (R, CU), 2),),
        (Row(ORDER, (R, U), 2),),
    ),
    Golden(
        18,
        "save-guard-early-return",
        "POST",
        # The save is in no arm of the check: the arm decided nothing, so the
        # basis stays argument-origin and there is no candidate (B2).
        (named(R, "existsById"), saved(None)),
        (Row(ORDER, (R, CU), 2),),
    ),
    Golden(
        19,
        "save-upsert-by-branch",
        "PUT",
        (named(R, "findById"), saved(None)),
        (Row(ORDER, (R, CU), 2),),
    ),
    Golden(
        20,
        "save-parameter-callers-agree",
        "PUT",
        # Both callers pass a read object: the hop resolves it (rule 4).
        (named(R, "findById"), named(R, "findById"), saved(U, owner="OrderWriter.storeAgreed")),
        (Row(ORDER, (R, CU), 3),),
        (Row(ORDER, (R, U), 3),),
    ),
    Golden(
        21,
        "save-parameter-callers-disagree",
        "PUT",
        (named(R, "findById"), saved(None, owner="OrderWriter.storeDisagreed")),
        (Row(ORDER, (R, CU), 2),),
    ),
    Golden(
        22,
        "save-parameter-from-request-body",
        "POST",
        # Still a parameter after one hop (R1-27).
        (saved(None, owner="OrderWriter.storeBody"),),
        (Row(ORDER, (CU,), 1),),
    ),
    Golden(
        23,
        "save-via-helper-wrapper",
        "PUT",
        # The getter on the wrapper is `other`: the read is a method away.
        (named(R, "findById", owner="OrderLookup.loadEnvelope"), saved(None)),
        (Row(ORDER, (R, CU), 2),),
    ),
    Golden(
        24,
        "delete-then-save",
        "PUT",
        # A static factory constructs, and a delete is not a lookup.
        (named(D, "deleteById"), saved(C)),
        (Row(ORDER, (D, CU), 2),),
        (Row(ORDER, (C, D), 2),),
    ),
    Golden(
        25,
        "two-calls-one-statement",
        "PUT",
        (named(R, "findById"), saved(U)),
        (Row(ORDER, (R, CU), 2),),
        (Row(ORDER, (R, U), 2),),
    ),
    # The save sits in a lambda body: in the export, in no endpoint flow
    # (R1-1, A1). The endpoint reads "no repository call found" and the
    # service's accounting carries the call (TestGoldenShapes, TestAccounting).
    Golden(26, "save-in-lambda", "POST", (), ()),
    # The update by dirty checking is not claimed (Q2): only the read is.
    Golden(27, "dirty-checking-setter", "PUT", (named(R, "findById"),), (Row(ORDER, (R,), 1),)),
    Golden(28, "forwarding-endpoint", "PUT", (), ()),
    Golden(
        29,
        "repository-only-entity",
        "GET",
        (named(R, "findAll", AUDIT_ENTRY, AUDIT_REPO),),
        (Row(AUDIT_ENTRY, (R,), 1),),
    ),
    Golden(
        30,
        "unbindable-entity-chain",
        "GET",
        # The receiver is `BaseRepository<E>` itself: nothing binds E, so the
        # verb is read and the entity is undetermined (R1-4, P10).
        (named(R, "count", None, BASE_REPO, owner="AbstractArchiver.countAll"),),
        (Row(None, (R,), 1),),
    ),
    Golden(
        31,
        "query-delete-with-subquery",
        "DELETE",
        # delete from Invoice i where i.customer in (select c from Client c ...):
        # one site, two accesses, two operations (C1).
        (
            queried(
                "deleteForNonVip",
                Access(INVOICE, D),
                Access(CUSTOMER, R),
                repository=INVOICE_REPO,
            ),
        ),
        (Row(CUSTOMER, (R,), 1), Row(INVOICE, (D,), 1)),
    ),
    Golden(
        32,
        "repository-default-method",
        "PUT",
        (
            # Named like a finder, with a body in the project: unknown (C3).
            named(UNK, "findAndTouch"),
            # The default body's own calls are Spring Data's, and classify.
            named(R, "findById", owner="OrderRepository.findAndTouch"),
            saved(U, owner="OrderRepository.findAndTouch"),
        ),
        (Row(ORDER, (R, CU, UNK), 3),),
        (Row(ORDER, (R, U, UNK), 3),),
    ),
    Golden(
        33,
        "repository-custom-fragment",
        "POST",
        (named(UNK, "archiveOld"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        34,
        "inherited-method-table",
        "POST",
        # E5: the inherited CrudRepository / JpaRepository / MongoRepository
        # methods, each named by the verb table.
        (
            named(R, "findAll"),
            named(R, "findAllById"),
            named(R, "count"),
            named(R, "existsById"),
            named(R, "getReferenceById"),
            saved(U, "saveAll"),
            saved(U, "saveAndFlush"),
            saved(U, "saveAllAndFlush"),
            named(D, "deleteAllById"),
            named(D, "deleteAllInBatch"),
            named(D, "deleteAll"),
            # `MongoRepository.insert` never updates, so its name says create
            # and it never reaches the save split (review B8).
            named(C, "insert", PET, PET_REPO),
        ),
        (Row(ORDER, (R, D, CU), 11), Row(PET, (C,), 1)),
        (Row(ORDER, (R, U, D), 11), Row(PET, (C,), 1)),
    ),
    # flush() is not an entity operation: no site, counted on its own.
    Golden(35, "flush-not-an-operation", "POST", (), ()),
    Golden(
        36,
        "same-simple-name-two-packages",
        "GET",
        (
            named(R, "findById", BILLING_ACCOUNT, BILLING_REPO),
            named(R, "findById", CRM_ACCOUNT, CRM_REPO),
        ),
        (Row(BILLING_ACCOUNT, (R,), 1), Row(CRM_ACCOUNT, (R,), 1)),
    ),
    # --- the rigor review's hardening shapes (export 2.15.0) -------------------
    Golden(
        37,
        "marker-typed-receiver",
        "GET",
        # A field and a parameter typed `CrudRepository<Order, String>`: Spring
        # Data's own interface is the receiver, and its calls count (review A2).
        (
            named(R, "count", ORDER, CRUD_REPOSITORY, owner="MarkerTypedOrders.countOrders"),
            named(R, "existsById", ORDER, CRUD_REPOSITORY, owner="MarkerTypedOrders.existsIn"),
        ),
        (Row(ORDER, (R,), 2),),
    ),
    Golden(
        38,
        "marker-receiver-unbound-entity",
        "GET",
        # `JpaRepository<E, String>` in a class generic in E: counted, entity
        # undetermined, the type argument kept as written (R1-4).
        (
            Site(
                JPA_REPOSITORY,
                "findAll",
                EntityAccessBasis.METHOD_NAME,
                (Access(None, R),),
                entity_type_text="E",
                owner="GenericStore.all",
            ),
        ),
        (Row(None, (R,), 1),),
    ),
    Golden(
        39,
        "type-variable-receiver",
        "GET",
        # `R repository` where `R extends JpaRepository<Order, String>`: the
        # bound is the repository it is known to be (review A2).
        (named(R, "findAll", ORDER, JPA_REPOSITORY, owner="BoundedStore.all"),),
        (Row(ORDER, (R,), 1),),
    ),
    Golden(
        40,
        "marker-named-project-base",
        "GET",
        # `KeyedJpaRepository<ID, E>` only contains a marker's name; it is a
        # project interface, so `<TripId, Trip>` binds Trip by position (A4).
        (named(R, "findById", TRIP, TRIP_REPO),),
        (Row(TRIP, (R,), 1),),
    ),
    Golden(
        41,
        "marker-named-mongo-base",
        "GET",
        (named(R, "findAll", PET_LOG, PET_LOG_REPO),),
        (Row(PET_LOG, (R,), 1),),
    ),
    Golden(
        42,
        "redeclared-query-override",
        "GET",
        # The sub-interface redeclares the base's `search` with `@Query`; the
        # nearest declaration wins, so the text decides, not the name (A3).
        (queried("search", Access(NOTE, R), repository=NOTE_REPO),),
        (Row(NOTE, (R,), 1),),
    ),
    Golden(
        43,
        "arity-mismatch",
        "GET",
        # A project interface declares `findTagged`, no declaration matches the
        # call's arity, so its annotations were not read: unknown (A3).
        (named(UNK, "findTagged", NOTE, NOTE_REPO),),
        (Row(NOTE, (UNK,), 1),),
    ),
    Golden(
        44,
        "annotation-mongo-update",
        "PUT",
        # Mongo `@Update` on a `find...` name: the name would say read (B1).
        (named(UNK, "findAndIncrementVisitsByStatus", PET, PET_REPO),),
        (Row(PET, (UNK,), 1),),
    ),
    Golden(
        45,
        "annotation-procedure",
        "PUT",
        (named(UNK, "getArchivedCount"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        46,
        "annotation-aggregation",
        "GET",
        (named(UNK, "findStatusSummary", PET, PET_REPO),),
        (Row(PET, (UNK,), 1),),
    ),
    Golden(
        47,
        "annotation-native-query",
        "GET",
        # `@NativeQuery` is read exactly as a native `@Query`.
        (queried("findNativeAnnotated", Access(ORDER, R)),),
        (Row(ORDER, (R,), 1),),
    ),
    Golden(
        48,
        "annotation-neutral",
        "GET",
        # `@Transactional` and `@Lock` change no verb: the name decides.
        (named(R, "findFirstByStatus"),),
        (Row(ORDER, (R,), 1),),
    ),
    Golden(
        49,
        "annotation-project-meta-query",
        "GET",
        # A project annotation meta-annotated with `@Query`: the export carries
        # no text for it, so nothing read decides (B1).
        (named(UNK, "openOrders"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        50,
        "query-native-schema-table",
        "GET",
        # `audit.orders` binds the entity that declares `schema = "audit"`, and
        # golden 11's unqualified `orders` keeps binding Order (B2).
        (queried("findAuditedByStatus", Access(AUDITED_ORDER, R), repository=AUDITED_ORDER_REPO),),
        (Row(AUDITED_ORDER, (R,), 1),),
    ),
    Golden(
        51,
        "soft-delete-entity",
        "DELETE",
        # `@SQLDelete` on Coupon: `deleteById` runs that statement instead (B1).
        (named(UNK, "deleteById", COUPON, COUPON_REPO),),
        (Row(COUPON, (UNK,), 1),),
    ),
    # --- the pre-landing review's mixed statements (§5.2.17) -------------------
    # One statement, a repository call and an HTTP call nested each way. Each
    # call is a site or a remote call by its own row's kind, whichever of the
    # two is the node's primary call (TestGoldenShapes pins the remote calls).
    Golden(
        52,
        "http-wraps-repository",
        "POST",
        # The read is the HTTP call's argument (pre-landing review #1).
        (named(R, "findById"),),
        (Row(ORDER, (R,), 1),),
    ),
    Golden(
        53,
        "repository-wraps-http",
        "POST",
        # What an HTTP call returned is `other`, so no candidate (review #2).
        (saved(None),),
        (Row(ORDER, (CU,), 1),),
    ),
)

GOLDEN_IDS = [golden.id for golden in GOLDENS]


# --- assembly ------------------------------------------------------------------


@dataclass(frozen=True)
class Assembled:
    export: ServiceExport
    artifacts: AssembledArtifacts

    def endpoint(self, route: tuple[str, str]) -> Endpoint:
        matches = [
            e for e in self.artifacts.endpoints if (e.http_method.value, e.full_uri) == route
        ]
        assert len(matches) == 1, f"{route}: {len(matches)} endpoints"
        return matches[0]

    def icfg(self, route: tuple[str, str]) -> Icfg:
        endpoint_id = self.endpoint(route).id
        return next(icfg for icfg in self.artifacts.icfgs if icfg.endpoint_id == endpoint_id)

    @property
    def accounting(self) -> EntityAccessAccounting:
        accounting = self.artifacts.entity_access_accounting
        assert accounting is not None, "a 2.14.0 export must produce an accounting"
        return accounting

    @property
    def models(self) -> dict[str, DataModel]:
        return {m.type_full_name: m for m in self.artifacts.data_models if m.type_full_name}

    def db_rows(self) -> list[ExportSink]:
        return [sink for sink in self.export.sinks if sink.kind == "db"]

    def owner_of(self, sink: ExportSink) -> str:
        method = next(m for m in self.export.methods if m.id == sink.method_id)
        return _owner(method.full_name)


def _assemble(path: Path, gate_flags: tuple[GateFlag, ...] | None) -> Assembled:
    """Assemble one real export; ``gate_flags=None`` is every flag on and current."""
    export = ServiceExport.model_validate(json.loads(path.read_text()))
    if gate_flags is None:
        gate_flags = flags_on_scored_at(export_rules_version(export))
    artifacts = Assembler(
        snapshot_id="snap_crudmatrix",
        service_id="svc_" + "c" * 16,
        gate_flags=gate_flags,
    ).assemble(export)
    return Assembled(export=export, artifacts=artifacts)


def _owner(full_name: str) -> str:
    """`com.acme.crud.web.SaveController.save:…` → `SaveController.save`."""
    return ".".join(full_name.split(":", 1)[0].rsplit(".", 2)[-2:])


def sites_of(icfg: Icfg) -> list[Site]:
    handler = icfg.root_entry().method.id
    return [
        Site(
            repository=site.repository,
            method=site.method_name,
            basis=site.basis,
            accesses=tuple(
                Access(access.entity, access.operation, access.candidate_operation)
                for access in site.accesses
            ),
            entity_type_text=site.entity_type_text,
            owner=None if node.method.id == handler else _owner(node.method.signature),
        )
        for node in icfg.nodes
        for site in node.entity_access_sites
    ]


def summary_of(endpoint: Endpoint) -> tuple[Row, ...]:
    assert endpoint.entity_access is not None, "analyzed at 2.14.0: [] or rows, never None"
    return tuple(
        Row(row.entity, tuple(row.operations), row.call_sites) for row in endpoint.entity_access
    )


def _multiset(sites: list[Site] | tuple[Site, ...]) -> list[Site]:
    return sorted(sites, key=repr)


@pytest.fixture(scope="module")
def shipped() -> Assembled:
    return _assemble(CRUD_MATRIX_EXPORT, SHIPPED_GATE_FLAGS)


@pytest.fixture(scope="module")
def flags_on() -> Assembled:
    return _assemble(CRUD_MATRIX_EXPORT, None)


# --- per golden ----------------------------------------------------------------


@requires_crud_matrix
class TestGoldenAsShipped:
    """Every gate flag off, as 0.9.0 ships (§5.2.17)."""

    def test_the_fixture_has_exactly_the_goldens(self, shipped: Assembled) -> None:
        routes = {(e.http_method.value, e.full_uri) for e in shipped.artifacts.endpoints}
        assert routes == {golden.route for golden in GOLDENS}

    @pytest.mark.parametrize("golden", GOLDENS, ids=GOLDEN_IDS)
    def test_sites(self, shipped: Assembled, golden: Golden) -> None:
        assert _multiset(sites_of(shipped.icfg(golden.route))) == _multiset(golden.sites)

    @pytest.mark.parametrize("golden", GOLDENS, ids=GOLDEN_IDS)
    def test_summary(self, shipped: Assembled, golden: Golden) -> None:
        assert summary_of(shipped.endpoint(golden.route)) == golden.summary


@requires_crud_matrix
class TestGoldenFlagsOn:
    """All four flags on and current: each save publishes its candidate."""

    @pytest.mark.parametrize("golden", GOLDENS, ids=GOLDEN_IDS)
    def test_sites(self, flags_on: Assembled, golden: Golden) -> None:
        expected = [published_with_flags_on(site) for site in golden.sites]
        assert _multiset(sites_of(flags_on.icfg(golden.route))) == _multiset(expected)

    @pytest.mark.parametrize("golden", GOLDENS, ids=GOLDEN_IDS)
    def test_summary(self, flags_on: Assembled, golden: Golden) -> None:
        expected = golden.summary_flags_on or golden.summary
        assert summary_of(flags_on.endpoint(golden.route)) == expected

    def test_a_flag_scored_on_stale_rules_publishes_nothing(self) -> None:
        # E4: a flag is the score of one rules version. On for any other, it
        # leaves every save at create-or-update, and the accounting records
        # the flag as configured so the staleness is visible.
        stale = _assemble(CRUD_MATRIX_EXPORT, FLAGS_ON_STALE)
        for golden in GOLDENS:
            actual = _multiset(sites_of(stale.icfg(golden.route)))
            assert actual == _multiset(golden.sites), golden.id
        flags = {(f.enabled, f.scored_rules_version) for f in stale.accounting.gate_flags}
        assert flags == {(True, STALE_RULES_VERSION)}
        assert stale.accounting.create_or_update == 18


# --- goldens whose claim is not only a site list -------------------------------


@requires_crud_matrix
class TestGoldenShapes:
    def test_25_two_calls_one_statement_are_two_sites_on_one_node(self, shipped: Assembled) -> None:
        # R1-2: the accounting unit is the call, so `save(findById(id)...)`
        # is two sites on the one flow node of its statement.
        icfg = shipped.icfg(("PUT", "/crud/two-calls-one-statement"))
        carrying = [node for node in icfg.nodes if node.entity_access_sites]
        assert len(carrying) == 1
        methods = sorted(site.method_name for site in carrying[0].entity_access_sites)
        assert methods == ["findById", "save"]

    def test_26_save_in_lambda_is_in_the_export_and_in_no_endpoint_flow(
        self, shipped: Assembled
    ) -> None:
        in_lambdas = [row for row in shipped.db_rows() if "<lambda>" in shipped.owner_of(row)]
        assert [(shipped.owner_of(r), r.db and r.db.method_name) for r in in_lambdas] == [
            ("SaveController.<lambda>0", "save")
        ]
        node_key = f"m{in_lambdas[0].method_id}:n{in_lambdas[0].node_id}"
        assert all(node.id != node_key for icfg in shipped.artifacts.icfgs for node in icfg.nodes)
        # Analyzed and empty: "no repository call found", not "predates" (R1-6).
        assert shipped.endpoint(("POST", "/crud/save-in-lambda")).entity_access == []
        # The accounting is what keeps the call from vanishing (R1-1).
        assert shipped.accounting.in_no_endpoint_flow == 1

    def test_28_forwarding_endpoint_touches_no_repository_and_makes_a_remote_call(
        self, shipped: Assembled
    ) -> None:
        # Q26: the data lives behind the service it calls. The summary is []
        # and the remote call is what a reader follows instead.
        route = ("PUT", "/crud/forwarding-endpoint")
        assert shipped.endpoint(route).entity_access == []
        assert any(node.remote_call_ids for node in shipped.icfg(route).nodes)

    def test_52_an_http_call_wrapping_a_repository_call_is_one_remote_call(
        self, shipped: Assembled
    ) -> None:
        # Pre-landing review #1: the db row beside the HTTP row is a site, not
        # a second URL candidate. Read as one, it put an `<undetermined>`
        # remote-call id on the node with no RemoteCall behind it.
        node = _sink_node(shipped, ("POST", "/crud/http-wraps-repository"))
        assert node.sink is SinkKind.HTTP_CLIENT
        assert _remote_calls_of(shipped, node) == [
            (HttpMethod.POST, "http://ts-order-service:12346/api/v1/orders")
        ]
        assert [site.method_name for site in node.entity_access_sites] == ["findById"]

    def test_53_an_http_call_inside_a_repository_call_is_still_a_remote_call(
        self, shipped: Assembled
    ) -> None:
        # Pre-landing review #2: the save is the primary call, and the HTTP
        # call whose result it saves is an outbound call all the same.
        node = _sink_node(shipped, ("POST", "/crud/repository-wraps-http"))
        assert node.sink is SinkKind.DB
        assert _remote_calls_of(shipped, node) == [
            (HttpMethod.GET, "http://ts-order-service:12346/api/v1/orders/{?}")
        ]
        assert [site.method_name for site in node.entity_access_sites] == ["save"]

    def test_every_remote_call_id_on_a_node_names_a_remote_call(self, shipped: Assembled) -> None:
        published = {call.id for call in shipped.artifacts.remote_calls}
        dangling = {
            rc_id
            for icfg in shipped.artifacts.icfgs
            for node in icfg.nodes
            for rc_id in node.remote_call_ids
            if rc_id not in published
        }
        assert dangling == set()

    def test_29_repository_only_entity_gets_its_own_record(self, shipped: Assembled) -> None:
        # Q1: no @Entity and no @Document, so the repository's type argument
        # is the only thing that names it an entity.
        record = shipped.models[AUDIT_ENTRY]
        assert record.declared_by is EntityDeclaredBy.REPOSITORY_ARGUMENT
        (row,) = shipped.endpoint(("GET", "/crud/repository-only-entity")).entity_access or []
        assert row.data_model_id == record.id

    def test_35_flush_is_a_db_call_with_no_site(self, shipped: Assembled) -> None:
        route = ("POST", "/crud/flush-not-an-operation")
        db_nodes = [node for node in shipped.icfg(route).nodes if node.sink is not None]
        assert [node.sink.value for node in db_nodes if node.sink] == ["db"]
        assert all(not node.entity_access_sites for node in db_nodes)
        assert shipped.endpoint(route).entity_access == []

    def test_36_same_simple_name_is_two_entities(self, shipped: Assembled) -> None:
        # C2: each `Account` resolves through its repository's own file, and
        # the two records are two ids.
        billing, crm = shipped.models[BILLING_ACCOUNT].id, shipped.models[CRM_ACCOUNT].id
        rows = shipped.endpoint(("GET", "/crud/same-simple-name-two-packages")).entity_access
        assert [row.data_model_id for row in rows or []] == [billing, crm]
        assert billing != crm

    def test_every_access_names_its_entity_record(self, shipped: Assembled) -> None:
        # B2/B3: a resolved entity carries the dm_ id of its record; an
        # undetermined one carries neither.
        models = shipped.models
        for icfg in shipped.artifacts.icfgs:
            for node in icfg.nodes:
                for site in node.entity_access_sites:
                    for access in site.accesses:
                        expected = models[access.entity].id if access.entity else None
                        assert access.data_model_id == expected, (node.id, site.method_name)
        for endpoint in shipped.artifacts.endpoints:
            for row in endpoint.entity_access or []:
                expected = models[row.entity].id if row.entity else None
                assert row.data_model_id == expected, endpoint.full_uri


def _sink_node(assembled: Assembled, route: tuple[str, str]) -> IcfgNode:
    """The one node of the endpoint's graph that carries a sink."""
    (node,) = [node for node in assembled.icfg(route).nodes if node.sink is not None]
    return node


def _remote_calls_of(assembled: Assembled, node: IcfgNode) -> list[tuple[HttpMethod | None, str]]:
    """The node's remote calls as (verb, url); a dangling id fails the lookup."""
    calls = {call.id: call for call in assembled.artifacts.remote_calls}
    return [(calls[rc].http_verb, calls[rc].url or "") for rc in node.remote_call_ids]


# --- the service's accounting --------------------------------------------------


@requires_crud_matrix
class TestAccounting:
    def test_as_shipped(self, shipped: Assembled) -> None:
        accounting = shipped.accounting
        assert accounting.model_dump(mode="json", exclude={"gate_flags"}) == {
            # 84, and goldens 52 and 53's repository calls: their HTTP calls
            # are remote calls, never sites.
            "call_sites": 86,
            # Partition 1: the lambda save (golden 26) is the one outside.
            "in_endpoint_flow": 85,
            "in_no_endpoint_flow": 1,
            # Partition 2, first match wins.
            "flush": 1,  # golden 35
            "implemented_in_project": 2,  # goldens 32 and 33
            "entity_undetermined": 2,  # goldens 30 and 38
            # The two queries the reader does not read (golden 12's undeclared
            # named query, golden 13's Mongo JSON), and the six hardening calls
            # whose verb nothing read decides: 43, 44, 45, 46, 49, 51.
            "unknown_operation": 8,
            # Every save-family call, the lambda's included; 34's insert is a
            # create by its name now (review B8), so not among them. Golden
            # 53's save joins them.
            "create_or_update": 18,
            # 44, golden 34's insert, the nine bound hardening sites: 37 (two),
            # 39, 40, 41, 42, 47, 48, 50, and golden 52's findById.
            "bound": 55,
            # 87 accesses over 85 sites: goldens 9 and 31 name two entities.
            "accesses_by_operation": {
                "create": 1,  # golden 34's insert
                "read": 50,  # 28 + 7 + golden 52 by name, 11 + 3 by query text
                "update": 1,  # golden 8
                "delete": 7,  # 6 by name, golden 31's Invoice
                "create-or-update": 18,  # golden 53 among them
                # Goldens 32 and 33 (C3), the two unread queries, the six above.
                "unknown": 10,
            },
            "sites_by_basis": {
                "method-name": 51,  # golden 52's findById among them
                "query-text": 16,
                "argument-origin": 16,  # golden 53's save among them
                "existence-guard": 2,
            },
            "rules_version": export_rules_version(shipped.export),
        }
        assert [(f.basis, f.operation, f.enabled) for f in accounting.gate_flags] == [
            (AO, C, False),
            (AO, U, False),
            (EG, C, False),
            (EG, U, False),
        ]
        _assert_partitions_sum(accounting)

    def test_flags_on(self, flags_on: Assembled) -> None:
        accounting = flags_on.accounting
        # Six saves have no candidate (goldens 18, 19, 21, 22, 23 and 53) and
        # stay create-or-update; the other twelve publish a single verb.
        assert (accounting.create_or_update, accounting.bound) == (6, 67)
        assert accounting.accesses_by_operation == {
            "create": 5,  # goldens 15, 16, 24, 26, and 34's insert by its name
            "read": 50,
            "update": 9,  # goldens 2, 17, 20, 25, 32 and 34's three saves, and 8's query
            "delete": 7,
            "create-or-update": 6,
            "unknown": 10,
        }
        flags = {(f.enabled, f.scored_rules_version) for f in accounting.gate_flags}
        assert flags == {(True, export_rules_version(flags_on.export))}
        _assert_partitions_sum(accounting)

    def test_every_db_row_carries_its_facts(self, shipped: Assembled) -> None:
        # A 2.14.0 db row without `db` would be counted entity_undetermined
        # with no site (T4); the Scala pass must never emit one.
        rows = shipped.db_rows()
        assert len({row.call_id for row in rows}) == 86
        assert [row.call_id for row in rows if row.db is None] == []


def _assert_partitions_sum(accounting: EntityAccessAccounting) -> None:
    assert accounting.in_endpoint_flow + accounting.in_no_endpoint_flow == accounting.call_sites
    assert (
        accounting.flush
        + accounting.implemented_in_project
        + accounting.entity_undetermined
        + accounting.unknown_operation
        + accounting.create_or_update
        + accounting.bound
    ) == accounting.call_sites


# --- raw facts across the boundary ---------------------------------------------


SAVE_FACTS: dict[tuple[str, str], tuple[str, bool, str, tuple[str, ...]]] = {
    # (owner, method): (argument_origin, lookup_same_repository, guard_arm, caller_origins)
    ("SaveController.inheritedSaveReadOrigin", "save"): ("read", True, "none", ()),
    ("SaveController.saveConstructedNoLookup", "save"): ("constructed", False, "none", ()),
    ("SaveController.saveGuardNotFoundArm", "save"): ("constructed", True, "not-found", ()),
    ("SaveController.saveGuardFoundArm", "save"): ("constructed", True, "found", ()),
    ("SaveController.saveGuardEarlyReturn", "save"): ("constructed", True, "none", ()),
    ("SaveController.saveUpsertByBranch", "save"): ("mixed", True, "none", ()),
    ("OrderWriter.storeAgreed", "save"): ("parameter", False, "none", ("read", "read")),
    ("OrderWriter.storeDisagreed", "save"): ("parameter", False, "none", ("read", "constructed")),
    ("OrderWriter.storeBody", "save"): ("parameter", False, "none", ("parameter",)),
    ("SaveController.saveViaHelperWrapper", "save"): ("other", False, "none", ()),
    ("SaveController.deleteThenSave", "save"): ("constructed", False, "none", ()),
    ("SaveController.twoCallsOneStatement", "save"): ("read", True, "none", ()),
    ("SaveController.<lambda>0", "save"): ("constructed", False, "none", ()),
    ("OrderRepository.findAndTouch", "save"): ("read", True, "none", ()),
    ("InheritedAndDerivedController.inheritedMethodTable", "saveAll"): ("read", True, "none", ()),
    ("InheritedAndDerivedController.inheritedMethodTable", "saveAndFlush"): (
        "read",
        True,
        "none",
        (),
    ),
    ("InheritedAndDerivedController.inheritedMethodTable", "saveAllAndFlush"): (
        "read",
        True,
        "none",
        (),
    ),
    ("InheritedAndDerivedController.inheritedMethodTable", "insert"): (
        "constructed",
        False,
        "none",
        (),
    ),
    # Golden 53: the saved object is what an HTTP call returned.
    ("MixedSinkController.repositoryWrapsHttp", "save"): ("other", False, "none", ()),
}
"""Rule 3's inputs as the Scala pass wrote them (export 2.14.0, A1). When a
candidate moves, this says whether the fact or the rule did."""

QUERY_FACTS: dict[str, tuple[str | None, bool, str | None, bool]] = {
    # method: (text, native, named_ref, modifying). M6 reads these (R1-24).
    "findBySkuText": ("select l from OrderLine l where l.sku = ?1", False, None, False),
    "updateStatus": ("update Order o set o.status = ?2 where o.id = ?1", False, None, True),
    "findContainingSku": (
        "select o from Order o join o.lines l where l.sku = ?1",
        False,
        None,
        False,
    ),
    "findInStatus": ("select o from Order o where o.status = ?1", False, None, False),
    "findNativeByStatus": ("select * from orders where status = ?1", True, None, False),
    # The long-query idiom: a concatenation, read as one string.
    "findNativeConcatenated": (
        "select * from orders where status = ?1 and id = ?2",
        True,
        None,
        False,
    ),
    "shipped": (
        "select o from Order o where o.status = 'SHIPPED'",
        False,
        "Order.findShipped",
        False,
    ),
    "findOpen": ("select i from Issue i where i.closed = false", False, "Issue.findOpen", False),
    # Implicit named query, keyed by the JPQL name `Client`, not `Customer`.
    "findVip": ("select c from Client c where c.vip = true", False, "Client.findVip", False),
    "sumOpen": (
        "select sum(amount) from invoices where paid = false",
        True,
        "Invoice.sumOpen",
        False,
    ),
    # A name nothing declares: the text stays unknown (P10).
    "undeclaredNamed": (None, False, "Order.notDeclaredAnywhere", False),
    # The hardening shapes: the sub-interface's redeclaration (A3), `@NativeQuery`
    # read as a native `@Query` (B1), and a schema-qualified table (B2).
    "search": ("select n from Note n where n.body like ?1", False, None, False),
    "findNativeAnnotated": ("select * from orders where status = ?1", True, None, False),
    "findAuditedByStatus": ("select * from audit.orders where status = ?1", True, None, False),
    "findByStatusJson": ("{ 'status': ?0 }", False, None, False),
    "deleteForNonVip": (
        "delete from Invoice i where i.customer in (select c from Client c where c.vip = false)",
        False,
        None,
        True,
    ),
}


@requires_crud_matrix
class TestRawFacts:
    def test_save_facts(self, shipped: Assembled) -> None:
        actual = {
            (shipped.owner_of(row), row.db.method_name): (
                row.db.save.argument_origin.value,
                row.db.save.lookup_same_repository,
                row.db.save.guard_arm.value,
                tuple(origin.value for origin in row.db.save.caller_origins),
            )
            for row in shipped.db_rows()
            if row.db is not None and row.db.save is not None
        }
        assert actual == SAVE_FACTS

    def test_query_facts(self, shipped: Assembled) -> None:
        actual = {
            row.db.method_name: (
                row.db.query.text,
                row.db.query.native,
                row.db.query.named_ref,
                row.db.query.modifying,
            )
            for row in shipped.db_rows()
            if row.db is not None and row.db.query is not None
        }
        assert actual == QUERY_FACTS

    def test_repository_kinds(self, shipped: Assembled) -> None:
        kinds = {r.db.repository: r.db.repository_kind.value for r in shipped.db_rows() if r.db}
        assert kinds[PET_REPO] == "mongo"
        # CrudRepository is store-agnostic: neither jpa nor mongo.
        assert kinds[AUDIT_REPO] == "other"
        assert {kinds[repo] for repo in (ORDER_REPO, ISSUE_REPO, TICKET_REPO, BASE_REPO)} == {"jpa"}

    def test_entity_records(self, shipped: Assembled) -> None:
        records = {
            name: (m.entity, m.declared_by, m.storage_name, m.jpql_name)
            for name, m in shipped.models.items()
            if m.storage_schema is None and m.delete_rewritten_by is None
        }
        by_annotation = EntityDeclaredBy.ANNOTATION
        assert records == {
            ORDER: ("Order", by_annotation, "orders", None),
            ORDER_LINE: ("OrderLine", by_annotation, None, None),
            PET: ("Pet", by_annotation, "pets", None),
            ISSUE: ("Issue", by_annotation, None, None),
            TICKET: ("Ticket", by_annotation, None, None),
            CUSTOMER: ("Customer", by_annotation, "customers", "Client"),
            INVOICE: ("Invoice", by_annotation, "invoices", None),
            # Declared, and reached by no endpoint (Q6).
            SHIPMENT: ("Shipment", by_annotation, "shipments", None),
            BILLING_ACCOUNT: ("Account", by_annotation, "billing_accounts", "BillingAccount"),
            CRM_ACCOUNT: ("Account", by_annotation, None, None),
            AUDIT_ENTRY: ("AuditEntry", EntityDeclaredBy.REPOSITORY_ARGUMENT, None, None),
            TRIP: ("Trip", by_annotation, "trips", None),
            PET_LOG: ("PetLog", by_annotation, "pet_logs", None),
            NOTE: ("Note", by_annotation, "notes", None),
        }
        reached = {row.entity for e in shipped.artifacts.endpoints for row in e.entity_access or []}
        assert SHIPMENT not in reached
        # 2.15.0's two entity facts, each on the one entity that carries it.
        # `TripId`, a key class, is no entity and gets no record (A4).
        assert {
            name: (m.storage_name, m.storage_schema, m.delete_rewritten_by)
            for name, m in shipped.models.items()
            if m.storage_schema is not None or m.delete_rewritten_by is not None
        } == {
            AUDITED_ORDER: ("orders", "audit", None),
            COUPON: ("coupons", None, "org.hibernate.annotations.SQLDelete"),
        }
        assert f"{_ACME}.domain.TripId" not in shipped.models

    def test_annotations_and_declaration_resolution(self, shipped: Assembled) -> None:
        # Export 2.15.0 (review B1, A3): what the classifier reads to refuse a
        # verb. Every row carries the list; a Spring-declared method's is empty.
        annotated = {
            row.db.method_name: tuple(row.db.method_annotations)
            for row in shipped.db_rows()
            if row.db is not None and row.db.method_annotations
        }
        spring = "org.springframework.data"
        assert annotated["findAndIncrementVisitsByStatus"] == (
            f"{spring}.mongodb.repository.Update",
        )
        assert annotated["getArchivedCount"] == (f"{spring}.jpa.repository.query.Procedure",)
        assert annotated["findStatusSummary"] == (f"{spring}.mongodb.repository.Aggregation",)
        assert annotated["findNativeAnnotated"] == (f"{spring}.jpa.repository.NativeQuery",)
        assert annotated["findFirstByStatus"] == (
            "org.springframework.transaction.annotation.Transactional",
            f"{spring}.jpa.repository.Lock",
        )
        meta = f"{_ACME}.repo.OpenOrdersQuery"
        assert f"{meta}>{spring}.jpa.repository.Query" in annotated["openOrders"]
        assert annotated["openOrders"][0] == meta
        unresolved = [
            r.db.method_name for r in shipped.db_rows() if r.db and not r.db.declaration_resolved
        ]
        assert unresolved == ["findTagged"]


# --- save-origin-mini: the save split's shapes ---------------------------------


class SaveShape(NamedTuple):
    """One save-origin-mini route and the one save its flow reaches."""

    uri: str
    basis: EntityAccessBasis
    candidate: EntityOperation | None
    owner: str | None = None
    method: str = "save"

    @property
    def id(self) -> str:
        return self.uri.removeprefix("/save/")


SAVE_SHAPES: tuple[SaveShape, ...] = (
    SaveShape("/save/guard/null-check-not-found", EG, C),
    # A found arm tested by `findByCode`, a lookup by a non-key field: a new
    # object saved there may well be an insert, so no candidate (review B5).
    SaveShape("/save/guard/not-null-found", AO, None),
    SaveShape("/save/guard/null-check-else-arm", AO, None),
    # The found arm of an identity lookup is the update it was written for.
    SaveShape("/save/guard/identity-is-present-found", EG, U),
    # A null test on a List or an Optional decides nothing (review A1).
    SaveShape("/save/guard/list-not-null-none", AO, None),
    SaveShape("/save/guard/optional-null-check-none", AO, None),
    SaveShape("/save/guard/is-present-local", EG, U),
    SaveShape("/save/guard/is-empty-chain", EG, C),
    SaveShape("/save/guard/exists-boolean-local", EG, C),
    SaveShape("/save/guard/no-braces-arm", EG, C),
    # The arm is not exactly the existence check's, so it decided nothing (B2).
    SaveShape("/save/guard/conjunction-none", AO, None),
    SaveShape("/save/guard/nested-loop-none", AO, None),
    # A check on another repository is no lookup on this one.
    SaveShape("/save/guard/other-repository-none", AO, C),
    SaveShape("/save/origin/orelse-constructed", AO, None),
    SaveShape("/save/origin/orelse-null", AO, U),
    SaveShape("/save/origin/to-builder", AO, None),
    SaveShape("/save/origin/reassigned-after-save", AO, U),
    SaveShape("/save/origin/parameter-reassigned", AO, U),
    SaveShape("/save/origin/ternary", AO, None),
    SaveShape("/save/origin/field", AO, None),
    SaveShape("/save/origin/cast", AO, None),
    # A new list is not a new entity.
    SaveShape("/save/origin/list-alloc-save-all", AO, None, method="saveAll"),
    SaveShape("/save/origin/subtype-constructed", AO, C),
    # A walk past depth 8 reports other, never a partial finding (review A5).
    SaveShape("/save/origin/deep-chain", AO, None),
    # Two reads on two paths, both inside the budget: read.
    SaveShape("/save/origin/budget-split", AO, U),
    # `searchByName` is a lookup (one prefix list, review B4), so a constructed
    # object beside it is no longer a plain create.
    SaveShape("/save/origin/search-lookup", AO, None),
    # The one caller hop: a caller outside the export does not count, and a
    # call through an interface reaches its DI-linked impl (R1-27).
    SaveShape("/save/origin/caller-outside-export", AO, U, "WidgetWriter.storeFromTwoPlaces"),
    SaveShape("/save/origin/di-interface-caller", AO, U, "WidgetServiceImpl.store"),
)
"""22 of the fixture's 23 saves. The 23rd is the lambda body of
`/save/origin/lambda-parameter-no-caller`, in no endpoint flow."""

_WIDGET = "com.acme.saves.domain.Widget"
_WIDGET_REPO = "com.acme.saves.repo.WidgetRepository"
_SAVE_FAMILY = {"save", "saveAll", "saveAndFlush", "saveAllAndFlush", "insert"}


def _save_sites(assembled: Assembled, uri: str) -> list[Site]:
    return [s for s in sites_of(assembled.icfg(("POST", uri))) if s.method in _SAVE_FAMILY]


@pytest.fixture(scope="module")
def save_origin() -> Assembled:
    return _assemble(SAVE_ORIGIN_EXPORT, SHIPPED_GATE_FLAGS)


@pytest.fixture(scope="module")
def save_origin_flags_on() -> Assembled:
    return _assemble(SAVE_ORIGIN_EXPORT, None)


@requires_save_origin
class TestSaveOriginMini:
    @pytest.mark.parametrize("shape", SAVE_SHAPES, ids=[shape.id for shape in SAVE_SHAPES])
    def test_save_candidate(
        self, save_origin: Assembled, save_origin_flags_on: Assembled, shape: SaveShape
    ) -> None:
        site = saved(
            shape.candidate,
            shape.method,
            basis=shape.basis,
            entity=_WIDGET,
            repository=_WIDGET_REPO,
            owner=shape.owner,
        )
        assert _save_sites(save_origin, shape.uri) == [site]
        assert _save_sites(save_origin_flags_on, shape.uri) == [published_with_flags_on(site)]

    def test_the_lambda_save_is_in_no_endpoint_flow(self, save_origin: Assembled) -> None:
        route = ("POST", "/save/origin/lambda-parameter-no-caller")
        assert save_origin.endpoint(route).entity_access == []
        saves = [r for r in save_origin.db_rows() if r.db is not None and r.db.save is not None]
        assert len(saves) == 29
        assert save_origin.accounting.in_no_endpoint_flow == 1

    def test_accounting(self, save_origin: Assembled, save_origin_flags_on: Assembled) -> None:
        shipped = save_origin.accounting
        flow = (shipped.call_sites, shipped.in_endpoint_flow, shipped.in_no_endpoint_flow)
        assert flow == (55, 54, 1)
        assert (shipped.create_or_update, shipped.bound) == (29, 26)
        # Seven guard shapes decided by their arm, less the two `findByCode`
        # found arms (B5), plus the identity found arm.
        assert shipped.sites_by_basis == {
            "method-name": 26,
            "query-text": 0,
            "argument-origin": 23,
            "existence-guard": 6,
        }
        _assert_partitions_sum(shipped)
        on = save_origin_flags_on.accounting
        # Fifteen saves have no candidate and stay create-or-update: the nine
        # before, the two `findByCode` found arms, and the List, Optional,
        # deep-chain and search-lookup shapes.
        assert (on.create_or_update, on.bound) == (15, 40)
        assert on.accesses_by_operation == {
            "create": 6,
            "read": 26,
            "update": 8,
            "delete": 0,
            "create-or-update": 15,
            "unknown": 0,
        }
        _assert_partitions_sum(on)

    def test_every_db_row_carries_its_facts(self, save_origin: Assembled) -> None:
        rows = save_origin.db_rows()
        assert len({row.call_id for row in rows}) == 55
        assert [row.call_id for row in rows if row.db is None] == []
