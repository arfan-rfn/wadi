"""Application state: one place that wires settings → storage → repositories.

Injected into routes via FastAPI dependencies so tests can construct the app
against any database/repo-cache without patching.
"""

from dataclasses import dataclass

from wadi_config import WadiSettings
from wadi_repo import RepoCache
from wadi_storage import (
    ArtifactRepository,
    GraphRepository,
    GraphStore,
    JobQueue,
    SnapshotRepository,
    StitchRepository,
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
    stitch: StitchRepository
    jobs: JobQueue
    repo_cache: RepoCache
    graph_store: GraphStore
    graph: GraphRepository

    @classmethod
    def build(
        cls,
        settings: WadiSettings,
        database: WadiDatabase,
        *,
        graph_store: GraphStore | None = None,
    ) -> "AppState":
        store = graph_store or GraphStore(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password.get_secret_value(),
        )
        return cls(
            settings=settings,
            database=database,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=ArtifactRepository(database),
            stitch=StitchRepository(database),
            jobs=JobQueue(database, lease_seconds=settings.job_lease_seconds),
            repo_cache=RepoCache(settings.repo_cache_dir),
            graph_store=store,
            graph=GraphRepository(store, database=settings.neo4j_database),
        )
