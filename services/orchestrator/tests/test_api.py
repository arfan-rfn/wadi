"""Orchestrator API integration tests (real Mongo, real git, ASGI client)."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from orchestrator_support import run_git

from wadi_contracts import (
    CalleeUnboundReason,
    CoverageReport,
    CoverageTotals,
    Endpoint,
    IcfgNodeKind,
    MethodRef,
    ServiceBoundary,
    ServiceKind,
    ShapeKind,
    Snapshot,
    TypeShape,
)
from wadi_orchestrator.state import AppState
from wadi_storage import GraphRepository
from wadi_testing.builders import (
    make_endpoint,
    make_icfg,
    make_service,
    make_snapshot,
    make_system,
)

pytestmark = pytest.mark.integration


async def _register_system(client: AsyncClient, sample_repo: Path, name: str = "shop") -> str:
    response = await client.post(
        "/api/v1/systems",
        json={"name": name, "repos": [{"source": str(sample_repo), "branch": "main"}]},
    )
    assert response.status_code == 201, response.text
    system_id: str = response.json()["id"]
    return system_id


class TestHealth:
    async def test_healthz(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestSystems:
    async def test_create_and_get(self, client: AsyncClient, sample_repo: Path) -> None:
        system_id = await _register_system(client, sample_repo)
        assert system_id.startswith("sys_")
        fetched = await client.get(f"/api/v1/systems/{system_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "shop"

    async def test_duplicate_name_conflict(self, client: AsyncClient, sample_repo: Path) -> None:
        await _register_system(client, sample_repo)
        response = await client.post(
            "/api/v1/systems",
            json={"name": "shop", "repos": [{"source": str(sample_repo)}]},
        )
        assert response.status_code == 409

    async def test_validation_rejects_empty_repos(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/systems", json={"name": "x", "repos": []})
        assert response.status_code == 422

    async def test_missing_system_404(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/systems/sys_" + "0" * 32)
        assert response.status_code == 404

    async def test_list(self, client: AsyncClient, sample_repo: Path) -> None:
        await _register_system(client, sample_repo, "a-system")
        listed = await client.get("/api/v1/systems")
        assert listed.status_code == 200
        assert [s["name"] for s in listed.json()] == ["a-system"]


class TestAnalyze:
    async def test_analyze_pins_sha_and_creates_job(
        self, client: AsyncClient, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        response = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert response.status_code == 202, response.text
        body = response.json()
        snapshot = body["snapshot"]
        assert snapshot["status"] == "running"
        (sha,) = snapshot["commits"].values()
        assert len(sha) == 40
        assert len(body["job_ids"]) == 1

        jobs = await client.get(f"/api/v1/snapshots/{snapshot['id']}/jobs")
        assert jobs.status_code == 200
        assert jobs.json()[0]["type"] == "extract"
        assert jobs.json()[0]["status"] == "pending"

    async def test_analyze_unknown_branch_400(self, client: AsyncClient, sample_repo: Path) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={
                "name": "badbranch",
                "repos": [{"source": str(sample_repo), "branch": "no-such-branch"}],
            },
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyze.status_code == 400
        assert "no-such-branch" in analyze.json()["detail"]

    async def test_analyze_unreachable_repo_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/systems",
            json={"name": "ghost", "repos": [{"source": "/nonexistent/path/repo"}]},
        )
        system_id = response.json()["id"]
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        assert analyze.status_code == 400

    async def test_snapshots_listing(self, client: AsyncClient, sample_repo: Path) -> None:
        system_id = await _register_system(client, sample_repo)
        await client.post(f"/api/v1/systems/{system_id}/analyze")
        await client.post(f"/api/v1/systems/{system_id}/analyze")
        listed = await client.get(f"/api/v1/systems/{system_id}/snapshots")
        assert listed.status_code == 200
        assert len(listed.json()) == 2


class TestReadApi:
    async def test_artifact_flow(self, client: AsyncClient, app_state: AppState) -> None:
        """Seed artifacts as the worker would, then read them through the API."""
        from wadi_testing.builders import make_system

        system = make_system("seeded")
        await app_state.systems.insert(system)
        snapshot = make_snapshot(system)
        await app_state.snapshots.insert(snapshot)
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)
        icfg = make_icfg(snapshot, boundary, endpoint)
        await app_state.artifacts.write_service_boundaries([boundary])
        await app_state.artifacts.write_endpoints([endpoint])
        await app_state.artifacts.write_icfg(icfg)

        services = await client.get(f"/api/v1/snapshots/{snapshot.id}/services")
        assert services.status_code == 200
        assert services.json()[0]["service_id"] == boundary.service_id
        assert services.json()[0]["endpoint_count"] == 1  # derived view field (§7 views)

        endpoints = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{boundary.service_id}/endpoints"
        )
        assert endpoints.status_code == 200
        assert endpoints.json()[0]["id"] == endpoint.id

        single = await client.get(f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}")
        assert single.status_code == 200

        graph = await client.get(f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/icfg")
        assert graph.status_code == 200
        assert len(graph.json()["nodes"]) == len(icfg.nodes)

    async def test_404s(self, client: AsyncClient) -> None:
        missing_snap = "snap_" + "0" * 32
        assert (await client.get(f"/api/v1/snapshots/{missing_snap}")).status_code == 404
        assert (await client.get(f"/api/v1/snapshots/{missing_snap}/services")).status_code == 404
        assert (
            await client.get(f"/api/v1/snapshots/{missing_snap}/endpoints/ep_{'0' * 16}")
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/snapshots/{missing_snap}/endpoints/ep_{'0' * 16}/icfg")
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/snapshots/{missing_snap}/endpoints/ep_{'0' * 16}/detail")
        ).status_code == 404


class TestEndpointListIsASummary:
    """The list route serves list rows, not whole endpoints (§5.2.15).

    ICPC's `contest` made the cost concrete: the two wire-shape fields were
    124 MB of a 126 MB response, and the browser parsed all of it before
    rendering a row. They are omitted from the *type* rather than nulled,
    because `None` already means "no request body" on 673 of those 804
    endpoints — a list that nulls them cannot be told from one reporting a
    fact, which is the P10 collapse this route is not allowed to make.
    """

    @staticmethod
    def _shape(type_name: str) -> TypeShape:
        return TypeShape(kind=ShapeKind.OBJECT, type_name=type_name)

    async def _seed(self, app_state: AppState) -> tuple[Snapshot, ServiceBoundary, Endpoint]:
        system = make_system("summary-seeded")
        await app_state.systems.insert(system)
        snapshot = make_snapshot(system)
        await app_state.snapshots.insert(snapshot)
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary).model_copy(
            update={
                "request_schema": self._shape("com.acme.OrderRequest"),
                "response_schema": self._shape("com.acme.Order"),
            }
        )
        await app_state.artifacts.write_service_boundaries([boundary])
        await app_state.artifacts.write_endpoints([endpoint])
        return snapshot, boundary, endpoint

    async def test_rows_omit_the_wire_shapes_entirely(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        snapshot, boundary, endpoint = await self._seed(app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{boundary.service_id}/endpoints"
        )
        assert response.status_code == 200, response.text
        row = response.json()[0]
        assert row["id"] == endpoint.id
        # Absent, not null: a null would be indistinguishable from "no body".
        assert "request_schema" not in row
        assert "response_schema" not in row

    async def test_rows_keep_everything_a_list_actually_renders(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """The trim is the two shapes and nothing else.

        The UI's row reads auth, handler, params, declared_statuses and the
        URIs; `wadi endpoints` reads id/method/uri/auth/handler. Dropping any
        of those would trade one round trip for a fan-out per visible row.
        """
        snapshot, boundary, _ = await self._seed(app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{boundary.service_id}/endpoints"
        )
        row = response.json()[0]
        for field in (
            "id",
            "snapshot_id",
            "service_id",
            "http_method",
            "full_uri",
            "simplified_uri",
            "params",
            "response_type",
            "declared_statuses",
            "auth",
            "handler",
            "trigger",
        ):
            assert field in row, f"list row lost {field}"

    async def test_the_shapes_are_still_reachable_per_endpoint(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """Trimming the list is only honest if the detail still carries them."""
        snapshot, _, endpoint = await self._seed(app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.status_code == 200, response.text
        detail = response.json()["endpoint"]
        assert detail["request_schema"]["type_name"] == "com.acme.OrderRequest"
        assert detail["response_schema"]["type_name"] == "com.acme.Order"


class TestStagedLibrarySource:
    """Source-on-demand for code the analyzed tree STAGED (§5.2.14, §5.2.15).

    Staging copies each library's `src/main/java` into the dependent's parse
    root under `wadi-libs/`, so every ICFG anchor in library code names a path
    that exists in the analyzed tree and in no repository's git history. The
    source route resolved against the SERVICE's repo and 404'd every one of
    them — on ICPC, every method the shared jar declares, which is most of what
    a reader following a call actually lands on.
    """

    @staticmethod
    def _library_repo(tmp_path: Path) -> tuple[Path, str]:
        repo = tmp_path / "lib-repo"
        (repo / "src" / "main" / "java" / "acme").mkdir(parents=True)
        run_git("init", "--initial-branch=main", cwd=repo)
        (repo / "src" / "main" / "java" / "acme" / "Base.java").write_text(
            "package acme;\nclass Base {\n  int shared;\n}\n"
        )
        run_git("add", ".", cwd=repo)
        run_git("commit", "-m", "library", cwd=repo)
        sha = run_git("rev-parse", "HEAD", cwd=repo).strip()
        return repo, sha

    async def _seed(
        self, app_state: AppState, tmp_path: Path
    ) -> tuple[Snapshot, ServiceBoundary, Path]:
        lib_repo, lib_sha = self._library_repo(tmp_path)
        system = make_system("staged-lib")
        await app_state.systems.insert(system)
        snapshot = make_snapshot(system)
        # The library root IS the repository, so staging contributes an empty
        # name segment — `wadi-libs/src/main/java/...` with nothing between.
        # That is ICPC's shape and the one a fixed-segment parse gets wrong.
        snapshot = snapshot.model_copy(
            update={"commits": {**snapshot.commits, str(lib_repo): lib_sha}}
        )
        await app_state.snapshots.insert(snapshot)

        service = make_service(snapshot)
        library = service.model_copy(
            update={
                "service_id": "svc_" + "b" * 16,
                "name": "base",
                "kind": ServiceKind.LIBRARY,
                "repo": str(lib_repo),
                "build_root": ".",
            }
        )
        await app_state.artifacts.write_service_boundaries([service, library])
        # The route reads through the mirror the analysis would have created.
        app_state.repo_cache.ensure_mirror(str(lib_repo))
        return snapshot, service, lib_repo

    async def test_a_staged_path_resolves_against_the_librarys_own_repo(
        self, client: AsyncClient, app_state: AppState, tmp_path: Path
    ) -> None:
        snapshot, service, _ = await self._seed(app_state, tmp_path)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{service.service_id}/source",
            params={"file": "wadi-libs/src/main/java/acme/Base.java"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "class Base" in body["content"]
        assert body["total_lines"] == 4

    async def test_an_unclaimed_staged_path_says_so(
        self, client: AsyncClient, app_state: AppState, tmp_path: Path
    ) -> None:
        """It must not fall back to the service's repo (P10).

        Reporting "not found at pinned commit" against the SERVICE would blame
        the wrong repository for a file that was never meant to be in it.
        """
        snapshot, service, _ = await self._seed(app_state, tmp_path)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{service.service_id}/source",
            params={"file": "wadi-libs/src/main/java/acme/Missing.java"},
        )
        assert response.status_code == 404
        assert "no library in this snapshot claims it" in response.json()["detail"]

    async def test_the_services_own_files_are_untouched_by_the_staging_branch(
        self, client: AsyncClient, app_state: AppState, tmp_path: Path
    ) -> None:
        """A path that merely CONTAINS the segment is not a staged path."""
        snapshot, service, _ = await self._seed(app_state, tmp_path)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/services/{service.service_id}/source",
            params={"file": "src/main/java/acme/wadi-libs-helper/Thing.java"},
        )
        # Resolved against the service repo (and absent there), NOT diverted.
        assert response.status_code == 404
        assert "not found at pinned commit" in response.json()["detail"]


class TestEndpointDetail:
    """The workspace aggregate (§11 Phase 2.8): one read, honest states."""

    @staticmethod
    async def _seed(app_state: AppState) -> "tuple[Snapshot, ServiceBoundary, Endpoint]":
        system = make_system("detail-seeded")
        await app_state.systems.insert(system)
        snapshot = make_snapshot(system)
        await app_state.snapshots.insert(snapshot)
        boundary = make_service(snapshot)
        endpoint = make_endpoint(snapshot, boundary)
        await app_state.artifacts.write_service_boundaries([boundary])
        await app_state.artifacts.write_endpoints([endpoint])
        return snapshot, boundary, endpoint

    async def test_unstitched_with_icfg(self, client: AsyncClient, app_state: AppState) -> None:
        """Pre-stitch: outbound is 'not yet' (stitched=False), never 'none' (P10)."""
        snapshot, boundary, endpoint = await self._seed(app_state)
        icfg = make_icfg(snapshot, boundary, endpoint, statement_count=3)
        await app_state.artifacts.write_icfg(icfg)

        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["system_id"] == snapshot.system_id
        assert body["service_id"] == boundary.service_id
        assert body["service_name"] == boundary.name
        assert body["endpoint"]["id"] == endpoint.id
        assert body["icfg_available"] is True
        assert body["stitched"] is False
        assert body["outbound"] == []
        # Entry nodes count (a file reached only via a callee's declaration is
        # still touched — the frontend source map uses the same rule); only
        # synthetic exits are dropped. 1 entry + 3 statements = 4.
        assert body["touched_files"] == [
            {"file": "src/A.java", "variant": "original", "node_count": 4}
        ]

    async def test_unopenable_calls_are_counted_by_reason(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """§5.4.2 T5: the endpoint-level honesty surface.

        `analysis_coverage` sizes reachability system-wide and the coverage
        report's unresolved counts cover only cross-service edges, so calls
        with no interior were counted NOWHERE per endpoint — which is what let
        a correct extraction read as data loss.
        """
        snapshot, boundary, endpoint = await self._seed(app_state)
        icfg = make_icfg(snapshot, boundary, endpoint, statement_count=3)
        callee = MethodRef(
            id=endpoint.handler.id, signature="com.acme.Order.getId:java.lang.String()"
        )
        reasons = [
            CalleeUnboundReason.LOMBOK_GENERATED,
            CalleeUnboundReason.LOMBOK_GENERATED,
            CalleeUnboundReason.THIRD_PARTY,
        ]
        patched = list(icfg.nodes)
        labelled = 0
        for index, node in enumerate(patched):
            if node.kind is IcfgNodeKind.STATEMENT and labelled < len(reasons):
                patched[index] = node.model_copy(
                    update={"callee": callee, "callee_unbound_reason": reasons[labelled]}
                )
                labelled += 1
        await app_state.artifacts.write_icfg(icfg.model_copy(update={"nodes": patched}))

        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.status_code == 200, response.text
        # Most-common first, and grouped BY REASON: "2 Lombok accessors, 1 JDK
        # method" is a fact about generated code; a bare "3 unopenable" would
        # read as damage.
        assert response.json()["unopenable_calls"] == [
            {"reason": "lombok-generated", "call_count": 2},
            {"reason": "third-party", "call_count": 1},
        ]

    async def test_endpoint_with_every_call_openable_reports_nothing(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        """Empty means 'nothing to explain', and must not be confused with
        'not measured' — the seeded ICFG has no unbound callees at all."""
        snapshot, boundary, endpoint = await self._seed(app_state)
        await app_state.artifacts.write_icfg(
            make_icfg(snapshot, boundary, endpoint, statement_count=3)
        )
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.json()["unopenable_calls"] == []

    async def test_no_icfg_is_stated_not_silent(
        self, client: AsyncClient, app_state: AppState
    ) -> None:
        snapshot, _, endpoint = await self._seed(app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["icfg_available"] is False
        assert body["touched_files"] == []

    async def test_unknown_endpoint_404(self, client: AsyncClient, app_state: AppState) -> None:
        snapshot, _, _ = await self._seed(app_state)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/ep_{'f' * 16}/detail"
        )
        assert response.status_code == 404

    async def test_stitched_outbound_filtered_to_this_endpoints_calls(
        self,
        client: AsyncClient,
        app_state: AppState,
        graph_repository: GraphRepository,
    ) -> None:
        """Only edges whose remote-call marker appears in THIS endpoint's ICFG
        come back — the service-wide set stays behind /remote-edges."""
        from wadi_contracts import IcfgEdge, IcfgEdgeKind, IcfgNode, SourceAnchor
        from wadi_testing.builders import make_analyzed_edge, make_remote_call

        app_state.graph = graph_repository
        snapshot, caller, endpoint = await self._seed(app_state)
        callee = make_service(snapshot, "services/inventory")
        target = make_endpoint(snapshot, callee, uri="/stock/{id}")
        in_flow_call = make_remote_call(snapshot, caller, line=27)
        other_call = make_remote_call(snapshot, caller, line=99, url="http://billing:8082/invoices")
        edges = [make_analyzed_edge(in_flow_call, target), make_analyzed_edge(other_call, target)]

        icfg = make_icfg(snapshot, caller, endpoint)
        icfg.nodes.append(
            IcfgNode(
                id="call0",
                kind=IcfgNodeKind.CALL,
                anchor=SourceAnchor(file="src/A.java", start_line=3, end_line=3),
                source_text="inventoryClient.stock(id);",
                method=endpoint.handler,
                remote_call_id=in_flow_call.id,
                remote_call_ids=[in_flow_call.id],
            )
        )
        icfg.edges.append(IcfgEdge(source="s2", target="call0", kind=IcfgEdgeKind.FLOW))
        await app_state.artifacts.write_icfg(icfg)
        await app_state.artifacts.write_service_boundaries([callee])
        await graph_repository.replace_snapshot(
            snapshot.id,
            boundaries=[caller, callee],
            endpoints=[target],
            remote_calls=[in_flow_call, other_call],
            edges=edges,
        )
        await app_state.stitch.write_coverage_report(
            CoverageReport(
                snapshot_id=snapshot.id,
                totals=CoverageTotals(
                    call_sites=2, edges=2, analyzed=2, external=0, placeholder=0, undetermined=0
                ),
            )
        )

        response = await client.get(
            f"/api/v1/snapshots/{snapshot.id}/endpoints/{endpoint.id}/detail"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stitched"] is True
        assert [edge["remote_call_id"] for edge in body["outbound"]] == [in_flow_call.id]
        assert body["outbound"][0]["target_kind"] == "analyzed"


class TestSourceOnDemand:
    async def test_reads_pinned_source(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]

        # Seed the boundary the worker would discover (build root at repo root).
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        snapshot = await app_state.snapshots.get(snapshot_id)
        assert snapshot is not None
        repo_key = normalize_repo_source(str(sample_repo))
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=repo_key,
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])

        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{boundary.service_id}/source",
            params={"file": "src/App.java", "start_line": 2, "end_line": 3},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "  int x;\n  int y;\n"
        assert body["variant"] == "original"

    async def test_missing_file_404(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{boundary.service_id}/source",
            params={"file": "src/Ghost.java"},
        )
        assert response.status_code == 404

    async def _seed_boundary(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> tuple[str, str]:
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])
        return snapshot_id, boundary.service_id

    async def test_whole_file_when_end_line_omitted(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """§11 Phase 2.7: on-demand whole-file serving with an honest length."""
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src/App.java"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "class App {\n  int x;\n  int y;\n}\n"
        assert body["start_line"] == 1
        assert body["end_line"] == 4
        assert body["total_lines"] == 4
        assert body["truncated"] is False

    async def test_window_beyond_cap_is_truncated_honestly(
        self,
        client: AsyncClient,
        app_state: AppState,
        sample_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A window larger than the server cap is cut and SAID to be cut."""
        import wadi_orchestrator.app as app_module

        monkeypatch.setattr(app_module, "SOURCE_MAX_LINES", 2)
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src/App.java"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"] == "class App {\n  int x;\n"
        assert body["end_line"] == 2
        assert body["total_lines"] == 4
        assert body["truncated"] is True

    async def test_directory_path_is_400_not_content(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """A tree path must never be served as file content."""
        snapshot_id, svc_id = await self._seed_boundary(client, app_state, sample_repo)
        response = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/services/{svc_id}/source",
            params={"file": "src"},
        )
        assert response.status_code == 400
        assert "not a file" in response.json()["detail"]


class TestMonitor:
    async def test_full_lifecycle_via_monitor_ticks(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """extract succeeds → stitch enqueued → stitch succeeds → snapshot SUCCEEDED."""
        from wadi_orchestrator.monitor import SnapshotMonitor

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        monitor = SnapshotMonitor(app_state)

        # Simulate the worker completing the extract job.
        extract = await app_state.jobs.claim("test-worker")
        assert extract is not None
        assert await app_state.jobs.complete(extract.id, "test-worker")

        await monitor.tick()  # sees extraction done → enqueues stitch
        jobs = await app_state.jobs.list_for_snapshot(snapshot_id)
        assert [j.type.value for j in jobs] == ["extract", "stitch"]

        stitch = await app_state.jobs.claim("stitch-worker")
        assert stitch is not None
        assert await app_state.jobs.complete(stitch.id, "stitch-worker")

        await monitor.tick()  # sees stitch done → snapshot succeeded
        snapshot = await client.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "succeeded"

    async def test_failed_job_fails_snapshot_loudly(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        from wadi_orchestrator.monitor import SnapshotMonitor

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]

        job = await app_state.jobs.claim("w")
        assert job is not None
        # Exhaust all attempts so the failure is permanent.
        for attempt in range(job.max_attempts):
            await app_state.jobs.fail(job.id, "w", f"boom {attempt}")
            reclaimed = await app_state.jobs.claim("w")
            if reclaimed is None:
                break

        await SnapshotMonitor(app_state).tick()
        snapshot = await client.get(f"/api/v1/snapshots/{snapshot_id}")
        assert snapshot.json()["status"] == "failed"
        assert "boom" in snapshot.json()["error"]


class TestAuth:
    async def test_token_enforced_when_configured(self, database: object, tmp_path: Path) -> None:
        from httpx import ASGITransport, AsyncClient
        from orchestrator_support import make_settings
        from pydantic import SecretStr

        from wadi_orchestrator.app import create_app
        from wadi_storage import WadiDatabase

        assert isinstance(database, WadiDatabase)
        settings = make_settings(tmp_path, api_token=SecretStr("s3cret"))
        app = create_app(settings, database=database, run_monitor=False)
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as http,
            app.router.lifespan_context(app),
        ):
            # /healthz stays open for platform probes.
            assert (await http.get("/healthz")).status_code == 200
            # API requires the bearer token.
            assert (await http.get("/api/v1/systems")).status_code == 401
            wrong = await http.get("/api/v1/systems", headers={"Authorization": "Bearer nope"})
            assert wrong.status_code == 401
            right = await http.get("/api/v1/systems", headers={"Authorization": "Bearer s3cret"})
            assert right.status_code == 200


class TestSystemGraph:
    async def test_prestitch_graph_lists_services_with_honest_stitched_flag(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        """§11 Phase 2.7 M4: before stitching, services render and the empty
        edge list is 'not yet' (stitched=False), never 'none'."""
        from wadi_contracts import ServiceBoundary, normalize_repo_source, service_id

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        boundary = ServiceBoundary(
            snapshot_id=snapshot_id,
            service_id=service_id(str(sample_repo), "."),
            name="sample",
            repo=normalize_repo_source(str(sample_repo)),
            build_root=".",
            languages=["java"],
            build_system="maven",
        )
        await app_state.artifacts.write_service_boundaries([boundary])

        response = await client.get(f"/api/v1/snapshots/{snapshot_id}/graph")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stitched"] is False
        assert body["edges"] == []
        assert [s["name"] for s in body["services"]] == ["sample"]
        service = body["services"][0]
        assert service["endpoint_count"] == 0
        assert service["gateway"] is False
        # cfg_anomalies=None on the boundary → unknown, never zero (P10).
        assert service["cfg_anomaly_count"] is None

    async def test_missing_snapshot_404(self, client: AsyncClient) -> None:
        missing = "snap_" + "0" * 32
        assert (await client.get(f"/api/v1/snapshots/{missing}/graph")).status_code == 404


class TestSystemAuthRoute:
    """§5.2.9 — "which endpoints here are unprotected?" in one read."""

    async def test_totals_partition_the_endpoints_by_auth_state(
        self, client: AsyncClient, app_state: AppState, sample_repo: Path
    ) -> None:
        from wadi_contracts import (
            AuthEffect,
            AuthEvidence,
            AuthEvidenceKind,
            AuthResolution,
            Endpoint,
            EndpointAuth,
            HttpMethod,
            MethodRef,
            ServiceBoundary,
            normalize_repo_source,
            service_id,
        )

        system_id = await _register_system(client, sample_repo)
        analyze = await client.post(f"/api/v1/systems/{system_id}/analyze")
        snapshot_id = analyze.json()["snapshot"]["id"]
        svc = service_id(str(sample_repo), ".")
        await app_state.artifacts.write_service_boundaries(
            [
                ServiceBoundary(
                    snapshot_id=snapshot_id,
                    service_id=svc,
                    name="sample",
                    repo=normalize_repo_source(str(sample_repo)),
                    build_root=".",
                    languages=["java"],
                    build_system="maven",
                )
            ]
        )

        def _endpoint(uri: str, auth: EndpointAuth) -> Endpoint:
            return Endpoint.create(
                snapshot_id=snapshot_id,
                service_id=svc,
                http_method=HttpMethod.GET,
                full_uri=uri,
                handler=MethodRef(id="m_" + "0" * 16, signature=f"C.h{uri}:void()"),
                auth=auth,
            )

        protected = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail='/a -> hasRole("ADMIN")',
            effect=AuthEffect.REQUIRE_ROLES,
            roles=["ADMIN"],
        )
        open_rule = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail="/b -> permitAll()",
            effect=AuthEffect.PERMIT_ALL,
        )
        unread = AuthEvidence(
            kind=AuthEvidenceKind.INTERCEPTOR,
            detail="AuthInterceptor",
            effect=AuthEffect.UNKNOWN,
            resolution=AuthResolution.OPAQUE,
            pattern="/c",
        )
        deny = AuthEvidence(
            kind=AuthEvidenceKind.SECURITY_DSL,
            detail="/e -> denyAll()",
            effect=AuthEffect.DENY_ALL,
        )
        await app_state.artifacts.write_endpoints(
            [
                _endpoint(
                    "/a", EndpointAuth(authenticated=True, roles=["ADMIN"], evidence=[protected])
                ),
                _endpoint("/b", EndpointAuth(authenticated=False, evidence=[open_rule])),
                _endpoint("/c", EndpointAuth(authenticated=None, evidence=[unread])),
                _endpoint("/d", EndpointAuth()),
                _endpoint("/e", EndpointAuth(authenticated=True, denied=True, evidence=[deny])),
            ]
        )

        response = await client.get(f"/api/v1/snapshots/{snapshot_id}/auth")
        assert response.status_code == 200, response.text
        body = response.json()
        # `denied` is carved OUT of `authenticated`, never counted in both:
        # a route nobody can reach is not part of the protected surface, and
        # double-counting it would break the partition this test exists for.
        assert body["totals"] == {
            "endpoints": 5,
            "authenticated": 1,
            "denied": 1,
            "unauthenticated": 1,
            "withheld": 1,
            "no_evidence": 1,
        }
        by_uri = {row["full_uri"]: row for row in body["rows"]}
        assert by_uri["/a"]["roles"] == ["ADMIN"]
        assert by_uri["/a"]["denied"] is False
        assert by_uri["/e"]["denied"] is True
        # withheld vs no-evidence must stay distinguishable: one is a wadi gap,
        # the other a possible hole in the system.
        assert by_uri["/c"]["unread_kinds"] == ["interceptor"]
        assert by_uri["/d"]["unread_kinds"] == []
        assert by_uri["/d"]["authenticated"] is None

    async def test_missing_snapshot_404(self, client: AsyncClient) -> None:
        missing = "snap_" + "0" * 32
        assert (await client.get(f"/api/v1/snapshots/{missing}/auth")).status_code == 404
