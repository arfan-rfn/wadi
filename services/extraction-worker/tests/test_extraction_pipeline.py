"""Pipeline integration test: real Mongo + real git + fake Joern extractor.

Everything except the JVM is real — this is the near-e2e that proves the
worker end of the vertical slice without requiring the wadi-joern image.
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from worker_support import petstore_like_export

from wadi_config import WadiSettings
from wadi_contracts import (
    ExtractionJob,
    JobType,
    RepoSource,
    Snapshot,
    System,
    normalize_repo_source,
)
from wadi_joern_client import ServiceExport
from wadi_repo import RepoCache
from wadi_storage import (
    ArtifactRepository,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline

pytestmark = pytest.mark.integration


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@e.c",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@e.c",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
        },
    ).stdout


class FakeExtractor:
    """Stands in for Joern: records calls, returns the canned petstore export."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, str]] = []

    def extract(self, source_path: Path, export_dir: Path, project_name: str) -> ServiceExport:
        assert source_path.exists(), f"pipeline passed a nonexistent build root: {source_path}"
        self.calls.append((source_path, export_dir, project_name))
        return petstore_like_export()


@pytest.fixture
def repo_with_service(tmp_path: Path) -> Path:
    repo = tmp_path / "petstore"
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=repo)
    (repo / "pom.xml").write_text(
        '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<modelVersion>4.0.0</modelVersion><artifactId>petstore-mini</artifactId></project>"
    )
    src = repo / "src" / "main" / "java"
    src.mkdir(parents=True)
    (src / "App.java").write_text("class App {}\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    return repo


async def _seed(
    database: WadiDatabase, repo: Path, tmp_path: Path
) -> tuple[WadiSettings, System, Snapshot, ExtractionJob]:
    settings = WadiSettings(
        _env_file=None,  # type: ignore[call-arg]
        workspace_dir=tmp_path / "workspace",
        cpg_cache_dir=tmp_path / "cpg-cache",
        repo_cache_dir=tmp_path / "repo-cache",
    )
    cache = RepoCache(settings.repo_cache_dir)
    cache.ensure_mirror(str(repo))
    sha = cache.resolve_ref(str(repo), None)

    system = System(
        id=f"sys_{uuid.uuid4().hex}",
        name="petstore",
        repos=[RepoSource(source=str(repo))],
    )
    snapshot = Snapshot(
        id=f"snap_{uuid.uuid4().hex}",
        system_id=system.id,
        commits={normalize_repo_source(str(repo)): sha},
    )
    job = ExtractionJob(id=f"job_{uuid.uuid4().hex}", type=JobType.EXTRACT, snapshot_id=snapshot.id)
    await SystemRepository(database).insert(system)
    await SnapshotRepository(database).insert(snapshot)
    return settings, system, snapshot, job


class TestExtractionPipeline:
    async def test_full_run_materializes_all_artifacts(
        self, database: WadiDatabase, repo_with_service: Path, tmp_path: Path
    ) -> None:
        settings, _, snapshot, job = await _seed(database, repo_with_service, tmp_path)
        artifacts = ArtifactRepository(database)
        extractor = FakeExtractor()
        pipeline = ExtractionPipeline(
            settings=settings,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=artifacts,
            repo_cache=RepoCache(settings.repo_cache_dir),
            extractor=extractor,
        )
        await pipeline.run(job)

        boundaries = await artifacts.list_service_boundaries(snapshot.id)
        assert len(boundaries) == 1
        boundary = boundaries[0]
        assert boundary.name == "petstore-mini"
        assert boundary.build_root == "."
        # Coverage counts ride the boundary (§5.4.3), straight from the export.
        assert boundary.analysis_coverage is not None
        assert boundary.analysis_coverage.production_methods == 3
        assert boundary.analysis_coverage.reachable_methods == 2

        endpoints = await artifacts.list_endpoints(snapshot.id, boundary.service_id)
        assert [e.simplified_uri for e in endpoints] == ["/pets/{?}"]

        icfg = await artifacts.get_icfg(snapshot.id, endpoints[0].id)
        assert icfg is not None
        assert icfg.root_entry().method_info is not None

        remote_calls = await artifacts.list_remote_calls(snapshot.id)
        assert len(remote_calls) == 1
        models = await artifacts.list_data_models(snapshot.id, boundary.service_id)
        assert [m.entity for m in models] == ["Pet"]

        # The extractor got the materialized checkout, on the shared workspace.
        (source_path, _, project) = extractor.calls[0]
        assert str(settings.workspace_dir) in str(source_path)
        assert snapshot.id in project

    async def test_rerun_is_idempotent(
        self, database: WadiDatabase, repo_with_service: Path, tmp_path: Path
    ) -> None:
        settings, _, snapshot, job = await _seed(database, repo_with_service, tmp_path)
        artifacts = ArtifactRepository(database)
        pipeline = ExtractionPipeline(
            settings=settings,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=artifacts,
            repo_cache=RepoCache(settings.repo_cache_dir),
            extractor=FakeExtractor(),
        )
        await pipeline.run(job)
        await pipeline.run(job)  # a retried job must converge

        boundaries = await artifacts.list_service_boundaries(snapshot.id)
        assert len(boundaries) == 1
        endpoints = await artifacts.list_endpoints(snapshot.id, boundaries[0].service_id)
        assert len(endpoints) == 1

    async def test_pre_metric_export_leaves_coverage_unknown(
        self, database: WadiDatabase, repo_with_service: Path, tmp_path: Path
    ) -> None:
        """A 2.1-era export has no analysis_coverage — the boundary must carry
        None (unknown), never fabricated zeros (P10)."""

        class LegacyExtractor(FakeExtractor):
            def extract(
                self, source_path: Path, export_dir: Path, project_name: str
            ) -> ServiceExport:
                export = super().extract(source_path, export_dir, project_name)
                return export.model_copy(update={"analysis_coverage": None})

        settings, _, snapshot, job = await _seed(database, repo_with_service, tmp_path)
        artifacts = ArtifactRepository(database)
        pipeline = ExtractionPipeline(
            settings=settings,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=artifacts,
            repo_cache=RepoCache(settings.repo_cache_dir),
            extractor=LegacyExtractor(),
        )
        await pipeline.run(job)

        boundaries = await artifacts.list_service_boundaries(snapshot.id)
        assert len(boundaries) == 1
        assert boundaries[0].analysis_coverage is None

    async def test_missing_snapshot_fails_loudly(
        self, database: WadiDatabase, tmp_path: Path
    ) -> None:
        settings = WadiSettings(
            _env_file=None,  # type: ignore[call-arg]
            workspace_dir=tmp_path / "ws",
            repo_cache_dir=tmp_path / "rc",
        )
        pipeline = ExtractionPipeline(
            settings=settings,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=ArtifactRepository(database),
            repo_cache=RepoCache(settings.repo_cache_dir),
            extractor=FakeExtractor(),
        )
        job = ExtractionJob(
            id=f"job_{uuid.uuid4().hex}", type=JobType.EXTRACT, snapshot_id="snap_missing"
        )
        with pytest.raises(RuntimeError, match="not found"):
            await pipeline.run(job)


class TestCpgqlExtractor:
    def test_reads_export_written_to_shared_volume(self, tmp_path: Path) -> None:
        """The real extractor: one control query + export.json pickup."""

        class ScriptedJoern:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def import_code(self, path: str, name: str) -> None:
                self.calls.append(f"import:{name}")

            def run_wadi_pipeline(self, export_dir: str) -> str:
                self.calls.append("pipeline")
                export = petstore_like_export()
                Path(export_dir).mkdir(parents=True, exist_ok=True)
                (Path(export_dir) / "export.json").write_text(export.model_dump_json())
                return "wadi export: ok"

            def delete_project(self, name: str) -> None:
                self.calls.append(f"delete:{name}")

        joern = ScriptedJoern()
        extractor = CpgqlJoernExtractor(joern)  # type: ignore[arg-type]
        export = extractor.extract(tmp_path, tmp_path / "out", "proj")
        assert export.endpoints[0].uri == "/pets/{id}"
        # CPG deleted even on success (P5 disposable).
        assert joern.calls == ["import:proj", "pipeline", "delete:proj"]

    def test_missing_export_file_is_an_error(self, tmp_path: Path) -> None:
        class SilentJoern:
            def import_code(self, path: str, name: str) -> None: ...
            def run_wadi_pipeline(self, export_dir: str) -> str:
                return "claims ok but writes nothing"

            def delete_project(self, name: str) -> None: ...

        extractor = CpgqlJoernExtractor(SilentJoern())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="no export"):
            extractor.extract(tmp_path, tmp_path / "out", "proj")

    def test_cpg_deleted_even_when_pipeline_fails(self, tmp_path: Path) -> None:
        class ExplodingJoern:
            def __init__(self) -> None:
                self.deleted = False

            def import_code(self, path: str, name: str) -> None: ...
            def run_wadi_pipeline(self, export_dir: str) -> str:
                raise RuntimeError("pipeline exploded")

            def delete_project(self, name: str) -> None:
                self.deleted = True

        joern = ExplodingJoern()
        extractor = CpgqlJoernExtractor(joern)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="exploded"):
            extractor.extract(tmp_path, tmp_path / "out", "proj")
        assert joern.deleted is True

    def test_json_shape_roundtrip(self, tmp_path: Path) -> None:
        """What Scala writes (plain JSON) must revalidate into ServiceExport."""
        raw = json.loads(petstore_like_export().model_dump_json())
        assert ServiceExport.model_validate(raw) == petstore_like_export()
