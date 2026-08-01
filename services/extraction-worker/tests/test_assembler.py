"""ICFG assembler unit tests — the algorithmic heart of extraction (§5.2)."""

import pytest
from worker_support import (
    CONTROLLER,
    HTTP_CALLSITE,
    REPO_CALLSITE,
    SERVICE_IMPL,
    petstore_like_export,
)

from wadi_contracts import (
    Confidence,
    IcfgEdgeKind,
    IcfgNodeKind,
    SinkKind,
)
from wadi_joern_client.export import (
    CfgNodeKind,
    ExportCall,
    ExportCfg,
    ExportCfgNode,
    ExportEndpoint,
    ExportMethod,
    ServiceExport,
)
from wadi_worker.assembler import Assembler, ExportIncompatibleError

SNAP = "snap_" + "a" * 16
SVC = "svc_" + "b" * 16


@pytest.fixture
def assembler() -> Assembler:
    return Assembler(snapshot_id=SNAP, service_id=SVC)


class TestPetstoreAssembly:
    def test_endpoint_created_with_derived_identity(self, assembler: Assembler) -> None:
        result = assembler.assemble(petstore_like_export())
        assert len(result.endpoints) == 1
        endpoint = result.endpoints[0]
        assert endpoint.simplified_uri == "/pets/{?}"
        assert endpoint.response_type == "com.acme.pets.Pet"
        assert endpoint.auth.authenticated is None  # honest unknown pre-Phase-2

    def test_icfg_is_interprocedural(self, assembler: Assembler) -> None:
        result = assembler.assemble(petstore_like_export())
        icfg = result.icfgs[0]
        # Root is the controller's entry.
        assert icfg.root_entry().id == f"m{CONTROLLER}:entry"
        # The DI-resolved call is inlined: call and return edges cross methods.
        edge_pairs = {(e.source, e.target, e.kind) for e in icfg.edges}
        assert (
            f"m{CONTROLLER}:n101",
            f"m{SERVICE_IMPL}:entry",
            IcfgEdgeKind.CALL,
        ) in edge_pairs
        assert (
            f"m{SERVICE_IMPL}:exit",
            f"m{CONTROLLER}:n101",
            IcfgEdgeKind.RETURN,
        ) in edge_pairs

    def test_branch_carries_condition_and_labels(self, assembler: Assembler) -> None:
        icfg = assembler.assemble(petstore_like_export()).icfgs[0]
        branch = next(n for n in icfg.nodes if n.kind is IcfgNodeKind.BRANCH)
        assert branch.condition is not None
        assert "isBlank" in branch.condition.expression
        kinds = {e.kind for e in icfg.edges}
        assert IcfgEdgeKind.TRUE_BRANCH in kinds
        assert IcfgEdgeKind.FALSE_BRANCH in kinds

    def test_sink_markers_on_call_nodes(self, assembler: Assembler) -> None:
        icfg = assembler.assemble(petstore_like_export()).icfgs[0]
        db_node = next(n for n in icfg.nodes if n.id == f"m{SERVICE_IMPL}:n{REPO_CALLSITE}")
        assert db_node.sink is SinkKind.DB
        http_node = next(n for n in icfg.nodes if n.id == f"m{SERVICE_IMPL}:n{HTTP_CALLSITE}")
        assert http_node.sink is SinkKind.HTTP_CLIENT
        assert http_node.remote_call_id is not None

    def test_remote_call_artifact_links_to_icfg_marker(self, assembler: Assembler) -> None:
        result = assembler.assemble(petstore_like_export())
        assert len(result.remote_calls) == 1
        call = result.remote_calls[0]
        assert call.url == "http://inventory:8080/stock/{id}"
        assert call.url_confidence is Confidence.HEURISTIC
        icfg = result.icfgs[0]
        marker = next(n for n in icfg.nodes if n.remote_call_id is not None)
        assert marker.remote_call_id == call.id  # same derived id on both sides

    def test_method_info_and_badges(self, assembler: Assembler) -> None:
        icfg = assembler.assemble(petstore_like_export()).icfgs[0]
        root = icfg.root_entry()
        assert root.method_info is not None
        assert root.method_info.doc_comment == "Fetches one pet by id."
        assert root.method_info.badges == ["endpoint"]
        impl_entry = next(n for n in icfg.nodes if n.id == f"m{SERVICE_IMPL}:entry")
        assert impl_entry.method_info is not None
        assert impl_entry.method_info.badges == ["calls-http", "touches-db"]

    def test_data_models(self, assembler: Assembler) -> None:
        result = assembler.assemble(petstore_like_export())
        assert len(result.data_models) == 1
        model = result.data_models[0]
        assert model.entity == "Pet"
        assert model.storage_name == "pets"

    def test_unresolved_callee_not_inlined_but_kept(self, assembler: Assembler) -> None:
        icfg = assembler.assemble(petstore_like_export()).icfgs[0]
        repo_call = next(n for n in icfg.nodes if n.id == f"m{SERVICE_IMPL}:n{REPO_CALLSITE}")
        assert repo_call.callee is not None  # the fact is kept (P10)
        # …but no interior was fabricated for the library method.
        assert not any("CrudRepository" in n.method.signature for n in icfg.nodes)

    def test_return_nodes_flow_to_exit(self, assembler: Assembler) -> None:
        icfg = assembler.assemble(petstore_like_export()).icfgs[0]
        edge_pairs = {(e.source, e.target) for e in icfg.edges}
        assert (f"m{SERVICE_IMPL}:n202", f"m{SERVICE_IMPL}:exit") in edge_pairs
        assert (f"m{SERVICE_IMPL}:n209", f"m{SERVICE_IMPL}:exit") in edge_pairs


def _minimal_method(mid: int, name: str) -> ExportMethod:
    return ExportMethod(
        id=mid,
        full_name=f"com.acme.{name}:void()",
        signature=f"{name}()",
        filename="src/A.java",
        line=1,
        line_end=2,
        code=f"void {name}()",
    )


def _call_node(nid: int, callee_id: int, callee: str) -> ExportCfgNode:
    return ExportCfgNode(
        id=nid,
        kind=CfgNodeKind.CALL,
        code=f"{callee}();",
        line=1,
        line_end=1,
        call=ExportCall(
            callee_full_name=f"com.acme.{callee}:void()", callee_id=callee_id, resolved=True
        ),
    )


class TestEdgeCases:
    def test_mutual_recursion_terminates_and_builds_cycle(self, assembler: Assembler) -> None:
        export = ServiceExport(
            language="java",
            methods=[_minimal_method(1, "a"), _minimal_method(2, "b")],
            cfgs=[
                ExportCfg(method_id=1, nodes=[_call_node(11, 2, "b")], edges=[]),
                ExportCfg(method_id=2, nodes=[_call_node(21, 1, "a")], edges=[]),
            ],
            endpoints=[ExportEndpoint(method_id=1, http_method="GET", uri="/recurse")],
            sinks=[],
        )
        icfg = assembler.assemble(export).icfgs[0]
        assert icfg.root_entry().id == "m1:entry"  # cycle didn't break root detection
        edge_pairs = {(e.source, e.target, e.kind) for e in icfg.edges}
        # a→b and the recursive b→a call edge both exist.
        assert ("m1:n11", "m2:entry", IcfgEdgeKind.CALL) in edge_pairs
        assert ("m2:n21", "m1:entry", IcfgEdgeKind.CALL) in edge_pairs

    def test_method_with_no_cfg_gets_entry_exit(self, assembler: Assembler) -> None:
        export = ServiceExport(
            language="java",
            methods=[_minimal_method(1, "handler")],
            cfgs=[],
            endpoints=[ExportEndpoint(method_id=1, http_method="POST", uri="/empty")],
            sinks=[],
        )
        icfg = assembler.assemble(export).icfgs[0]
        assert {n.id for n in icfg.nodes} == {"m1:entry", "m1:exit"}
        assert [(e.source, e.target) for e in icfg.edges] == [("m1:entry", "m1:exit")]

    def test_zero_line_numbers_clamped_to_valid_anchor(self, assembler: Assembler) -> None:
        method = _minimal_method(1, "synthetic").model_copy(update={"line": 0, "line_end": 0})
        export = ServiceExport(
            language="java",
            methods=[method],
            cfgs=[],
            endpoints=[ExportEndpoint(method_id=1, http_method="GET", uri="/synthetic")],
            sinks=[],
        )
        icfg = assembler.assemble(export).icfgs[0]
        assert icfg.root_entry().anchor.start_line == 1  # contract requires >= 1

    def test_endpoint_referencing_missing_method_skipped(self, assembler: Assembler) -> None:
        export = ServiceExport(
            language="java",
            methods=[],
            cfgs=[],
            endpoints=[ExportEndpoint(method_id=999, http_method="GET", uri="/ghost")],
            sinks=[],
        )
        result = assembler.assemble(export)
        assert result.endpoints == []
        assert result.icfgs == []

    def test_incompatible_export_version_rejected(self, assembler: Assembler) -> None:
        export = petstore_like_export().model_copy(update={"export_schema_version": "2.0.0"})
        with pytest.raises(ExportIncompatibleError):
            assembler.assemble(export)

    def test_two_endpoints_sharing_methods_get_independent_icfgs(
        self, assembler: Assembler
    ) -> None:
        shared = _minimal_method(3, "shared")
        handler_a = _minimal_method(1, "a")
        handler_b = _minimal_method(2, "b")
        export = ServiceExport(
            language="java",
            methods=[handler_a, handler_b, shared],
            cfgs=[
                ExportCfg(method_id=1, nodes=[_call_node(11, 3, "shared")], edges=[]),
                ExportCfg(method_id=2, nodes=[_call_node(21, 3, "shared")], edges=[]),
            ],
            endpoints=[
                ExportEndpoint(method_id=1, http_method="GET", uri="/a"),
                ExportEndpoint(method_id=2, http_method="GET", uri="/b"),
            ],
            sinks=[],
        )
        result = assembler.assemble(export)
        assert len(result.icfgs) == 2
        for icfg in result.icfgs:
            assert any(n.id == "m3:entry" for n in icfg.nodes)
            icfg.root_entry()  # unique root in each
