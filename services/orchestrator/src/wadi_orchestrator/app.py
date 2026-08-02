"""The orchestrator FastAPI app — /api/v1 from the first endpoint (§14).

Pure I/O coordination: systems/snapshots/jobs ownership and the read API.
No analysis logic lives here (§5.3).
"""

# Route handlers are registered via decorators, not called by name:
# pyright: reportUnusedFunction=false

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version as metadata_version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from wadi_config import WadiSettings
from wadi_contracts import (
    CoverageReport,
    Endpoint,
    ExtractionJob,
    Icfg,
    JobStatus,
    JobType,
    RemoteEdgesView,
    RepoSource,
    ServiceSummary,
    Snapshot,
    SnapshotStatus,
    SourceVariant,
    System,
    normalize_repo_source,
)
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import GitError, RefNotFoundError
from wadi_storage import DuplicateSystemNameError, WadiDatabase, create_client

API_PREFIX = "/api/v1"
# Single source: the installed package's own version (pyproject.toml, kept in
# lockstep with the release tag) — surfaced via /healthz and the OpenAPI spec.
ORCHESTRATOR_VERSION = metadata_version("wadi-orchestrator")


# --- request/response bodies (thin wrappers over contract models) -----------------


class CreateSystemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repos: list[RepoSource] = Field(min_length=1)


class AnalyzeResponse(BaseModel):
    snapshot: Snapshot
    job_ids: list[str]


class SourceResponse(BaseModel):
    file: str
    start_line: int
    end_line: int
    variant: SourceVariant
    content: str


class HealthResponse(BaseModel):
    status: str
    version: str


# --- dependencies ------------------------------------------------------------------


def _get_state(request: Request) -> AppState:
    state: AppState = request.app.state.wadi
    return state


StateDep = Annotated[AppState, Depends(_get_state)]


async def _require_auth(request: Request) -> None:
    """Bearer-token auth, enforced only when a token is configured (§14)."""
    state: AppState = request.app.state.wadi
    token = state.settings.api_token
    if token is None:
        return
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {token.get_secret_value()}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


def create_app(
    settings: WadiSettings,
    *,
    database: WadiDatabase | None = None,
    run_monitor: bool = True,
) -> FastAPI:
    """Build the app. Tests inject ``database`` and disable the monitor loop."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        owns_database = database is None
        db = database
        if db is None:
            client = create_client(settings.mongo_uri)
            db = WadiDatabase(client, settings.mongo_database)
        await db.ensure_indexes()
        state = AppState.build(settings, db)
        app.state.wadi = state
        monitor_task: asyncio.Task[None] | None = None
        if run_monitor:
            monitor = SnapshotMonitor(state)
            monitor_task = asyncio.create_task(monitor.run(settings.job_poll_seconds))
        try:
            yield
        finally:
            if monitor_task is not None:
                monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor_task
            await state.graph_store.close()
            if owns_database:
                await db.close()

    app = FastAPI(title="wadi-orchestrator", version=ORCHESTRATOR_VERSION, lifespan=lifespan)

    # --- health (unauthenticated: platform probes) --------------------------------

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz(state: StateDep) -> HealthResponse:
        await state.database.db.command("ping")
        return HealthResponse(status="ok", version=ORCHESTRATOR_VERSION)

    # --- systems -------------------------------------------------------------------

    @app.post(
        f"{API_PREFIX}/systems",
        response_model=System,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(_require_auth)],
    )
    async def create_system(body: CreateSystemRequest, state: StateDep) -> System:
        system = System(id=f"sys_{uuid.uuid4().hex}", name=body.name, repos=body.repos)
        try:
            await state.systems.insert(system)
        except DuplicateSystemNameError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return system

    @app.get(
        f"{API_PREFIX}/systems",
        response_model=list[System],
        dependencies=[Depends(_require_auth)],
    )
    async def list_systems(state: StateDep) -> list[System]:
        return await state.systems.list_all()

    @app.get(
        f"{API_PREFIX}/systems/{{system_id}}",
        response_model=System,
        dependencies=[Depends(_require_auth)],
    )
    async def get_system(system_id: str, state: StateDep) -> System:
        system = await state.systems.get(system_id)
        if system is None:
            raise HTTPException(status_code=404, detail=f"system {system_id} not found")
        return system

    # --- analyze -------------------------------------------------------------------

    @app.post(
        f"{API_PREFIX}/systems/{{system_id}}/analyze",
        response_model=AnalyzeResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(_require_auth)],
    )
    async def analyze(system_id: str, state: StateDep) -> AnalyzeResponse:
        system = await state.systems.get(system_id)
        if system is None:
            raise HTTPException(status_code=404, detail=f"system {system_id} not found")

        def _resolve_commits() -> dict[str, str]:
            commits: dict[str, str] = {}
            for repo in system.repos:
                state.repo_cache.ensure_mirror(repo.source)
                sha = state.repo_cache.resolve_ref(repo.source, repo.branch)
                commits[normalize_repo_source(repo.source)] = sha
            return commits

        try:
            commits = await asyncio.to_thread(_resolve_commits)
        except RefNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except GitError as exc:
            raise HTTPException(status_code=400, detail=f"repository unreachable: {exc}") from exc

        snapshot = Snapshot(
            id=f"snap_{uuid.uuid4().hex}",
            system_id=system.id,
            commits=commits,
            status=SnapshotStatus.RUNNING,  # jobs exist the moment it is visible
        )
        await state.snapshots.insert(snapshot)
        # Phase 1: one extract job covers fetch → boundary scan → per-service
        # extraction (§4 workflow). Per-service fan-out arrives with incremental
        # rebuilds (Phase 3); the contract already supports it (service_id field).
        job = ExtractionJob(
            id=f"job_{uuid.uuid4().hex}", type=JobType.EXTRACT, snapshot_id=snapshot.id
        )
        await state.jobs.enqueue(job)
        return AnalyzeResponse(snapshot=snapshot, job_ids=[job.id])

    # --- snapshots & jobs ------------------------------------------------------------

    @app.get(
        f"{API_PREFIX}/systems/{{system_id}}/snapshots",
        response_model=list[Snapshot],
        dependencies=[Depends(_require_auth)],
    )
    async def list_snapshots(system_id: str, state: StateDep) -> list[Snapshot]:
        if await state.systems.get(system_id) is None:
            raise HTTPException(status_code=404, detail=f"system {system_id} not found")
        return await state.snapshots.list_for_system(system_id)

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}",
        response_model=Snapshot,
        dependencies=[Depends(_require_auth)],
    )
    async def get_snapshot(snapshot_id: str, state: StateDep) -> Snapshot:
        snapshot = await state.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        return snapshot

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/jobs",
        response_model=list[ExtractionJob],
        dependencies=[Depends(_require_auth)],
    )
    async def list_jobs(snapshot_id: str, state: StateDep) -> list[ExtractionJob]:
        return await state.jobs.list_for_snapshot(snapshot_id)

    # --- stitched graph: coverage / remote edges / restitch ---------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/coverage",
        response_model=CoverageReport,
        dependencies=[Depends(_require_auth)],
    )
    async def get_coverage(snapshot_id: str, state: StateDep) -> CoverageReport:
        """What the map knows it doesn't know (§5.4.4) — check this first."""
        if await state.snapshots.get(snapshot_id) is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        report = await state.stitch.get_coverage_report(snapshot_id)
        if report is None:
            raise HTTPException(
                status_code=404, detail=f"snapshot {snapshot_id} is not stitched yet"
            )
        return report

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/services/{{service_id}}/remote-edges",
        response_model=RemoteEdgesView,
        dependencies=[Depends(_require_auth)],
    )
    async def get_remote_edges(
        snapshot_id: str, service_id: str, state: StateDep
    ) -> RemoteEdgesView:
        """Who this service calls and who calls it (§8), from the stitched graph."""
        if await state.artifacts.get_service_boundary(snapshot_id, service_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"service {service_id} not found in snapshot {snapshot_id}",
            )
        return await state.graph.remote_edges(snapshot_id, service_id)

    @app.post(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/restitch",
        response_model=AnalyzeResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(_require_auth)],
    )
    async def restitch(snapshot_id: str, state: StateDep) -> AnalyzeResponse:
        """Re-run stitching over the stored artifacts (§5.4 recovery).

        No re-fetch, no re-extraction: extraction artifacts are Tier-1 truth.
        The fresh stitch job supersedes any earlier one (monitor uses only the
        latest); a FAILED snapshot goes back to running.
        """
        snapshot = await state.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        jobs = await state.jobs.list_for_snapshot(snapshot_id)
        active = [j for j in jobs if j.status in (JobStatus.PENDING, JobStatus.RUNNING)]
        if active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"snapshot {snapshot_id} has active jobs; wait for them to finish",
            )
        extract_jobs = [j for j in jobs if j.type is JobType.EXTRACT]
        if not extract_jobs or any(j.status is not JobStatus.SUCCEEDED for j in extract_jobs):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"snapshot {snapshot_id} has no successful extraction to restitch",
            )
        job = ExtractionJob(
            id=f"job_{uuid.uuid4().hex}", type=JobType.STITCH, snapshot_id=snapshot_id
        )
        await state.jobs.enqueue(job)
        await state.snapshots.set_status(snapshot_id, SnapshotStatus.RUNNING)
        refreshed = await state.snapshots.get(snapshot_id)
        assert refreshed is not None
        return AnalyzeResponse(snapshot=refreshed, job_ids=[job.id])

    # --- read API: services / endpoints / ICFG ---------------------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/services",
        response_model=list[ServiceSummary],
        dependencies=[Depends(_require_auth)],
    )
    async def list_services(snapshot_id: str, state: StateDep) -> list[ServiceSummary]:
        if await state.snapshots.get(snapshot_id) is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        boundaries = await state.artifacts.list_service_boundaries(snapshot_id)
        counts = await state.artifacts.count_endpoints_by_service(snapshot_id)
        return [
            ServiceSummary(
                **boundary.model_dump(),
                endpoint_count=counts.get(boundary.service_id, 0),
            )
            for boundary in boundaries
        ]

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/services/{{service_id}}/endpoints",
        response_model=list[Endpoint],
        dependencies=[Depends(_require_auth)],
    )
    async def list_endpoints(snapshot_id: str, service_id: str, state: StateDep) -> list[Endpoint]:
        boundary = await state.artifacts.get_service_boundary(snapshot_id, service_id)
        if boundary is None:
            raise HTTPException(
                status_code=404,
                detail=f"service {service_id} not found in snapshot {snapshot_id}",
            )
        return await state.artifacts.list_endpoints(snapshot_id, service_id)

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/endpoints/{{endpoint_id}}",
        response_model=Endpoint,
        dependencies=[Depends(_require_auth)],
    )
    async def get_endpoint(snapshot_id: str, endpoint_id: str, state: StateDep) -> Endpoint:
        endpoint = await state.artifacts.get_endpoint(snapshot_id, endpoint_id)
        if endpoint is None:
            raise HTTPException(
                status_code=404,
                detail=f"endpoint {endpoint_id} not found in snapshot {snapshot_id}",
            )
        return endpoint

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/endpoints/{{endpoint_id}}/icfg",
        response_model=Icfg,
        dependencies=[Depends(_require_auth)],
    )
    async def get_icfg(snapshot_id: str, endpoint_id: str, state: StateDep) -> Icfg:
        icfg = await state.artifacts.get_icfg(snapshot_id, endpoint_id)
        if icfg is None:
            raise HTTPException(
                status_code=404,
                detail=f"no ICFG for endpoint {endpoint_id} in snapshot {snapshot_id}",
            )
        return icfg

    # --- source-on-demand (§5.3) -------------------------------------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/services/{{service_id}}/source",
        response_model=SourceResponse,
        dependencies=[Depends(_require_auth)],
    )
    async def get_source(
        snapshot_id: str,
        service_id: str,
        state: StateDep,
        file: Annotated[str, Query(min_length=1)],
        start_line: Annotated[int, Query(ge=1)] = 1,
        end_line: Annotated[int | None, Query(ge=1)] = None,
    ) -> SourceResponse:
        snapshot = await state.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        boundary = await state.artifacts.get_service_boundary(snapshot_id, service_id)
        if boundary is None:
            raise HTTPException(
                status_code=404,
                detail=f"service {service_id} not found in snapshot {snapshot_id}",
            )
        sha = snapshot.commits.get(boundary.repo)
        if sha is None:
            raise HTTPException(
                status_code=404, detail=f"no pinned commit for repo {boundary.repo}"
            )
        repo_path = file if boundary.build_root == "." else f"{boundary.build_root}/{file}"
        try:
            content = await asyncio.to_thread(
                state.repo_cache.read_file, boundary.repo, sha, repo_path
            )
        except GitError as exc:
            raise HTTPException(
                status_code=404, detail=f"file {file!r} not found at pinned commit"
            ) from exc
        lines = content.splitlines(keepends=True)
        last = end_line if end_line is not None else len(lines)
        if last < start_line:
            raise HTTPException(status_code=400, detail="end_line must be >= start_line")
        selected = "".join(lines[start_line - 1 : last])
        return SourceResponse(
            file=file,
            start_line=start_line,
            end_line=min(last, len(lines)),
            variant=SourceVariant.ORIGINAL,
            content=selected,
        )

    return app


def main() -> None:
    """Production entrypoint: uvicorn against env-configured settings."""
    import uvicorn

    from wadi_config import get_settings

    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.api_port,
    )
