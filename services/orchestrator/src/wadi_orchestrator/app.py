"""The orchestrator FastAPI app — /api/v1 from the first endpoint (§14).

Pure I/O coordination: systems/snapshots/jobs ownership and the read API.
No analysis logic lives here (§5.3).
"""

# Route handlers are registered via decorators, not called by name:
# pyright: reportUnusedFunction=false

import asyncio
import contextlib
import uuid
from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version as metadata_version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from wadi_config import WadiSettings
from wadi_contracts import (
    CalleeUnboundReason,
    CoverageReport,
    Endpoint,
    EndpointDetailView,
    EndpointTouchedFile,
    ExtractionJob,
    Icfg,
    IcfgNodeKind,
    JobStatus,
    JobType,
    RemoteEdgeItem,
    RemoteEdgesView,
    RepoSource,
    ServiceSummary,
    Snapshot,
    SnapshotStatus,
    SourceVariant,
    SourceView,
    System,
    SystemGraphService,
    SystemGraphView,
    TargetKind,
    UnopenableCallCount,
    normalize_repo_source,
)
from wadi_orchestrator.export import export_stream
from wadi_orchestrator.monitor import SnapshotMonitor
from wadi_orchestrator.state import AppState
from wadi_repo import GitError, RefNotFoundError
from wadi_storage import DuplicateSystemNameError, WadiDatabase, create_client

API_PREFIX = "/api/v1"

# §11 Phase 2.7: the source route serves whole files on demand but never more
# than this many lines per response — larger windows return truncated=True
# with total_lines so clients page honestly.
SOURCE_MAX_LINES = 2000
# Single source: the installed package's own version (pyproject.toml, kept in
# lockstep with the release tag) — surfaced via /healthz and the OpenAPI spec.
ORCHESTRATOR_VERSION = metadata_version("wadi-orchestrator")


def source_lines(content: str) -> list[str]:
    """Split source the way a COMPILER counts lines, keeping the terminators.

    Not ``str.splitlines``: Python also breaks on form feed, vertical tab,
    file separator and U+2028, none of which Java, JavaScript or Go treat as a
    line terminator. Every ICFG anchor is a compiler line number, so a single
    form feed anywhere in a file shifted this response against the anchors and
    the source panel highlighted confidently wrong code — invisibly, because
    the line numbers it printed were its own.
    """
    parts = content.split("\n")
    tail = parts.pop()
    lines = [part + "\n" for part in parts]
    if tail:
        lines.append(tail)
    return lines


# --- request/response bodies (thin wrappers over contract models) -----------------


class CreateSystemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repos: list[RepoSource] = Field(min_length=1)


class AnalyzeResponse(BaseModel):
    snapshot: Snapshot
    job_ids: list[str]


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

    # --- export (§14): the full artifact bundle as an NDJSON stream -------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/export",
        dependencies=[Depends(_require_auth)],
    )
    async def export_snapshot(snapshot_id: str, state: StateDep) -> StreamingResponse:
        """Every artifact of a succeeded snapshot, one NDJSON record each,
        with the manifest as the completeness trailer (§14)."""
        snapshot = await state.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        if snapshot.status is not SnapshotStatus.SUCCEEDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"snapshot {snapshot_id} is {snapshot.status.value}; only succeeded "
                    "snapshots export — a partial bundle is a misleading half-map (§14)"
                ),
            )
        system = await state.systems.get(snapshot.system_id)
        if system is None:
            raise HTTPException(status_code=404, detail=f"system {snapshot.system_id} not found")
        return StreamingResponse(
            export_stream(state, system, snapshot, ORCHESTRATOR_VERSION),
            media_type="application/x-ndjson",
        )

    # --- stitched graph: coverage / remote edges / restitch ---------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/coverage",
        response_model=CoverageReport,
        dependencies=[Depends(_require_auth)],
    )
    async def get_coverage(snapshot_id: str, state: StateDep) -> CoverageReport:
        """What the map knows it doesn't know (§5.4) — check this first."""
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

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/endpoints/{{endpoint_id}}/detail",
        response_model=EndpointDetailView,
        dependencies=[Depends(_require_auth)],
    )
    async def get_endpoint_detail(
        snapshot_id: str, endpoint_id: str, state: StateDep
    ) -> EndpointDetailView:
        """The endpoint workspace's one-read aggregate (§11 Phase 2.8).

        Joins the endpoint artifact with its outbound stitched edges (filtered
        server-side by the ICFG's remote-call markers) and the touched-file
        list derived from ICFG anchors. The ICFG itself and source content
        stay separate on-demand fetches (§5.3).
        """
        # Four reads that take no input from each other, so they go together:
        # this is the workspace's one blocking fetch and the latency is the
        # reader's. `endpoint.service_id` is the only value anything downstream
        # depends on, which is why the boundary and the graph read follow.
        # 404s are raised after the gather, in the same order as before.
        endpoint, snapshot, icfg, stitched = await asyncio.gather(
            state.artifacts.get_endpoint(snapshot_id, endpoint_id),
            state.snapshots.get(snapshot_id),
            state.artifacts.get_icfg(snapshot_id, endpoint_id),
            state.stitch.coverage_report_exists(snapshot_id),
        )
        if endpoint is None:
            raise HTTPException(
                status_code=404,
                detail=f"endpoint {endpoint_id} not found in snapshot {snapshot_id}",
            )
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        boundary = await state.artifacts.get_service_boundary(snapshot_id, endpoint.service_id)
        service_name = boundary.name if boundary is not None else endpoint.service_id

        remote_call_ids: set[str] = set()
        touched: dict[tuple[str, SourceVariant], int] = {}
        unopenable: Counter[CalleeUnboundReason] = Counter()
        if icfg is not None:
            for node in icfg.nodes:
                remote_call_ids.update(node.remote_call_ids)
                # §5.4.2 T5: count the call sites whose target has no interior,
                # grouped by why. Counting per reason (not one lump total) is
                # the point — "10 Lombok accessors" is a fact about generated
                # code, "10 calls you cannot open" would read as data loss.
                if node.callee_unbound_reason is not None:
                    unopenable[node.callee_unbound_reason] += 1
                # Same rule as the frontend source map: a method's ENTRY node
                # anchors to its declaration, so a file reached only through a
                # callee's entry (e.g. a constructor with no coarsened body)
                # still counts as touched. Only synthetic exits are dropped —
                # both surfaces must name the same files.
                if node.kind is IcfgNodeKind.EXIT:
                    continue
                key = (node.anchor.file, node.anchor.variant)
                touched[key] = touched.get(key, 0) + 1

        # Pre-stitch, outbound is 'not yet', never 'none' (P10) — same rule as
        # the system graph. (`stitched` came back from the gather above.)
        outbound: list[RemoteEdgeItem] = []
        if stitched and remote_call_ids:
            edges_view = await state.graph.remote_edges(snapshot_id, endpoint.service_id)
            outbound = [
                edge for edge in edges_view.outbound if edge.remote_call_id in remote_call_ids
            ]

        return EndpointDetailView(
            snapshot_id=snapshot_id,
            system_id=snapshot.system_id,
            service_id=endpoint.service_id,
            service_name=service_name,
            endpoint=endpoint,
            icfg_available=icfg is not None,
            stitched=stitched,
            outbound=outbound,
            touched_files=[
                EndpointTouchedFile(file=file, variant=variant, node_count=count)
                for (file, variant), count in sorted(touched.items())
            ],
            # Most-common first: the reader wants the dominant explanation, and
            # on real Spring code that is overwhelmingly `lombok-generated`.
            unopenable_calls=[
                UnopenableCallCount(reason=reason, call_count=count)
                for reason, count in unopenable.most_common()
            ],
            # Lets a consumer tell "every call opens" from "this graph predates
            # the accounting", which the empty list alone cannot say (P10).
            icfg_schema_version=icfg.schema_version if icfg is not None else None,
        )

    # --- system graph (§11 Phase 2.7 M4) ----------------------------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/graph",
        response_model=SystemGraphView,
        dependencies=[Depends(_require_auth)],
    )
    async def system_graph(snapshot_id: str, state: StateDep) -> SystemGraphView:
        snapshot = await state.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"snapshot {snapshot_id} not found")
        boundaries = await state.artifacts.list_service_boundaries(snapshot_id)
        counts = await state.artifacts.count_endpoints_by_service(snapshot_id)
        # Pre-stitch the edge set is 'not yet', never 'none' (P10) — services
        # render, stitched=False says why edges are absent, and Neo4j is not
        # touched at all.
        stitched = await state.stitch.get_coverage_report(snapshot_id) is not None
        edges: list[RemoteEdgeItem] = []
        if stitched:
            edges = await state.graph.all_edges(snapshot_id)
            # UNDETERMINED facts are deliberately edge-less in Neo4j (a
            # RemoteCall with no INVOKES_REMOTE — §6 schema); the map must
            # still show them, so they join from the Tier-1 stitched set.
            names = {b.service_id: b.name for b in boundaries}
            edges.extend(
                RemoteEdgeItem(
                    edge_id=edge.id,
                    remote_call_id=edge.remote_call_id,
                    caller_service_id=edge.service_id,
                    caller_service_name=names.get(edge.service_id),
                    mechanism=edge.mechanism,
                    http_verb=edge.http_verb,
                    url=edge.url,
                    target_kind=edge.target_kind,
                    confidence=edge.confidence,
                    provenance=edge.provenance,
                    evidence=edge.evidence,
                )
                for edge in await state.stitch.list_stitched_edges(snapshot_id)
                if edge.target_kind is TargetKind.UNDETERMINED
            )
        services = [
            SystemGraphService(
                service_id=boundary.service_id,
                name=boundary.name,
                kind=boundary.kind,
                endpoint_count=counts.get(boundary.service_id, 0),
                async_root_count=len(boundary.async_roots),
                gateway=bool(boundary.network.gateway_routes)
                or boundary.network.gateway_discovery_locator,
                extraction_error=boundary.extraction_error,
                cfg_anomaly_count=(
                    sum(anomaly.count for anomaly in boundary.cfg_anomalies)
                    if boundary.cfg_anomalies is not None
                    else None
                ),
            )
            for boundary in boundaries
        ]
        return SystemGraphView(
            snapshot_id=snapshot_id, stitched=stitched, services=services, edges=edges
        )

    # --- source-on-demand (§5.3) -------------------------------------------------------

    @app.get(
        f"{API_PREFIX}/snapshots/{{snapshot_id}}/services/{{service_id}}/source",
        response_model=SourceView,
        dependencies=[Depends(_require_auth)],
    )
    async def get_source(
        snapshot_id: str,
        service_id: str,
        state: StateDep,
        file: Annotated[str, Query(min_length=1)],
        start_line: Annotated[int, Query(ge=1)] = 1,
        end_line: Annotated[int | None, Query(ge=1)] = None,
    ) -> SourceView:
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
            kind = await asyncio.to_thread(
                state.repo_cache.object_kind, boundary.repo, sha, repo_path
            )
        except GitError as exc:
            raise HTTPException(
                status_code=404, detail=f"file {file!r} not found at pinned commit"
            ) from exc
        if kind != "blob":
            raise HTTPException(status_code=400, detail=f"{file!r} is a {kind}, not a file")
        try:
            content = await asyncio.to_thread(
                state.repo_cache.read_file, boundary.repo, sha, repo_path
            )
        except GitError as exc:
            raise HTTPException(
                status_code=404, detail=f"file {file!r} not found at pinned commit"
            ) from exc
        lines = source_lines(content)
        last = end_line if end_line is not None else len(lines)
        if last < start_line:
            raise HTTPException(status_code=400, detail="end_line must be >= start_line")
        # §11 Phase 2.7: whole-file serving stays on-demand AND bounded — a
        # window larger than the cap is cut and SAID to be cut (truncated),
        # with total_lines so the client fetches the next window.
        capped_last = min(last, len(lines), start_line + SOURCE_MAX_LINES - 1)
        selected = "".join(lines[start_line - 1 : capped_last])
        return SourceView(
            file=file,
            start_line=start_line,
            end_line=capped_last,
            variant=SourceVariant.ORIGINAL,
            content=selected,
            total_lines=len(lines),
            truncated=capped_last < min(last, len(lines)),
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
