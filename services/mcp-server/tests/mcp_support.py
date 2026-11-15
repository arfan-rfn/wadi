"""Builders for MCP tests: an interprocedural ICFG with sinks, and entity facts."""

from wadi_contracts import (
    DataModel,
    Endpoint,
    EntityAccess,
    EntityAccessAccounting,
    EntityAccessBasis,
    EntityAccessSite,
    EntityDeclaredBy,
    EntityOperation,
    Icfg,
    IcfgEdge,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    MethodInfo,
    MethodRef,
    ServiceBoundary,
    SinkKind,
    Snapshot,
    SourceAnchor,
    data_model_id,
    method_id,
    remote_call_id,
)


def _anchor(line: int, file: str = "src/OrderController.java") -> SourceAnchor:
    return SourceAnchor(file=file, start_line=line, end_line=line)


def make_two_method_icfg(
    snapshot: Snapshot,
    boundary: ServiceBoundary,
    endpoint: Endpoint,
    *,
    db_sites: list[EntityAccessSite] | None = None,
) -> Icfg:
    """Controller handler calls a service method that hits the DB and an HTTP client.

    ``db_sites`` are the entity access sites the worker would put on the
    repository call (§5.2.17); none by default, as on a pre-phase graph.
    """
    svc = boundary.service_id
    controller = endpoint.handler
    service_sig = "com.acme.OrderService.load(java.lang.String)"
    service = MethodRef(id=method_id(svc, service_sig), signature=service_sig)
    repo_sig = "com.acme.OrderRepository.findById(java.lang.String)"
    repo = MethodRef(id=method_id(svc, repo_sig), signature=repo_sig)
    client_sig = "org.springframework.web.client.RestTemplate.getForObject"
    rest = MethodRef(id=method_id(svc, client_sig), signature=client_sig)
    rc_id = remote_call_id(svc, "src/OrderService.java", 25, "http://billing/invoices/{id}")

    nodes = [
        IcfgNode(
            id="c-entry",
            kind=IcfgNodeKind.ENTRY,
            anchor=_anchor(10),
            source_text="public Order get(@PathVariable String id) {",
            method=controller,
            method_info=MethodInfo(signature=controller.signature, badges=["endpoint"]),
        ),
        IcfgNode(
            id="c-call",
            kind=IcfgNodeKind.CALL,
            anchor=_anchor(11),
            source_text="return orderService.load(id);",
            method=controller,
            callee=service,
        ),
        IcfgNode(
            id="c-exit",
            kind=IcfgNodeKind.EXIT,
            anchor=_anchor(12),
            source_text="}",
            method=controller,
        ),
        IcfgNode(
            id="s-entry",
            kind=IcfgNodeKind.ENTRY,
            anchor=_anchor(20, "src/OrderService.java"),
            source_text="public Order load(String id) {",
            method=service,
            method_info=MethodInfo(signature=service_sig, badges=["touches-db", "calls-http"]),
        ),
        IcfgNode(
            id="s-branch",
            kind=IcfgNodeKind.BRANCH,
            anchor=_anchor(21, "src/OrderService.java"),
            source_text="if (cache.contains(id)) {",
            method=service,
        ),
        IcfgNode(
            id="s-db",
            kind=IcfgNodeKind.CALL,
            anchor=_anchor(23, "src/OrderService.java"),
            source_text="Order o = orderRepository.findById(id);",
            method=service,
            callee=repo,
            sink=SinkKind.DB,
            entity_access_sites=db_sites or [],
        ),
        IcfgNode(
            id="s-http",
            kind=IcfgNodeKind.CALL,
            anchor=_anchor(25, "src/OrderService.java"),
            source_text='restTemplate.getForObject("http://billing/invoices/{id}", ...);',
            method=service,
            callee=rest,
            sink=SinkKind.HTTP_CLIENT,
            remote_call_id=rc_id,
        ),
        IcfgNode(
            id="s-exit",
            kind=IcfgNodeKind.EXIT,
            anchor=_anchor(27, "src/OrderService.java"),
            source_text="}",
            method=service,
        ),
    ]
    edges = [
        IcfgEdge(source="c-entry", target="c-call", kind=IcfgEdgeKind.FLOW),
        IcfgEdge(source="c-call", target="s-entry", kind=IcfgEdgeKind.CALL),
        IcfgEdge(source="s-entry", target="s-branch", kind=IcfgEdgeKind.FLOW),
        IcfgEdge(source="s-branch", target="s-db", kind=IcfgEdgeKind.TRUE_BRANCH),
        IcfgEdge(source="s-branch", target="s-http", kind=IcfgEdgeKind.FALSE_BRANCH),
        IcfgEdge(source="s-db", target="s-exit", kind=IcfgEdgeKind.FLOW),
        IcfgEdge(source="s-http", target="s-exit", kind=IcfgEdgeKind.FLOW),
        IcfgEdge(source="s-exit", target="c-call", kind=IcfgEdgeKind.RETURN),
        IcfgEdge(source="c-call", target="c-exit", kind=IcfgEdgeKind.FLOW),
    ]
    return Icfg(
        snapshot_id=snapshot.id,
        service_id=svc,
        endpoint_id=endpoint.id,
        entry_node_id="c-entry",
        nodes=nodes,
        edges=edges,
    )


def make_site(
    operation: EntityOperation,
    *,
    entity: str | None = "com.acme.Order",
    model_id: str | None = None,
    method_name: str = "save",
) -> EntityAccessSite:
    """One repository call site, classified the way the worker classifies it."""
    demoted = operation is EntityOperation.CREATE_OR_UPDATE
    return EntityAccessSite(
        repository="com.acme.OrderRepository",
        method_name=method_name,
        basis=EntityAccessBasis.ARGUMENT_ORIGIN if demoted else EntityAccessBasis.METHOD_NAME,
        accesses=[
            EntityAccess(
                entity=entity,
                data_model_id=model_id,
                operation=operation,
                candidate_operation=EntityOperation.UPDATE if demoted else None,
            )
        ],
    )


def make_data_model(snapshot: Snapshot, boundary: ServiceBoundary, entity: str) -> DataModel:
    simple = entity.rsplit(".", 1)[-1]
    return DataModel(
        snapshot_id=snapshot.id,
        service_id=boundary.service_id,
        id=data_model_id(boundary.service_id, entity),
        entity=simple,
        type_full_name=entity,
        persistence_framework="spring-data-jpa",
        storage_name=simple.lower(),
        declared_by=EntityDeclaredBy.ANNOTATION,
    )


def make_accounting(call_sites: int) -> EntityAccessAccounting:
    return EntityAccessAccounting(
        call_sites=call_sites,
        in_endpoint_flow=call_sites,
        in_no_endpoint_flow=0,
        flush=0,
        implemented_in_project=0,
        entity_undetermined=0,
        unknown_operation=0,
        create_or_update=0,
        bound=call_sites,
        accesses_by_operation={op.value: 0 for op in EntityOperation},
        sites_by_basis={basis.value: 0 for basis in EntityAccessBasis},
        rules_version="rules-test",
        gate_flags=[],
    )
