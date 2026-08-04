"""Stitched-edge + coverage-report persistence (§5.4).

The stitcher is the single writer of both collections (P4) — kept separate
from :class:`~wadi_storage.artifacts.ArtifactRepository`, whose writes belong
to the extraction worker. Writes are replace-by-snapshot: stitching is
deterministic over a snapshot's artifacts, so a retry converges on identical
rows, and delete-first removes any stale rows an aborted earlier run (or a
changed input set) left behind.
"""

from collections.abc import Sequence

from wadi_contracts import CoverageReport, StitchedEdge
from wadi_storage.codec import from_doc, to_doc
from wadi_storage.mongo import COVERAGE_REPORTS, STITCHED_EDGES, WadiDatabase


class StitchRepository:
    """Typed access to the stitcher-owned collections."""

    def __init__(self, database: WadiDatabase) -> None:
        self._db = database

    # --- stitched edges ------------------------------------------------------------

    async def replace_stitched_edges(self, snapshot_id: str, edges: Sequence[StitchedEdge]) -> None:
        """Replace the snapshot's edge set atomically enough to converge on retry.

        Rows are inserted in sorted-id order so identical inputs produce an
        identical collection state regardless of matcher iteration order.
        """
        collection = self._db.collection(STITCHED_EDGES)
        await collection.delete_many({"snapshot_id": snapshot_id})
        ordered = sorted(edges, key=lambda edge: edge.id)
        if ordered:
            await collection.insert_many([to_doc(edge) for edge in ordered])

    async def list_stitched_edges(
        self,
        snapshot_id: str,
        service_id: str | None = None,
        *,
        direction: str = "outbound",
    ) -> list[StitchedEdge]:
        """Edges for a snapshot; optionally scoped to one service.

        ``direction="outbound"`` — edges whose call sites live in the service;
        ``direction="inbound"`` — edges that land on the service's endpoints.
        """
        if direction not in ("outbound", "inbound"):
            raise ValueError(f"direction must be 'outbound' or 'inbound', got {direction!r}")
        query: dict[str, object] = {"snapshot_id": snapshot_id}
        if service_id is not None:
            key = "service_id" if direction == "outbound" else "target_service_id"
            query[key] = service_id
        cursor = self._db.collection(STITCHED_EDGES).find(query).sort("id", 1)
        return [from_doc(StitchedEdge, doc) async for doc in cursor]

    async def list_edges_for_remote_calls(
        self, snapshot_id: str, remote_call_ids: Sequence[str]
    ) -> list[StitchedEdge]:
        """All edges resolving any of the given call facts (ICFG → graph join)."""
        if not remote_call_ids:
            return []
        cursor = (
            self._db.collection(STITCHED_EDGES)
            .find({"snapshot_id": snapshot_id, "remote_call_id": {"$in": list(remote_call_ids)}})
            .sort("id", 1)
        )
        return [from_doc(StitchedEdge, doc) async for doc in cursor]

    # --- coverage report -----------------------------------------------------------

    async def write_coverage_report(self, report: CoverageReport) -> None:
        """Upsert the snapshot's coverage report (one per snapshot)."""
        await self._db.collection(COVERAGE_REPORTS).replace_one(
            {"snapshot_id": report.snapshot_id}, to_doc(report), upsert=True
        )

    async def get_coverage_report(self, snapshot_id: str) -> CoverageReport | None:
        doc = await self._db.collection(COVERAGE_REPORTS).find_one({"snapshot_id": snapshot_id})
        if doc is None:
            return None
        return from_doc(CoverageReport, doc)

    async def coverage_report_exists(self, snapshot_id: str) -> bool:
        """Has the stitcher run for this snapshot?

        Separate from :meth:`get_coverage_report` because the report carries
        unbounded lists — placeholders, unresolved sites, cfg anomalies — and
        reading the whole document just to compare it against None deserializes
        thousands of nested models to answer a yes/no question.
        """
        doc = await self._db.collection(COVERAGE_REPORTS).find_one(
            {"snapshot_id": snapshot_id}, projection={"_id": 1}
        )
        return doc is not None
