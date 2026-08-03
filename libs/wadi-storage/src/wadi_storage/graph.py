"""Neo4j Tier-2 graph: connection seam + stitched-graph repository (§5.4.3, §6).

Kept here so no service ever imports the neo4j driver directly (P1:
`wadi-storage` is the only DB-driver importer). The graph is a **derived,
materialized view** rebuilt from Tier-1 Mongo artifacts at any time:
:meth:`GraphRepository.replace_snapshot` deletes the snapshot's subgraph and
rewrites it, so a crashed or retried stitch converges instead of stranding
stale nodes (MERGE alone could not remove rows a changed input set dropped).

Schema (recorded decision — §5.4.3 binds the INVOKES_REMOTE shape and the
async labels; the rest is decided here):

- Nodes: ``:Service`` ``:Endpoint`` ``:RemoteCall`` (call site)
  ``:ExternalApi`` ``:PlaceholderService`` — every node carries
  ``snapshot_id``; composite uniqueness constraints double as the partition
  indexes (single database, property partitioning; database-per-snapshot is
  Enterprise-only and label-per-snapshot is unindexable).
- Edges: ``(:Service)-[:EXPOSES]->(:Endpoint)``,
  ``(:Service)-[:HAS_CALL_SITE]->(:RemoteCall)``,
  ``(:RemoteCall)-[:INVOKES_REMOTE {…}]->(target)`` and, for ANALYZED targets
  only, ``(:Endpoint)-[:RETURNS_TO]->(:RemoteCall)`` — external/placeholder
  targets have no interior to walk back out of, so a return edge would only
  fabricate cycles. UNDETERMINED facts are RemoteCall nodes with **no**
  INVOKES_REMOTE edge — visible honesty (P10).
- Reserved for Phase 3 (MQ): ``:Producer`` ``:Topic`` ``:Handler`` with
  ``PUBLISHES``/``CONSUMED_BY`` and deliberately no return edge (§5.4.3).
"""

from collections.abc import Sequence
from types import TracebackType
from typing import Any, LiteralString, cast

from neo4j import AsyncDriver, AsyncGraphDatabase

from wadi_contracts import (
    Confidence,
    Endpoint,
    HttpMethod,
    PlaceholderEntry,
    Provenance,
    RemoteCall,
    RemoteEdgeItem,
    RemoteEdgesView,
    ServiceBoundary,
    StitchedEdge,
    TargetKind,
)

_DELETE_BATCH = 5_000

_CONSTRAINTS = (
    "CREATE CONSTRAINT wadi_service_key IF NOT EXISTS "
    "FOR (n:Service) REQUIRE (n.snapshot_id, n.service_id) IS UNIQUE",
    "CREATE CONSTRAINT wadi_endpoint_key IF NOT EXISTS "
    "FOR (n:Endpoint) REQUIRE (n.snapshot_id, n.endpoint_id) IS UNIQUE",
    "CREATE CONSTRAINT wadi_remote_call_key IF NOT EXISTS "
    "FOR (n:RemoteCall) REQUIRE (n.snapshot_id, n.remote_call_id) IS UNIQUE",
    "CREATE CONSTRAINT wadi_external_key IF NOT EXISTS "
    "FOR (n:ExternalApi) REQUIRE (n.snapshot_id, n.host) IS UNIQUE",
    "CREATE CONSTRAINT wadi_placeholder_key IF NOT EXISTS "
    "FOR (n:PlaceholderService) REQUIRE (n.snapshot_id, n.placeholder_id) IS UNIQUE",
)

_NODE_LABELS = ("Endpoint", "RemoteCall", "ExternalApi", "PlaceholderService", "Service")


class GraphStore:
    """Async Neo4j driver wrapper. Derived store — always rebuildable from Tier 1."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
            uri, auth=(user, password)
        )

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()  # pyright: ignore[reportUnknownMemberType]

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> "GraphStore":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def driver(self) -> AsyncDriver:
        """Escape hatch for the stitcher (the graph's single writer, P4)."""
        return self._driver


class GraphRepository:
    """Stitched-graph writes and reads over a :class:`GraphStore`.

    Contract-model ↔ row mapping lives here so callers stay Cypher-free.
    """

    def __init__(
        self, store: GraphStore, *, database: str = "neo4j", batch_size: int = 1_000
    ) -> None:
        self._store = store
        self._database = database
        self._batch_size = max(1, batch_size)

    async def _run(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        result = await self._store.driver.execute_query(  # pyright: ignore[reportUnknownMemberType]
            cast(LiteralString, query), parameters_=parameters or {}, database_=self._database
        )
        records = cast(list[Any], result.records)
        return [dict(record) for record in records]

    # --- schema ---------------------------------------------------------------------

    async def ensure_schema(self) -> None:
        """Create uniqueness constraints (idempotent; writer calls at startup)."""
        for statement in _CONSTRAINTS:
            await self._run(statement)

    # --- rebuild --------------------------------------------------------------------

    async def delete_snapshot(self, snapshot_id: str) -> None:
        """Remove one snapshot's subgraph, batched to bound transaction size."""
        for label in _NODE_LABELS:
            while True:
                rows = await self._run(
                    f"MATCH (n:{label} {{snapshot_id: $snapshot_id}}) "
                    "WITH n LIMIT $batch DETACH DELETE n RETURN count(n) AS deleted",
                    {"snapshot_id": snapshot_id, "batch": _DELETE_BATCH},
                )
                if not rows or int(rows[0].get("deleted", 0)) == 0:
                    break

    async def replace_snapshot(
        self,
        snapshot_id: str,
        *,
        boundaries: Sequence[ServiceBoundary],
        endpoints: Sequence[Endpoint],
        remote_calls: Sequence[RemoteCall],
        edges: Sequence[StitchedEdge],
        placeholders: Sequence[PlaceholderEntry] = (),
    ) -> None:
        """Delete-and-rewrite the snapshot's derived view from Tier-1 truth."""
        await self.delete_snapshot(snapshot_id)

        await self._write_batched(
            "UNWIND $rows AS row "
            "MERGE (s:Service {snapshot_id: $snapshot_id, service_id: row.service_id}) "
            "SET s.name = row.name, s.repo = row.repo, s.build_root = row.build_root",
            snapshot_id,
            [
                {
                    "service_id": b.service_id,
                    "name": b.name,
                    "repo": b.repo,
                    "build_root": b.build_root,
                }
                for b in sorted(boundaries, key=lambda b: b.service_id)
            ],
        )
        await self._write_batched(
            "UNWIND $rows AS row "
            "MERGE (e:Endpoint {snapshot_id: $snapshot_id, endpoint_id: row.endpoint_id}) "
            "SET e.service_id = row.service_id, e.http_method = row.http_method, "
            "    e.simplified_uri = row.simplified_uri, e.full_uri = row.full_uri, "
            "    e.auth_authenticated = row.auth_authenticated, e.auth_roles = row.auth_roles "
            "WITH e, row "
            "MATCH (s:Service {snapshot_id: $snapshot_id, service_id: row.service_id}) "
            "MERGE (s)-[:EXPOSES]->(e)",
            snapshot_id,
            [
                {
                    "endpoint_id": e.id,
                    "service_id": e.service_id,
                    "http_method": e.http_method.value,
                    "simplified_uri": e.simplified_uri,
                    "full_uri": e.full_uri,
                    "auth_authenticated": e.auth.authenticated,
                    "auth_roles": e.auth.roles,
                }
                for e in sorted(endpoints, key=lambda e: e.id)
            ],
        )
        await self._write_batched(
            "UNWIND $rows AS row "
            "MERGE (rc:RemoteCall {snapshot_id: $snapshot_id, remote_call_id: row.remote_call_id}) "
            "SET rc.service_id = row.service_id, rc.mechanism = row.mechanism, "
            "    rc.http_verb = row.http_verb, rc.url = row.url, "
            "    rc.url_confidence = row.url_confidence, rc.file = row.file, rc.line = row.line "
            "WITH rc, row "
            "MATCH (s:Service {snapshot_id: $snapshot_id, service_id: row.service_id}) "
            "MERGE (s)-[:HAS_CALL_SITE]->(rc)",
            snapshot_id,
            [
                {
                    "remote_call_id": c.id,
                    "service_id": c.service_id,
                    "mechanism": c.mechanism,
                    "http_verb": c.http_verb.value if c.http_verb else None,
                    "url": c.url,
                    "url_confidence": c.url_confidence.value,
                    "file": c.site.file,
                    "line": c.site.start_line,
                }
                for c in sorted(remote_calls, key=lambda c: c.id)
            ],
        )
        await self._write_batched(
            "UNWIND $rows AS row "
            "MERGE (p:PlaceholderService "
            "       {snapshot_id: $snapshot_id, placeholder_id: row.placeholder_id}) "
            "SET p.name = row.name, p.resolved_via = row.resolved_via",
            snapshot_id,
            [
                {
                    "placeholder_id": p.placeholder_id,
                    "name": p.name,
                    "resolved_via": p.resolved_via,
                }
                for p in sorted(placeholders, key=lambda p: p.placeholder_id)
            ],
        )

        by_kind: dict[TargetKind, list[StitchedEdge]] = {}
        for edge in edges:
            by_kind.setdefault(edge.target_kind, []).append(edge)

        await self._write_batched(
            "UNWIND $rows AS row "
            "MATCH (rc:RemoteCall "
            "       {snapshot_id: $snapshot_id, remote_call_id: row.remote_call_id}) "
            "MATCH (ep:Endpoint {snapshot_id: $snapshot_id, endpoint_id: row.target_endpoint_id}) "
            "MERGE (rc)-[e:INVOKES_REMOTE {edge_id: row.edge_id}]->(ep) "
            "SET e += row.props "
            "MERGE (ep)-[:RETURNS_TO {edge_id: row.edge_id}]->(rc)",
            snapshot_id,
            [
                self._edge_row(e)
                for e in sorted(by_kind.get(TargetKind.ANALYZED, []), key=lambda e: e.id)
            ],
        )
        await self._write_batched(
            "UNWIND $rows AS row "
            "MATCH (rc:RemoteCall "
            "       {snapshot_id: $snapshot_id, remote_call_id: row.remote_call_id}) "
            "MERGE (x:ExternalApi {snapshot_id: $snapshot_id, host: row.external_host}) "
            "MERGE (rc)-[e:INVOKES_REMOTE {edge_id: row.edge_id}]->(x) "
            "SET e += row.props",
            snapshot_id,
            [
                self._edge_row(e)
                for e in sorted(by_kind.get(TargetKind.EXTERNAL, []), key=lambda e: e.id)
            ],
        )
        await self._write_batched(
            "UNWIND $rows AS row "
            "MATCH (rc:RemoteCall "
            "       {snapshot_id: $snapshot_id, remote_call_id: row.remote_call_id}) "
            "MERGE (p:PlaceholderService "
            "       {snapshot_id: $snapshot_id, placeholder_id: row.target_service_id}) "
            "MERGE (rc)-[e:INVOKES_REMOTE {edge_id: row.edge_id}]->(p) "
            "SET e += row.props",
            snapshot_id,
            [
                self._edge_row(e)
                for e in sorted(by_kind.get(TargetKind.PLACEHOLDER, []), key=lambda e: e.id)
            ],
        )
        # UNDETERMINED: deliberately no edge — the dangling RemoteCall node IS
        # the honest representation (P10).

    @staticmethod
    def _edge_row(edge: StitchedEdge) -> dict[str, Any]:
        return {
            "edge_id": edge.id,
            "remote_call_id": edge.remote_call_id,
            "target_endpoint_id": edge.target_endpoint_id,
            "target_service_id": edge.target_service_id,
            "external_host": edge.external_host,
            "props": {
                "url": edge.url,
                "confidence": edge.confidence.value,
                "provenance": edge.provenance.value,
                "mechanism": edge.mechanism,
                "http_verb": edge.http_verb.value if edge.http_verb else None,
                "target_kind": edge.target_kind.value,
                "evidence": edge.evidence,
            },
        }

    async def _write_batched(
        self, query: str, snapshot_id: str, rows: list[dict[str, Any]]
    ) -> None:
        for start in range(0, len(rows), self._batch_size):
            chunk = rows[start : start + self._batch_size]
            await self._run(query, {"snapshot_id": snapshot_id, "rows": chunk})

    # --- reads ----------------------------------------------------------------------

    _EDGE_RETURN = (
        "RETURN e.edge_id AS edge_id, rc.remote_call_id AS remote_call_id, "
        "rc.service_id AS caller_service_id, caller.name AS caller_service_name, "
        "e.mechanism AS mechanism, e.http_verb AS http_verb, e.url AS url, "
        "e.target_kind AS target_kind, e.confidence AS confidence, "
        "e.provenance AS provenance, e.evidence AS evidence, "
        "CASE WHEN target:Endpoint THEN target.service_id "
        "     WHEN target:PlaceholderService THEN target.placeholder_id END AS target_service_id, "
        "CASE WHEN target:Endpoint THEN target_svc.name "
        "     WHEN target:PlaceholderService THEN target.name END AS target_service_name, "
        "CASE WHEN target:Endpoint THEN target.endpoint_id END AS target_endpoint_id, "
        "CASE WHEN target:Endpoint THEN target.http_method END AS target_http_method, "
        "CASE WHEN target:Endpoint THEN target.simplified_uri END AS target_simplified_uri, "
        "CASE WHEN target:ExternalApi THEN target.host END AS external_host "
        "ORDER BY edge_id"
    )

    _EDGE_MATCH = (
        "MATCH (caller:Service {snapshot_id: $snapshot_id})-[:HAS_CALL_SITE]->(rc)"
        "-[e:INVOKES_REMOTE]->(target) "
        "OPTIONAL MATCH (target_svc:Service {snapshot_id: $snapshot_id}) "
        "WHERE target:Endpoint AND target_svc.service_id = target.service_id "
    )

    async def remote_edges(self, snapshot_id: str, service_id: str) -> RemoteEdgesView:
        """Who this service calls, and who calls it (§8 ``remote_edges``)."""
        outbound = await self._run(
            self._EDGE_MATCH + "WITH * WHERE caller.service_id = $service_id " + self._EDGE_RETURN,
            {"snapshot_id": snapshot_id, "service_id": service_id},
        )
        inbound = await self._run(
            self._EDGE_MATCH
            + "WITH * WHERE target:Endpoint AND target.service_id = $service_id "
            + self._EDGE_RETURN,
            {"snapshot_id": snapshot_id, "service_id": service_id},
        )
        return RemoteEdgesView(
            service_id=service_id,
            outbound=[self._edge_item(row) for row in outbound],
            inbound=[self._edge_item(row) for row in inbound],
        )

    async def all_edges(self, snapshot_id: str) -> list[RemoteEdgeItem]:
        """Every stitched edge in the snapshot — the system map's read
        (§11 Phase 2.7 M4). Same denormalized shape as ``remote_edges``,
        one row per edge (no per-service duplication)."""
        rows = await self._run(self._EDGE_MATCH + self._EDGE_RETURN, {"snapshot_id": snapshot_id})
        return [self._edge_item(row) for row in rows]

    async def resolve_call_targets(
        self, snapshot_id: str, remote_call_ids: Sequence[str]
    ) -> list[RemoteEdgeItem]:
        """Stitched targets for specific call facts (cross-service ICFG expansion)."""
        if not remote_call_ids:
            return []
        rows = await self._run(
            self._EDGE_MATCH
            + "WITH * WHERE rc.remote_call_id IN $remote_call_ids "
            + self._EDGE_RETURN,
            {"snapshot_id": snapshot_id, "remote_call_ids": list(remote_call_ids)},
        )
        return [self._edge_item(row) for row in rows]

    @staticmethod
    def _edge_item(row: dict[str, Any]) -> RemoteEdgeItem:
        return RemoteEdgeItem(
            edge_id=str(row["edge_id"]),
            remote_call_id=str(row["remote_call_id"]),
            caller_service_id=str(row["caller_service_id"]),
            caller_service_name=row.get("caller_service_name"),
            mechanism=str(row["mechanism"]),
            http_verb=HttpMethod(row["http_verb"]) if row.get("http_verb") else None,
            url=row.get("url"),
            target_kind=TargetKind(row["target_kind"]),
            target_service_id=row.get("target_service_id"),
            target_service_name=row.get("target_service_name"),
            target_endpoint_id=row.get("target_endpoint_id"),
            target_http_method=(
                HttpMethod(row["target_http_method"]) if row.get("target_http_method") else None
            ),
            target_simplified_uri=row.get("target_simplified_uri"),
            external_host=row.get("external_host"),
            confidence=Confidence(row["confidence"]),
            provenance=Provenance(row["provenance"]),
            evidence=row.get("evidence"),
        )
