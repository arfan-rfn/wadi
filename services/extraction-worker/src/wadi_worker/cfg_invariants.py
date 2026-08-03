"""§5.2.8 M2: always-on structural invariants over every exported method CFG.

Runs against the RAW export — deliberately BEFORE the assembler's synthetic
entry/exit patching, which guarantees every node an in- and out-edge by
construction and would make reachability invariants vacuously true. Violations
are never errors: they aggregate into ``ServiceBoundary.cfg_anomalies`` facts
(P10 — the weird code lives in real repos, and every snapshot is a CFG test).
"""

from collections import defaultdict

from wadi_contracts.boundary import CfgAnomaly
from wadi_contracts.source import SourceAnchor
from wadi_joern_client.export import (
    CfgNodeKind,
    ExportCfg,
    ExportCfgEdgeLabel,
    ExportCfgNode,
    ExportMethod,
)

_SWITCH_CONSTRUCTS = {"switch", "switch-arrow"}
_MAX_SAMPLE_SITES = 5


def _anchor(method: ExportMethod, node: ExportCfgNode | None = None) -> SourceAnchor:
    line = node.line if node is not None else method.line
    end = node.line_end if node is not None else (method.line_end or method.line)
    return SourceAnchor(file=method.filename, start_line=max(line, 1), end_line=max(end, line, 1))


def check_cfg(cfg: ExportCfg, method: ExportMethod) -> list[tuple[str, SourceAnchor]]:
    """Structural-invariant findings for one method's raw coarsened CFG."""
    findings: list[tuple[str, SourceAnchor]] = []
    nodes = {node.id: node for node in cfg.nodes}

    intra = [edge for edge in cfg.edges if edge.source in nodes and edge.target in nodes]
    for edge in cfg.edges:
        if edge.source not in nodes or edge.target not in nodes:
            findings.append(("dangling-edge", _anchor(method)))

    incoming: dict[int, list[ExportCfgEdgeLabel]] = defaultdict(list)
    outgoing: dict[int, list[ExportCfgEdgeLabel]] = defaultdict(list)
    for edge in intra:
        incoming[edge.target].append(edge.label)
        outgoing[edge.source].append(edge.label)

    if len(nodes) >= 2:
        # The method's entry statement legitimately has no incoming edge;
        # every other in-degree-0 node is a disconnection the downstream
        # patching would disguise as an extra entry point.
        entry = min(cfg.nodes, key=lambda n: (n.line, n.id))
        for node in cfg.nodes:
            if node.id != entry.id and node.id not in incoming:
                findings.append(("disconnected-node", _anchor(method, node)))

    for node in cfg.nodes:
        labels = set(outgoing.get(node.id, []))
        if node.kind is CfgNodeKind.BRANCH:
            if node.construct_kind in _SWITCH_CONSTRUCTS:
                if not labels & {ExportCfgEdgeLabel.CASE, ExportCfgEdgeLabel.DEFAULT}:
                    findings.append(("branch-arity", _anchor(method, node)))
            elif not {ExportCfgEdgeLabel.TRUE, ExportCfgEdgeLabel.FALSE} <= labels:
                findings.append(("branch-arity", _anchor(method, node)))
        elif node.kind is CfgNodeKind.LOOP:
            body_edges = [
                e for e in intra if e.source == node.id and e.label is ExportCfgEdgeLabel.TRUE
            ]
            if body_edges:
                closes_cycle = any(
                    e.back and (e.source == node.id or e.target == node.id) for e in intra
                )
                if not closes_cycle:
                    findings.append(("loop-no-back-edge", _anchor(method, node)))
            # Empty-body loops carry no back edge by recorded design (§5.2.8).

    if nodes:
        has_return = any(node.kind is CfgNodeKind.RETURN for node in cfg.nodes)
        has_terminal = any(node.id not in outgoing for node in cfg.nodes)
        if not has_return and not has_terminal:
            findings.append(("exit-unreachable", _anchor(method)))

    return findings


def aggregate_anomalies(
    findings: list[tuple[str, SourceAnchor]],
) -> list[CfgAnomaly]:
    """Fold per-method findings into the boundary's per-code fact list."""
    counts: dict[str, int] = defaultdict(int)
    samples: dict[str, list[SourceAnchor]] = defaultdict(list)
    for code, anchor in findings:
        counts[code] += 1
        if len(samples[code]) < _MAX_SAMPLE_SITES:
            samples[code].append(anchor)
    return [
        CfgAnomaly(code=code, count=counts[code], sample_sites=samples[code])
        for code in sorted(counts)
    ]
