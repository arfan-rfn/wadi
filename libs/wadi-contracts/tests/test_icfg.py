"""ICFG artifact tests: graph integrity is enforced by the contract itself."""

import pytest
from pydantic import ValidationError

from wadi_contracts.enums import IcfgEdgeKind, IcfgNodeKind, SinkKind
from wadi_contracts.icfg import (
    BranchCondition,
    Icfg,
    IcfgEdge,
    IcfgNode,
    MethodInfo,
    OperandOrigin,
    OperandRef,
)
from wadi_contracts.ids import endpoint_id, method_id, remote_call_id
from wadi_contracts.source import MethodRef, SourceAnchor


def _node(
    node_id: str,
    kind: IcfgNodeKind,
    method: MethodRef,
    line: int = 10,
    **kwargs: object,
) -> IcfgNode:
    return IcfgNode(
        id=node_id,
        kind=kind,
        anchor=SourceAnchor(file="src/A.java", start_line=line, end_line=line),
        source_text="return orderService.get(id);",
        method=method,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def method(svc_id: str) -> MethodRef:
    sig = "com.acme.OrderController.getOrder(java.lang.String)"
    return MethodRef(id=method_id(svc_id, sig), signature=sig)


@pytest.fixture
def ep_id(svc_id: str) -> str:
    return endpoint_id(svc_id, "GET", "/orders/{id}")


class TestIcfgIntegrity:
    def test_minimal_valid_graph(self, svc_id: str, method: MethodRef, ep_id: str) -> None:
        icfg = Icfg(
            snapshot_id="snap",
            service_id=svc_id,
            endpoint_id=ep_id,
            entry_node_id="n1",
            nodes=[
                _node(
                    "n1",
                    IcfgNodeKind.ENTRY,
                    method,
                    method_info=MethodInfo(signature=method.signature),
                ),
                _node("n2", IcfgNodeKind.STATEMENT, method, line=11),
                _node("n3", IcfgNodeKind.EXIT, method, line=12),
            ],
            edges=[
                IcfgEdge(source="n1", target="n2", kind=IcfgEdgeKind.FLOW),
                IcfgEdge(source="n2", target="n3", kind=IcfgEdgeKind.FLOW),
            ],
        )
        assert icfg.root_entry().id == "n1"

    def test_duplicate_node_ids_rejected(self, svc_id: str, method: MethodRef, ep_id: str) -> None:
        with pytest.raises(ValidationError, match="duplicate node id"):
            Icfg(
                snapshot_id="snap",
                service_id=svc_id,
                endpoint_id=ep_id,
                entry_node_id="n1",
                nodes=[
                    _node("n1", IcfgNodeKind.ENTRY, method),
                    _node("n1", IcfgNodeKind.STATEMENT, method),
                ],
            )

    def test_dangling_edge_rejected(self, svc_id: str, method: MethodRef, ep_id: str) -> None:
        with pytest.raises(ValidationError, match="unknown node"):
            Icfg(
                snapshot_id="snap",
                service_id=svc_id,
                endpoint_id=ep_id,
                entry_node_id="n1",
                nodes=[_node("n1", IcfgNodeKind.ENTRY, method)],
                edges=[IcfgEdge(source="n1", target="ghost", kind=IcfgEdgeKind.FLOW)],
            )

    def test_entry_node_id_must_reference_an_entry(
        self, svc_id: str, method: MethodRef, ep_id: str
    ) -> None:
        with pytest.raises(ValidationError, match="entry node"):
            Icfg(
                snapshot_id="snap",
                service_id=svc_id,
                endpoint_id=ep_id,
                entry_node_id="n1",  # a statement, not an entry
                nodes=[_node("n1", IcfgNodeKind.STATEMENT, method)],
            )

    def test_entry_node_id_must_exist(self, svc_id: str, method: MethodRef, ep_id: str) -> None:
        with pytest.raises(ValidationError, match="entry node"):
            Icfg(
                snapshot_id="snap",
                service_id=svc_id,
                endpoint_id=ep_id,
                entry_node_id="ghost",
                nodes=[_node("n1", IcfgNodeKind.ENTRY, method)],
            )

    def test_explicit_root_survives_recursion_into_handler(
        self, svc_id: str, method: MethodRef, ep_id: str
    ) -> None:
        # A recursive call edge back into the handler's entry must not
        # break root identification (the reason the root is explicit).
        icfg = Icfg(
            snapshot_id="snap",
            service_id=svc_id,
            endpoint_id=ep_id,
            entry_node_id="n1",
            nodes=[
                _node("n1", IcfgNodeKind.ENTRY, method),
                _node("n2", IcfgNodeKind.CALL, method, line=20, callee=method),
            ],
            edges=[
                IcfgEdge(source="n1", target="n2", kind=IcfgEdgeKind.FLOW),
                IcfgEdge(source="n2", target="n1", kind=IcfgEdgeKind.CALL),
            ],
        )
        assert icfg.root_entry().id == "n1"

    def test_interprocedural_call_edges(self, svc_id: str, method: MethodRef, ep_id: str) -> None:
        callee_sig = "com.acme.OrderService.get(java.lang.String)"
        callee = MethodRef(id=method_id(svc_id, callee_sig), signature=callee_sig)
        icfg = Icfg(
            snapshot_id="snap",
            service_id=svc_id,
            endpoint_id=ep_id,
            entry_node_id="n1",
            nodes=[
                _node("n1", IcfgNodeKind.ENTRY, method),
                _node("n2", IcfgNodeKind.CALL, method, line=11, callee=callee),
                _node("n3", IcfgNodeKind.ENTRY, callee, line=30),
                _node("n4", IcfgNodeKind.EXIT, callee, line=35),
                _node("n5", IcfgNodeKind.EXIT, method, line=12),
            ],
            edges=[
                IcfgEdge(source="n1", target="n2", kind=IcfgEdgeKind.FLOW),
                IcfgEdge(source="n2", target="n3", kind=IcfgEdgeKind.CALL),
                IcfgEdge(source="n4", target="n2", kind=IcfgEdgeKind.RETURN),
                IcfgEdge(source="n2", target="n5", kind=IcfgEdgeKind.FLOW),
            ],
        )
        # n3 is an entry but has an incoming call edge — root is still n1.
        assert icfg.root_entry().id == "n1"


class TestNodeKindPayloads:
    def test_condition_only_on_branch_or_loop(self, method: MethodRef) -> None:
        condition = BranchCondition(
            expression="order.getTotal() > 100",
            operands=[OperandRef(name="order", origin=OperandOrigin.PAYLOAD)],
        )
        node = _node("b1", IcfgNodeKind.BRANCH, method, condition=condition)
        assert node.condition is not None
        _node("l1", IcfgNodeKind.LOOP, method, condition=condition)
        with pytest.raises(ValidationError, match="branch/loop"):
            _node("s1", IcfgNodeKind.STATEMENT, method, condition=condition)

    def test_callee_only_on_call(self, method: MethodRef) -> None:
        with pytest.raises(ValidationError, match="call nodes"):
            _node("s1", IcfgNodeKind.STATEMENT, method, callee=method)

    def test_method_info_only_on_entry(self, method: MethodRef) -> None:
        info = MethodInfo(signature=method.signature)
        with pytest.raises(ValidationError, match="entry nodes"):
            _node("s1", IcfgNodeKind.STATEMENT, method, method_info=info)

    def test_remote_call_marker_only_on_call(self, svc_id: str, method: MethodRef) -> None:
        rc_id = remote_call_id(svc_id, "src/A.java", 11, "http://svc-b/x")
        node = _node(
            "c1",
            IcfgNodeKind.CALL,
            method,
            callee=method,
            sink=SinkKind.HTTP_CLIENT,
            remote_call_id=rc_id,
        )
        assert node.sink is SinkKind.HTTP_CLIENT
        with pytest.raises(ValidationError, match="call nodes"):
            _node("s1", IcfgNodeKind.STATEMENT, method, remote_call_id=rc_id)

    def test_anchor_line_range_validated(self, method: MethodRef) -> None:
        with pytest.raises(ValidationError, match="end_line"):
            IcfgNode(
                id="n1",
                kind=IcfgNodeKind.STATEMENT,
                anchor=SourceAnchor(file="A.java", start_line=10, end_line=5),
                source_text="x",
                method=method,
            )
