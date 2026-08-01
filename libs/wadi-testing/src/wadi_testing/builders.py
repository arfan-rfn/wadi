"""Contract-model builders for tests across the workspace."""

import uuid

from wadi_contracts import (
    Endpoint,
    HttpMethod,
    Icfg,
    IcfgEdge,
    IcfgEdgeKind,
    IcfgNode,
    IcfgNodeKind,
    MethodInfo,
    MethodRef,
    RepoSource,
    ServiceBoundary,
    Snapshot,
    SourceAnchor,
    System,
    method_id,
    service_id,
)

REPO = "https://github.com/acme/shop.git"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def make_system(name: str = "shop") -> System:
    return System(id=new_id("sys"), name=name, repos=[RepoSource(source=REPO, branch="main")])


def make_snapshot(system: System) -> Snapshot:
    return Snapshot(
        id=new_id("snap"),
        system_id=system.id,
        commits={"github.com/acme/shop": "a" * 40},
    )


def make_service(snapshot: Snapshot, build_root: str = "services/orders") -> ServiceBoundary:
    svc = service_id(REPO, build_root)
    return ServiceBoundary(
        snapshot_id=snapshot.id,
        service_id=svc,
        name=build_root.rsplit("/", 1)[-1],
        repo="github.com/acme/shop",
        build_root=build_root,
        languages=["java"],
        build_system="maven",
    )


def make_method(svc_id: str, signature: str) -> MethodRef:
    return MethodRef(id=method_id(svc_id, signature), signature=signature)


def make_endpoint(
    snapshot: Snapshot, boundary: ServiceBoundary, uri: str = "/orders/{id}"
) -> Endpoint:
    handler = make_method(
        boundary.service_id, f"com.acme.OrderController.handler_{uri}(java.lang.String)"
    )
    return Endpoint.create(
        snapshot_id=snapshot.id,
        service_id=boundary.service_id,
        http_method=HttpMethod.GET,
        full_uri=uri,
        handler=handler,
    )


def make_icfg(
    snapshot: Snapshot,
    boundary: ServiceBoundary,
    endpoint: Endpoint,
    *,
    statement_count: int = 3,
    statement_text: str = "orderService.get(id);",
) -> Icfg:
    method = endpoint.handler
    nodes = [
        IcfgNode(
            id="entry",
            kind=IcfgNodeKind.ENTRY,
            anchor=SourceAnchor(file="src/A.java", start_line=1, end_line=1),
            source_text="public Order get(String id) {",
            method=method,
            method_info=MethodInfo(signature=method.signature),
        )
    ]
    edges: list[IcfgEdge] = []
    previous = "entry"
    for index in range(statement_count):
        node_id = f"s{index}"
        nodes.append(
            IcfgNode(
                id=node_id,
                kind=IcfgNodeKind.STATEMENT,
                anchor=SourceAnchor(file="src/A.java", start_line=index + 2, end_line=index + 2),
                source_text=statement_text,
                method=method,
            )
        )
        edges.append(IcfgEdge(source=previous, target=node_id, kind=IcfgEdgeKind.FLOW))
        previous = node_id
    nodes.append(
        IcfgNode(
            id="exit",
            kind=IcfgNodeKind.EXIT,
            anchor=SourceAnchor(
                file="src/A.java", start_line=statement_count + 2, end_line=statement_count + 2
            ),
            source_text="}",
            method=method,
        )
    )
    edges.append(IcfgEdge(source=previous, target="exit", kind=IcfgEdgeKind.FLOW))
    return Icfg(
        snapshot_id=snapshot.id,
        service_id=boundary.service_id,
        endpoint_id=endpoint.id,
        entry_node_id="entry",
        nodes=nodes,
        edges=edges,
    )
