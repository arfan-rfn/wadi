"""Extraction worker entrypoint: claims extract jobs and runs the pipeline."""

import asyncio
import logging
import socket
import uuid

from wadi_config import get_settings
from wadi_contracts import ExtractionJob, JobType
from wadi_joern_client import JoernClient
from wadi_repo import RepoCache
from wadi_storage import (
    ArtifactRepository,
    JobQueue,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
    create_client,
)
from wadi_storage.runner import JobRunner
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

logger = logging.getLogger(__name__)


async def serve() -> None:
    settings = get_settings()
    client = create_client(settings.mongo_uri)
    database = WadiDatabase(client, settings.mongo_database)
    await database.ensure_indexes()
    queue = JobQueue(database, lease_seconds=settings.job_lease_seconds)
    joern = JoernClient(
        settings.joern_url,
        username=settings.joern_username,
        password=settings.joern_password.get_secret_value() if settings.joern_password else None,
    )
    pipeline = ExtractionPipeline(
        settings=settings,
        systems=SystemRepository(database),
        snapshots=SnapshotRepository(database),
        artifacts=ArtifactRepository(database),
        repo_cache=RepoCache(settings.repo_cache_dir),
        extractor=CpgqlJoernExtractor(joern),
    )

    async def handle(job: ExtractionJob) -> None:
        await pipeline.run(job)

    runner = JobRunner(
        queue,
        worker_id=f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:8]}",
        handler=handle,
        types=[JobType.EXTRACT],
        heartbeat_seconds=settings.job_heartbeat_seconds,
        poll_seconds=settings.job_poll_seconds,
    )
    try:
        await runner.run_forever()
    finally:
        joern.close()
        await database.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
