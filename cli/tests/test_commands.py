"""CLI command tests via CliRunner with a mocked API transport."""

import json
from collections.abc import Callable

import httpx
import pytest
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli.client import WadiApiClient
from wadi_cli.main import app
from wadi_contracts import Snapshot, SnapshotStatus
from wadi_testing.builders import make_snapshot, make_system

runner = CliRunner()


@pytest.fixture
def mock_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[httpx.MockTransport], None]:
    """Route the CLI's API client through a mock transport."""

    def install(transport: httpx.MockTransport) -> None:
        def factory() -> WadiApiClient:
            return WadiApiClient("http://testserver", transport=transport)

        monkeypatch.setattr(cli_main, "_api_client", factory)

    return install


class TestSystemsCommand:
    def test_table_output(self, mock_api: Callable[[httpx.MockTransport], None]) -> None:
        system = make_system("shop")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[system.model_dump(mode="json")])

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["systems"])
        assert result.exit_code == 0, result.output
        assert "shop" in result.output

    def test_json_output(self, mock_api: Callable[[httpx.MockTransport], None]) -> None:
        system = make_system("shop")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[system.model_dump(mode="json")])

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["systems", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed[0]["name"] == "shop"

    def test_unreachable_exit_code_3(self, mock_api: Callable[[httpx.MockTransport], None]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["systems"])
        assert result.exit_code == 3


class TestAnalyzeCommand:
    def _transport(self, statuses: list[SnapshotStatus]) -> httpx.MockTransport:
        """API double: no systems yet → create → analyze → poll through ``statuses``."""
        system = make_system("proj")
        snapshot = make_snapshot(system)
        state = {"registered": False, "polls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/systems" and request.method == "GET":
                registered = [system.model_dump(mode="json")] if state["registered"] else []
                return httpx.Response(200, json=registered)
            if path == "/api/v1/systems" and request.method == "POST":
                state["registered"] = True
                return httpx.Response(201, json=system.model_dump(mode="json"))
            if path.endswith("/analyze"):
                return httpx.Response(
                    202,
                    json={
                        "snapshot": snapshot.model_dump(mode="json"),
                        "job_ids": ["job_1"],
                    },
                )
            if path == f"/api/v1/snapshots/{snapshot.id}":
                index = min(state["polls"], len(statuses) - 1)
                state["polls"] += 1
                polled = snapshot.model_copy(
                    update={
                        "status": statuses[index],
                        "error": "boom" if statuses[index] is SnapshotStatus.FAILED else None,
                    }
                )
                return httpx.Response(200, json=polled.model_dump(mode="json"))
            return httpx.Response(404, json={"detail": f"unexpected {path}"})

        return httpx.MockTransport(handler)

    def test_analyze_registers_and_starts(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        target = tmp_path_factory.mktemp("proj")
        mock_api(self._transport([SnapshotStatus.RUNNING]))
        result = runner.invoke(app, ["analyze", str(target)])
        assert result.exit_code == 0, result.output
        assert "registered system" in result.output
        assert "snapshot" in result.output

    def test_analyze_wait_success(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_main, "_wait_for_snapshot", _poll_now)
        target = tmp_path_factory.mktemp("proj")
        mock_api(self._transport([SnapshotStatus.RUNNING, SnapshotStatus.SUCCEEDED]))
        result = runner.invoke(app, ["analyze", str(target), "--wait"])
        assert result.exit_code == 0, result.output
        assert "succeeded" in result.output

    def test_analyze_wait_failure_exit_code_1(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_main, "_wait_for_snapshot", _poll_now)
        target = tmp_path_factory.mktemp("proj")
        mock_api(self._transport([SnapshotStatus.FAILED]))
        result = runner.invoke(app, ["analyze", str(target), "--wait"])
        assert result.exit_code == 1

    def test_analyze_missing_path_usage_error(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        mock_api(self._transport([SnapshotStatus.RUNNING]))
        result = runner.invoke(app, ["analyze", "/definitely/not/a/path"])
        assert result.exit_code == 2

    def test_analyze_reuses_existing_system(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        transport = self._transport([SnapshotStatus.RUNNING])
        # Pre-register by making one analyze call first.
        mock_api(transport)
        target = tmp_path_factory.mktemp("proj")
        first = runner.invoke(app, ["analyze", str(target), "--name", "proj"])
        assert first.exit_code == 0
        second = runner.invoke(app, ["analyze", str(target), "--name", "proj"])
        assert second.exit_code == 0
        assert "using existing system" in second.output


def _poll_now(client: WadiApiClient, snapshot_id: str, poll_seconds: float = 0.0) -> Snapshot:
    """Poll without sleeping until a terminal status arrives (test double)."""
    del poll_seconds
    while True:
        snapshot = client.get_snapshot(snapshot_id)
        if snapshot.status in (SnapshotStatus.SUCCEEDED, SnapshotStatus.FAILED):
            return snapshot


class TestMcpInstall:
    def test_prints_config_snippet(self) -> None:
        result = runner.invoke(app, ["mcp", "install"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["mcpServers"]["wadi"]["command"] == "wadi"
