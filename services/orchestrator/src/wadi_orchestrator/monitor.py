"""Snapshot lifecycle monitor.

The orchestrator owns snapshots and job *creation* (P4). Workers only claim
and finish jobs; this monitor advances the snapshot state machine:

    extract jobs all succeeded          → enqueue the stitch job
    stitch job succeeded                → snapshot SUCCEEDED
    any job permanently failed          → snapshot FAILED (loud, with the error)

``tick()`` is a pure state-advance pass over running snapshots — unit-testable
without the surrounding polling task.
"""

import asyncio
import logging
import uuid

from wadi_contracts import ExtractionJob, JobStatus, JobType, Snapshot, SnapshotStatus
from wadi_orchestrator.state import AppState

logger = logging.getLogger(__name__)


class SnapshotMonitor:
    def __init__(self, state: AppState) -> None:
        self._state = state

    async def tick(self) -> None:
        """Advance every unfinished snapshot one step, if its jobs allow."""
        systems = await self._state.systems.list_all()
        for system in systems:
            for snapshot in await self._state.snapshots.list_for_system(system.id):
                if snapshot.status in (SnapshotStatus.PENDING, SnapshotStatus.RUNNING):
                    await self._advance(snapshot)

    async def _advance(self, snapshot: Snapshot) -> None:
        jobs = await self._state.jobs.list_for_snapshot(snapshot.id)
        failed = [job for job in jobs if job.status is JobStatus.FAILED]
        if failed:
            first = failed[0]
            await self._state.snapshots.set_status(
                snapshot.id,
                SnapshotStatus.FAILED,
                error=f"job {first.id} ({first.type.value}) failed: {first.error}",
            )
            return

        extract_jobs = [job for job in jobs if job.type is JobType.EXTRACT]
        stitch_jobs = [job for job in jobs if job.type is JobType.STITCH]
        extraction_done = bool(extract_jobs) and all(
            job.status is JobStatus.SUCCEEDED for job in extract_jobs
        )
        if extraction_done and not stitch_jobs:
            await self._state.jobs.enqueue(
                ExtractionJob(
                    id=f"job_{uuid.uuid4().hex}",
                    type=JobType.STITCH,
                    snapshot_id=snapshot.id,
                )
            )
            return
        if (
            extraction_done
            and stitch_jobs
            and all(job.status is JobStatus.SUCCEEDED for job in stitch_jobs)
        ):
            await self._state.snapshots.set_status(snapshot.id, SnapshotStatus.SUCCEEDED)

    async def run(self, interval_seconds: float) -> None:
        """The background polling loop (started from the app lifespan)."""
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("snapshot monitor tick failed; will retry")
            await asyncio.sleep(interval_seconds)
