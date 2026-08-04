"""§5.2.8 M2: always-on structural invariants over every exported method CFG.

Runs against the RAW export — deliberately BEFORE the assembler's synthetic
entry/exit patching, which guarantees every node an in- and out-edge by
construction and would make reachability invariants vacuously true. Violations
are never errors: they aggregate into ``ServiceBoundary.cfg_anomalies`` facts
(P10 — the weird code lives in real repos, and every snapshot is a CFG test).

Codes: ``dangling-edge``, ``disconnected-node``, ``branch-arity`` (a branch or
loop that names no outcome at all), ``unlabeled-arm`` (§5.2.8 T3 — a `flow`
edge among several successors of a branch: the coarsening could not say which
way control went), ``loop-no-back-edge``, ``exit-unreachable``. An arm that is
simply *absent* is not a finding: control leaves the method, which an exit-free
export cannot express and the assembler completes against its exit node.
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


def _is_unconditional_loop(node: ExportCfgNode) -> bool:
    """``while (true)`` / ``do … while (true)`` / ``for (;;)`` — a loop with no
    exit test (§5.2.8 T3).

    Its label set is indistinguishable from a trailing loop's — body arm plus a
    back edge, no exit arm — so the exit-arm rule below would complete it, and
    the graph would claim the method can return past a loop it can never leave.
    Measured against the fixtures: a `for` states no ``condition_code`` only
    when it has no condition clause at all, while `foreach` always carries one
    (the loop's own text), so the two cannot be confused.
    """
    condition = (node.condition_code or "").strip()
    if node.construct_kind == "for":
        return not condition
    if node.construct_kind in {"while", "do-while"}:
        return condition == "true"
    return False


def arms_leaving_method(
    node: ExportCfgNode, labels: set[ExportCfgEdgeLabel]
) -> list[ExportCfgEdgeLabel]:
    """Arm labels of ``node`` whose control leaves the method (§5.2.8 T3).

    A construct that is its method's last statement has no successor statement
    for the arm not taken, and the export is deliberately exit-free — so the
    raw CFG goes silent exactly where the graph should say "on false, the
    method returns". Shared by the assembler, which materializes these arms
    against the exit node it owns, and by :func:`check_cfg`, which must not
    report them as anomalies. One predicate, so the two can never disagree
    about which silences are honest.

    Callers pass the node's *intra-method* out-edge labels; a node with none at
    all is terminal outright and is not this function's business.
    """
    if ExportCfgEdgeLabel.FLOW in labels:
        # An unlabeled successor IS the arm that could not be named — a
        # convergent branch (`if (c) { }` with no else) reaches the same
        # statement either way. Completing it would assert a path out of the
        # method that the source does not have.
        return []
    if node.kind is CfgNodeKind.BRANCH:
        if node.construct_kind in _SWITCH_CONSTRUCTS:
            # No `default` arm and nothing to fall out to: when no case
            # matches, control leaves the method.
            return [] if ExportCfgEdgeLabel.DEFAULT in labels else [ExportCfgEdgeLabel.DEFAULT]
        return [
            label
            for label in (ExportCfgEdgeLabel.TRUE, ExportCfgEdgeLabel.FALSE)
            if label not in labels
        ]
    if node.kind is CfgNodeKind.LOOP:
        # Exit arm only. A missing body arm is an empty-body loop (a recorded
        # non-representable); fabricating one would assert a body that is not
        # there, and would claim that body exits the method besides.
        if _is_unconditional_loop(node):
            # No exit test, so no exit arm exists to name. Returning nothing
            # here also keeps `exit-unreachable` live below: a method whose
            # only way out is a loop it cannot leave HAS an unreachable exit,
            # and that is a fact worth counting, not one to paper over with a
            # `false` edge nobody can take.
            return []
        return [] if ExportCfgEdgeLabel.FALSE in labels else [ExportCfgEdgeLabel.FALSE]
    if labels == {ExportCfgEdgeLabel.EXCEPTION}:
        # Every successor is a handler, so normal completion left the method.
        # Sound only because the exporter now wires normal completion wherever
        # a target exists — searching OUTWARD past the enclosing block and, at
        # the tail of a loop body, back to the loop header (§5.2.8 T3). What
        # survives to here is a construct whose normal completion genuinely
        # reached the method boundary.
        return [ExportCfgEdgeLabel.FLOW]
    return []


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
        if node.kind in (CfgNodeKind.BRANCH, CfgNodeKind.LOOP):
            # §5.2.8 T3: a MISSING arm is no longer evidence of anything — the
            # arm may simply leave the method, which the export cannot express
            # (it is deliberately exit-free) and the assembler completes. What
            # stays a defect is a construct that names NO outcome at all, or
            # one whose arm edge went out unlabeled: `flow` out of a branch
            # means the coarsening could not say which way control went.
            if not labels:
                findings.append(("branch-arity", _anchor(method, node)))
            elif node.construct_kind in _SWITCH_CONSTRUCTS:
                if not labels & {ExportCfgEdgeLabel.CASE, ExportCfgEdgeLabel.DEFAULT}:
                    findings.append(("branch-arity", _anchor(method, node)))
            elif ExportCfgEdgeLabel.FLOW in labels and len(outgoing[node.id]) > 1:
                # A construct whose ONLY successor is unlabeled is the recorded
                # convergent case (`if (c) { }` — both arms reach the same
                # statement, and one edge cannot carry two labels). More than
                # one successor with an unlabeled arm among them is not.
                findings.append(("unlabeled-arm", _anchor(method, node)))
        if node.kind is CfgNodeKind.LOOP:
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
        # A construct with an arm that goes nowhere leaves the method by that
        # arm (§5.2.8 T3) — as much a way out as a node with no successors.
        has_terminal = any(
            node.id not in outgoing or arms_leaving_method(node, set(outgoing[node.id]))
            for node in cfg.nodes
        )
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
