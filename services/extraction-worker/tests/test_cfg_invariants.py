"""§5.2.8 M2: structural invariants over raw exported CFGs."""

from wadi_joern_client.export import (
    CfgNodeKind,
    ExportCfg,
    ExportCfgEdge,
    ExportCfgEdgeLabel,
    ExportCfgNode,
    ExportMethod,
)
from wadi_worker.cfg_invariants import aggregate_anomalies, check_cfg


def _method(method_id: int = 1) -> ExportMethod:
    return ExportMethod(
        id=method_id,
        full_name="com.acme.Svc.handle:void()",
        signature="void()",
        filename="src/main/java/com/acme/Svc.java",
        line=10,
        line_end=40,
        code="public void handle()",
    )


def _node(
    node_id: int,
    kind: CfgNodeKind = CfgNodeKind.STATEMENT,
    line: int = 0,
    construct_kind: str | None = None,
) -> ExportCfgNode:
    return ExportCfgNode(
        id=node_id,
        kind=kind,
        code=f"stmt{node_id}",
        line=line or node_id,
        line_end=line or node_id,
        construct_kind=construct_kind,
    )


def _edge(
    source: int,
    target: int,
    label: ExportCfgEdgeLabel = ExportCfgEdgeLabel.FLOW,
    back: bool = False,
) -> ExportCfgEdge:
    return ExportCfgEdge(source=source, target=target, label=label, back=back)


def _cfg(nodes: list[ExportCfgNode], edges: list[ExportCfgEdge]) -> ExportCfg:
    return ExportCfg(method_id=1, nodes=nodes, edges=edges)


class TestCheckCfg:
    def test_clean_linear_cfg_has_no_findings(self) -> None:
        cfg = _cfg(
            [_node(1), _node(2), _node(3, CfgNodeKind.RETURN)],
            [_edge(1, 2), _edge(2, 3)],
        )
        assert check_cfg(cfg, _method()) == []

    def test_clean_if_with_both_labels(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.BRANCH, construct_kind="if"),
                _node(2),
                _node(3, CfgNodeKind.RETURN),
            ],
            [
                _edge(1, 2, ExportCfgEdgeLabel.TRUE),
                _edge(1, 3, ExportCfgEdgeLabel.FALSE),
                _edge(2, 3),
            ],
        )
        assert check_cfg(cfg, _method()) == []

    def test_disconnected_node_is_reported_but_entry_is_not(self) -> None:
        # Node 3 has no incoming edge — the pre-M1 synchronized class; the
        # entry statement (lowest line) legitimately has none.
        cfg = _cfg(
            [_node(1), _node(2), _node(3), _node(4, CfgNodeKind.RETURN)],
            [_edge(1, 2), _edge(2, 4), _edge(3, 4)],
        )
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["disconnected-node"]

    def test_branch_missing_false_successor(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.BRANCH, construct_kind="if"),
                _node(2, CfgNodeKind.RETURN),
            ],
            [_edge(1, 2, ExportCfgEdgeLabel.TRUE)],
        )
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["branch-arity"]

    def test_switch_without_any_arm_edge(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.BRANCH, construct_kind="switch"),
                _node(2, CfgNodeKind.RETURN),
            ],
            [_edge(1, 2)],
        )
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["branch-arity"]

    def test_switch_with_case_edges_is_clean(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.BRANCH, construct_kind="switch"),
                _node(2),
                _node(3, CfgNodeKind.RETURN),
            ],
            [
                ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.CASE, case_values=["0"]),
                _edge(1, 3, ExportCfgEdgeLabel.DEFAULT),
                _edge(2, 3),
            ],
        )
        assert check_cfg(cfg, _method()) == []

    def test_loop_with_body_but_no_back_edge(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.LOOP, construct_kind="while"),
                _node(2),
                _node(3, CfgNodeKind.RETURN),
            ],
            [
                _edge(1, 2, ExportCfgEdgeLabel.TRUE),
                _edge(1, 3, ExportCfgEdgeLabel.FALSE),
                _edge(2, 3),  # body exits forward, never closes the cycle
            ],
        )
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["loop-no-back-edge"]

    def test_loop_with_back_edge_is_clean(self) -> None:
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.LOOP, construct_kind="while"),
                _node(2),
                _node(3, CfgNodeKind.RETURN),
            ],
            [
                _edge(1, 2, ExportCfgEdgeLabel.TRUE),
                _edge(1, 3, ExportCfgEdgeLabel.FALSE),
                _edge(2, 1, back=True),
            ],
        )
        assert check_cfg(cfg, _method()) == []

    def test_empty_body_loop_suppressed(self) -> None:
        # Recorded §5.2.8: statement-level self-loops are unrepresentable, so
        # an empty-body loop carries no back edge by design — not an anomaly.
        cfg = _cfg(
            [
                _node(1, CfgNodeKind.LOOP, construct_kind="while"),
                _node(2, CfgNodeKind.RETURN),
            ],
            [_edge(1, 2, ExportCfgEdgeLabel.FALSE)],
        )
        assert check_cfg(cfg, _method()) == []

    def test_dangling_edge(self) -> None:
        cfg = _cfg([_node(1, CfgNodeKind.RETURN)], [_edge(1, 99)])
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["dangling-edge"]

    def test_exit_unreachable_pure_cycle(self) -> None:
        cfg = _cfg([_node(1), _node(2)], [_edge(1, 2), _edge(2, 1)])
        codes = [code for code, _ in check_cfg(cfg, _method())]
        assert codes == ["exit-unreachable"]

    def test_empty_cfg_is_clean(self) -> None:
        assert check_cfg(_cfg([], []), _method()) == []


class TestAggregateAnomalies:
    def test_folds_counts_and_caps_samples(self) -> None:
        cfg = _cfg(
            [_node(n) for n in range(1, 9)] + [_node(9, CfgNodeKind.RETURN)],
            [_edge(1, 9)],  # nodes 2..8 all disconnected
        )
        anomalies = aggregate_anomalies(check_cfg(cfg, _method()))
        assert len(anomalies) == 1
        anomaly = anomalies[0]
        assert anomaly.code == "disconnected-node"
        assert anomaly.count == 7
        assert len(anomaly.sample_sites) == 5  # capped examples, honest count

    def test_empty_findings_fold_to_empty(self) -> None:
        assert aggregate_anomalies([]) == []
