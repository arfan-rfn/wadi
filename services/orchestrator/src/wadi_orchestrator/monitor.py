"""Snapshot lifecycle monitor.

The orchestrator owns snapshots and job *creation* (P4). Workers only claim
and finish jobs; this monitor advances the snapshot state machine:

    extract jobs all succeeded          → enqueue the stitch job
    latest stitch job succeeded         → snapshot SUCCEEDED
    any extract job failed              → snapshot FAILED (loud, with the error)
    latest stitch job failed            → snapshot FAILED

Only the LATEST stitch job counts: a restitch (recovery over stored
artifacts, §5.4 failure semantics) enqueues a fresh stitch job that
supersedes an earlier failed one — the old failure must not re-fail the
snapshot the moment recovery starts.

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
        extract_jobs = [job for job in jobs if job.type is JobType.EXTRACT]
        stitch_jobs = [job for job in jobs if job.type is JobType.STITCH]
        # Restitch supersession: only the most recent stitch job is authoritative.
        latest_stitch = max(stitch_jobs, key=lambda j: (j.created_at, j.id), default=None)

        failed = [job for job in extract_jobs if job.status is JobStatus.FAILED]
        if latest_stitch is not None and latest_stitch.status is JobStatus.FAILED:
            failed.append(latest_stitch)
        if failed:
            first = failed[0]
            await self._state.snapshots.set_status(
                snapshot.id,
                SnapshotStatus.FAILED,
                error=f"job {first.id} ({first.type.value}) failed: {first.error}",
            )
            return

        extraction_done = bool(extract_jobs) and all(
            job.status is JobStatus.SUCCEEDED for job in extract_jobs
        )
        if extraction_done and latest_stitch is None:
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
            and latest_stitch is not None
            and latest_stitch.status is JobStatus.SUCCEEDED
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
