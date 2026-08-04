"""Per-endpoint interprocedural control-flow graph artifact (§7).

Design invariants enforced here (not left to writers):

- node ids unique; every edge references existing nodes;
- exactly one entry node (the endpoint handler's entry);
- kind-specific payloads (condition / callee / method_info) appear only on the
  node kinds they belong to;
- every node carries a source anchor, its one-line source text, and its
  owning-method ref — the roll-up key for progressive disclosure.

Full source bodies are never duplicated into artifacts — served on demand
(§5.3).
"""

import re
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import CalleeUnboundReason, IcfgEdgeKind, IcfgNodeKind, SinkKind
from wadi_contracts.source import MethodRef, SourceAnchor

_RC_ID = re.compile(r"^rc_[0-9a-f]{16}$")


class OperandOrigin(StrEnum):
    PAYLOAD = "payload"
    LOCAL = "local"
    FIELD = "field"
    CONFIG = "config"
    UNKNOWN = "unknown"


class OperandRef(WadiModel):
    """A structured reference to one operand of a branch condition."""

    name: str = Field(min_length=1)
    origin: OperandOrigin = OperandOrigin.UNKNOWN


class BranchCondition(WadiModel):
    """Branch/loop condition: expression text + operand refs where recoverable (§7)."""

    expression: str = Field(min_length=1)
    operands: list[OperandRef] = Field(default_factory=list[OperandRef])


class MethodParam(WadiModel):
    name: str
    type_name: str | None = None


class MethodInfo(WadiModel):
    """Carried by method entry nodes: signature, typing, docs, behavior badges (§7)."""

    signature: str = Field(min_length=1)
    params: list[MethodParam] = Field(default_factory=list[MethodParam])
    return_type: str | None = None
    doc_comment: str | None = None
    badges: list[str] = Field(
        default_factory=list[str],
        description="Derived behavior badges from tags, e.g. 'touches-db', 'calls-http'",
    )


class IcfgNode(WadiModel):
    id: str = Field(min_length=1)
    kind: IcfgNodeKind
    anchor: SourceAnchor
    source_text: str = Field(
        description="The node's one-line source text (graph labels are real code)"
    )
    method: MethodRef = Field(description="Owning method — the roll-up key (§7)")
    construct_kind: str | None = Field(
        default=None,
        description=(
            "Which Java construct this node is (§5.2.8): if | switch | "
            "switch-arrow | for | foreach | while | do-while | try | catch | "
            "finally | throw | break | continue | goto. None = plain statement "
            "or an artifact predating 1.8.0 (unknown, not 'statement' — P10). "
            "(Named construct_kind because pydantic reserves `construct`.)"
        ),
    )
    condition: BranchCondition | None = None
    callee: MethodRef | None = None
    callee_unbound_reason: CalleeUnboundReason | None = Field(
        default=None,
        description=(
            "Why this call's target has no interior in the graph (§5.4.2 T5): "
            "lombok-generated | inherited-external | compiler-generated | "
            "third-party | ambiguous-overload | unresolved-receiver. The node "
            "is ALWAYS kept — a call with no visible body still runs — so this "
            "is what lets a consumer say 'no source to analyse' instead of "
            "rendering a silent dead end (P10). None = the callee is in this "
            "graph, or the artifact predates 1.12.0 (unknown, not 'bound')."
        ),
    )
    sink: SinkKind | None = None
    remote_call_id: str | None = Field(
        default=None,
        pattern=r"^rc_[0-9a-f]{16}$",
        description=(
            "DEPRECATED (since 1.1.0): first entry of remote_call_ids, kept for "
            "readers predating multi-candidate URL slicing. Prefer remote_call_ids."
        ),
    )
    remote_call_ids: list[str] = Field(
        default_factory=list[str],
        description=(
            "All RemoteCall facts at this call site — one per sliced candidate "
            "URL (§5.2 over-approximation). Order matches the export."
        ),
    )
    mq_interaction_id: str | None = Field(default=None, pattern=r"^mq_[0-9a-f]{16}$")
    method_info: MethodInfo | None = None

    @model_validator(mode="after")
    def _kind_specific_payloads(self) -> Self:
        # Since 1.8.0 (§5.2.8) conditions live beyond branch/loop nodes: a
        # switch-arrow CARRIER (`return switch(n){…}`) is a return/call/
        # statement node carrying the selector. Only synthetic entry/exit can
        # never hold one — same rule as markers and callees below.
        synthetic = (IcfgNodeKind.ENTRY, IcfgNodeKind.EXIT)
        if self.condition is not None and self.kind in synthetic:
            raise ValueError(f"condition is not valid on {self.kind} nodes")
        if self.construct_kind is not None and self.kind in synthetic:
            raise ValueError(f"construct_kind is not valid on {self.kind} nodes")
        # 1.8.0: a callee rides any real statement — `return svc.find(id)` is a
        # RETURN node whose call resolves interprocedurally, a sink inside a
        # branch condition puts the call on the BRANCH node (§5.2.8).
        if self.callee is not None and self.kind in synthetic:
            raise ValueError(f"callee is not valid on {self.kind} nodes")
        # 1.12.0 (§5.4.2 T5): the reason explains a CALLEE that has no interior,
        # so it is meaningless without one — and a reason on a callee the graph
        # does contain would contradict itself (the writer's own bookkeeping is
        # what the invariant guards).
        if self.callee_unbound_reason is not None and self.callee is None:
            raise ValueError("callee_unbound_reason requires a callee")
        if self.method_info is not None and self.kind is not IcfgNodeKind.ENTRY:
            raise ValueError(f"method_info is only valid on entry nodes, not {self.kind}")
        # Markers anchor to the coarsened statement, which is not always a
        # CALL node: `return client.get(...)` coarsens to RETURN and
        # `if (client.get(...) != null)` to BRANCH. Only the synthetic
        # entry/exit nodes can never carry a call site.
        has_marker = bool(self.remote_call_id or self.remote_call_ids or self.mq_interaction_id)
        if has_marker and self.kind in (IcfgNodeKind.ENTRY, IcfgNodeKind.EXIT):
            raise ValueError("remote-call / MQ markers are not valid on entry/exit nodes")
        for rc_id in self.remote_call_ids:
            if not _RC_ID.match(rc_id):
                raise ValueError(f"remote_call_ids entries must be rc_ ids, got {rc_id!r}")
        # Legacy 1.0.x artifacts carry only the singular field; artifacts are
        # never rewritten in place (§7), so that shape must stay readable.
        if self.remote_call_ids and self.remote_call_id != self.remote_call_ids[0]:
            raise ValueError("remote_call_id must equal remote_call_ids[0] (back-compat invariant)")
        return self


class IcfgEdge(WadiModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: IcfgEdgeKind
    case_values: list[str] = Field(
        default_factory=list[str],
        description=(
            "Stacked case labels on a `case` edge (source text of each value); "
            "empty on every other kind (§5.2.8)."
        ),
    )
    back: bool = Field(
        default=False,
        description="Cycle-closing loop edge (§5.2.8); orthogonal to kind (do-while: true+back)",
    )

    @model_validator(mode="after")
    def _case_values_only_on_case(self) -> Self:
        if self.case_values and self.kind is not IcfgEdgeKind.CASE:
            raise ValueError(f"case_values are only valid on case edges, not {self.kind}")
        return self


class Icfg(ArtifactEnvelope):
    """The assembled ICFG of one endpoint (statement-granularity, coarsened).

    The root is *explicit* (``entry_node_id``), never inferred from topology:
    a recursive flow back into the handler would give the root incoming
    edges, so "the entry with no incoming edges" is not a sound definition.
    """

    endpoint_id: str = Field(pattern=r"^ep_[0-9a-f]{16}$")
    entry_node_id: str = Field(
        min_length=1, description="The endpoint handler's entry node (explicit root)"
    )
    nodes: list[IcfgNode] = Field(min_length=1)
    edges: list[IcfgEdge] = Field(default_factory=list[IcfgEdge])

    @model_validator(mode="after")
    def _graph_integrity(self) -> Self:
        node_ids: set[str] = set()
        entry_nodes: dict[str, IcfgNode] = {}
        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"duplicate node id: {node.id!r}")
            node_ids.add(node.id)
            if node.kind is IcfgNodeKind.ENTRY:
                entry_nodes[node.id] = node
        root = entry_nodes.get(self.entry_node_id)
        if root is None:
            raise ValueError(
                f"entry_node_id {self.entry_node_id!r} must reference an entry node in the graph"
            )
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(f"edge source references unknown node: {edge.source!r}")
            if edge.target not in node_ids:
                raise ValueError(f"edge target references unknown node: {edge.target!r}")
        return self

    def root_entry(self) -> IcfgNode:
        """The endpoint handler's entry node."""
        return next(node for node in self.nodes if node.id == self.entry_node_id)
