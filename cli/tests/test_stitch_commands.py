"""CLI tests for the stitched-graph commands: coverage + restitch."""

import json
from collections.abc import Callable

import httpx
import pytest
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli.client import WadiApiClient
from wadi_cli.main import app
from wadi_contracts import (
    AnalysisCoverageSection,
    CoverageReport,
    CoverageTotals,
    PlaceholderEntry,
    ServiceCoverageEntry,
    SnapshotStatus,
    placeholder_service_id,
)
from wadi_testing.builders import make_snapshot, make_system

runner = CliRunner()


@pytest.fixture
def mock_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[httpx.MockTransport], None]:
    def install(transport: httpx.MockTransport) -> None:
        def factory() -> WadiApiClient:
            return WadiApiClient("http://testserver", transport=transport)

        monkeypatch.setattr(cli_main, "_api_client", factory)

    return install


def _report(snapshot_id: str) -> CoverageReport:
    return CoverageReport(
        snapshot_id=snapshot_id,
        totals=CoverageTotals(
            call_sites=3, edges=3, analyzed=1, external=1, placeholder=1, undetermined=0
        ),
        placeholders=[
            PlaceholderEntry(
                placeholder_id=placeholder_service_id("billing"),
                name="billing",
                resolved_via="bare-hostname",
                call_count=1,
                caller_service_ids=["svc_" + "a" * 16],
            )
        ],
        analysis_coverage=AnalysisCoverageSection(
            production_methods=24,
            reachable_methods=19,
            coverage_percent=79.2,
            services=[
                ServiceCoverageEntry(
                    service_id="svc_" + "a" * 16,
                    name="petstore",
                    production_methods=24,
                    reachable_methods=19,
                    coverage_percent=79.2,
                ),
                # No coverage fact: must render as unknown, never 0% (P10).
                ServiceCoverageEntry(service_id="svc_" + "b" * 16, name="legacy"),
            ],
        ),
    )


class TestCoverageCommand:
    def test_human_output_surfaces_unknowns(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        snapshot = make_snapshot(make_system())

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith(f"/snapshots/{snapshot.id}/coverage")
            return httpx.Response(200, json=_report(snapshot.id).model_dump(mode="json"))

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["coverage", snapshot.id])
        assert result.exit_code == 0, result.output
        assert "Placeholder services" in result.output
        assert "billing" in result.output
        # Analysis coverage (§5.4.3): rollup + per-service, unknown never zero.
        assert "Analysis coverage" in result.output
        assert "19/24 (79.2%)" in result.output
        assert "legacy: unknown (no coverage fact)" in result.output

    def test_json_output(self, mock_api: Callable[[httpx.MockTransport], None]) -> None:
        snapshot = make_snapshot(make_system())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_report(snapshot.id).model_dump(mode="json"))

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["coverage", snapshot.id, "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["totals"]["placeholder"] == 1

    def test_not_stitched_is_api_error(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "snapshot snap_x is not stitched yet"})

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["coverage", "snap_x"])
        assert result.exit_code == 1


class TestRestitchCommand:
    def test_restitch_starts(self, mock_api: Callable[[httpx.MockTransport], None]) -> None:
        snapshot = make_snapshot(make_system()).model_copy(
            update={"status": SnapshotStatus.RUNNING}
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path.endswith(f"/snapshots/{snapshot.id}/restitch")
            return httpx.Response(
                202,
                json={"snapshot": snapshot.model_dump(mode="json"), "job_ids": ["job_1"]},
            )

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["restitch", snapshot.id])
        assert result.exit_code == 0, result.output
        assert "running" in result.output

    def test_restitch_wait_reports_failure(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        running = make_snapshot(make_system()).model_copy(update={"status": SnapshotStatus.RUNNING})
        failed = running.model_copy(
            update={"status": SnapshotStatus.FAILED, "error": "stitch job failed: boom"}
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    202, json={"snapshot": running.model_dump(mode="json"), "job_ids": ["j"]}
                )
            return httpx.Response(200, json=failed.model_dump(mode="json"))

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["restitch", running.id, "--wait"])
        assert result.exit_code == 1
        assert "boom" in result.output

    def test_conflict_surfaces_detail(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "snapshot has active jobs"})

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["restitch", "snap_busy"])
        assert result.exit_code == 1
        assert "active jobs" in result.output
