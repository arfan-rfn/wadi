"""The tool logic behind the MCP server — a plain class over wadi-storage.

The MCP layer (server.py) is a thin registration shim over these methods, so
the logic is testable without any transport. Outputs are the same contract
models as stored artifacts (§8: one schema everywhere), rendered to JSON-mode
dicts at the boundary.
"""

from typing import Any, Literal

from wadi_contracts import Icfg, resolve_type_shape
from wadi_mcp.rollup import method_rollup, statement_detail
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    SnapshotRepository,
    StitchRepository,
    SystemRepository,
    WadiDatabase,
)


class NotFoundError(LookupError):
    """Requested entity does not exist — message is agent-facing and precise."""


class WadiMcpService:
    def __init__(self, database: WadiDatabase, graph: GraphRepository) -> None:
        self._systems = SystemRepository(database)
        self._snapshots = SnapshotRepository(database)
        self._artifacts = ArtifactRepository(database)
        self._stitch = StitchRepository(database)
        self._graph = graph

    async def list_systems(self) -> list[dict[str, Any]]:
        return [system.model_dump(mode="json") for system in await self._systems.list_all()]

    async def list_snapshots(self, system_id: str) -> list[dict[str, Any]]:
        system = await self._systems.get(system_id)
        if system is None:
            raise NotFoundError(f"system {system_id!r} not found; use list_systems first")
        return [
            snapshot.model_dump(mode="json")
            for snapshot in await self._snapshots.list_for_system(system_id)
        ]

    async def list_services(self, snapshot_id: str) -> list[dict[str, Any]]:
        if await self._snapshots.get(snapshot_id) is None:
            raise NotFoundError(f"snapshot {snapshot_id!r} not found; use list_snapshots first")
        return [
            boundary.model_dump(mode="json")
            for boundary in await self._artifacts.list_service_boundaries(snapshot_id)
        ]

    async def list_endpoints(self, snapshot_id: str, service_id: str) -> list[dict[str, Any]]:
        boundary = await self._artifacts.get_service_boundary(snapshot_id, service_id)
        if boundary is None:
            raise NotFoundError(
                f"service {service_id!r} not found in snapshot {snapshot_id!r}; "
                "use list_services first"
            )
        # List rows, not whole endpoints (§5.2.15). The wire shapes are 124 MB
        # of a 126 MB response on ICPC's `contest`, and this tool answers into
        # an agent's context window — the one consumer that can least afford
        # it. `endpoint_detail` carries both shapes for a single endpoint.
        return [
            row.model_dump(mode="json")
            for row in await self._artifacts.list_endpoint_summaries(snapshot_id, service_id)
        ]

    async def endpoint_detail(
        self, snapshot_id: str, endpoint_id: str, *, resolve_shapes: bool = True
    ) -> dict[str, Any]:
        """One endpoint's full contract — the shapes a list row does not carry.

        §5.2.15 moved the wire shapes off the list row for size, and this tool
        did not exist, so `list_endpoints` had been an agent's ONLY route to a
        request or response shape. That left the MCP surface — the one that
        exists so agents can read ground truth rather than grep — unable to
        answer what an endpoint accepts or returns.

        `resolve_shapes` inlines the `type_defs` refs (§5.2.16) so a caller
        reads a tree without implementing resolution. Pass False to get the
        shared form plus `type_defs`, which is far smaller when a shape names
        the same type repeatedly and is what a large entity model needs.
        """
        endpoint = await self._artifacts.get_endpoint(snapshot_id, endpoint_id)
        if endpoint is None:
            raise NotFoundError(
                f"endpoint {endpoint_id!r} not found in snapshot {snapshot_id!r}; "
                "use list_endpoints to find endpoint ids"
            )
        if resolve_shapes and endpoint.type_defs:
            endpoint = endpoint.model_copy(
                update={
                    "request_schema": (
                        resolve_type_shape(endpoint.request_schema, endpoint.type_defs)
                        if endpoint.request_schema is not None
                        else None
                    ),
                    "response_schema": (
                        resolve_type_shape(endpoint.response_schema, endpoint.type_defs)
                        if endpoint.response_schema is not None
                        else None
                    ),
                    # Dropped once inlined: keeping them would ship every
                    # definition twice, which is the cost this avoids.
                    "type_defs": {},
                }
            )
        return endpoint.model_dump(mode="json")

    async def coverage_report(self, snapshot_id: str) -> dict[str, Any]:
        if await self._snapshots.get(snapshot_id) is None:
            raise NotFoundError(f"snapshot {snapshot_id!r} not found; use list_snapshots first")
        report = await self._stitch.get_coverage_report(snapshot_id)
        if report is None:
            raise NotFoundError(
                f"snapshot {snapshot_id!r} is not stitched yet — no coverage report exists"
            )
        return report.model_dump(mode="json")

    async def remote_edges(self, snapshot_id: str, service_id: str) -> dict[str, Any]:
        boundary = await self._artifacts.get_service_boundary(snapshot_id, service_id)
        if boundary is None:
            raise NotFoundError(
                f"service {service_id!r} not found in snapshot {snapshot_id!r}; "
                "use list_services first"
            )
        view = await self._graph.remote_edges(snapshot_id, service_id)
        return view.model_dump(mode="json")

    async def endpoint_icfg(
        self,
        snapshot_id: str,
        endpoint_id: str,
        detail: Literal["methods", "statements"] = "methods",
        method_id: str | None = None,
        cross_service: bool = False,
    ) -> dict[str, Any]:
        icfg = await self._load_icfg(snapshot_id, endpoint_id)
        if detail == "methods":
            rollup = method_rollup(icfg)
            if cross_service:
                await self._annotate_cross_service(snapshot_id, icfg, rollup)
            return rollup
        if method_id is None:
            raise ValueError(
                "detail='statements' requires method_id — statement-level output is a "
                "method-scoped drill-down; call with detail='methods' first and pick a method"
            )
        try:
            return statement_detail(icfg, method_id)
        except KeyError as exc:
            raise NotFoundError(str(exc)) from exc

    async def _annotate_cross_service(
        self, snapshot_id: str, icfg: Icfg, rollup: dict[str, Any]
    ) -> None:
        """Expand call sites into their stitched targets (§8 cross_service=true).

        Depth-1 by design: the ``downstream`` list gives the analyzed endpoints
        an agent can recurse into with further endpoint_icfg calls — fan-out is
        bounded per query, never inlined into one response (§5.4.3).
        """
        call_ids = sorted(
            {rc_id for node in icfg.nodes for rc_id in node.remote_call_ids}
            | {node.remote_call_id for node in icfg.nodes if node.remote_call_id is not None}
        )
        items = await self._graph.resolve_call_targets(snapshot_id, call_ids)
        rollup["remote_targets"] = [item.model_dump(mode="json") for item in items]
        rollup["downstream"] = [
            {
                "endpoint_id": item.target_endpoint_id,
                "service_id": item.target_service_id,
                "service_name": item.target_service_name,
                "http_method": item.target_http_method.value if item.target_http_method else None,
                "simplified_uri": item.target_simplified_uri,
                "confidence": item.confidence.value,
            }
            for item in items
            if item.target_endpoint_id is not None
        ]

    async def _load_icfg(self, snapshot_id: str, endpoint_id: str) -> Icfg:
        icfg = await self._artifacts.get_icfg(snapshot_id, endpoint_id)
        if icfg is None:
            raise NotFoundError(
                f"no ICFG for endpoint {endpoint_id!r} in snapshot {snapshot_id!r}; "
                "use list_endpoints to find endpoint ids"
            )
        return icfg
