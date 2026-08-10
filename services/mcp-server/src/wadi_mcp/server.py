"""MCP registration shim over the tool logic (§8).

Same codebase, two transports: stdio (spawned by a coding agent; needs only
DB connection strings) and streamable HTTP (a container in the compose
stack). Tools are high-level and semantic — agents are never expected to
write CPGQL.
"""

# Tool functions are registered via decorators, not called by name:
# pyright: reportUnusedFunction=false

from typing import Any, Literal

from mcp.server import MCPServer

from wadi_mcp.service import WadiMcpService

SERVER_INSTRUCTIONS = (
    "Wadi serves the analyzed, ground-truth architecture of microservice systems: "
    "services, REST endpoints (with structured auth), per-endpoint control-flow "
    "graphs down to database/HTTP/message-queue calls, and the stitched "
    "cross-service graph. Navigate top-down: "
    "list_systems -> list_snapshots -> list_services -> list_endpoints -> "
    "endpoint_detail | endpoint_icfg. "
    "Before trusting cross-service answers, call coverage_report for the snapshot "
    "first: it lists what the map knows it doesn't know — placeholder services, "
    "external APIs, unresolved/low-confidence calls. Use remote_edges for a "
    "service's callers/callees, and endpoint_icfg with cross_service=true to see "
    "which downstream endpoints a flow reaches (recurse into them with further "
    "endpoint_icfg calls). Every stitched edge carries confidence "
    "(exact/high/heuristic/none) and provenance (how it was determined) — "
    "undetermined targets are explicit facts, never silently dropped."
)


def create_server(service: WadiMcpService) -> MCPServer:
    mcp = MCPServer("wadi", instructions=SERVER_INSTRUCTIONS)

    @mcp.tool()
    async def list_systems() -> list[dict[str, Any]]:
        """List every system registered for analysis, with its repositories."""
        return await service.list_systems()

    @mcp.tool()
    async def list_snapshots(system_id: str) -> list[dict[str, Any]]:
        """List a system's analysis snapshots (newest first): pinned commits + status."""
        return await service.list_snapshots(system_id)

    @mcp.tool()
    async def list_services(snapshot_id: str) -> list[dict[str, Any]]:
        """List the services discovered in a snapshot: languages, build roots, network identity."""
        return await service.list_services(snapshot_id)

    @mcp.tool()
    async def list_endpoints(snapshot_id: str, service_id: str) -> list[dict[str, Any]]:
        """List a service's REST endpoints: method, URI, params, structured auth, handler."""
        return await service.list_endpoints(snapshot_id, service_id)

    @mcp.tool()
    async def endpoint_detail(
        snapshot_id: str, endpoint_id: str, resolve_shapes: bool = True
    ) -> dict[str, Any]:
        """One endpoint's full contract: request/response shapes, declared
        statuses, params, structured auth, handler.

        The shapes are NOT on `list_endpoints` rows — that list is deliberately
        light — so this is where you read what an endpoint accepts and returns.

        `resolve_shapes=True` (default) gives a plain tree. Pass False for the
        shared form: each type defined once in `type_defs` and referenced
        wherever it occurs, which is dramatically smaller when a response names
        the same types repeatedly, as entity models do.
        """
        return await service.endpoint_detail(
            snapshot_id, endpoint_id, resolve_shapes=resolve_shapes
        )

    @mcp.tool()
    async def coverage_report(snapshot_id: str) -> dict[str, Any]:
        """What the stitched map knows it doesn't know — check this FIRST.

        Lists placeholder services (config knows them, wadi wasn't given the
        repo), external APIs, unresolved calls with machine-readable reasons,
        low-confidence edges, and config conflicts.
        """
        return await service.coverage_report(snapshot_id)

    @mcp.tool()
    async def remote_edges(snapshot_id: str, service_id: str) -> dict[str, Any]:
        """Who this service calls and who calls it, from the stitched graph.

        Each edge carries the target kind (analyzed service / external API /
        placeholder), confidence, provenance, and the resolution evidence.
        """
        return await service.remote_edges(snapshot_id, service_id)

    @mcp.tool()
    async def endpoint_icfg(
        snapshot_id: str,
        endpoint_id: str,
        detail: Literal["methods", "statements"] = "methods",
        method_id: str | None = None,
        cross_service: bool = False,
    ) -> dict[str, Any]:
        """Get an endpoint's control-flow graph.

        Default detail='methods' returns the method-level roll-up (which methods
        run, what they call, DB/HTTP/MQ sinks). Use detail='statements' with a
        method_id from the roll-up to drill into one method's statements,
        branches, and loops with source anchors. With cross_service=true the
        roll-up gains 'remote_targets' (stitched targets per call site) and
        'downstream' (analyzed endpoints this flow reaches — recurse into them
        with further endpoint_icfg calls).
        """
        return await service.endpoint_icfg(
            snapshot_id, endpoint_id, detail, method_id, cross_service
        )

    return mcp
