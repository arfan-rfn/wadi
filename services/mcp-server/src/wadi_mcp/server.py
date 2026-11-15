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
    "undetermined targets are explicit facts, never silently dropped. "
    "For data, endpoint_detail's entity_access says which entities an endpoint "
    "may touch and how, and entity_usage answers the reverse: which endpoints "
    "may create, read, update or delete a given entity."
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

        Also here: `entity_access` (the entities it may touch, and how),
        `entity_facts` ("analyzed", or "predates-phase" with a note to
        re-analyze), and `outbound` with `stitched`, the stitched calls this
        endpoint's flow makes. An endpoint with no entity access but outbound
        calls forwards the work to another service.

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
    async def entity_usage(
        snapshot_id: str, entity: str | None = None, service_id: str | None = None
    ) -> dict[str, Any]:
        """Which endpoints may create, read, update, delete each entity.

        One row per entity per service, with all six operations (create, read,
        update, delete, create-or-update, unknown) and the endpoints under
        each. "May" is the meaning: some path through the endpoint performs
        it. `create-or-update` is one save the analysis could not split, never
        a create plus an update. An entity no endpoint reaches is a row of
        empty lists; accesses whose entity could not be determined have their
        own "entity not determined" row.

        Under each operation, an endpoint's `call_sites` counts its calls that
        perform THAT operation on that entity, not all its calls on the
        entity. It is null, with a `call_sites_note`, when the endpoint's
        summary predates per-operation counts; re-analyze to get them.

        `entity` takes a qualified type name, or a simple name that names one
        entity. `service_id` narrows to one service.

        Each service carries a `status`: `reporting` (examined; its
        `accounting` is present), `predating` (written before entity facts;
        re-analyze), `extraction-failed` (never examined), or `library` (its
        calls are counted in each service that depends on it).
        `analyzed: false` means nothing in the answer was examined, so an
        empty list is not "no endpoint touches it". The `note` says why.
        """
        return await service.entity_usage(snapshot_id, entity, service_id)

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

        Repository calls carry `entity_access_sites` (the entities and
        operations each one touches) at both levels, and `entity_facts` says
        whether the snapshot was analyzed for them: on a "predates-phase"
        graph, no sites does not mean no repository calls. An access's
        `operation` is the claim. A `candidate_operation` beside it is the
        verb a gated rule computed and withheld, labelled by its
        `candidate_note`; it is evidence, never the operation.
        """
        return await service.endpoint_icfg(
            snapshot_id, endpoint_id, detail, method_id, cross_service
        )

    return mcp
