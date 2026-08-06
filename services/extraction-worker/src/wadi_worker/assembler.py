"""Per-endpoint ICFG assembly (§5.2 step 3) and artifact materialization.

Takes one :class:`ServiceExport` (the Scala side's bulk export) and produces
contract artifacts: endpoints, per-endpoint ICFGs (interprocedural, statement
granularity), remote calls, MQ interactions, and data models.

Interprocedural structure: the walk starts at the endpoint handler and
follows *resolved* call edges to methods present in the export (the
endpoint-reachable closure). Cycles are fine — the ICFG is a graph, calls
into an already-included method just add edges (§5.4 note applies one level
down). Unresolved callees stay as honest call nodes with no interior (P10).
"""

import logging
from dataclasses import dataclass, field

from wadi_contracts import (
    BranchCondition,
    CalleeUnboundReason,
    CfgAnomaly,
    Confidence,
    DataModel,
    DataModelField,
    Endpoint,
    EndpointCollision,
    EndpointParam,
    EndpointStatus,
    FieldShape,
    HttpMethod,
    Icfg,
    IcfgEdge,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    MethodInfo,
    MethodParam,
    MethodRef,
    MqDirection,
    MqInteraction,
    ParamLocation,
    Reachability,
    RemoteCall,
    ShapeKind,
    ShapeOrigin,
    SinkKind,
    SourceAnchor,
    StatusOrigin,
    TokenPropagation,
    TypeShape,
    method_id,
    mq_interaction_id,
    remote_call_id,
)
from wadi_joern_client.export import (
    CfgNodeKind,
    ExportCfg,
    ExportCfgEdgeLabel,
    ExportMethod,
    ExportSink,
    ExportTypeShape,
    ServiceExport,
    SinkValueConfidence,
)
from wadi_joern_client.export import (
    UnboundReason as ExportUnboundReason,
)
from wadi_worker.auth_merge import merge_endpoint_auth
from wadi_worker.cfg_invariants import aggregate_anomalies, arms_leaving_method, check_cfg

logger = logging.getLogger(__name__)

_CFG_KIND_TO_ICFG = {
    CfgNodeKind.STATEMENT: IcfgNodeKind.STATEMENT,
    CfgNodeKind.BRANCH: IcfgNodeKind.BRANCH,
    CfgNodeKind.LOOP: IcfgNodeKind.LOOP,
    CfgNodeKind.CALL: IcfgNodeKind.CALL,
    CfgNodeKind.RETURN: IcfgNodeKind.RETURN,
}

# §5.4.2 T5: the export's vocabulary is the contract's vocabulary. Mapped
# explicitly rather than by value coercion so a new reason code added upstream
# fails a test here instead of silently reaching the UI unlabelled.
_UNBOUND_REASON = {
    ExportUnboundReason.LOMBOK_GENERATED: CalleeUnboundReason.LOMBOK_GENERATED,
    ExportUnboundReason.INHERITED_EXTERNAL: CalleeUnboundReason.INHERITED_EXTERNAL,
    ExportUnboundReason.COMPILER_GENERATED: CalleeUnboundReason.COMPILER_GENERATED,
    ExportUnboundReason.THIRD_PARTY: CalleeUnboundReason.THIRD_PARTY,
    ExportUnboundReason.AMBIGUOUS_OVERLOAD: CalleeUnboundReason.AMBIGUOUS_OVERLOAD,
    ExportUnboundReason.UNRESOLVED_RECEIVER: CalleeUnboundReason.UNRESOLVED_RECEIVER,
    ExportUnboundReason.DECLARED_NOT_BOUND: CalleeUnboundReason.DECLARED_NOT_BOUND,
    ExportUnboundReason.NOT_DECLARED: CalleeUnboundReason.NOT_DECLARED,
    ExportUnboundReason.UNPARSEABLE_CALLEE: CalleeUnboundReason.UNPARSEABLE_CALLEE,
    None: None,
}

_EDGE_LABEL_TO_KIND = {
    ExportCfgEdgeLabel.FLOW: IcfgEdgeKind.FLOW,
    ExportCfgEdgeLabel.TRUE: IcfgEdgeKind.TRUE_BRANCH,
    ExportCfgEdgeLabel.FALSE: IcfgEdgeKind.FALSE_BRANCH,
    ExportCfgEdgeLabel.CASE: IcfgEdgeKind.CASE,
    ExportCfgEdgeLabel.DEFAULT: IcfgEdgeKind.DEFAULT,
    ExportCfgEdgeLabel.FALLTHROUGH: IcfgEdgeKind.FALLTHROUGH,
    ExportCfgEdgeLabel.EXCEPTION: IcfgEdgeKind.EXCEPTION,
}

_CONFIDENCE_MAP = {
    SinkValueConfidence.EXACT: Confidence.EXACT,
    SinkValueConfidence.HIGH: Confidence.HIGH,
    SinkValueConfidence.HEURISTIC: Confidence.HEURISTIC,
    SinkValueConfidence.NONE: Confidence.NONE,
}


@dataclass
class AssembledArtifacts:
    endpoints: list[Endpoint] = field(default_factory=list[Endpoint])
    icfgs: list[Icfg] = field(default_factory=list[Icfg])
    remote_calls: list[RemoteCall] = field(default_factory=list[RemoteCall])
    mq_interactions: list[MqInteraction] = field(default_factory=list[MqInteraction])
    data_models: list[DataModel] = field(default_factory=list[DataModel])
    cfg_anomalies: list[CfgAnomaly] = field(default_factory=list[CfgAnomaly])
    endpoint_collisions: list[EndpointCollision] = field(default_factory=list[EndpointCollision])


class ExportIncompatibleError(RuntimeError):
    """The export's schema major version doesn't match this reader."""


def resolve_id_collisions(artifacts: AssembledArtifacts) -> None:
    """Endpoints sharing a content-derived id cannot all be stored (§7).

    The store upserts on ``(snapshot_id, service_id, id)``, so a duplicate
    id does not merge — the later write REPLACES the earlier one and the
    endpoint is gone. Left alone that is silent: the loss happens at the
    storage key, downstream of the coverage report and every other counter,
    which is exactly how three handlers of a real controller disappeared
    while every honesty surface read clean.

    So the collision is resolved HERE, where it is still visible: a
    deterministic winner is kept (lowest handler signature, so the snapshot
    stays reproducible), the losers and their ICFGs are dropped together —
    an ICFG whose endpoint was not stored would be an orphan — and the whole
    event is recorded as a queryable fact (P10).
    """
    by_id: dict[str, list[Endpoint]] = {}
    for endpoint in artifacts.endpoints:
        by_id.setdefault(endpoint.id, []).append(endpoint)

    dropped_ids: set[int] = set()
    for endpoint_id, group in sorted(by_id.items()):
        if len(group) == 1:
            continue
        ordered = sorted(group, key=lambda e: e.handler.signature)
        kept, losers = ordered[0], ordered[1:]
        artifacts.endpoint_collisions.append(
            EndpointCollision(
                endpoint_id=endpoint_id,
                http_method=kept.http_method.value,
                uri=kept.simplified_uri,
                kept_handler=kept.handler.signature,
                dropped_handlers=[e.handler.signature for e in losers],
            )
        )
        dropped_ids.update(id(e) for e in losers)
        logger.warning(
            "endpoint id collision on %s %s (%s): kept %s, dropped %s",
            kept.http_method.value,
            kept.simplified_uri,
            endpoint_id,
            kept.handler.signature,
            ", ".join(e.handler.signature for e in losers),
        )

    if not dropped_ids:
        return
    artifacts.endpoints = [e for e in artifacts.endpoints if id(e) not in dropped_ids]
    kept_endpoint_ids = {e.id for e in artifacts.endpoints}
    artifacts.icfgs = [i for i in artifacts.icfgs if i.endpoint_id in kept_endpoint_ids]


class Assembler:
    def __init__(
        self,
        *,
        snapshot_id: str,
        service_id: str,
        config_env: dict[str, str] | None = None,
        config_structured: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._snapshot_id = snapshot_id
        self._service_id = service_id
        self._config_env = config_env or {}
        self._config_structured = config_structured or {}

    def assemble(self, export: ServiceExport) -> AssembledArtifacts:
        if not export.compatible_with_reader():
            raise ExportIncompatibleError(
                f"export schema {export.export_schema_version} is incompatible with this worker"
            )
        methods = {m.id: m for m in export.methods}
        cfgs = {c.method_id: c for c in export.cfgs}
        # Since export 2.0.0 a call site emits one sink row per candidate value
        # (§5.2 over-approximation) — rows sharing a node are one site.
        sinks_by_node: dict[int, list[ExportSink]] = {}
        for sink in export.sinks:
            sinks_by_node.setdefault(sink.node_id, []).append(sink)

        artifacts = AssembledArtifacts()
        artifacts.remote_calls = self._build_remote_calls(export, methods)
        artifacts.mq_interactions = self._build_mq_interactions(export, methods)
        artifacts.data_models = self._build_data_models(export)
        # §5.2.8 M2: structural invariants over every RAW method CFG, once per
        # method (an ICFG inlines a method into many endpoints; the invariant
        # is a per-method fact). Pre-patch by construction — this runs on the
        # export, before the synthetic entry/exit edges below exist.
        findings = [
            finding
            for cfg in export.cfgs
            if (cfg_method := methods.get(cfg.method_id)) is not None
            for finding in check_cfg(cfg, cfg_method)
        ]
        artifacts.cfg_anomalies = aggregate_anomalies(findings)

        for export_endpoint in export.endpoints:
            handler = methods.get(export_endpoint.method_id)
            if handler is None:
                logger.warning(
                    "endpoint %s %s references method id %d missing from export — skipped",
                    export_endpoint.http_method,
                    export_endpoint.uri,
                    export_endpoint.method_id,
                )
                continue
            http_method = HttpMethod(export_endpoint.http_method.upper())
            endpoint = Endpoint.create(
                snapshot_id=self._snapshot_id,
                service_id=self._service_id,
                http_method=http_method,
                full_uri=export_endpoint.uri,
                handler=self._method_ref(handler),
                params=[
                    EndpointParam(
                        name=param.name,
                        location=ParamLocation(param.location),
                        type_name=param.type_name,
                        required=param.required,
                    )
                    for param in export_endpoint.params
                ],
                response_type=handler.return_type,
                declared_statuses=[
                    EndpointStatus(
                        code=status.code,
                        origin=StatusOrigin(status.origin),
                        detail=status.detail,
                        anchor=self._anchor(
                            handler.filename, max(status.line, 1), max(status.line, 1)
                        ),
                    )
                    for status in export_endpoint.status_codes
                ],
                request_schema=_shape(export_endpoint.request_schema),
                response_schema=_shape(export_endpoint.response_schema),
                auth=merge_endpoint_auth(
                    full_uri=export_endpoint.uri,
                    http_method=http_method,
                    auth_tags=export_endpoint.auth_tags,
                    security_rules=export.security_rules,
                    handler_anchor=self._anchor(handler.filename, handler.line, handler.line_end),
                    config_env=self._config_env,
                    auth_enforcements=export.auth_enforcements,
                    auth_mechanisms=export.auth_mechanisms,
                    method_security=export.method_security,
                    config_structured=self._config_structured,
                    authority_models=export.auth_authorities,
                ),
            )
            artifacts.endpoints.append(endpoint)
            artifacts.icfgs.append(
                self._assemble_icfg(endpoint, handler, methods, cfgs, sinks_by_node)
            )
        resolve_id_collisions(artifacts)
        return artifacts

    # --- ICFG construction -----------------------------------------------------

    def _assemble_icfg(
        self,
        endpoint: Endpoint,
        handler: ExportMethod,
        methods: dict[int, ExportMethod],
        cfgs: dict[int, ExportCfg],
        sinks_by_node: dict[int, list[ExportSink]],
    ) -> Icfg:
        closure = self._reachable_closure(handler.id, methods, cfgs)
        nodes: list[IcfgNode] = []
        edges: list[IcfgEdge] = []

        for included_id in closure:
            method = methods[included_id]
            cfg = cfgs.get(included_id)
            self._emit_method_subgraph(method, cfg, sinks_by_node, methods, closure, nodes, edges)

        return Icfg(
            snapshot_id=self._snapshot_id,
            service_id=self._service_id,
            endpoint_id=endpoint.id,
            entry_node_id=f"m{handler.id}:entry",
            nodes=nodes,
            edges=edges,
        )

    def _reachable_closure(
        self,
        handler_id: int,
        methods: dict[int, ExportMethod],
        cfgs: dict[int, ExportCfg],
    ) -> list[int]:
        """Methods reachable from the handler via resolved in-export calls (BFS order)."""
        visited: list[int] = []
        seen: set[int] = set()
        queue = [handler_id]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            visited.append(current)
            cfg = cfgs.get(current)
            if cfg is None:
                continue
            for node in cfg.nodes:
                if (
                    node.call is not None
                    and node.call.resolved
                    and node.call.callee_id is not None
                    and node.call.callee_id in methods
                    and node.call.callee_id not in seen
                ):
                    queue.append(node.call.callee_id)
        return visited

    def _emit_method_subgraph(
        self,
        method: ExportMethod,
        cfg: ExportCfg | None,
        sinks_by_node: dict[int, list[ExportSink]],
        methods: dict[int, ExportMethod],
        closure: list[int],
        nodes: list[IcfgNode],
        edges: list[IcfgEdge],
    ) -> None:
        method_ref = self._method_ref(method)
        entry_id = f"m{method.id}:entry"
        exit_id = f"m{method.id}:exit"
        nodes.append(
            IcfgNode(
                id=entry_id,
                kind=IcfgNodeKind.ENTRY,
                anchor=self._anchor(method.filename, method.line, method.line),
                source_text=method.code,
                method=method_ref,
                method_info=MethodInfo(
                    signature=method.signature,
                    params=[MethodParam(name=p.name, type_name=p.type_name) for p in method.params],
                    return_type=method.return_type,
                    doc_comment=method.doc_comment,
                    badges=self._badges(method, cfg, sinks_by_node),
                ),
            )
        )

        cfg_nodes = cfg.nodes if cfg is not None else []
        cfg_edges = cfg.edges if cfg is not None else []
        closure_set = set(closure)

        for cfg_node in cfg_nodes:
            node_id = f"m{method.id}:n{cfg_node.id}"
            site_sinks = sinks_by_node.get(cfg_node.id, [])
            kind = _CFG_KIND_TO_ICFG[cfg_node.kind]
            callee_ref: MethodRef | None = None
            unbound_reason: CalleeUnboundReason | None = None
            remote_ids: list[str] = []
            mq_id: str | None = None
            sink_kind: SinkKind | None = None
            # A callee rides any real statement since 1.8.0 (§5.2.8):
            # `return svc.find(id)` is a RETURN node whose call resolves
            # interprocedurally, and a sink inside a branch condition puts
            # the call on the BRANCH node itself.
            if cfg_node.call is not None:
                callee_ref = self._callee_ref(
                    cfg_node.call.callee_id, cfg_node.call.callee_full_name, methods
                )
                # 1.12.0 (§5.4.2 T5): only carry the reason where the callee is
                # genuinely absent from THIS graph. A call can be unbound in the
                # export yet land inside the endpoint closure anyway (the export
                # is service-wide, the closure is endpoint-scoped), and labelling
                # a node whose interior the user can open would be a lie.
                if cfg_node.call.callee_id not in closure_set:
                    unbound_reason = _UNBOUND_REASON.get(cfg_node.call.unbound_reason)
            # Sinks anchor to the coarsened statement, which is not always a
            # CALL node — `return restTemplate.getForObject(...)` coarsens to
            # RETURN, `if (client.get(...) != null)` to BRANCH. Gating on CALL
            # would silently drop those markers from the ICFG (P10).
            if site_sinks:
                sink_kind = self._sink_kind(site_sinks[0].kind)
                if sink_kind is SinkKind.HTTP_CLIENT:
                    for sink in site_sinks:
                        candidate_id = remote_call_id(
                            self._service_id,
                            method.filename,
                            cfg_node.line,
                            sink.value or "<undetermined>",
                        )
                        if candidate_id not in remote_ids:
                            remote_ids.append(candidate_id)
                elif sink_kind is SinkKind.MQ:
                    mq_id = mq_interaction_id(
                        self._service_id,
                        method.filename,
                        cfg_node.line,
                        MqDirection.PUBLISH.value,
                        site_sinks[0].value or "<undetermined>",
                    )
            nodes.append(
                IcfgNode(
                    id=node_id,
                    kind=kind,
                    anchor=self._anchor(method.filename, cfg_node.line, cfg_node.line_end),
                    source_text=cfg_node.code,
                    method=method_ref,
                    construct_kind=cfg_node.construct_kind,
                    # 1.8.0 (§5.2.8): conditions live beyond branch/loop —
                    # a switch-arrow carrier is a return/call node holding
                    # the selector. The exporter only emits condition_code
                    # where it belongs; pass it through.
                    condition=(
                        BranchCondition(expression=cfg_node.condition_code)
                        if cfg_node.condition_code
                        else None
                    ),
                    callee=callee_ref,
                    callee_unbound_reason=unbound_reason if callee_ref is not None else None,
                    sink=sink_kind,
                    remote_call_id=remote_ids[0] if remote_ids else None,
                    remote_call_ids=remote_ids,
                    mq_interaction_id=mq_id,
                )
            )

        nodes.append(
            IcfgNode(
                id=exit_id,
                kind=IcfgNodeKind.EXIT,
                anchor=self._anchor(
                    method.filename, method.line_end or method.line, method.line_end or method.line
                ),
                source_text="<exit>",
                method=method_ref,
            )
        )

        # Intra-method flow edges.
        local = {c.id for c in cfg_nodes}
        has_incoming = {e.target for e in cfg_edges if e.source in local}
        has_outgoing = {e.source for e in cfg_edges if e.target in local}
        outgoing_labels: dict[int, set[ExportCfgEdgeLabel]] = {}
        for edge in cfg_edges:
            if edge.source in local and edge.target in local:
                outgoing_labels.setdefault(edge.source, set()).add(edge.label)
                edges.append(
                    IcfgEdge(
                        source=f"m{method.id}:n{edge.source}",
                        target=f"m{method.id}:n{edge.target}",
                        kind=_EDGE_LABEL_TO_KIND[edge.label],
                        case_values=edge.case_values,
                        back=edge.back,
                    )
                )
        if cfg_nodes:
            for cfg_node in cfg_nodes:
                node_id = f"m{method.id}:n{cfg_node.id}"
                if cfg_node.id not in has_incoming:
                    edges.append(IcfgEdge(source=entry_id, target=node_id, kind=IcfgEdgeKind.FLOW))
                to_exit: list[IcfgEdgeKind] = []
                if cfg_node.id not in has_outgoing or cfg_node.kind is CfgNodeKind.RETURN:
                    to_exit.append(IcfgEdgeKind.FLOW)
                # §5.2.8 T3: an arm whose control leaves the method has no
                # target in an exit-free export, so the graph would otherwise
                # go silent where it should say "on false, the method
                # returns". The exit node is the assembler's to own, so arity
                # completes here — against the same predicate the invariants
                # use, so the two can never disagree. Keyed off the
                # intra-method successors rather than `has_outgoing`, which
                # also counts dangling edges.
                if (labels := outgoing_labels.get(cfg_node.id)) is not None:
                    to_exit.extend(
                        kind
                        for label in arms_leaving_method(cfg_node, labels)
                        if (kind := _EDGE_LABEL_TO_KIND[label]) not in to_exit
                    )
                for kind in to_exit:
                    edges.append(IcfgEdge(source=node_id, target=exit_id, kind=kind))
        else:
            edges.append(IcfgEdge(source=entry_id, target=exit_id, kind=IcfgEdgeKind.FLOW))

        # Interprocedural call/return edges into inlined callees.
        for cfg_node in cfg_nodes:
            call = cfg_node.call
            if (
                call is not None
                and call.resolved
                and call.callee_id is not None
                and call.callee_id in closure_set
            ):
                node_id = f"m{method.id}:n{cfg_node.id}"
                edges.append(
                    IcfgEdge(
                        source=node_id,
                        target=f"m{call.callee_id}:entry",
                        kind=IcfgEdgeKind.CALL,
                    )
                )
                edges.append(
                    IcfgEdge(
                        source=f"m{call.callee_id}:exit",
                        target=node_id,
                        kind=IcfgEdgeKind.RETURN,
                    )
                )

    # --- artifact builders --------------------------------------------------------

    _HTTP_SINK_KINDS = frozenset({SinkKind.HTTP_CLIENT, SinkKind.HTTP_CLIENT_SUSPECTED})

    def _build_remote_calls(
        self, export: ServiceExport, methods: dict[int, ExportMethod]
    ) -> list[RemoteCall]:
        calls: list[RemoteCall] = []
        seen: set[str] = set()
        for sink in export.sinks:
            kind = self._sink_kind(sink.kind)
            if kind not in self._HTTP_SINK_KINDS:
                continue
            method = methods.get(sink.method_id)
            if method is None:
                continue
            line = self._sink_line(sink, export)
            call = self._remote_call(
                sink,
                filename=method.filename,
                line=line,
                method_ref=self._method_ref(method),
                suspected=kind is SinkKind.HTTP_CLIENT_SUSPECTED,
                reachable=True,
            )
            if call.id in seen:
                continue
            seen.add(call.id)
            calls.append(call)
        # Sinks outside the endpoint closure (§5.2.5): excluded from the map by
        # design, inventoried so the exclusion is a queryable fact (P10).
        # §5.2.11 T2: "outside the endpoint closure" is two different facts —
        # startup/scheduled code that really runs, and code nothing reaches.
        async_rooted = self._async_root_closure(export, methods)
        for unreachable in export.unreachable_sinks:
            kind = self._sink_kind(unreachable.kind)
            if kind not in self._HTTP_SINK_KINDS:
                continue
            call = self._remote_call(
                unreachable,
                filename=unreachable.file,
                line=max(unreachable.line, 1),
                method_ref=MethodRef(
                    id=method_id(self._service_id, unreachable.method_full_name),
                    signature=unreachable.method_full_name,
                ),
                suspected=kind is SinkKind.HTTP_CLIENT_SUSPECTED,
                reachable=False,
                reachability=(
                    Reachability.ASYNC_ROOT
                    if unreachable.method_full_name in async_rooted
                    else Reachability.UNREACHED
                ),
            )
            if call.id in seen:
                continue
            seen.add(call.id)
            calls.append(call)
        return calls

    def _remote_call(
        self,
        sink: ExportSink,
        *,
        filename: str,
        line: int,
        method_ref: MethodRef,
        suspected: bool,
        reachable: bool,
        reachability: Reachability = Reachability.ENDPOINT,
    ) -> RemoteCall:
        return RemoteCall(
            snapshot_id=self._snapshot_id,
            service_id=self._service_id,
            id=remote_call_id(self._service_id, filename, line, sink.value or "<undetermined>"),
            site=self._anchor(filename, line, line),
            method=method_ref,
            mechanism=sink.mechanism or "http-client",
            http_verb=HttpMethod(sink.http_verb.upper()) if sink.http_verb else None,
            url=sink.value,
            url_confidence=_CONFIDENCE_MAP[sink.value_confidence]
            if sink.value is not None
            else Confidence.NONE,
            evidence=sink.evidence,
            auth_propagation=sink.auth_propagation,
            auth_propagation_state=TokenPropagation(sink.auth_propagation_state),
            suspected=suspected,
            reachable=reachable,
            reachability=reachability,
        )

    def _async_root_closure(
        self, export: ServiceExport, methods: dict[int, ExportMethod]
    ) -> set[str]:
        """Method full names reachable from a non-HTTP root (§5.2.11 T2).

        The Scala closure is already rooted at endpoints + async roots, so
        every method involved is in the export — what was missing is the
        walk that says WHICH root got there. Returns full names because an
        unreachable sink carries its enclosing method by name, not by id (its
        method is inventoried inline rather than exported).
        """
        cfgs = {cfg.method_id: cfg for cfg in export.cfgs}
        reached: set[str] = set()
        for root in export.async_roots:
            for reached_id in self._reachable_closure(root.method_id, methods, cfgs):
                # The BFS seeds with the root id unconditionally, so a root the
                # export did not carry would KeyError here rather than simply
                # contributing nothing.
                reached_method = methods.get(reached_id)
                if reached_method is not None:
                    reached.add(reached_method.full_name)
        return reached

    def _build_mq_interactions(
        self, export: ServiceExport, methods: dict[int, ExportMethod]
    ) -> list[MqInteraction]:
        interactions: list[MqInteraction] = []
        seen: set[str] = set()
        for sink in export.sinks:
            if not sink.kind.startswith("mq:"):
                continue
            method = methods.get(sink.method_id)
            if method is None:
                continue
            line = self._sink_line(sink, export)
            interaction_id = mq_interaction_id(
                self._service_id,
                method.filename,
                line,
                MqDirection.PUBLISH.value,
                sink.value or "<undetermined>",
            )
            if interaction_id in seen:
                continue
            seen.add(interaction_id)
            interactions.append(
                MqInteraction(
                    snapshot_id=self._snapshot_id,
                    service_id=self._service_id,
                    id=interaction_id,
                    direction=MqDirection.PUBLISH,
                    broker=sink.kind.removeprefix("mq:"),
                    topic=sink.value,
                    topic_confidence=_CONFIDENCE_MAP[sink.value_confidence]
                    if sink.value is not None
                    else Confidence.NONE,
                    site=self._anchor(method.filename, line, line),
                    method=self._method_ref(method),
                )
            )
        return interactions

    def _build_data_models(self, export: ServiceExport) -> list[DataModel]:
        from wadi_contracts import data_model_id

        return [
            DataModel(
                snapshot_id=self._snapshot_id,
                service_id=self._service_id,
                id=data_model_id(self._service_id, model.entity),
                entity=model.entity,
                fields=[DataModelField(name=f.name, type_name=f.type_name) for f in model.fields],
                persistence_framework=model.persistence_framework,
                storage_name=model.storage_name,
            )
            for model in export.data_models
        ]

    # --- small helpers ---------------------------------------------------------------

    def _method_ref(self, method: ExportMethod) -> MethodRef:
        return MethodRef(
            id=method_id(self._service_id, method.full_name), signature=method.full_name
        )

    def _callee_ref(
        self, callee_id: int | None, callee_full_name: str, methods: dict[int, ExportMethod]
    ) -> MethodRef:
        if callee_id is not None and callee_id in methods:
            return self._method_ref(methods[callee_id])
        return MethodRef(
            id=method_id(self._service_id, callee_full_name), signature=callee_full_name
        )

    def _anchor(self, filename: str, line: int, line_end: int) -> SourceAnchor:
        start = max(line, 1)
        return SourceAnchor(file=filename, start_line=start, end_line=max(line_end, start))

    def _badges(
        self,
        method: ExportMethod,
        cfg: ExportCfg | None,
        sinks_by_node: dict[int, list[ExportSink]],
    ) -> list[str]:
        badges: set[str] = set()
        if any(tag.startswith("endpoint=") for tag in method.tags):
            badges.add("endpoint")
        for cfg_node in cfg.nodes if cfg is not None else []:
            for sink in sinks_by_node.get(cfg_node.id, []):
                if sink.kind == "db":
                    badges.add("touches-db")
                elif sink.kind == "http-client":
                    badges.add("calls-http")
                elif sink.kind.startswith("mq:"):
                    badges.add("publishes-mq")
        return sorted(badges)

    def _sink_kind(self, kind: str) -> SinkKind:
        """Map a registered ``sink=`` tag value to the contract enum.

        Unregistered values are vocabulary drift between the packs and this
        reader — they fail the job loudly rather than being silently absorbed
        (§7 tag-registry rule).
        """
        from wadi_contracts.tags import validate_tag

        validate_tag("sink", kind)
        if kind == "db":
            return SinkKind.DB
        if kind == "http-client":
            return SinkKind.HTTP_CLIENT
        if kind == "http-client-suspected":
            return SinkKind.HTTP_CLIENT_SUSPECTED
        return SinkKind.MQ

    def _sink_line(self, sink: ExportSink, export: ServiceExport) -> int:
        for cfg in export.cfgs:
            if cfg.method_id == sink.method_id:
                for node in cfg.nodes:
                    if node.id == sink.node_id:
                        return max(node.line, 1)
        return 1


def _shape(exported: "ExportTypeShape | None") -> TypeShape | None:
    """Recursive export→contract shape mapping (§5.2.7); identity by design."""
    if exported is None:
        return None
    return TypeShape(
        kind=ShapeKind(exported.kind),
        origin=ShapeOrigin(exported.origin),
        type_name=exported.type_name,
        fields=[
            FieldShape(name=f.name, java_name=f.java_name, shape=_shape_required(f.shape))
            for f in exported.fields
        ],
        element=_shape(exported.element),
    )


def _shape_required(exported: "ExportTypeShape") -> TypeShape:
    shape = _shape(exported)
    assert shape is not None
    return shape
