"""Cross-language golden for entity access per endpoint (§5.2.17).

Consumes the REAL sbt-produced `spring-data-crud-matrix` and `save-origin-mini`
exports and assembles them with the worker's `Assembler`, proving the chain end
to end: the Scala pass describes each repository call (export 2.14.0 `db`
rows), and the worker turns that into per-node sites, a per-endpoint summary
and a per-service accounting.

The unit tests in `test_entity_classification.py` and
`test_assembler_entity_access.py` pin the rules against synthetic rows. This
pins them against what Joern actually produces from Java source, one golden
per endpoint of the plan's 36 (R1-18), so a golden that drifts names itself in
the test id.

Both gate states run (rule 5): the shipped table, where every save publishes
`create-or-update` and keeps its candidate as evidence (R1-11), and all four
flags on and scored against the current `RULES_VERSION`, where the candidate
is what publishes. Goldens 7-13 and 31 carry a query, and until milestone M6
reads it they publish `unknown` on the `query-text` basis. M6 changes those
expectations on purpose.
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
    Icfg,
)
from wadi_joern_client.export import ExportSink, ServiceExport
from wadi_worker.assembler import AssembledArtifacts, Assembler
from wadi_worker.entity_access import RULES_VERSION, SHIPPED_GATE_FLAGS, GateFlag

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

FLAGS_ON: tuple[GateFlag, ...] = (
    GateFlag(AO, C, True, RULES_VERSION),
    GateFlag(AO, U, True, RULES_VERSION),
    GateFlag(EG, C, True, RULES_VERSION),
    GateFlag(EG, U, True, RULES_VERSION),
)
"""Every (basis, verb) flag on, scored against the rules that run."""

STALE_RULES_VERSION = "0000000000000000"
FLAGS_ON_STALE: tuple[GateFlag, ...] = tuple(
    GateFlag(flag.basis, flag.operation, True, STALE_RULES_VERSION) for flag in FLAGS_ON
)
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


def queried(method: str, entity: str = ORDER, repository: str = ORDER_REPO) -> Site:
    """An annotated query method before M6: the name never decides (R1-12)."""
    return Site(repository, method, EntityAccessBasis.QUERY_TEXT, (Access(entity, UNK),))


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
    # Goldens 7-13 and 31: M6 replaces `unknown` with the verb the query reader
    # finds, and 9 and 31 gain the second entity the query names (rule 6, C1).
    Golden(
        7,
        "query-jpql-select",
        "GET",
        (queried("findBySkuText", ORDER_LINE, ORDER_LINE_REPO),),
        (Row(ORDER_LINE, (UNK,), 1),),
    ),
    Golden(
        8,
        "query-jpql-update-modifying",
        "PUT",
        (queried("updateStatus"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        9,
        "query-jpql-join-association",
        "GET",
        (queried("findContainingSku"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        10,
        "query-jpql-keyword-entity",
        "GET",
        (queried("findInStatus"),),
        (Row(ORDER, (UNK,), 1),),
    ),
    Golden(
        11,
        "query-native-table",
        "GET",
        (queried("findNativeByStatus"), queried("findNativeConcatenated")),
        (Row(ORDER, (UNK,), 2),),
    ),
    Golden(
        12,
        "query-named",
        "GET",
        (
            queried("shipped"),
            queried("findOpen", ISSUE, ISSUE_REPO),
            queried("findVip", CUSTOMER, CUSTOMER_REPO),
            queried("sumOpen", INVOICE, INVOICE_REPO),
            queried("undeclaredNamed"),
        ),
        (
            Row(CUSTOMER, (UNK,), 1),
            Row(INVOICE, (UNK,), 1),
            Row(ISSUE, (UNK,), 1),
            Row(ORDER, (UNK,), 2),
        ),
    ),
    Golden(
        13,
        "query-mongo-json",
        "GET",
        (queried("findByStatusJson", PET, PET_REPO),),
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
        (queried("deleteForNonVip", INVOICE, INVOICE_REPO),),
        (Row(INVOICE, (UNK,), 1),),
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
            # `Pet.builder()...build()` constructs.
            saved(C, "insert", entity=PET, repository=PET_REPO),
        ),
        (Row(ORDER, (R, D, CU), 11), Row(PET, (CU,), 1)),
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


def _assemble(path: Path, gate_flags: tuple[GateFlag, ...]) -> Assembled:
    export = ServiceExport.model_validate(json.loads(path.read_text()))
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
    return _assemble(CRUD_MATRIX_EXPORT, FLAGS_ON)


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


# --- the service's accounting --------------------------------------------------


@requires_crud_matrix
class TestAccounting:
    def test_as_shipped(self, shipped: Assembled) -> None:
        accounting = shipped.accounting
        assert accounting.model_dump(mode="json", exclude={"gate_flags"}) == {
            "call_sites": 68,
            # Partition 1: the lambda save (golden 26) is the one outside.
            "in_endpoint_flow": 67,
            "in_no_endpoint_flow": 1,
            # Partition 2, first match wins.
            "flush": 1,  # golden 35
            "implemented_in_project": 2,  # goldens 32 and 33
            "entity_undetermined": 1,  # golden 30
            "unknown_operation": 13,  # the query methods, goldens 7-13 and 31
            "create_or_update": 18,  # every save-family call, the lambda's included
            "bound": 33,
            "accesses_by_operation": {
                "create": 0,
                "read": 28,
                "update": 0,
                "delete": 6,
                "create-or-update": 18,
                "unknown": 15,
            },
            "sites_by_basis": {
                "method-name": 36,
                "query-text": 13,
                "argument-origin": 16,
                "existence-guard": 2,
            },
            "rules_version": RULES_VERSION,
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
        # Five saves have no candidate (goldens 18, 19, 21, 22, 23) and stay
        # create-or-update; the other thirteen publish a single verb.
        assert (accounting.create_or_update, accounting.bound) == (5, 46)
        assert accounting.accesses_by_operation == {
            "create": 5,  # goldens 15, 16, 24, 26 and 34's insert
            "read": 28,
            "update": 8,  # goldens 2, 17, 20, 25, 32 and 34's three saves
            "delete": 6,
            "create-or-update": 5,
            "unknown": 15,
        }
        flags = {(f.enabled, f.scored_rules_version) for f in accounting.gate_flags}
        assert flags == {(True, RULES_VERSION)}
        _assert_partitions_sum(accounting)

    def test_every_db_row_carries_its_facts(self, shipped: Assembled) -> None:
        # A 2.14.0 db row without `db` would be counted entity_undetermined
        # with no site (T4); the Scala pass must never emit one.
        rows = shipped.db_rows()
        assert len({row.call_id for row in rows}) == 68
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
        }
        reached = {row.entity for e in shipped.artifacts.endpoints for row in e.entity_access or []}
        assert SHIPMENT not in reached


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
    SaveShape("/save/guard/not-null-found", EG, U),
    SaveShape("/save/guard/null-check-else-arm", EG, U),
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
    return _assemble(SAVE_ORIGIN_EXPORT, FLAGS_ON)


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
        assert len(saves) == 23
        assert save_origin.accounting.in_no_endpoint_flow == 1

    def test_accounting(self, save_origin: Assembled, save_origin_flags_on: Assembled) -> None:
        shipped = save_origin.accounting
        flow = (shipped.call_sites, shipped.in_endpoint_flow, shipped.in_no_endpoint_flow)
        assert flow == (41, 40, 1)
        assert (shipped.create_or_update, shipped.bound) == (23, 18)
        assert shipped.sites_by_basis == {
            "method-name": 18,
            "query-text": 0,
            "argument-origin": 16,
            "existence-guard": 7,
        }
        _assert_partitions_sum(shipped)
        on = save_origin_flags_on.accounting
        # Nine saves have no candidate and stay create-or-update.
        assert (on.create_or_update, on.bound) == (9, 32)
        assert on.accesses_by_operation == {
            "create": 6,
            "read": 18,
            "update": 8,
            "delete": 0,
            "create-or-update": 9,
            "unknown": 0,
        }
        _assert_partitions_sum(on)

    def test_every_db_row_carries_its_facts(self, save_origin: Assembled) -> None:
        rows = save_origin.db_rows()
        assert len({row.call_id for row in rows}) == 41
        assert [row.call_id for row in rows if row.db is None] == []
