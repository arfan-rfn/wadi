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
    "services, REST endpoints (with structured auth), and per-endpoint control-flow "
    "graphs down to database/HTTP/message-queue calls. Navigate top-down: "
    "list_systems -> list_snapshots -> list_services -> list_endpoints -> endpoint_icfg."
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
    async def endpoint_icfg(
        snapshot_id: str,
        endpoint_id: str,
        detail: Literal["methods", "statements"] = "methods",
        method_id: str | None = None,
    ) -> dict[str, Any]:
        """Get an endpoint's control-flow graph.

        Default detail='methods' returns the method-level roll-up (which methods
        run, what they call, DB/HTTP/MQ sinks). Use detail='statements' with a
        method_id from the roll-up to drill into one method's statements,
        branches, and loops with source anchors.
        """
        return await service.endpoint_icfg(snapshot_id, endpoint_id, detail, method_id)

    return mcp
