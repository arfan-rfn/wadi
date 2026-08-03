"""Unit tests for the method-level roll-up view (no database)."""

import pytest
from mcp_support import make_two_method_icfg

from wadi_contracts import Icfg, IcfgNodeKind
from wadi_mcp.rollup import method_rollup, statement_detail
from wadi_testing.builders import make_endpoint, make_service, make_snapshot, make_system


@pytest.fixture
def icfg() -> Icfg:
    snapshot = make_snapshot(make_system())
    boundary = make_service(snapshot)
    endpoint = make_endpoint(snapshot, boundary)
    return make_two_method_icfg(snapshot, boundary, endpoint)


class TestMethodRollup:
    def test_groups_by_owning_method(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        assert rollup["detail"] == "methods"
        signatures = {m["signature"] for m in rollup["methods"]}
        # Two real methods; callees referenced but with no nodes don't get groups.
        assert any("OrderController" in s for s in signatures)
        assert any("OrderService.load" in s for s in signatures)

    def test_root_method_is_the_handler(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        root = next(m for m in rollup["methods"] if m["id"] == rollup["root_method_id"])
        assert "OrderController" in root["signature"]
        assert root["badges"] == ["endpoint"]

    def test_calls_carry_sink_and_remote_markers(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        service = next(m for m in rollup["methods"] if "OrderService" in m["signature"])
        sinks = {call.get("sink") for call in service["calls"]}
        assert sinks == {"db", "http-client"}
        remote = next(c for c in service["calls"] if c.get("sink") == "http-client")
        assert remote["remote_call_id"].startswith("rc_")

    def test_marker_on_return_statement_still_counts(self, icfg: Icfg) -> None:
        # `return client.get(...)` coarsens to a RETURN node with no callee
        # ref (the contract only allows callee on CALL) — its sink marker
        # must still appear in the roll-up (P10).
        nodes = [
            n.model_copy(update={"kind": IcfgNodeKind.RETURN, "callee": None})
            if n.id == "s-http"
            else n
            for n in icfg.nodes
        ]
        rollup = method_rollup(icfg.model_copy(update={"nodes": nodes}))
        service = next(m for m in rollup["methods"] if "OrderService" in m["signature"])
        remote = next(c for c in service["calls"] if c.get("sink") == "http-client")
        assert remote["remote_call_id"].startswith("rc_")
        assert "callee_id" not in remote

    def test_statement_counts_present(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        assert sum(rollup["statement_counts"].values()) == len(icfg.nodes)

    def test_rollup_is_much_smaller_than_statements(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        assert len(rollup["methods"]) < len(icfg.nodes)


class TestStatementDetail:
    def test_scoped_to_method(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        service_method = next(m for m in rollup["methods"] if "OrderService" in m["signature"])
        detail = statement_detail(icfg, service_method["id"])
        assert detail["detail"] == "statements"
        assert {n["id"] for n in detail["nodes"]} == {
            "s-entry",
            "s-branch",
            "s-db",
            "s-http",
            "s-exit",
        }
        # Includes the boundary edges (call in, return out).
        edge_pairs = {(e["source"], e["target"]) for e in detail["edges"]}
        assert ("c-call", "s-entry") in edge_pairs
        assert ("s-exit", "c-call") in edge_pairs

    def test_branch_labels_survive(self, icfg: Icfg) -> None:
        rollup = method_rollup(icfg)
        service_method = next(m for m in rollup["methods"] if "OrderService" in m["signature"])
        detail = statement_detail(icfg, service_method["id"])
        kinds = {e["kind"] for e in detail["edges"]}
        assert {"true", "false"} <= kinds

    def test_unknown_method_lists_known_ones(self, icfg: Icfg) -> None:
        with pytest.raises(KeyError, match="known methods"):
            statement_detail(icfg, "m_" + "f" * 16)
