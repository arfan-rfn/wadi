"""Reconciling the source oracle with wadi's db sinks, one site at a time (§5.2.17, C4)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from wadi_contracts import (
    EntityAccess,
    EntityAccessBasis,
    EntityAccessSite,
    EntityOperation,
    IcfgNode,
    IcfgNodeKind,
    SinkKind,
    SourceAnchor,
)
from wadi_joern_client.export import ServiceExport
from wadi_testing.builders import make_endpoint, make_icfg, make_service, make_snapshot, make_system
from wadi_testing.measure.reconcile_repository_sites import (
    EntityVerdict,
    OperationVerdict,
    load_published,
    main,
    method_spans,
    reconcile,
    wadi_sites,
)
from wadi_testing.measure.repository_oracle import (
    OracleOperation,
    RepositoryCallSite,
    name_operation,
    scan,
)

_FILE = "src/main/java/com/acme/web/OrderController.java"
_REPOSITORY = "com.acme.repo.OrderRepository"


def _oracle(
    line: int,
    method: str,
    *,
    file: str = "orders/" + _FILE,
    entity: str | None = "Order",
    operation: OracleOperation | None = None,
    unread: bool = False,
) -> RepositoryCallSite:
    """An oracle site; its operation is read from the name unless given, and
    ``unread`` gives a format-1 site, which read neither entity nor operation."""
    return RepositoryCallSite(
        module="orders",
        file=file,
        line=line,
        repository="OrderRepository",
        receiver="orderRepository",
        method=method,
        enclosing_class="OrderController",
        enclosing_method="m",
        in_lambda=False,
        entity=None if unread else entity,
        operation=None if unread else (operation or name_operation(method)),
    )


def _export(
    sinks: list[tuple[int, str, int, int]],
    *,
    filename: str = _FILE,
    facts: dict[int, dict[str, Any]] | None = None,
) -> ServiceExport:
    """One method whose db sinks are (call_id, repository method, line, line_end).

    ``facts`` adds raw db facts per call id, such as its bound entity.
    """
    nodes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for call_id, method, line, line_end in sinks:
        node_id = 1000 + line
        if all(node["id"] != node_id for node in nodes):
            nodes.append(
                {"id": node_id, "kind": "call", "code": "...", "line": line, "line_end": line_end}
            )
        rows.append(
            {
                "node_id": node_id,
                "call_id": call_id,
                "method_id": 1,
                "kind": "db",
                "db": {
                    "repository": _REPOSITORY,
                    "method_name": method,
                    "repository_kind": "jpa",
                    "implemented_in_project": False,
                    **(facts or {}).get(call_id, {}),
                },
            }
        )
    return ServiceExport.model_validate(
        {
            "language": "java",
            "methods": [
                {
                    "id": 1,
                    "full_name": "com.acme.web.OrderController.m:void()",
                    "signature": "void()",
                    "filename": filename,
                    "line": 1,
                    "line_end": 40,
                    "code": "void m()",
                }
            ],
            "cfgs": [{"method_id": 1, "nodes": nodes, "edges": []}],
            "endpoints": [],
            "sinks": rows,
        }
    )


class TestMatchingIsBySite:
    def test_two_identical_calls_on_one_line_are_two_sites_and_extras_are_listed(self) -> None:
        oracle = [_oracle(7, "count"), _oracle(7, "count"), _oracle(9, "save")]
        wadi = wadi_sites(
            _export([(11, "count", 7, 7), (12, "count", 7, 7), (13, "deleteAll", 12, 12)]),
            "orders",
        )

        result = reconcile(oracle, wadi)

        assert [(a.oracle.line, a.wadi.call_id) for a in result.agree] == [(7, 11), (7, 12)]
        assert [(s.line, s.method) for s in result.oracle_only] == [(9, "save")]
        assert [(s.line, s.method, s.call_id) for s in result.wadi_only] == [(12, "deleteAll", 13)]

    def test_a_call_inside_a_multi_line_statement_matches_on_the_statement_span(
        self,
    ) -> None:
        # `List<Order> orders = mapper.map(\n    orderRepository.findAll());`: the
        # export carries the statement's lines 20-21, the source the call's 21.
        oracle = [_oracle(21, "findAll"), _oracle(30, "findAll")]
        wadi = wadi_sites(_export([(11, "findAll", 20, 21)]), "orders")

        result = reconcile(oracle, wadi)

        assert [(a.oracle.line, a.wadi.line, a.by_span) for a in result.agree] == [(21, 20, True)]
        assert [s.line for s in result.oracle_only] == [30]
        assert result.wadi_only == []

    def test_an_exact_line_wins_over_a_span(self) -> None:
        # An `if` node spans its whole statement (51-54); the save inside it
        # is its own node at 54 and must not be taken by the condition's site.
        oracle = [_oracle(51, "existsById"), _oracle(54, "save")]
        wadi = wadi_sites(_export([(11, "save", 54, 54), (12, "existsById", 51, 54)]), "orders")

        result = reconcile(oracle, wadi)

        assert [(a.oracle.line, a.wadi.call_id, a.by_span) for a in result.agree] == [
            (51, 12, False),
            (54, 11, False),
        ]


class TestOracleOnlySites:
    def test_an_untagged_call_in_an_exported_method_is_told_apart_from_one_outside(
        self,
    ) -> None:
        # The export holds the endpoint-reachable closure only. A call in a
        # method it holds and did not tag is the C4 case; a call in a method
        # it never exported is unreached code, a different question.
        export = _export([(11, "count", 7, 7)])  # its one method spans lines 1-40
        oracle = [
            _oracle(7, "count"),
            _oracle(9, "save"),
            _oracle(9, "save", file="orders/src/main/java/com/acme/web/Unreached.java"),
        ]

        result = reconcile(oracle, wadi_sites(export, "orders"), method_spans(export, "orders"))

        assert [(s.file.rsplit("/", 1)[-1], s.line) for s in result.oracle_only] == [
            ("OrderController.java", 9),
            ("Unreached.java", 9),
        ]
        assert [(s.file.rsplit("/", 1)[-1], s.line) for s in result.in_exported_method] == [
            ("OrderController.java", 9)
        ]


class TestStagedLibraries:
    def test_a_library_site_copied_into_two_services_is_one_site(self) -> None:
        # §5.2.6 stages a library's sources under `wadi-libs/<dir>/` in EVERY
        # dependent's parse root, so one source call is a sink in each export.
        library_file = "common/src/main/java/com/acme/Lookup.java"
        oracle = [_oracle(5, "findById", file=library_file)]
        staged = "wadi-libs/" + library_file
        wadi = [
            *wadi_sites(_export([(11, "findById", 5, 5)], filename=staged), "orders"),
            *wadi_sites(_export([(77, "findById", 5, 5)], filename=staged), "billing"),
        ]

        result = reconcile(oracle, wadi)

        assert [(a.wadi.export, a.wadi.call_id) for a in result.agree] == [("orders", 11)]
        assert result.wadi_only == []
        assert [(s.export, s.call_id) for s in result.library_copies] == [("billing", 77)]


def _bound(*calls: tuple[int, str]) -> dict[int, dict[str, Any]]:
    """Raw facts binding each (call id, qualified entity) the way the export does."""
    return {
        call_id: {"entity_type_text": entity.rsplit(".", 1)[-1], "entity_type_full_name": entity}
        for call_id, entity in calls
    }


class TestEntityIsCompared:
    """Review D6: a location match said nothing about WHAT the call touches."""

    def test_an_entity_mismatch_is_listed_with_both_sides(self) -> None:
        oracle = [_oracle(7, "findById"), _oracle(9, "count")]
        export = _export(
            [(11, "findById", 7, 7), (12, "count", 9, 9)],
            facts=_bound((11, "com.acme.Order"), (12, "com.acme.billing.Invoice")),
        )

        result = reconcile(oracle, wadi_sites(export, "orders"))

        assert [(c.oracle_entity, c.wadi_entity, c.entity) for c in result.compared] == [
            ("Order", "Order", EntityVerdict.AGREE),
            ("Order", "Invoice", EntityVerdict.DISAGREE),
        ]
        assert [c.agreement.wadi.call_id for c in result.entity_disagreements] == [12]
        totals = result.totals()
        assert (totals["agree_entity"], totals["entity_disagree"]) == (1, 1)

    def test_an_undetermined_wadi_entity_is_withheld_never_agreement(self) -> None:
        # The first is AbstractArchiver's shape: both sides unbound, and it is
        # still not an agreement. The second wrote a type argument the export
        # could not resolve to a project type.
        oracle = [_oracle(7, "count", entity=None), _oracle(9, "count")]
        export = _export(
            [(11, "count", 7, 7), (12, "count", 9, 9)],
            facts={12: {"entity_type_text": "Order"}},
        )

        result = reconcile(oracle, wadi_sites(export, "orders"))

        assert [c.entity for c in result.compared] == [
            EntityVerdict.WITHHELD,
            EntityVerdict.WITHHELD,
        ]
        assert [c.agreement.wadi.call_id for c in result.entity_withheld] == [11, 12]
        totals = result.totals()
        assert (totals["agree_entity"], totals["entity_withheld"]) == (0, 2)

    def test_an_unbound_oracle_entity_against_a_bound_wadi_one_is_a_disagreement(
        self,
    ) -> None:
        oracle = [_oracle(7, "count", entity=None)]
        export = _export([(11, "count", 7, 7)], facts=_bound((11, "com.acme.Order")))

        [compared] = reconcile(oracle, wadi_sites(export, "orders")).compared

        assert (compared.oracle_entity, compared.wadi_entity, compared.entity) == (
            None,
            "Order",
            EntityVerdict.DISAGREE,
        )

    def test_an_oracle_run_that_read_neither_is_not_read(self) -> None:
        export = _export([(11, "count", 7, 7)], facts=_bound((11, "com.acme.Order")))

        [compared] = reconcile([_oracle(7, "count", unread=True)], wadi_sites(export, "o")).compared

        assert (compared.entity, compared.operation) == (
            EntityVerdict.NOT_READ,
            OperationVerdict.NOT_READ,
        )


def _site(
    method: str,
    operation: EntityOperation,
    *,
    basis: EntityAccessBasis = EntityAccessBasis.METHOD_NAME,
    candidate: EntityOperation | None = None,
) -> EntityAccessSite:
    return EntityAccessSite(
        repository=_REPOSITORY,
        method_name=method,
        basis=basis,
        accesses=[
            EntityAccess(
                entity="com.acme.Order",
                data_model_id=None,
                operation=operation,
                candidate_operation=candidate,
            )
        ],
    )


def _bundle(
    tmp_path: Path,
    db_nodes: list[tuple[int, list[EntityAccessSite]]],
    *,
    service: str = "orders",
    endpoints: int = 1,
) -> Path:
    """A snapshot bundle as `GET /snapshots/{id}/export` streams it.

    Each endpoint's ICFG holds the same db statement nodes, one per (line,
    sites), so ``endpoints=2`` is one site that two endpoints reach.
    """
    snapshot = make_snapshot(make_system())
    boundary = make_service(snapshot, build_root=f"services/{service}")
    records = [{"kind": "service_boundary", "artifact": boundary.model_dump(mode="json")}]
    for index in range(endpoints):
        endpoint = make_endpoint(snapshot, boundary, f"/orders/{index}")
        icfg = make_icfg(snapshot, boundary, endpoint, statement_count=0)
        nodes = [
            IcfgNode(
                id=f"m1:n{1000 + line}",
                kind=IcfgNodeKind.STATEMENT,
                anchor=SourceAnchor(file=_FILE, start_line=line, end_line=line),
                source_text="orderRepository.call();",
                method=endpoint.handler,
                sink=SinkKind.DB,
                entity_access_sites=sites,
            )
            for line, sites in db_nodes
        ]
        icfg = icfg.model_copy(update={"nodes": [*icfg.nodes, *nodes]})
        records.append({"kind": "icfg", "artifact": icfg.model_dump(mode="json")})
    path = tmp_path / "snapshot.ndjson"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


C, R, D, COU = (
    EntityOperation.CREATE,
    EntityOperation.READ,
    EntityOperation.DELETE,
    EntityOperation.CREATE_OR_UPDATE,
)


class TestOperationIsComparedWithWhatWadiPublished:
    """The export carries no operation; the snapshot's ICFG sites are wadi's claim."""

    def test_an_operation_mismatch_is_listed_with_both_sides(self, tmp_path: Path) -> None:
        # `MongoRepository.insert` never updates, so publishing it as a save
        # that may update is a different claim from the oracle's `create`.
        oracle = [_oracle(7, "insert"), _oracle(9, "findById"), _oracle(11, "deleteById")]
        export = _export([(21, "insert", 7, 7), (22, "findById", 9, 9), (23, "deleteById", 11, 11)])
        published = load_published(
            _bundle(
                tmp_path,
                [
                    (7, [_site("insert", COU, candidate=C)]),
                    (9, [_site("findById", R)]),
                    (11, [_site("deleteById", D)]),
                ],
            )
        )

        result = reconcile(oracle, wadi_sites(export, "orders"), published=published)

        assert [(c.oracle_operation, c.wadi_operation, c.operation) for c in result.compared] == [
            ("create", "create-or-update", OperationVerdict.DISAGREE),
            ("read", "read", OperationVerdict.AGREE),
            ("delete", "delete", OperationVerdict.AGREE),
        ]
        assert [c.agreement.wadi.call_id for c in result.operation_disagreements] == [21]
        totals = result.totals()
        assert (totals["agree_operation"], totals["operation_disagree"]) == (2, 1)

    def test_a_query_on_both_sides_is_not_compared_and_a_one_sided_one_is_listed(
        self, tmp_path: Path
    ) -> None:
        # The oracle does not read query text, so two query readings are not
        # compared on the verb. `findVip` runs an implicit named query the
        # oracle cannot see: one side says query, the other a name, and that
        # is a disagreement to open.
        oracle = [
            _oracle(7, "findInStatus", operation=OracleOperation.QUERY),
            _oracle(9, "findVip"),
        ]
        export = _export([(21, "findInStatus", 7, 7), (22, "findVip", 9, 9)])
        published = load_published(
            _bundle(
                tmp_path,
                [
                    (7, [_site("findInStatus", R, basis=EntityAccessBasis.QUERY_TEXT)]),
                    (9, [_site("findVip", R, basis=EntityAccessBasis.QUERY_TEXT)]),
                ],
            )
        )

        result = reconcile(oracle, wadi_sites(export, "orders"), published=published)

        assert [(c.oracle_operation, c.wadi_operation, c.operation) for c in result.compared] == [
            ("query", "query-text:read", OperationVerdict.BOTH_QUERY),
            ("read", "query-text:read", OperationVerdict.ONE_SIDED_QUERY),
        ]
        assert [c.agreement.wadi.call_id for c in result.operation_disagreements] == [22]
        totals = result.totals()
        assert totals["agree_operation"] + totals["operation_disagree"] == 0
        assert (totals["operation_both_query"], totals["operation_one_sided_query"]) == (1, 1)

    def test_flush_in_an_endpoint_flow_publishes_no_site_and_agrees_with_none(
        self, tmp_path: Path
    ) -> None:
        export = _export([(21, "flush", 7, 7)])
        published = load_published(_bundle(tmp_path, [(7, [])]))

        [compared] = reconcile(
            [_oracle(7, "flush")], wadi_sites(export, "orders"), published=published
        ).compared

        assert (compared.oracle_operation, compared.wadi_operation, compared.operation) == (
            "none",
            "none",
            OperationVerdict.AGREE,
        )

    def test_a_site_in_no_endpoint_flow_or_with_no_snapshot_is_unpublished(
        self, tmp_path: Path
    ) -> None:
        # Wadi publishes a site only on an endpoint's ICFG. A site in no flow
        # is counted in the accounting and has no reading to compare.
        oracle = [_oracle(7, "save"), _oracle(9, "save")]
        sites = wadi_sites(_export([(21, "save", 7, 7), (22, "save", 9, 9)]), "orders")
        published = load_published(_bundle(tmp_path, [(7, [_site("save", COU)])]))

        with_snapshot = reconcile(oracle, sites, published=published)
        without = reconcile(oracle, sites)

        assert [c.operation for c in with_snapshot.compared] == [
            OperationVerdict.AGREE,
            OperationVerdict.UNPUBLISHED,
        ]
        assert [c.operation for c in without.compared] == [OperationVerdict.UNPUBLISHED] * 2
        assert without.totals()["operation_unpublished"] == 2

    def test_a_site_two_endpoints_reach_is_one_reading_and_two_calls_pair_in_order(
        self, tmp_path: Path
    ) -> None:
        bundle = _bundle(tmp_path, [(7, [_site("count", R), _site("count", R)])], endpoints=2)

        published = load_published(bundle)

        assert len(published.readings[("orders", _FILE, 7, _REPOSITORY, "count")]) == 2
        result = reconcile(
            [_oracle(7, "count"), _oracle(7, "count")],
            wadi_sites(_export([(21, "count", 7, 7), (22, "count", 7, 7)]), "orders"),
            published=published,
        )
        assert [c.operation for c in result.compared] == [OperationVerdict.AGREE] * 2

    def test_an_export_no_published_service_is_named_after_is_reported(
        self, tmp_path: Path
    ) -> None:
        published = load_published(_bundle(tmp_path, [(7, [_site("save", COU)])]))

        result = reconcile(
            [_oracle(7, "save")],
            wadi_sites(_export([(21, "save", 7, 7)]), "billing"),
            published=published,
        )

        assert result.exports_without_published_service == ["billing"]
        assert [c.operation for c in result.compared] == [OperationVerdict.UNPUBLISHED]


JOERN_PLATFORM = Path(__file__).resolve().parents[3] / "joern-platform"
CRUD_MATRIX = JOERN_PLATFORM / "fixtures" / "spring-data-crud-matrix"
CRUD_MATRIX_EXPORT = JOERN_PLATFORM / "target" / "spring-data-crud-matrix-export" / "export.json"


@pytest.mark.skipif(
    not CRUD_MATRIX_EXPORT.exists(),
    reason="spring-data-crud-matrix export not present — run `sbt test` in joern-platform first",
)
class TestCrudMatrixReconciles:
    def test_every_oracle_site_is_a_wadi_site_and_back(self) -> None:
        export = ServiceExport.model_validate(json.loads(CRUD_MATRIX_EXPORT.read_text()))

        result = reconcile(scan(CRUD_MATRIX).sites, wadi_sites(export, "crud-matrix"))

        # No expected disagreements: the two implicit-receiver calls in the
        # golden-32 default method are sites on both sides, and the golden-26
        # lambda save is in the export (in no endpoint flow, A1) and in source.
        assert result.oracle_only == []
        assert result.wadi_only == []
        assert len(result.agree) == 68
        # Review D6: every agreed site also names the same entity, except
        # AbstractArchiver's `BaseRepository<E>`, which neither side binds and
        # which counts as withheld, never as agreement. No snapshot is read
        # here, so no operation is compared; the oracle's own operation
        # counts are pinned in `test_repository_oracle.py`.
        totals = result.totals()
        entity_keys = ("agree_entity", "entity_disagree", "entity_withheld", "entity_not_read")
        assert [totals[key] for key in entity_keys] == [67, 0, 1, 0]
        assert [
            (c.agreement.oracle.file.rsplit("/", 1)[-1], c.agreement.oracle.method)
            for c in result.entity_withheld
        ] == [("AbstractArchiver.java", "count")]
        assert totals["operation_unpublished"] == 68


class TestCommandLine:
    def test_it_prints_the_three_lists_and_writes_them(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oracle_json = tmp_path / "oracle.json"
        oracle_json.write_text(
            json.dumps(
                {
                    "sites": [
                        asdict(_oracle(7, "count")),
                        asdict(_oracle(9, "save")),
                    ]
                }
            )
        )
        exports = tmp_path / "exports"
        exports.mkdir()
        (exports / "orders.json").write_text(
            _export([(11, "count", 7, 7), (13, "deleteAll", 12, 12)]).model_dump_json()
        )
        out = tmp_path / "reconciled.json"

        assert (
            main(["--oracle", str(oracle_json), "--exports", str(exports), "--json", str(out)]) == 0
        )

        printed = capsys.readouterr().out
        assert "agree (1)" in printed
        assert "oracle-only (1)" in printed
        assert "orders/src/main/java/com/acme/web/OrderController.java:9" in printed
        assert "wadi-only (1)" in printed
        assert "orders: src/main/java/com/acme/web/OrderController.java:12" in printed
        written = json.loads(out.read_text())
        assert written["totals"] == {
            "agree": 1,
            "oracle_only": 1,
            "oracle_only_in_exported_method": 1,
            "wadi_only": 1,
            "oracle_sites": 2,
            "wadi_sites": 2,
            "library_copies": 0,
            "agree_by_span": 0,
            "agree_entity": 0,
            "entity_disagree": 0,
            "entity_withheld": 1,
            "entity_not_read": 0,
            "agree_operation": 0,
            "operation_disagree": 0,
            "operation_one_sided_query": 0,
            "operation_both_query": 0,
            "operation_unpublished": 1,
            "operation_not_read": 0,
        }
        assert [row["wadi"]["call_id"] for row in written["agree"]] == [11]
        assert written["agree"][0]["entity"] == {
            "oracle": "Order",
            "wadi": None,
            "verdict": "withheld",
        }

    def test_with_a_snapshot_it_compares_operations_and_lists_disagreements(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oracle_json = tmp_path / "oracle.json"
        oracle_json.write_text(
            json.dumps({"sites": [asdict(_oracle(7, "insert")), asdict(_oracle(9, "count"))]})
        )
        export = tmp_path / "orders.json"
        export.write_text(
            _export(
                [(11, "insert", 7, 7), (12, "count", 9, 9)],
                facts=_bound((11, "com.acme.Order"), (12, "com.acme.Invoice")),
            ).model_dump_json()
        )
        bundle = _bundle(tmp_path, [(7, [_site("insert", COU)]), (9, [_site("count", R)])])
        out = tmp_path / "reconciled.json"

        assert (
            main(
                [
                    *("--oracle", str(oracle_json), "--exports", str(export)),
                    *("--published", str(bundle), "--json", str(out)),
                ]
            )
            == 0
        )

        printed = capsys.readouterr().out
        assert "entity disagreements (1)" in printed
        assert "operation disagreements (1)" in printed
        assert "oracle create  wadi create-or-update" in printed
        written = json.loads(out.read_text())
        assert (written["totals"]["agree_operation"], written["totals"]["agree_entity"]) == (1, 1)
        assert [row["wadi"]["call_id"] for row in written["operation_disagreements"]] == [11]
        assert written["operation_disagreements"][0]["operation"] == {
            "oracle": "create",
            "wadi": "create-or-update",
            "verdict": "disagree",
        }
        assert [row["wadi"]["call_id"] for row in written["entity_disagreements"]] == [12]
