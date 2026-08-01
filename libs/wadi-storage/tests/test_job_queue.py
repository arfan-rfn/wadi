"""Integration tests: job-queue correctness under contention and crashes."""

import asyncio

import pytest

from wadi_contracts import ExtractionJob, JobStatus, JobType
from wadi_storage import JobQueue, WadiDatabase
from wadi_testing.builders import new_id

pytestmark = pytest.mark.integration


def make_job(
    snapshot_id: str = "snap_test",
    job_type: JobType = JobType.EXTRACT,
    max_attempts: int = 3,
) -> ExtractionJob:
    return ExtractionJob(
        id=new_id("job"),
        type=job_type,
        snapshot_id=snapshot_id,
        service_id="svc_x" if job_type is JobType.EXTRACT else None,
        max_attempts=max_attempts,
    )


class TestClaim:
    async def test_claim_returns_oldest_pending(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        first, second = make_job(), make_job()
        await queue.enqueue(first)
        await queue.enqueue(second)
        claimed = await queue.claim("worker-1")
        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.status is JobStatus.RUNNING
        assert claimed.attempts == 1
        assert claimed.claim is not None
        assert claimed.claim.worker_id == "worker-1"

    async def test_claim_empty_queue_returns_none(self, database: WadiDatabase) -> None:
        assert await JobQueue(database).claim("worker-1") is None

    async def test_claim_filters_by_type(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        await queue.enqueue(make_job(job_type=JobType.STITCH))
        assert await queue.claim("w", types=[JobType.EXTRACT]) is None
        claimed = await queue.claim("w", types=[JobType.STITCH])
        assert claimed is not None

    async def test_concurrent_claims_have_exactly_one_winner(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        job = make_job()
        await queue.enqueue(job)
        results = await asyncio.gather(*(queue.claim(f"worker-{i}") for i in range(10)))
        winners = [r for r in results if r is not None]
        assert len(winners) == 1

    async def test_many_jobs_many_workers_no_double_assignment(
        self, database: WadiDatabase
    ) -> None:
        queue = JobQueue(database)
        for _ in range(5):
            await queue.enqueue(make_job())
        results = await asyncio.gather(*(queue.claim(f"worker-{i}") for i in range(8)))
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 5
        assert len({job.id for job in claimed}) == 5


class TestLease:
    async def test_expired_lease_is_reclaimable(self, database: WadiDatabase) -> None:
        queue = JobQueue(database, lease_seconds=1)
        job = make_job()
        await queue.enqueue(job)
        first_claim = await queue.claim("worker-crashed")
        assert first_claim is not None

        assert await queue.claim("worker-2") is None  # lease still live
        await asyncio.sleep(1.2)
        reclaimed = await queue.claim("worker-2")
        assert reclaimed is not None
        assert reclaimed.id == job.id
        assert reclaimed.attempts == 2
        assert reclaimed.claim is not None
        assert reclaimed.claim.worker_id == "worker-2"

    async def test_heartbeat_extends_lease(self, database: WadiDatabase) -> None:
        queue = JobQueue(database, lease_seconds=1)
        await queue.enqueue(make_job())
        claimed = await queue.claim("worker-1")
        assert claimed is not None
        for _ in range(3):
            await asyncio.sleep(0.6)
            assert await queue.heartbeat(claimed.id, "worker-1") is True
        assert await queue.claim("worker-2") is None  # kept alive by heartbeats

    async def test_heartbeat_fenced_after_ownership_loss(self, database: WadiDatabase) -> None:
        queue = JobQueue(database, lease_seconds=1)
        await queue.enqueue(make_job())
        claimed = await queue.claim("worker-1")
        assert claimed is not None
        await asyncio.sleep(1.2)
        stolen = await queue.claim("worker-2")
        assert stolen is not None
        assert await queue.heartbeat(claimed.id, "worker-1") is False
        assert await queue.complete(claimed.id, "worker-1") is False

    async def test_exhausted_expired_job_is_reaped_to_failed(self, database: WadiDatabase) -> None:
        queue = JobQueue(database, lease_seconds=1)
        job = make_job(max_attempts=1)
        await queue.enqueue(job)
        assert await queue.claim("worker-1") is not None
        await asyncio.sleep(1.2)
        assert await queue.claim("worker-2") is None  # nothing runnable…
        reaped = await queue.get(job.id)
        assert reaped is not None
        assert reaped.status is JobStatus.FAILED  # …and the corpse is loud, not silent
        assert reaped.error is not None


class TestCompletion:
    async def test_complete(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        job = make_job()
        await queue.enqueue(job)
        claimed = await queue.claim("worker-1")
        assert claimed is not None
        assert await queue.complete(job.id, "worker-1") is True
        done = await queue.get(job.id)
        assert done is not None
        assert done.status is JobStatus.SUCCEEDED
        assert done.finished_at is not None

    async def test_fail_requeues_until_attempts_exhausted(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        job = make_job(max_attempts=2)
        await queue.enqueue(job)

        first = await queue.claim("worker-1")
        assert first is not None
        assert await queue.fail(job.id, "worker-1", "CPG import OOM") is True
        after_first = await queue.get(job.id)
        assert after_first is not None
        assert after_first.status is JobStatus.PENDING  # retry available
        assert after_first.error == "CPG import OOM"
        assert after_first.claim is None

        second = await queue.claim("worker-2")
        assert second is not None
        assert second.attempts == 2
        assert await queue.fail(job.id, "worker-2", "OOM again") is True
        final = await queue.get(job.id)
        assert final is not None
        assert final.status is JobStatus.FAILED  # permanently failed
        assert final.finished_at is not None

    async def test_counts_and_unfinished(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        snap = "snap_counts"
        jobs = [make_job(snap) for _ in range(3)]
        for job in jobs:
            await queue.enqueue(job)
        claimed = await queue.claim("w")
        assert claimed is not None
        await queue.complete(claimed.id, "w")

        counts = await queue.status_counts(snap)
        assert counts == {"succeeded": 1, "pending": 2}
        assert await queue.unfinished_count(snap) == 2
        assert await queue.unfinished_count(snap, JobType.EXTRACT) == 2
        assert await queue.unfinished_count(snap, JobType.STITCH) == 0

    async def test_listing(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        snap = "snap_list"
        jobs = [make_job(snap) for _ in range(3)]
        for job in jobs:
            await queue.enqueue(job)
        listed = await queue.list_for_snapshot(snap)
        assert [j.id for j in listed] == [j.id for j in jobs]  # creation order
