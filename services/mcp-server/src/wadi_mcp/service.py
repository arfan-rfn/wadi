"""The tool logic behind the MCP server — a plain class over wadi-storage.

The MCP layer (server.py) is a thin registration shim over these methods, so
the logic is testable without any transport. Outputs are the same contract
models as stored artifacts (§8: one schema everywhere), rendered to JSON-mode
dicts at the boundary.
"""

from typing import Any, Literal

from wadi_contracts import Icfg
from wadi_mcp.rollup import method_rollup, statement_detail
from wadi_storage import (
    ArtifactRepository,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)


class NotFoundError(LookupError):
    """Requested entity does not exist — message is agent-facing and precise."""


class WadiMcpService:
    def __init__(self, database: WadiDatabase) -> None:
        self._systems = SystemRepository(database)
        self._snapshots = SnapshotRepository(database)
        self._artifacts = ArtifactRepository(database)

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
        return [
            endpoint.model_dump(mode="json")
            for endpoint in await self._artifacts.list_endpoints(snapshot_id, service_id)
        ]

    async def endpoint_icfg(
        self,
        snapshot_id: str,
        endpoint_id: str,
        detail: Literal["methods", "statements"] = "methods",
        method_id: str | None = None,
    ) -> dict[str, Any]:
        icfg = await self._load_icfg(snapshot_id, endpoint_id)
        if detail == "methods":
            return method_rollup(icfg)
        if method_id is None:
            raise ValueError(
                "detail='statements' requires method_id — statement-level output is a "
                "method-scoped drill-down; call with detail='methods' first and pick a method"
            )
        try:
            return statement_detail(icfg, method_id)
        except KeyError as exc:
            raise NotFoundError(str(exc)) from exc

    async def _load_icfg(self, snapshot_id: str, endpoint_id: str) -> Icfg:
        icfg = await self._artifacts.get_icfg(snapshot_id, endpoint_id)
        if icfg is None:
            raise NotFoundError(
                f"no ICFG for endpoint {endpoint_id!r} in snapshot {snapshot_id!r}; "
                "use list_endpoints to find endpoint ids"
            )
        return icfg
