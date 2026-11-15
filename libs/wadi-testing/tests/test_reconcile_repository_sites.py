"""Reconciling the source oracle with wadi's db sinks, one site at a time (§5.2.17, C4)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from wadi_joern_client.export import ServiceExport
from wadi_testing.measure.reconcile_repository_sites import (
    main,
    method_spans,
    reconcile,
    wadi_sites,
)
from wadi_testing.measure.repository_oracle import RepositoryCallSite, scan

_FILE = "src/main/java/com/acme/web/OrderController.java"


def _oracle(line: int, method: str, *, file: str = "orders/" + _FILE) -> RepositoryCallSite:
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
    )


def _export(sinks: list[tuple[int, str, int, int]], *, filename: str = _FILE) -> ServiceExport:
    """One method whose db sinks are (call_id, repository method, line, line_end)."""
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
                    "repository": "com.acme.repo.OrderRepository",
                    "method_name": method,
                    "repository_kind": "jpa",
                    "implemented_in_project": False,
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
        }
        assert [row["wadi"]["call_id"] for row in written["agree"]] == [11]
