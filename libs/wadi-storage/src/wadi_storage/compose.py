"""Read compositions shared by the orchestrator and the MCP server (C5).

Both services answer some questions over the same stored facts, and P1 forbids
one importing the other. A join written in both services can drift into two
different answers, so the joins both of them need are written once, here, in
the package both already depend on.
"""

import asyncio
from typing import NamedTuple

from wadi_contracts import (
    EntityAccountingStatus,
    EntityUsageService,
    EntityUsageView,
    Icfg,
    RemoteEdgeItem,
    ServiceBoundary,
    ServiceKind,
    build_entity_usage_view,
)
from wadi_storage.artifacts import ArtifactRepository
from wadi_storage.graph import GraphRepository
from wadi_storage.stitch import StitchRepository


class EndpointOutbound(NamedTuple):
    """An endpoint's outbound stitched edges, and whether stitching has run.

    ``stitched=False`` makes an empty ``outbound`` mean "not yet": the
    stitcher has not run, so nothing is known about where the calls go (P10).
    """

    outbound: list[RemoteEdgeItem]
    stitched: bool


async def endpoint_outbound(
    stitch: StitchRepository,
    graph: GraphRepository,
    *,
    snapshot_id: str,
    service_id: str,
    icfg: Icfg | None,
) -> EndpointOutbound:
    """The stitched edges leaving one endpoint's flow (§11 Phase 2.8, C5).

    The endpoint workspace reads this through `/detail`, and an agent reads it
    through MCP `endpoint_detail`, where it is what explains a forwarding
    endpoint whose own entity summary is empty (Q26). An edge belongs to the
    endpoint when its remote-call id is on a node of the endpoint's ICFG; the
    rest of the service's edges stay behind `/remote-edges`.

    Neo4j is read only when it can contribute: after stitching, and when the
    flow makes a remote call at all. Before stitching the answer is "not yet"
    whatever the graph holds, the same rule as the system graph.
    """
    stitched = await stitch.coverage_report_exists(snapshot_id)
    remote_call_ids: set[str] = set()
    if icfg is not None:
        for node in icfg.nodes:
            remote_call_ids.update(node.remote_call_ids)
    if not stitched or not remote_call_ids:
        return EndpointOutbound(outbound=[], stitched=stitched)
    edges_view = await graph.remote_edges(snapshot_id, service_id)
    return EndpointOutbound(
        outbound=[edge for edge in edges_view.outbound if edge.remote_call_id in remote_call_ids],
        stitched=stitched,
    )


async def entity_usage_view(
    artifacts: ArtifactRepository, snapshot_id: str, *, service_id: str | None = None
) -> EntityUsageView:
    """Which endpoints may do what to each entity, for one snapshot (§5.2.17).

    The orchestrator's `/entities` and MCP `entity_usage` both read through
    here, and both fold through :func:`~wadi_contracts.build_entity_usage_view`
    (R1-22), so the reverse question has one set of inputs and one fold. The
    inputs are the two snapshot-wide projections (R1-8) and the service
    boundaries, whose accounting the fold copies into the view unchanged.

    ``service_id`` narrows the inputs rather than the output, so ``analyzed``
    and ``endpoints_predating`` describe that service: a service re-analyzed
    after the phase is not reported as predating it because a sibling was
    not, and a reporting service with no endpoints is analyzed and lists its
    entities (review C4, live on ``ts-gateway``).
    """
    rows, models, boundaries = await asyncio.gather(
        artifacts.list_endpoint_entity_access(snapshot_id),
        artifacts.list_data_models_for_snapshot(snapshot_id),
        artifacts.list_service_boundaries(snapshot_id),
    )
    if service_id is not None:
        rows = [row for row in rows if row.service_id == service_id]
        models = [model for model in models if model.service_id == service_id]
        boundaries = [boundary for boundary in boundaries if boundary.service_id == service_id]
    return build_entity_usage_view(
        snapshot_id,
        rows,
        models,
        [
            EntityUsageService(
                service_id=boundary.service_id,
                service_name=boundary.name,
                status=_accounting_status(boundary),
                accounting=(
                    None
                    if boundary.kind is ServiceKind.LIBRARY
                    else boundary.entity_access_accounting
                ),
            )
            for boundary in boundaries
        ],
    )


def _accounting_status(boundary: ServiceBoundary) -> EntityAccountingStatus:
    """Why a boundary does or does not carry accounting (1.27.0).

    A library has no export of its own (§5.2.14); its calls count in each
    dependent. A failed extraction and a boundary from before the phase both
    have nothing measured, and ``extraction_error`` tells them apart. Only
    ``library`` is a library: the kinds reserved for Phase 9 (``function``,
    ``edge-worker``, ``firmware``) have exports of their own, so they report
    or not on their accounting like a service.
    """
    if boundary.kind is ServiceKind.LIBRARY:
        return EntityAccountingStatus.LIBRARY
    if boundary.entity_access_accounting is not None:
        return EntityAccountingStatus.REPORTING
    if boundary.extraction_error is not None:
        return EntityAccountingStatus.EXTRACTION_FAILED
    return EntityAccountingStatus.PREDATING
