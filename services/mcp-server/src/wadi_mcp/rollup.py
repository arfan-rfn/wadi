"""Method-level roll-up of an ICFG (§8 progressive disclosure).

A 5,000-node statement-level graph would drown the context window these tools
exist to save, so every graph-returning tool answers at method granularity by
default. The roll-up is a *view* over the same artifact — computed from the
owning-method key every node carries (§7) — never a second schema.
"""

from typing import Any

from wadi_contracts import Icfg, IcfgNodeKind


def method_rollup(icfg: Icfg) -> dict[str, Any]:
    """Collapse an ICFG to its methods and the calls between them."""
    methods: dict[str, dict[str, Any]] = {}

    def method_entry(method_id: str, signature: str) -> dict[str, Any]:
        if method_id not in methods:
            methods[method_id] = {
                "id": method_id,
                "signature": signature,
                "badges": [],
                "doc_comment": None,
                "anchor": None,
                "calls": [],
            }
        return methods[method_id]

    for node in icfg.nodes:
        record = method_entry(node.method.id, node.method.signature)
        if node.kind is IcfgNodeKind.ENTRY:
            if record["anchor"] is None:
                record["anchor"] = node.anchor.model_dump(mode="json")
            if node.method_info is not None:
                record["badges"] = node.method_info.badges
                record["doc_comment"] = node.method_info.doc_comment
                # NOTE: method_info.signature is Joern's bare type signature
                # (return + params, no name) — method.signature stays the
                # display identity. Same trap as the frontend roll-up.
        elif node.kind is IcfgNodeKind.CALL and node.callee is not None:
            call: dict[str, Any] = {
                "callee_id": node.callee.id,
                "callee_signature": node.callee.signature,
                "line": node.anchor.start_line,
            }
            if node.sink is not None:
                call["sink"] = node.sink.value
            if node.remote_call_id is not None:
                call["remote_call_id"] = node.remote_call_id
            if node.mq_interaction_id is not None:
                call["mq_interaction_id"] = node.mq_interaction_id
            record["calls"].append(call)

    root = icfg.root_entry()
    return {
        "endpoint_id": icfg.endpoint_id,
        "snapshot_id": icfg.snapshot_id,
        "service_id": icfg.service_id,
        "detail": "methods",
        "root_method_id": root.method.id,
        "methods": list(methods.values()),
        "statement_counts": _statement_counts(icfg),
    }


def _statement_counts(icfg: Icfg) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in icfg.nodes:
        counts[node.method.id] = counts.get(node.method.id, 0) + 1
    return counts


def statement_detail(icfg: Icfg, method_id: str) -> dict[str, Any]:
    """Statement-level drill-down, scoped to one method (§8)."""
    nodes = [node for node in icfg.nodes if node.method.id == method_id]
    if not nodes:
        known = sorted({node.method.id for node in icfg.nodes})
        raise KeyError(f"method {method_id!r} is not part of this ICFG; known methods: {known}")
    node_ids = {node.id for node in nodes}
    edges = [edge for edge in icfg.edges if edge.source in node_ids or edge.target in node_ids]
    return {
        "endpoint_id": icfg.endpoint_id,
        "snapshot_id": icfg.snapshot_id,
        "service_id": icfg.service_id,
        "detail": "statements",
        "method_id": method_id,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
    }
