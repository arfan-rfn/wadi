"""Mongo-backed job queue with lease-based claims (§3, §7).

The queue is behind this interface so it can be swapped for Redis/arq later
without touching services. Correctness properties, enforced by atomic
``find_one_and_update`` operations:

- a job is claimed by exactly one worker (atomic pending→running transition);
- an expired lease makes the job claimable again — a crashed worker never
  strands work;
- a job that exhausts ``max_attempts`` lands in ``failed``, never loops;
- heartbeat/complete/fail are fenced by ``(job id, worker id)`` so a worker
  that lost its lease cannot overwrite the new owner's state.
"""

from datetime import timedelta

from pymongo import ReturnDocument

from wadi_contracts import ExtractionJob, JobStatus, JobType
from wadi_contracts.timeutil import utc_now
from wadi_storage.codec import from_doc, to_doc
from wadi_storage.mongo import JOBS, MongoDocument, WadiDatabase


class JobQueue:
    def __init__(self, database: WadiDatabase, *, lease_seconds: int = 600) -> None:
        self._col = database.collection(JOBS)
        self._lease_seconds = lease_seconds

    async def enqueue(self, job: ExtractionJob) -> None:
        await self._col.insert_one(to_doc(job))

    async def get(self, job_id: str) -> ExtractionJob | None:
        doc = await self._col.find_one({"id": job_id})
        return from_doc(ExtractionJob, doc) if doc else None

    async def claim(
        self, worker_id: str, *, types: list[JobType] | None = None
    ) -> ExtractionJob | None:
        """Atomically claim the oldest runnable job, or return None.

        Runnable = pending, or running with an expired lease (crash recovery),
        with attempts remaining. Jobs that expired with no attempts left are
        reaped to ``failed`` first so they surface as errors, not silence.
        """
        now = utc_now()
        await self._reap_exhausted(now)
        query: MongoDocument = {
            "$and": [
                {
                    "$or": [
                        {"status": JobStatus.PENDING.value},
                        {
                            "status": JobStatus.RUNNING.value,
                            "claim.lease_expires_at": {"$lt": now},
                        },
                    ]
                },
                {"$expr": {"$lt": ["$attempts", "$max_attempts"]}},
            ]
        }
        if types is not None:
            query["type"] = {"$in": [t.value for t in types]}
        doc = await self._col.find_one_and_update(
            query,
            {
                "$set": {
                    "status": JobStatus.RUNNING.value,
                    "claim": {
                        "worker_id": worker_id,
                        "claimed_at": now,
                        "lease_expires_at": now + timedelta(seconds=self._lease_seconds),
                        "heartbeat_at": now,
                    },
                    "started_at": now,
                    "error": None,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", 1), ("_id", 1)],  # _id breaks same-millisecond ties
            return_document=ReturnDocument.AFTER,
        )
        return from_doc(ExtractionJob, doc) if doc else None

    async def _reap_exhausted(self, now: object) -> None:
        """Expired lease + no attempts left → failed (loud, not silent)."""
        await self._col.update_many(
            {
                "status": JobStatus.RUNNING.value,
                "claim.lease_expires_at": {"$lt": now},
                "$expr": {"$gte": ["$attempts", "$max_attempts"]},
            },
            {
                "$set": {
                    "status": JobStatus.FAILED.value,
                    "error": "lease expired with no attempts remaining (worker crash?)",
                    "finished_at": now,
                }
            },
        )

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        """Extend the lease. Returns False if this worker no longer owns the job."""
        now = utc_now()
        result = await self._col.update_one(
            {
                "id": job_id,
                "status": JobStatus.RUNNING.value,
                "claim.worker_id": worker_id,
            },
            {
                "$set": {
                    "claim.heartbeat_at": now,
                    "claim.lease_expires_at": now + timedelta(seconds=self._lease_seconds),
                }
            },
        )
        return result.modified_count == 1

    async def complete(self, job_id: str, worker_id: str) -> bool:
        """Mark succeeded. Fenced by worker id; returns False if ownership was lost."""
        result = await self._col.update_one(
            {
                "id": job_id,
                "status": JobStatus.RUNNING.value,
                "claim.worker_id": worker_id,
            },
            {"$set": {"status": JobStatus.SUCCEEDED.value, "finished_at": utc_now()}},
        )
        return result.modified_count == 1

    async def fail(self, job_id: str, worker_id: str, error: str) -> bool:
        """Record a failure: requeue if attempts remain, else fail permanently."""
        now = utc_now()
        result = await self._col.update_one(
            {
                "id": job_id,
                "status": JobStatus.RUNNING.value,
                "claim.worker_id": worker_id,
            },
            [
                {
                    "$set": {
                        "status": {
                            "$cond": [
                                {"$gte": ["$attempts", "$max_attempts"]},
                                JobStatus.FAILED.value,
                                JobStatus.PENDING.value,
                            ]
                        },
                        "error": error,
                        "finished_at": {
                            "$cond": [
                                {"$gte": ["$attempts", "$max_attempts"]},
                                now,
                                None,
                            ]
                        },
                        "claim": {
                            "$cond": [
                                {"$gte": ["$attempts", "$max_attempts"]},
                                "$claim",
                                None,
                            ]
                        },
                    }
                }
            ],
        )
        return result.modified_count == 1

    async def list_for_snapshot(self, snapshot_id: str) -> list[ExtractionJob]:
        cursor = self._col.find({"snapshot_id": snapshot_id}).sort([("created_at", 1), ("_id", 1)])
        return [from_doc(ExtractionJob, doc) async for doc in cursor]

    async def status_counts(self, snapshot_id: str) -> dict[str, int]:
        pipeline = [
            {"$match": {"snapshot_id": snapshot_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        counts: dict[str, int] = {}
        async for row in await self._col.aggregate(pipeline):
            counts[str(row["_id"])] = int(row["count"])  # type: ignore[arg-type]
        return counts

    async def unfinished_count(self, snapshot_id: str, job_type: JobType | None = None) -> int:
        query: MongoDocument = {
            "snapshot_id": snapshot_id,
            "status": {"$in": [JobStatus.PENDING.value, JobStatus.RUNNING.value]},
        }
        if job_type is not None:
            query["type"] = job_type.value
        return await self._col.count_documents(query)
