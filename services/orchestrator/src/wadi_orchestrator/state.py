"""Application state: one place that wires settings → storage → repositories.

Injected into routes via FastAPI dependencies so tests can construct the app
against any database/repo-cache without patching.
"""

from dataclasses import dataclass

from wadi_config import WadiSettings
from wadi_repo import RepoCache
from wadi_storage import (
    ArtifactRepository,
    JobQueue,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)


@dataclass
class AppState:
    settings: WadiSettings
    database: WadiDatabase
    systems: SystemRepository
    snapshots: SnapshotRepository
    artifacts: ArtifactRepository
    jobs: JobQueue
    repo_cache: RepoCache

    @classmethod
    def build(cls, settings: WadiSettings, database: WadiDatabase) -> "AppState":
        return cls(
            settings=settings,
            database=database,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=ArtifactRepository(database),
            jobs=JobQueue(database, lease_seconds=settings.job_lease_seconds),
            repo_cache=RepoCache(settings.repo_cache_dir),
        )
