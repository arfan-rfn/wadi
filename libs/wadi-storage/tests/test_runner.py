"""JobRunner integration tests: success, failure, heartbeat under long jobs."""

import asyncio

import pytest

from wadi_contracts import ExtractionJob, JobStatus, JobType
from wadi_storage import JobQueue, WadiDatabase
from wadi_storage.runner import JobRunner
from wadi_testing.builders import new_id

pytestmark = pytest.mark.integration


def make_job(max_attempts: int = 3) -> ExtractionJob:
    return ExtractionJob(
        id=new_id("job"), type=JobType.EXTRACT, snapshot_id="snap_runner", max_attempts=max_attempts
    )


class TestJobRunner:
    async def test_success_path(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        job = make_job()
        await queue.enqueue(job)
        handled: list[str] = []

        async def handler(claimed: ExtractionJob) -> None:
            handled.append(claimed.id)

        runner = JobRunner(queue, worker_id="w1", handler=handler)
        claimed = await queue.claim("w1")
        assert claimed is not None
        assert await runner.run_one(claimed) is True
        assert handled == [job.id]
        final = await queue.get(job.id)
        assert final is not None
        assert final.status is JobStatus.SUCCEEDED

    async def test_failure_records_error_and_requeues(self, database: WadiDatabase) -> None:
        queue = JobQueue(database)
        job = make_job()
        await queue.enqueue(job)

        async def handler(claimed: ExtractionJob) -> None:
            raise RuntimeError("CPG import exploded")

        runner = JobRunner(queue, worker_id="w1", handler=handler)
        claimed = await queue.claim("w1")
        assert claimed is not None
        assert await runner.run_one(claimed) is False
        final = await queue.get(job.id)
        assert final is not None
        assert final.status is JobStatus.PENDING  # attempts remain
        assert final.error is not None
        assert "CPG import exploded" in final.error

    async def test_heartbeat_keeps_long_job_alive(self, database: WadiDatabase) -> None:
        queue = JobQueue(database, lease_seconds=1)
        job = make_job()
        await queue.enqueue(job)

        async def slow_handler(claimed: ExtractionJob) -> None:
            await asyncio.sleep(2.5)  # longer than the lease

        runner = JobRunner(queue, worker_id="w1", handler=slow_handler, heartbeat_seconds=0.4)
        claimed = await queue.claim("w1")
        assert claimed is not None
        assert await runner.run_one(claimed) is True  # completed despite short lease
        final = await queue.get(job.id)
        assert final is not None
        assert final.status is JobStatus.SUCCEEDED
