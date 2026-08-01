"""Stitcher service entrypoint: claims stitch jobs and runs the pipeline."""

import asyncio
import logging
import socket
import uuid

from wadi_config import get_settings
from wadi_contracts import ExtractionJob, JobType
from wadi_stitcher.pipeline import StitchPipeline
from wadi_storage import ArtifactRepository, JobQueue, WadiDatabase, create_client
from wadi_storage.runner import JobRunner

logger = logging.getLogger(__name__)


async def serve() -> None:
    settings = get_settings()
    client = create_client(settings.mongo_uri)
    database = WadiDatabase(client, settings.mongo_database)
    await database.ensure_indexes()
    queue = JobQueue(database, lease_seconds=settings.job_lease_seconds)
    pipeline = StitchPipeline(ArtifactRepository(database))

    async def handle(job: ExtractionJob) -> None:
        await pipeline.run(job.snapshot_id)

    runner = JobRunner(
        queue,
        worker_id=f"stitcher-{socket.gethostname()}-{uuid.uuid4().hex[:8]}",
        handler=handle,
        types=[JobType.STITCH],
        heartbeat_seconds=settings.job_heartbeat_seconds,
        poll_seconds=settings.job_poll_seconds,
    )
    try:
        await runner.run_forever()
    finally:
        await database.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
