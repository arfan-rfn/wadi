"""Shared job-worker loop: claim → heartbeat → run → complete/fail.

Used by every job-processing service (extraction worker, stitcher) so the
lease/heartbeat/fencing discipline is implemented exactly once. The handler
is the only per-service part.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from wadi_contracts import ExtractionJob, JobType
from wadi_storage.jobs import JobQueue

logger = logging.getLogger(__name__)

JobHandler = Callable[[ExtractionJob], Awaitable[None]]


class JobRunner:
    def __init__(
        self,
        queue: JobQueue,
        *,
        worker_id: str,
        handler: JobHandler,
        types: list[JobType] | None = None,
        heartbeat_seconds: float = 60,
        poll_seconds: float = 2.0,
    ) -> None:
        self._queue = queue
        self._worker_id = worker_id
        self._handler = handler
        self._types = types
        self._heartbeat_seconds = heartbeat_seconds
        self._poll_seconds = poll_seconds

    async def run_one(self, job: ExtractionJob) -> bool:
        """Run a claimed job under a heartbeat; returns True if it succeeded."""
        heartbeat = asyncio.create_task(self._heartbeat_loop(job.id))
        try:
            await self._handler(job)
        except Exception as exc:
            logger.exception("job %s (%s) failed", job.id, job.type.value)
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await self._queue.fail(job.id, self._worker_id, f"{type(exc).__name__}: {exc}")
            return False
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        completed = await self._queue.complete(job.id, self._worker_id)
        if not completed:
            logger.error("job %s finished but ownership was lost (lease expired mid-run?)", job.id)
        return completed

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            alive = await self._queue.heartbeat(job_id, self._worker_id)
            if not alive:
                logger.error("lost lease on job %s; heartbeat rejected", job_id)
                return

    async def run_forever(self) -> None:
        """Poll-claim-run loop; the service entrypoint."""
        logger.info("worker %s polling for jobs (types=%s)", self._worker_id, self._types)
        while True:
            job = await self._queue.claim(self._worker_id, types=self._types)
            if job is None:
                await asyncio.sleep(self._poll_seconds)
                continue
            logger.info("claimed job %s (%s)", job.id, job.type.value)
            await self.run_one(job)
