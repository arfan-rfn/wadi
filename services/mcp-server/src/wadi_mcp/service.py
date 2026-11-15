"""The tool logic behind the MCP server — a plain class over wadi-storage.

The MCP layer (server.py) is a thin registration shim over these methods, so
the logic is testable without any transport. Outputs are the same contract
models as stored artifacts (§8: one schema everywhere), rendered to JSON-mode
dicts at the boundary.
"""

import asyncio
from typing import Any, Literal

from wadi_contracts import (
    UNDETERMINED_ENTITY_NAME,
    EndpointEntityAccess,
    EntityUsageRow,
    EntityUsageView,
    Icfg,
    resolve_type_shape,
)
from wadi_mcp.rollup import method_rollup, statement_detail
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    SnapshotRepository,
    StitchRepository,
    SystemRepository,
    WadiDatabase,
    endpoint_outbound,
    entity_usage_view,
)

#: Said wherever an endpoint's entity summary is None (R1-6). An agent cannot
#: open the code to check, so `null` has to arrive already explained, and with
#: the one action that fixes it.
ENTITY_FACTS_PREDATE_NOTE = (
    "This snapshot predates entity facts: entity_access is null because nothing was "
    "examined, not because the endpoint touches no data. Re-analyze the system to get them."
)


class NotFoundError(LookupError):
    """Requested entity does not exist — message is agent-facing and precise."""


def _select_entity(rows: list[EntityUsageRow], entity: str) -> list[EntityUsageRow]:
    """The reverse-view rows one `entity` argument names.

    A qualified name selects its rows, in every service that has the type. A
    simple name is accepted when it names exactly one entity, and an ambiguous
    one is refused with the candidates: two classes called `Order` in two
    services are two entities, and merging them would answer a question
    nobody asked.
    """
    exact = [row for row in rows if row.entity == entity]
    if exact:
        return exact
    named = [row for row in rows if row.name == entity]
    candidates = sorted({row.entity or UNDETERMINED_ENTITY_NAME for row in named})
    if len(candidates) > 1:
        raise ValueError(
            f"{entity!r} names {len(candidates)} entities in this snapshot: {candidates}; "
            "pass one qualified name, or a service_id to narrow it"
        )
    if not named:
        raise NotFoundError(
            f"no entity {entity!r} is declared or touched here; call entity_usage without "
            "`entity` to list the entities this snapshot has"
        )
    return named


def _usage_note(view: EntityUsageView) -> str | None:
    """Say what an empty or partial reverse view is, so it is not read as a fact.

    `entities: []` on a snapshot that predates the phase means nothing was
    looked at; read as "touched by nothing" it would be the claim R1-6 exists
    to prevent.
    """
    predating = view.endpoints_predating
    if not view.analyzed:
        if predating == 0:
            return "This snapshot holds no endpoints yet, so there are no entity facts to read."
        return (
            "This snapshot predates entity facts: its endpoints were never examined for "
            "repository calls, so `entities` is empty because nothing was looked at. "
            "Re-analyze the system to get them."
        )
    if predating == 1:
        return (
            "1 endpoint predates entity facts and is not in this view; "
            "re-analyze the system to include it."
        )
    if predating:
        return (
            f"{predating} endpoints predate entity facts and are not in this view; "
            "re-analyze the system to include them."
        )
    return None


def _entity_facts(summary: list[EndpointEntityAccess] | None) -> dict[str, str]:
    """Which of the two answers an endpoint's entity summary is (§5.2.17, R1-6).

    `analyzed` covers `[]` too: looked, and no repository call was found. A
    forwarding endpoint is one of those, and its `outbound` says where the
    work went instead (Q26).
    """
    if summary is None:
        return {"entity_facts": "predates-phase", "entity_facts_note": ENTITY_FACTS_PREDATE_NOTE}
    return {"entity_facts": "analyzed"}


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

        The result adds three keys to the endpoint's own fields: `outbound`
        and `stitched`, from the same function the workspace's `/detail` calls
        (C5), and `entity_facts`. Without the edges a forwarding endpoint reads as one
        that does nothing: its entity summary is `[]` because the data lives
        behind the service it calls (Q26).
        """
        endpoint, icfg = await asyncio.gather(
            self._artifacts.get_endpoint(snapshot_id, endpoint_id),
            self._artifacts.get_icfg(snapshot_id, endpoint_id),
        )
        if endpoint is None:
            raise NotFoundError(
                f"endpoint {endpoint_id!r} not found in snapshot {snapshot_id!r}; "
                "use list_endpoints to find endpoint ids"
            )
        outbound, stitched = await endpoint_outbound(
            self._stitch,
            self._graph,
            snapshot_id=snapshot_id,
            service_id=endpoint.service_id,
            icfg=icfg,
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
        return {
            **endpoint.model_dump(mode="json"),
            "outbound": [edge.model_dump(mode="json") for edge in outbound],
            "stitched": stitched,
            **_entity_facts(endpoint.entity_access),
        }

    async def entity_usage(
        self, snapshot_id: str, entity: str | None = None, service_id: str | None = None
    ) -> dict[str, Any]:
        """Which endpoints may create, read, update or delete each entity (§5.2.17).

        The view is folded by the same function as the orchestrator's
        `/entities` route (R1-22), then narrowed: `service_id` scopes its
        inputs, so `analyzed` describes that service, and `entity` keeps the
        rows it names together with the services they belong to.

        A snapshot written before entity facts answers `analyzed: false` and a
        `note` saying so, whatever entity is asked about, because nothing was
        examined. It never answers that no endpoint touches the entity.
        """
        if await self._snapshots.get(snapshot_id) is None:
            raise NotFoundError(f"snapshot {snapshot_id!r} not found; use list_snapshots first")
        if (
            service_id is not None
            and await self._artifacts.get_service_boundary(snapshot_id, service_id) is None
        ):
            raise NotFoundError(
                f"service {service_id!r} not found in snapshot {snapshot_id!r}; "
                "use list_services first"
            )
        view = await entity_usage_view(self._artifacts, snapshot_id, service_id=service_id)
        if entity is not None and view.analyzed:
            rows = _select_entity(view.entities, entity)
            owners = {row.service_id for row in rows}
            view = view.model_copy(
                update={
                    "entities": rows,
                    "services": [s for s in view.services if s.service_id in owners],
                }
            )
        result = view.model_dump(mode="json")
        note = _usage_note(view)
        if note is not None:
            result["note"] = note
        return result

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
        icfg, summary = await asyncio.gather(
            self._load_icfg(snapshot_id, endpoint_id),
            self._artifacts.get_endpoint_entity_access(snapshot_id, endpoint_id),
        )
        # §5.2.17: empty `entity_access_sites` on every node reads the same on
        # a graph that predates the phase and on an endpoint that makes no
        # repository call. Only the endpoint's summary tells them apart, so
        # both levels say which (R1-6).
        facts = _entity_facts(summary.entity_access if summary is not None else None)
        if detail == "methods":
            rollup = method_rollup(icfg)
            if cross_service:
                await self._annotate_cross_service(snapshot_id, icfg, rollup)
            return rollup | facts
        if method_id is None:
            raise ValueError(
                "detail='statements' requires method_id — statement-level output is a "
                "method-scoped drill-down; call with detail='methods' first and pick a method"
            )
        try:
            return statement_detail(icfg, method_id) | facts
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
