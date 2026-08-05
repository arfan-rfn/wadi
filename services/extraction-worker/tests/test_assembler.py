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
    CalleeUnboundReason,
    Confidence,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    Reachability,
    RemoteCall,
    SinkKind,
)
from wadi_joern_client.export import (
    CfgNodeKind,
    ExportAsyncRoot,
    ExportCall,
    ExportCfg,
    ExportCfgEdge,
    ExportCfgEdgeLabel,
    ExportCfgNode,
    ExportEndpoint,
    ExportMethod,
    ExportSink,
    ExportUnreachableSink,
    ServiceExport,
    SinkValueConfidence,
)
from wadi_joern_client.export import (
    UnboundReason as ExportUnboundReason,
)
from wadi_worker.assembler import Assembler, ExportIncompatibleError

SNAP = "snap_" + "a" * 16
SVC = "svc_" + "b" * 16

_UNSET = "<unset>"
"""Distinguishes 'the caller said nothing' from an explicit `None`, which for a
loop is the meaningful value: `for (;;)` states no condition."""


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

    def test_sink_marker_survives_non_call_statement_kinds(self, assembler: Assembler) -> None:
        # `return restTemplate.getForObject(...)` coarsens to a RETURN
        # statement, not CALL — the sink marker must still land on the ICFG
        # node, or the endpoint page shows "no remote calls" for a
        # call-rich endpoint (P10).
        export = petstore_like_export()
        cfg = next(c for c in export.cfgs if c.method_id == SERVICE_IMPL)
        site = next(n for n in cfg.nodes if n.id == HTTP_CALLSITE)
        site.kind = CfgNodeKind.RETURN
        result = assembler.assemble(export)
        marker = next(
            n for n in result.icfgs[0].nodes if n.id == f"m{SERVICE_IMPL}:n{HTTP_CALLSITE}"
        )
        assert marker.kind is IcfgNodeKind.RETURN
        assert marker.sink is SinkKind.HTTP_CLIENT
        assert marker.remote_call_ids == [result.remote_calls[0].id]

    def test_remote_call_artifact_links_to_icfg_marker(self, assembler: Assembler) -> None:
        result = assembler.assemble(petstore_like_export())
        assert len(result.remote_calls) == 1
        call = result.remote_calls[0]
        assert call.url == "{?}/stock/{?}"
        assert call.url_confidence is Confidence.HEURISTIC
        icfg = result.icfgs[0]
        marker = next(n for n in icfg.nodes if n.remote_call_id is not None)
        assert marker.remote_call_id == call.id  # same derived id on both sides
        assert marker.remote_call_ids == [call.id]

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


class TestMultiCandidateSinks:
    """Export 2.0.0: one sink row per candidate URL at one call site (§5.2)."""

    def _export_with_two_candidates(self) -> ServiceExport:
        handler = _minimal_method(1, "handler")
        node = ExportCfgNode(
            id=11,
            kind=CfgNodeKind.CALL,
            code="restTemplate.getForObject(base + path, X.class);",
            line=5,
            line_end=5,
            call=ExportCall(
                callee_full_name="org.springframework.web.client.RestTemplate.getForObject",
                resolved=False,
            ),
        )
        candidates = [
            ExportSink(
                node_id=11,
                call_id=911,
                method_id=1,
                kind="http-client",
                value="http://orders:8080/orders/{?}",
                value_confidence=SinkValueConfidence.HIGH,
                http_verb="GET",
                mechanism="resttemplate",
                evidence="branch true: base <- ORDERS_URL",
            ),
            ExportSink(
                node_id=11,
                call_id=911,
                method_id=1,
                kind="http-client",
                value="http://billing:8080/orders/{?}",
                value_confidence=SinkValueConfidence.HIGH,
                http_verb="GET",
                mechanism="resttemplate",
                evidence="branch false: base <- BILLING_URL",
            ),
        ]
        return ServiceExport(
            language="java",
            methods=[handler],
            cfgs=[ExportCfg(method_id=1, nodes=[node], edges=[])],
            endpoints=[ExportEndpoint(method_id=1, http_method="GET", uri="/x")],
            sinks=candidates,
        )

    def test_one_remote_call_fact_per_candidate(self, assembler: Assembler) -> None:
        result = assembler.assemble(self._export_with_two_candidates())
        assert len(result.remote_calls) == 2
        urls = {c.url for c in result.remote_calls}
        assert urls == {"http://orders:8080/orders/{?}", "http://billing:8080/orders/{?}"}
        assert all(c.url_confidence is Confidence.HIGH for c in result.remote_calls)
        assert {c.evidence for c in result.remote_calls} == {
            "branch true: base <- ORDERS_URL",
            "branch false: base <- BILLING_URL",
        }

    def test_icfg_node_carries_all_candidates(self, assembler: Assembler) -> None:
        result = assembler.assemble(self._export_with_two_candidates())
        marker = next(n for n in result.icfgs[0].nodes if n.remote_call_ids)
        assert len(marker.remote_call_ids) == 2
        assert marker.remote_call_id == marker.remote_call_ids[0]
        assert set(marker.remote_call_ids) == {c.id for c in result.remote_calls}


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
        export = petstore_like_export().model_copy(update={"export_schema_version": "3.0.0"})
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


class TestUnboundCalleeReason:
    """§5.4.2 T5 — an unopenable call node must carry WHY it is unopenable.

    The node is never dropped: `order.setId(x)` runs at runtime whether or not
    Lombok left a body to read. What the graph owes the reader is the reason,
    so "no source to analyse" is a stated fact rather than an unexplained
    dead end (P10).
    """

    def _assemble(self, reason: ExportUnboundReason | None) -> IcfgNode:
        export = petstore_like_export()
        for cfg in export.cfgs:
            for node in cfg.nodes:
                if node.id == REPO_CALLSITE and node.call is not None:
                    node.call.unbound_reason = reason
        icfg = Assembler(snapshot_id="snap_x", service_id="svc_x").assemble(export).icfgs[0]
        return next(n for n in icfg.nodes if n.id.endswith(f":n{REPO_CALLSITE}"))

    def test_every_reason_reaches_the_contract(self) -> None:
        """The mapping table's whole purpose (see the comment above it in
        assembler.py) is that a reason code added upstream fails HERE rather
        than reaching the UI unlabelled — which only holds if something checks
        the table is total. Driven through the real assembly path rather than
        the table itself, so an unmapped member cannot pass by degrading to
        `None`, i.e. "this callee opens fine": the exact silent dead end T5
        exists to remove (P10).
        """
        for export_reason in ExportUnboundReason:
            node = self._assemble(export_reason)
            assert node.callee_unbound_reason is not None, export_reason
            assert node.callee_unbound_reason.value == export_reason.value
        node = self._assemble(ExportUnboundReason.INHERITED_EXTERNAL)
        assert node.callee_unbound_reason is CalleeUnboundReason.INHERITED_EXTERNAL
        # The node itself survives — losing it is what would make the map lie.
        assert node.callee is not None

    def test_pre_2_6_0_export_leaves_the_reason_unknown(self) -> None:
        """Absent upstream is 'unknown', never 'it bound' — older exports are
        replayed as-is (§7 artifacts are never rewritten in place)."""
        assert self._assemble(None).callee_unbound_reason is None

    def test_a_call_resolved_into_the_closure_is_never_labelled(self) -> None:
        """The export is service-wide, the closure endpoint-scoped: a call can
        be unbound in one and present in the other. Labelling a node the user
        can actually open would be a lie in the opposite direction.
        """
        export = petstore_like_export()
        for cfg in export.cfgs:
            for node in cfg.nodes:
                # The controller's call into the service impl DOES resolve.
                if node.call is not None and node.call.callee_id == SERVICE_IMPL:
                    node.call.unbound_reason = ExportUnboundReason.THIRD_PARTY
        icfg = Assembler(snapshot_id="snap_x", service_id="svc_x").assemble(export).icfgs[0]
        resolved = [
            n
            for n in icfg.nodes
            if n.callee is not None and "PetServiceImpl.findPet" in n.callee.signature
        ]
        assert resolved, "expected the DI-resolved call node"
        assert all(n.callee_unbound_reason is None for n in resolved)


class TestArmsLeavingTheMethod:
    """§5.2.8 T3 — the arm not taken, when there is nothing left to take it to.

    A construct that ends its method has no successor statement for the untaken
    arm, and the export is deliberately exit-free, so the raw CFG goes silent
    exactly where the graph should say "on false, the method returns". The exit
    node belongs to the assembler, so arity completes here.
    """

    def _icfg_edges(
        self, nodes: list[ExportCfgNode], edges: list[ExportCfgEdge]
    ) -> set[tuple[str, str, IcfgEdgeKind]]:
        export = ServiceExport(
            language="java",
            methods=[_minimal_method(1, "handler")],
            cfgs=[ExportCfg(method_id=1, nodes=nodes, edges=edges)],
            endpoints=[ExportEndpoint(method_id=1, http_method="GET", uri="/t")],
            sinks=[],
        )
        icfg = Assembler(snapshot_id=SNAP, service_id=SVC).assemble(export).icfgs[0]
        return {(e.source, e.target, e.kind) for e in icfg.edges}

    def _node(
        self,
        nid: int,
        kind: CfgNodeKind = CfgNodeKind.STATEMENT,
        construct_kind: str | None = None,
        condition_code: str | None = _UNSET,
    ) -> ExportCfgNode:
        # A conditional loop states its condition in a real export; only
        # `for (;;)` states none. That is the discriminator T3 uses to refuse
        # an exit arm to a loop with no exit test, so it has to be faithful —
        # and an explicit `None` from the caller has to survive as `None`.
        if condition_code == _UNSET:
            condition_code = "i < n" if construct_kind in {"for", "while", "do-while"} else None
        return ExportCfgNode(
            id=nid,
            kind=kind,
            code=f"s{nid}",
            line=nid,
            line_end=nid,
            construct_kind=construct_kind,
            condition_code=condition_code,
        )

    def test_trailing_if_gains_its_false_arm(self) -> None:
        # `void h(int n) { if (n > 0) { hits += n; } }` — before T3 the false
        # path was absent from the assembled graph too: the exit patch keys on
        # has-any-out-edge, and a branch with one arm looks connected.
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.BRANCH, "if"), self._node(2)],
            [ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.TRUE)],
        )
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.FALSE_BRANCH) in edges
        assert ("m1:n1", "m1:n2", IcfgEdgeKind.TRUE_BRANCH) in edges

    def test_trailing_loop_gains_its_exit_arm_but_never_a_body(self) -> None:
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.LOOP, "for"), self._node(2)],
            [
                ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.TRUE),
                ExportCfgEdge(source=2, target=1, label=ExportCfgEdgeLabel.FLOW, back=True),
            ],
        )
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.FALSE_BRANCH) in edges
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.TRUE_BRANCH) not in edges

    def test_an_unconditional_loop_is_never_given_an_exit_arm(self) -> None:
        """`void h(int n) { while (true) { hits += n; } }` — §5.2.8 T3.

        Indistinguishable from a trailing loop by label set alone, so the
        condition is what tells them apart. Completing a `false` arm here
        would draw an exit path out of a loop that has no exit test, on the
        one surface whose whole claim is that the graph is honest.
        """
        for construct, condition in (("while", "true"), ("do-while", "true"), ("for", None)):
            edges = self._icfg_edges(
                [
                    self._node(1, CfgNodeKind.LOOP, construct, condition_code=condition),
                    self._node(2),
                ],
                [
                    ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.TRUE),
                    ExportCfgEdge(source=2, target=1, label=ExportCfgEdgeLabel.FLOW, back=True),
                ],
            )
            assert ("m1:n1", "m1:exit", IcfgEdgeKind.FALSE_BRANCH) not in edges, construct

    def test_empty_body_loop_is_never_given_a_body(self) -> None:
        # The body arm is missing because there IS no body (a recorded
        # non-representable). Completing it would assert a body that does not
        # exist AND claim that body exits the method.
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.LOOP, "while"), self._node(2, CfgNodeKind.RETURN)],
            [ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.FALSE)],
        )
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.TRUE_BRANCH) not in edges

    def test_default_less_trailing_switch_gains_its_no_match_path(self) -> None:
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.BRANCH, "switch"), self._node(2), self._node(3)],
            [
                ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.CASE, case_values=["0"]),
                ExportCfgEdge(source=1, target=3, label=ExportCfgEdgeLabel.CASE, case_values=["1"]),
            ],
        )
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.DEFAULT) in edges

    def test_convergent_branch_is_not_given_a_second_way_out(self) -> None:
        # `if (c) { }` with no else: both outcomes reach the same statement, so
        # the single unlabeled edge already IS the arm. An exit edge on top
        # would assert a path out of the method that the source does not have.
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.BRANCH, "if"), self._node(2, CfgNodeKind.RETURN)],
            [ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.FLOW)],
        )
        assert not [e for e in edges if e[0] == "m1:n1" and e[1] == "m1:exit"]

    def test_node_whose_only_successor_is_a_handler_completes_normally(self) -> None:
        # An empty try body: the handler is reachable exceptionally, and normal
        # completion left the method.
        edges = self._icfg_edges(
            [self._node(1, CfgNodeKind.STATEMENT, "try"), self._node(2, construct_kind="catch")],
            [ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.EXCEPTION)],
        )
        assert ("m1:n1", "m1:exit", IcfgEdgeKind.FLOW) in edges

    def test_a_complete_branch_gains_nothing(self) -> None:
        edges = self._icfg_edges(
            [
                self._node(1, CfgNodeKind.BRANCH, "if"),
                self._node(2),
                self._node(3, CfgNodeKind.RETURN),
            ],
            [
                ExportCfgEdge(source=1, target=2, label=ExportCfgEdgeLabel.TRUE),
                ExportCfgEdge(source=1, target=3, label=ExportCfgEdgeLabel.FALSE),
                ExportCfgEdge(source=2, target=3, label=ExportCfgEdgeLabel.FLOW),
            ],
        )
        assert not [e for e in edges if e[0] == "m1:n1" and e[1] == "m1:exit"]


class TestReachabilityProvenance:
    """§5.2.11 T2 — "outside the endpoint closure" is two different facts.

    A call reached only from a `CommandLineRunner` or `@Scheduled` method
    genuinely runs in production; a call in a vendored class no root reaches is
    dead. Both were published as `reachable=False`, which made the first
    invisible and the second indistinguishable from it. Measured on
    train-ticket-aitest: 430 async roots contributed no edges at all.
    """

    SEEDER = 900
    SEEDER_SINK_NODE = 905
    ORPHAN = 950

    def _export_with_async_root(self) -> ServiceExport:
        export = petstore_like_export()
        seeder = _minimal_method(self.SEEDER, "pets.PetSeeder.run")
        helper = _minimal_method(910, "pets.PetSeeder.push")
        orphan = _minimal_method(self.ORPHAN, "pets.Vendored.push")
        export.methods.extend([seeder, helper, orphan])
        export.cfgs.append(
            ExportCfg(
                method_id=self.SEEDER,
                nodes=[_call_node(self.SEEDER_SINK_NODE, 910, "pets.PetSeeder.push")],
                edges=[],
            )
        )
        export.async_roots.append(ExportAsyncRoot(method_id=self.SEEDER, kind="application-runner"))
        # Two sinks outside the ENDPOINT closure. One is reached by the runner
        # (transitively, via push); the other by nothing at all.
        export.unreachable_sinks.extend(
            [
                ExportUnreachableSink(
                    node_id=9001,
                    call_id=9001,
                    method_id=910,
                    kind="http-client",
                    value="http://inventory/seed",
                    value_confidence=SinkValueConfidence.EXACT,
                    http_verb="POST",
                    mechanism="resttemplate",
                    method_full_name="com.acme.pets.PetSeeder.push:void()",
                    file="src/main/java/com/acme/pets/PetSeeder.java",
                    line=22,
                ),
                ExportUnreachableSink(
                    node_id=9002,
                    call_id=9002,
                    method_id=self.ORPHAN,
                    kind="http-client",
                    value="http://inventory/dead",
                    value_confidence=SinkValueConfidence.EXACT,
                    http_verb="GET",
                    mechanism="resttemplate",
                    method_full_name="com.acme.pets.Vendored.push:void()",
                    file="src/main/java/com/acme/pets/Vendored.java",
                    line=9,
                ),
            ]
        )
        return export

    def _calls_by_url(self, assembler: Assembler) -> dict[str, RemoteCall]:
        artifacts = assembler.assemble(self._export_with_async_root())
        return {c.url: c for c in artifacts.remote_calls if c.url}

    def test_a_startup_reached_call_is_async_rooted_not_dead(self, assembler: Assembler) -> None:
        call = self._calls_by_url(assembler)["http://inventory/seed"]
        assert call.reachability is Reachability.ASYNC_ROOT
        # Still excluded from stitching — no request is behind it — but the
        # exclusion now carries its reason.
        assert call.reachable is False

    def test_a_call_no_root_reaches_stays_unreached(self, assembler: Assembler) -> None:
        call = self._calls_by_url(assembler)["http://inventory/dead"]
        assert call.reachability is Reachability.UNREACHED
        assert call.reachable is False

    def test_endpoint_reached_calls_keep_their_provenance(self, assembler: Assembler) -> None:
        call = self._calls_by_url(assembler)["{?}/stock/{?}"]
        assert call.reachability is Reachability.ENDPOINT
        assert call.reachable is True
