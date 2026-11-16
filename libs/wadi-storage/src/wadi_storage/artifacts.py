"""Artifact repository — per-(snapshot, service) versioned JSON artifacts (Tier 1).

Single writer: the extraction worker (P4). All writes are idempotent upserts
keyed on ``(snapshot_id, service_id, id)`` so a retried job converges instead
of duplicating or failing.

ICFG documents are chunk-aware: oversized graphs become a manifest in
``icfgs`` plus parts in ``icfg_parts``; readers always get one logical
:class:`~wadi_contracts.Icfg` back (§6).
"""

from collections import Counter
from collections.abc import Sequence
from typing import NamedTuple, cast

from pymongo import ReplaceOne

from wadi_contracts import (
    DataModel,
    Endpoint,
    EndpointEntityAccessRow,
    EndpointSummary,
    Icfg,
    MqInteraction,
    RemoteCall,
    ServiceBoundary,
)
from wadi_storage.chunking import needs_chunking, pack_items
from wadi_storage.codec import from_doc, to_doc
from wadi_storage.mongo import (
    DATA_MODELS,
    ENDPOINTS,
    ICFG_PARTS,
    ICFGS,
    MQ_INTERACTIONS,
    REMOTE_CALLS,
    SERVICE_BOUNDARIES,
    MongoDocument,
    WadiDatabase,
)

#: The five fields the entity reads name (R1-8). An inclusion projection, so a
#: field a later contract adds to an endpoint is not read by accident.
_ENTITY_ACCESS_PROJECTION: MongoDocument = {
    "_id": 0,
    "id": 1,
    "service_id": 1,
    "http_method": 1,
    "full_uri": 1,
    "entity_access": 1,
}


#: Every remote-call id on a graph document's nodes: an array of arrays
#: (`nodes.remote_call_ids`) flattened, then deduped by the set union.
_CALL_IDS_UNION: MongoDocument = {
    "$setUnion": [
        {
            "$reduce": {
                "input": {"$ifNull": ["$nodes.remote_call_ids", []]},
                "initialValue": [],
                "in": {"$concatArrays": ["$$value", {"$ifNull": ["$$this", []]}]},
            }
        },
        [],
    ]
}

#: The unbound reason of every node that has one, one entry per node. The
#: codec writes `None` for a bound call, so the nulls are filtered out.
_UNBOUND_REASONS: MongoDocument = {
    "$filter": {
        "input": {"$ifNull": ["$nodes.callee_unbound_reason", []]},
        "as": "reason",
        "cond": {"$ne": ["$$reason", None]},
    }
}


class FlowMarks(NamedTuple):
    """What one endpoint's flow is marked with, read without the flow (review #6).

    ``unbound_reasons`` counts the call nodes whose callee has no interior, by
    the reason's wire value (§5.4.2 T5). Wire values rather than the enum, so
    a reason newer than this reader is counted instead of failing the read.
    """

    remote_call_ids: set[str]
    unbound_reasons: dict[str, int]


def _entity_access_row(doc: MongoDocument) -> EndpointEntityAccessRow:
    # `get`, not indexing: a document written before the phase has no
    # `entity_access` key, and that absence is the answer "predates" (R1-6).
    return EndpointEntityAccessRow.model_validate(
        {
            "endpoint_id": doc["id"],
            "service_id": doc["service_id"],
            "http_method": doc["http_method"],
            "full_uri": doc["full_uri"],
            "entity_access": doc.get("entity_access"),
        }
    )


class ArtifactRepository:
    def __init__(self, database: WadiDatabase) -> None:
        self._db = database

    # --- generic upsert helpers -------------------------------------------------

    async def _upsert_many(
        self,
        collection: str,
        artifacts: Sequence[Endpoint | RemoteCall | MqInteraction | DataModel],
    ) -> None:
        if not artifacts:
            return
        operations = [
            ReplaceOne(
                {
                    "snapshot_id": artifact.snapshot_id,
                    "service_id": artifact.service_id,
                    "id": artifact.id,
                },
                to_doc(artifact),
                upsert=True,
            )
            for artifact in artifacts
        ]
        await self._db.collection(collection).bulk_write(operations, ordered=False)

    # --- service boundaries ------------------------------------------------------

    async def write_service_boundaries(self, boundaries: Sequence[ServiceBoundary]) -> None:
        if not boundaries:
            return
        operations = [
            ReplaceOne(
                # The boundary IS the service: identity is (snapshot, service).
                {"snapshot_id": boundary.snapshot_id, "service_id": boundary.service_id},
                to_doc(boundary),
                upsert=True,
            )
            for boundary in boundaries
        ]
        await self._db.collection(SERVICE_BOUNDARIES).bulk_write(operations, ordered=False)

    async def list_service_boundaries(self, snapshot_id: str) -> list[ServiceBoundary]:
        cursor = (
            self._db.collection(SERVICE_BOUNDARIES)
            .find({"snapshot_id": snapshot_id})
            .sort("name", 1)
        )
        return [from_doc(ServiceBoundary, doc) async for doc in cursor]

    async def get_service_boundary(
        self, snapshot_id: str, service_id: str
    ) -> ServiceBoundary | None:
        doc = await self._db.collection(SERVICE_BOUNDARIES).find_one(
            {"snapshot_id": snapshot_id, "service_id": service_id}
        )
        return from_doc(ServiceBoundary, doc) if doc else None

    # --- endpoints ----------------------------------------------------------------

    async def write_endpoints(self, endpoints: Sequence[Endpoint]) -> None:
        await self._upsert_many(ENDPOINTS, endpoints)

    async def list_endpoints(self, snapshot_id: str, service_id: str) -> list[Endpoint]:
        cursor = (
            self._db.collection(ENDPOINTS)
            .find({"snapshot_id": snapshot_id, "service_id": service_id})
            .sort([("simplified_uri", 1), ("http_method", 1)])
        )
        return [from_doc(Endpoint, doc) async for doc in cursor]

    async def list_endpoint_summaries(
        self, snapshot_id: str, service_id: str
    ) -> list[EndpointSummary]:
        """List rows, projected in the QUERY rather than after it (§5.2.15).

        Projecting in Python still pays for the thing being dropped: the wire
        shapes are 124 MB of ICPC `contest`'s 126 MB, and reading plus
        validating them took ~11 s before anything was discarded — the reason
        trimming the response alone moved the payload 47x and the clock barely
        at all. Excluding them server-side is what makes the route fast, not
        just small.

        `type_defs` goes with them (§5.2.16): it exists to hold the types the
        shapes reference, so without the shapes it is dead weight, and
        `EndpointSummary` has no field for it.
        """
        cursor = (
            self._db.collection(ENDPOINTS)
            .find(
                {"snapshot_id": snapshot_id, "service_id": service_id},
                projection={"request_schema": 0, "response_schema": 0, "type_defs": 0},
            )
            .sort([("simplified_uri", 1), ("http_method", 1)])
        )
        return [from_doc(EndpointSummary, doc) async for doc in cursor]

    async def list_endpoints_for_snapshot(self, snapshot_id: str) -> list[Endpoint]:
        """Every endpoint in the snapshot, all services — the matcher's index input."""
        cursor = (
            self._db.collection(ENDPOINTS)
            .find({"snapshot_id": snapshot_id})
            .sort([("service_id", 1), ("simplified_uri", 1), ("http_method", 1)])
        )
        return [from_doc(Endpoint, doc) async for doc in cursor]

    async def list_endpoint_entity_access(self, snapshot_id: str) -> list[EndpointEntityAccessRow]:
        """Every endpoint's entity summary in the snapshot, as projected rows (§5.2.17).

        The reverse view's input. It names the five fields it reads instead of
        excluding the ones it does not (R1-8): an exclusion projection would
        carry whatever a later contract adds to an endpoint, and the wire shapes
        alone were 124 MB of one service's documents before §5.2.15.

        Sorted by the unique ``(snapshot_id, service_id, id)`` index so the
        order costs no in-memory sort; the view sorts its own output anyway.

        A document written before the phase has no ``entity_access`` key, so
        the row reads it with ``get`` and the absence arrives as ``None``: the
        snapshot predates entity facts, never "touches nothing" (R1-6).
        """
        cursor = (
            self._db.collection(ENDPOINTS)
            .find({"snapshot_id": snapshot_id}, projection=_ENTITY_ACCESS_PROJECTION)
            .sort([("service_id", 1), ("id", 1)])
        )
        return [_entity_access_row(doc) async for doc in cursor]

    async def get_endpoint_entity_access(
        self, snapshot_id: str, endpoint_id: str
    ) -> EndpointEntityAccessRow | None:
        """One endpoint's entity summary, without reading the endpoint (§5.2.17).

        The ICFG tools need only whether the summary is ``None``, to say
        whether empty ``entity_access_sites`` mean "no repository call" or "not
        looked at" (R1-6). The full document carries the wire shapes, which is
        the cost this projection exists to avoid.
        """
        doc = await self._db.collection(ENDPOINTS).find_one(
            {"snapshot_id": snapshot_id, "id": endpoint_id},
            projection=_ENTITY_ACCESS_PROJECTION,
        )
        return _entity_access_row(doc) if doc is not None else None

    async def count_endpoints_by_service(self, snapshot_id: str) -> dict[str, int]:
        """Endpoint counts per service for one snapshot (single aggregation)."""
        pipeline = [
            {"$match": {"snapshot_id": snapshot_id}},
            {"$group": {"_id": "$service_id", "count": {"$sum": 1}}},
        ]
        counts: dict[str, int] = {}
        async for row in await self._db.collection(ENDPOINTS).aggregate(pipeline):
            counts[str(row["_id"])] = int(row["count"])  # type: ignore[arg-type]
        return counts

    async def get_endpoint(self, snapshot_id: str, endpoint_id: str) -> Endpoint | None:
        doc = await self._db.collection(ENDPOINTS).find_one(
            {"snapshot_id": snapshot_id, "id": endpoint_id}
        )
        return from_doc(Endpoint, doc) if doc else None

    # --- ICFGs (chunk-aware) --------------------------------------------------------

    async def write_icfg(self, icfg: Icfg) -> None:
        """Store an ICFG, transparently chunking when it would exceed Mongo's limit."""
        doc = to_doc(icfg)
        key: MongoDocument = {"snapshot_id": icfg.snapshot_id, "endpoint_id": icfg.endpoint_id}
        parts_collection = self._db.collection(ICFG_PARTS)
        # Idempotent retries: clear any stale parts from a previous attempt first.
        await parts_collection.delete_many(key)
        if not needs_chunking(doc):
            await self._db.collection(ICFGS).replace_one(key, doc | {"chunked": False}, upsert=True)
            return

        nodes = cast(list[object], doc.pop("nodes"))
        edges = cast(list[object], doc.pop("edges"))
        node_parts = pack_items(nodes)
        edge_parts = pack_items(edges)
        part_docs: list[MongoDocument] = []
        for part_index, node_group in enumerate(node_parts):
            part_doc: MongoDocument = {
                **key,
                "service_id": icfg.service_id,
                "part": part_index,
                "nodes": node_group,
                "edges": [],
            }
            part_docs.append(part_doc)
        for edge_index, edge_group in enumerate(edge_parts):
            edge_part_doc: MongoDocument = {
                **key,
                "service_id": icfg.service_id,
                "part": len(node_parts) + edge_index,
                "nodes": [],
                "edges": edge_group,
            }
            part_docs.append(edge_part_doc)
        manifest = doc | {
            "chunked": True,
            "part_count": len(part_docs),
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        await parts_collection.insert_many(part_docs)
        await self._db.collection(ICFGS).replace_one(key, manifest, upsert=True)

    async def get_icfg(self, snapshot_id: str, endpoint_id: str) -> Icfg | None:
        key = {"snapshot_id": snapshot_id, "endpoint_id": endpoint_id}
        manifest = await self._db.collection(ICFGS).find_one(key)
        if manifest is None:
            return None
        manifest = dict(manifest)
        chunked = bool(manifest.pop("chunked", False))
        if not chunked:
            return from_doc(Icfg, manifest)

        part_count = cast(int, manifest.pop("part_count"))
        node_count = cast(int, manifest.pop("node_count"))
        edge_count = cast(int, manifest.pop("edge_count"))
        nodes: list[object] = []
        edges: list[object] = []
        seen_parts = 0
        cursor = self._db.collection(ICFG_PARTS).find(key).sort("part", 1)
        async for part_doc in cursor:
            seen_parts += 1
            nodes.extend(cast(list[object], part_doc["nodes"]))
            edges.extend(cast(list[object], part_doc["edges"]))
        if seen_parts != part_count or len(nodes) != node_count or len(edges) != edge_count:
            raise RuntimeError(
                f"chunked ICFG {endpoint_id} in snapshot {snapshot_id} is incomplete: "
                f"{seen_parts}/{part_count} parts, {len(nodes)}/{node_count} nodes, "
                f"{len(edges)}/{edge_count} edges"
            )
        manifest["nodes"] = nodes
        manifest["edges"] = edges
        return from_doc(Icfg, manifest)

    async def remote_call_ids_by_endpoint(
        self, snapshot_id: str, service_id: str
    ) -> dict[str, set[str]]:
        """Which remote calls each endpoint's flow reaches — WITHOUT the ICFGs.

        The endpoint-dependencies view needs one set of ids per endpoint and
        nothing else, but the only way to get them used to be `get_icfg` per
        endpoint: 804 graphs on ICPC `contest`, reassembled from their chunks
        and validated into Pydantic models, to answer in 125 bytes. It took
        ~3 s against 5-8 ms for every other read on that page.

        The union is computed in the aggregation instead, so the wire carries
        one small row per endpoint. Same lesson as the endpoint list (§5.2.15):
        the cost was never the response, it was reading everything to build it.

        Chunked graphs keep their nodes in ``icfg_parts`` and leave none on the
        manifest, so they contribute an empty set from the first pass and are
        picked up by the second — the two are merged, never one or the other.
        """
        by_endpoint: dict[str, set[str]] = {}
        chunked: list[str] = []
        manifest_pipeline: list[MongoDocument] = [
            {"$match": {"snapshot_id": snapshot_id, "service_id": service_id}},
            {"$project": {"endpoint_id": 1, "chunked": 1, "call_ids": _CALL_IDS_UNION}},
        ]
        async for row in await self._db.collection(ICFGS).aggregate(manifest_pipeline):
            endpoint_id = str(row["endpoint_id"])  # type: ignore[index]
            ids = {str(call) for call in cast(list[object], row.get("call_ids") or [])}
            if ids:
                by_endpoint[endpoint_id] = ids
            if row.get("chunked"):
                chunked.append(endpoint_id)

        if chunked:
            parts_pipeline: list[MongoDocument] = [
                {"$match": {"snapshot_id": snapshot_id, "endpoint_id": {"$in": chunked}}},
                {"$project": {"endpoint_id": 1, "call_ids": _CALL_IDS_UNION}},
                {"$unwind": "$call_ids"},
                {"$group": {"_id": "$endpoint_id", "call_ids": {"$addToSet": "$call_ids"}}},
            ]
            async for row in await self._db.collection(ICFG_PARTS).aggregate(parts_pipeline):
                ids = {str(call) for call in cast(list[object], row.get("call_ids") or [])}
                if ids:
                    by_endpoint.setdefault(str(row["_id"]), set()).update(ids)  # type: ignore[index]
        return by_endpoint

    async def endpoint_flow_marks(self, snapshot_id: str, endpoint_id: str) -> FlowMarks | None:
        """One endpoint's remote-call ids and unbound callees, WITHOUT its ICFG.

        MCP `endpoint_detail` needs these two facts and nothing else of the
        flow, and it used to assemble the whole graph for them: every chunk
        read and validated, the cost §5.2.15 took out of the endpoint list
        (pre-landing review #6). The answers are the ones a reader of the
        assembled graph would compute, from the same two collections.

        None when the endpoint has no ICFG: not known, which an empty set
        would not say (P10).
        """
        key: MongoDocument = {"snapshot_id": snapshot_id, "endpoint_id": endpoint_id}
        marks: MongoDocument = {"call_ids": _CALL_IDS_UNION, "reasons": _UNBOUND_REASONS}
        rows: list[MongoDocument] = []
        manifest_pipeline: list[MongoDocument] = [
            {"$match": key},
            {"$project": {"_id": 0, "chunked": 1, "part_count": 1, "node_count": 1, **marks}},
        ]
        async for row in await self._db.collection(ICFGS).aggregate(manifest_pipeline):
            rows.append(row)
        if not rows:
            return None
        # A chunked manifest carries no nodes; they are all in its parts. A
        # graph whose parts are not all there is incomplete, exactly as
        # get_icfg says: a partial union would read as a clean answer
        # (pre-landing review, adversarial #2).
        manifest = rows[0]
        if manifest.get("chunked"):
            parts_pipeline: list[MongoDocument] = [
                {"$match": key},
                {"$project": {"_id": 0, "node_n": {"$size": "$nodes"}, **marks}},
            ]
            seen_parts = 0
            seen_nodes = 0
            async for row in await self._db.collection(ICFG_PARTS).aggregate(parts_pipeline):
                seen_parts += 1
                seen_nodes += cast(int, row.get("node_n", 0))
                rows.append(row)
            part_count = cast(int, manifest.get("part_count"))
            node_count = cast(int, manifest.get("node_count"))
            if seen_parts != part_count or seen_nodes != node_count:
                raise RuntimeError(
                    f"chunked ICFG {endpoint_id} in snapshot {snapshot_id} is incomplete: "
                    f"{seen_parts}/{part_count} parts, {seen_nodes}/{node_count} nodes"
                )

        call_ids: set[str] = set()
        reasons: Counter[str] = Counter()
        for row in rows:
            call_ids.update(str(call) for call in cast(list[object], row.get("call_ids") or []))
            reasons.update(str(reason) for reason in cast(list[object], row.get("reasons") or []))
        return FlowMarks(remote_call_ids=call_ids, unbound_reasons=dict(reasons))

    # --- remote calls / MQ / data models ---------------------------------------------

    async def write_remote_calls(self, calls: Sequence[RemoteCall]) -> None:
        await self._upsert_many(REMOTE_CALLS, calls)

    async def list_remote_calls(
        self, snapshot_id: str, service_id: str | None = None
    ) -> list[RemoteCall]:
        query: MongoDocument = {"snapshot_id": snapshot_id}
        if service_id is not None:
            query["service_id"] = service_id
        cursor = self._db.collection(REMOTE_CALLS).find(query).sort("id", 1)
        return [from_doc(RemoteCall, doc) async for doc in cursor]

    async def write_mq_interactions(self, interactions: Sequence[MqInteraction]) -> None:
        await self._upsert_many(MQ_INTERACTIONS, interactions)

    async def list_mq_interactions(
        self, snapshot_id: str, service_id: str | None = None
    ) -> list[MqInteraction]:
        query: MongoDocument = {"snapshot_id": snapshot_id}
        if service_id is not None:
            query["service_id"] = service_id
        cursor = self._db.collection(MQ_INTERACTIONS).find(query).sort("id", 1)
        return [from_doc(MqInteraction, doc) async for doc in cursor]

    async def write_data_models(self, models: Sequence[DataModel]) -> None:
        await self._upsert_many(DATA_MODELS, models)

    async def list_data_models(self, snapshot_id: str, service_id: str) -> list[DataModel]:
        cursor = (
            self._db.collection(DATA_MODELS)
            .find({"snapshot_id": snapshot_id, "service_id": service_id})
            .sort("entity", 1)
        )
        return [from_doc(DataModel, doc) async for doc in cursor]

    async def list_data_models_for_snapshot(self, snapshot_id: str) -> list[DataModel]:
        """Every service's data models in one query (§5.2.17, R1-8).

        The reverse view lists each declared entity, reached or not (Q6), for
        the whole snapshot. One query rather than one per service, ordered by
        the unique ``(snapshot_id, service_id, id)`` index so no sort stage
        runs.
        """
        cursor = (
            self._db.collection(DATA_MODELS)
            .find({"snapshot_id": snapshot_id})
            .sort([("service_id", 1), ("id", 1)])
        )
        return [from_doc(DataModel, doc) async for doc in cursor]
