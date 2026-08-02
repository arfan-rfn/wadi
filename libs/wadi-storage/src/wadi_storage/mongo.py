"""Mongo connection + database bootstrap.

Single seam for the Mongo driver (P1): services construct a
:class:`WadiDatabase` and use the typed repositories — never raw collections.

The client is created ``tz_aware=True`` so every datetime read back is
timezone-aware UTC and revalidates cleanly against the contracts (P9).
"""

from pymongo import AsyncMongoClient, IndexModel
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

type MongoDocument = dict[str, object]

# Collection names — the single-writer map (P4) is documented per name.
SYSTEMS = "systems"  # writer: orchestrator
SNAPSHOTS = "snapshots"  # writer: orchestrator
JOBS = "jobs"  # writer: orchestrator (create) + workers (claim/complete via JobQueue)
SERVICE_BOUNDARIES = "service_boundaries"  # writer: extraction worker
ENDPOINTS = "endpoints"  # writer: extraction worker
ICFGS = "icfgs"  # writer: extraction worker (chunk-aware)
ICFG_PARTS = "icfg_parts"  # writer: extraction worker (overflow parts)
REMOTE_CALLS = "remote_calls"  # writer: extraction worker
MQ_INTERACTIONS = "mq_interactions"  # writer: extraction worker
DATA_MODELS = "data_models"  # writer: extraction worker
STITCHED_EDGES = "stitched_edges"  # writer: stitcher (§5.4, Tier-1 truth; Neo4j is derived)
COVERAGE_REPORTS = "coverage_reports"  # writer: stitcher (§5.4, snapshot-level)


def create_client(mongo_uri: str) -> AsyncMongoClient[MongoDocument]:
    """Create the async Mongo client (tz-aware datetimes, P9)."""
    return AsyncMongoClient(mongo_uri, tz_aware=True)


class WadiDatabase:
    """Handle to the wadi database; owns index bootstrap."""

    def __init__(self, client: AsyncMongoClient[MongoDocument], database_name: str) -> None:
        self._client = client
        self._db: AsyncDatabase[MongoDocument] = client[database_name]

    @property
    def db(self) -> AsyncDatabase[MongoDocument]:
        return self._db

    def collection(self, name: str) -> AsyncCollection[MongoDocument]:
        return self._db[name]

    async def ensure_indexes(self) -> None:
        """Create all indexes; idempotent, called at service startup."""
        await self._db[SYSTEMS].create_indexes(
            [IndexModel([("id", 1)], unique=True), IndexModel([("name", 1)], unique=True)]
        )
        await self._db[SNAPSHOTS].create_indexes(
            [
                IndexModel([("id", 1)], unique=True),
                IndexModel([("system_id", 1), ("created_at", -1)]),
            ]
        )
        await self._db[JOBS].create_indexes(
            [
                IndexModel([("id", 1)], unique=True),
                IndexModel([("status", 1), ("created_at", 1)]),
                IndexModel([("snapshot_id", 1), ("type", 1), ("status", 1)]),
            ]
        )
        # Boundaries are identified by (snapshot, service) — the boundary IS the service.
        await self._db[SERVICE_BOUNDARIES].create_indexes(
            [IndexModel([("snapshot_id", 1), ("service_id", 1)], unique=True)]
        )
        for artifact_collection in (
            ENDPOINTS,
            REMOTE_CALLS,
            MQ_INTERACTIONS,
            DATA_MODELS,
        ):
            await self._db[artifact_collection].create_indexes(
                [
                    IndexModel([("snapshot_id", 1), ("service_id", 1), ("id", 1)], unique=True),
                    IndexModel([("snapshot_id", 1), ("service_id", 1)]),
                ]
            )
        await self._db[ICFGS].create_indexes(
            [
                IndexModel([("snapshot_id", 1), ("endpoint_id", 1)], unique=True),
                IndexModel([("snapshot_id", 1), ("service_id", 1)]),
            ]
        )
        await self._db[ICFG_PARTS].create_indexes(
            [IndexModel([("snapshot_id", 1), ("endpoint_id", 1), ("part", 1)], unique=True)]
        )
        await self._db[STITCHED_EDGES].create_indexes(
            [
                IndexModel([("snapshot_id", 1), ("service_id", 1), ("id", 1)], unique=True),
                IndexModel([("snapshot_id", 1), ("remote_call_id", 1)]),
                # Inbound reads: "who calls this service" (§8 remote_edges).
                IndexModel([("snapshot_id", 1), ("target_service_id", 1)]),
            ]
        )
        await self._db[COVERAGE_REPORTS].create_indexes(
            [IndexModel([("snapshot_id", 1)], unique=True)]
        )

    async def close(self) -> None:
        await self._client.close()
