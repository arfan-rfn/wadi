"""CLI command tests via CliRunner with a mocked API transport."""

import json
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
import typer
from support import plain
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli.client import ApiTimeoutError, ApiUnreachableError, WadiApiClient
from wadi_cli.main import app
from wadi_contracts import RepoSource, Snapshot, SnapshotStatus
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
        assert "shop" in plain(result.output)

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
        state: dict[str, Any] = {"registered": False, "polls": 0, "system": None}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/systems" and request.method == "GET":
                registered = [state["system"]] if state["registered"] else []
                return httpx.Response(200, json=registered)
            if path == "/api/v1/systems" and request.method == "POST":
                state["registered"] = True
                # Echo back the sources that were registered, as a real server
                # does. A double that always returns a FIXED source cannot
                # exercise reuse at all: every lookup looks like a collision
                # with a different repo.
                body = json.loads(request.content)
                registered_system = system.model_copy(
                    update={"repos": [RepoSource(**r) for r in body["repos"]]}
                )
                state["system"] = registered_system.model_dump(mode="json")
                return httpx.Response(201, json=state["system"])
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
        assert "registered system" in plain(result.output)
        assert "snapshot" in plain(result.output)

    def test_analyze_wait_success(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_main, "wait_for_snapshot", _poll_now)
        target = tmp_path_factory.mktemp("proj")
        mock_api(self._transport([SnapshotStatus.RUNNING, SnapshotStatus.SUCCEEDED]))
        result = runner.invoke(app, ["analyze", str(target), "--wait"])
        assert result.exit_code == 0, result.output
        assert "succeeded" in plain(result.output)

    def test_analyze_wait_failure_exit_code_1(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_main, "wait_for_snapshot", _poll_now)
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
        assert "using existing system" in plain(second.output)


class TestErrorsThatHelp:
    """Reported against 0.7.1, all three the same defect: the CLI said something
    confident and wrong about what had just happened, and never said what to do
    next. A user who hits an error is already stuck — the message is the only
    thing between them and being unstuck.
    """

    def test_a_name_collision_names_both_sources_and_suggests_a_free_name(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        """`--repo <github url> --name yas` silently reused a system registered
        from a LOCAL path, cloned that instead, and failed on it. Nothing in the
        output said the flag had been ignored."""
        system = make_system("yas").model_copy(
            update={"repos": [RepoSource(source="/Users/me/local/yas", branch=None)]}
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/systems" and request.method == "GET":
                name = request.url.params.get("name")
                # Only the original name is taken; the suggested one is free.
                taken = name in (None, "yas")
                return httpx.Response(200, json=[system.model_dump(mode="json")] if taken else [])
            raise AssertionError(f"unexpected call: {request.method} {request.url.path}")

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(
            app, ["analyze", "--repo", "https://github.com/cloudhubs/yas.git", "--name", "yas"]
        )
        output = plain(result.output)
        assert result.exit_code == 2, output
        # Both sources named, so the user can see WHICH one it would have used.
        assert "/Users/me/local/yas" in output
        assert "https://github.com/cloudhubs/yas.git" in output
        # And a suggestion that is runnable as printed, not a hint to decode.
        assert "--name yas-2" in output
        assert "wadi analyze --repo https://github.com/cloudhubs/yas.git" in output

    def test_reuse_is_silent_when_the_sources_match(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        """The check must not become a nuisance: re-analyzing the SAME source is
        the normal path and stays a one-liner."""
        system = make_system("proj").model_copy(
            update={"repos": [RepoSource(source="https://example.com/proj.git", branch=None)]}
        )
        snapshot = make_snapshot(system)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/systems":
                return httpx.Response(200, json=[system.model_dump(mode="json")])
            if request.url.path.endswith("/analyze"):
                return httpx.Response(
                    202, json={"snapshot": snapshot.model_dump(mode="json"), "job_ids": []}
                )
            raise AssertionError(f"unexpected call: {request.url.path}")

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(
            app, ["analyze", "--repo", "https://example.com/proj.git", "--name", "proj"]
        )
        assert result.exit_code == 0, result.output
        assert "using existing system" in plain(result.output)

    def test_a_timeout_says_the_work_may_still_be_running(
        self, mock_api: Callable[[httpx.MockTransport], None]
    ) -> None:
        """The 0.7.1 report verbatim: `analyze` outlived the 30s client timeout
        while the snapshot was RUNNING, and the CLI answered "is the stack up?
        (wadi up)". It sent a user with a healthy stack to restart it, and
        invited a retry that would start a second snapshot."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/systems" and request.method == "GET":
                return httpx.Response(200, json=[])
            if request.url.path == "/api/v1/systems" and request.method == "POST":
                body = json.loads(request.content)
                created = make_system(body["name"]).model_copy(
                    update={"repos": [RepoSource(**r) for r in body["repos"]]}
                )
                return httpx.Response(201, json=created.model_dump(mode="json"))
            raise httpx.ReadTimeout("clone is slow")

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(
            app, ["analyze", "--repo", "https://example.com/big.git", "--name", "big"]
        )
        output = plain(result.output)
        assert result.exit_code == 3
        assert "may still be running" in output
        # It must NOT blame the stack.
        assert "wadi up" not in output
        # And it must point at the check, not at a retry that duplicates work.
        assert "wadi snapshots big" in output

    def test_a_damaged_repository_explains_itself(
        self,
        mock_api: Callable[[httpx.MockTransport], None],
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """The first report: a wall of git output with no interpretation. The
        git reason is kept as evidence, but it is no longer the headline."""
        target = tmp_path_factory.mktemp("yas")
        broken = (
            f"repository unreachable: git clone --mirror {target} /repo-cache/x.git "
            "failed (128): Cloning into bare repository ... done.\n"
            "fatal: 'refs/heads/evosuit' has a null OID"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/systems" and request.method == "GET":
                return httpx.Response(200, json=[])
            if request.url.path == "/api/v1/systems" and request.method == "POST":
                body = json.loads(request.content)
                created = make_system(body["name"]).model_copy(
                    update={"repos": [RepoSource(**r) for r in body["repos"]]}
                )
                return httpx.Response(201, json=created.model_dump(mode="json"))
            return httpx.Response(400, json={"detail": broken})

        mock_api(httpx.MockTransport(handler))
        result = runner.invoke(app, ["analyze", str(target), "--name", "yas-local"])
        output = plain(result.output)
        assert result.exit_code == 1, output
        assert "git metadata looks damaged" in output
        assert "null OID" in output  # evidence kept
        # The suggestion carries the REAL path, not a placeholder to fill in.
        assert f"git -C {target}" in output
        assert "fsck" in output


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


def _no_sleep(seconds: float) -> None:
    """Collapse the poll interval so these run instantly."""
    return


class TestWaitSurvivesAFlakyLink:
    """A failed poll is not a verdict on the run (§13 CLI honesty).

    Measured on a real 4.5-minute analysis: the connection dropped 64 seconds
    in, and `--wait` ended with "the wadi API is not answering — try: wadi up"
    against a stack that was up and a snapshot that went on to SUCCEED. The
    orchestrator neither saw an error nor restarted; the run finished fine.
    Telling a user their analysis died when it did not is worse than waiting
    longer to be certain.
    """

    @staticmethod
    def _snapshot(status: SnapshotStatus) -> Snapshot:
        return Snapshot(
            id="snap_" + "0" * 16,
            system_id="sys_" + "0" * 16,
            commits={"repo": "a" * 40},
            status=status,
        )

    def test_a_transient_drop_does_not_end_the_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        class Flaky:
            def get_snapshot(self, snapshot_id: str) -> Snapshot:
                calls.append(1)
                if len(calls) < 3:  # two dropped connections, then a reply
                    raise ApiUnreachableError("Server disconnected without sending a response.")
                return TestWaitSurvivesAFlakyLink._snapshot(SnapshotStatus.SUCCEEDED)

        monkeypatch.setattr(cli_main.time, "sleep", _no_sleep)
        final = cli_main.wait_for_snapshot(cast(WadiApiClient, Flaky()), "snap_x")
        assert final.status is SnapshotStatus.SUCCEEDED
        assert len(calls) == 3

    def test_a_timeout_is_retried_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A busy server is slow, not gone — same reasoning, same treatment."""
        calls: list[int] = []

        class Slow:
            def get_snapshot(self, snapshot_id: str) -> Snapshot:
                calls.append(1)
                if len(calls) < 2:
                    raise ApiTimeoutError("http://127.0.0.1:9234", 30.0, "/snapshots/x")
                return TestWaitSurvivesAFlakyLink._snapshot(SnapshotStatus.SUCCEEDED)

        monkeypatch.setattr(cli_main.time, "sleep", _no_sleep)
        final = cli_main.wait_for_snapshot(cast(WadiApiClient, Slow()), "snap_x")
        assert final.status is SnapshotStatus.SUCCEEDED

    def test_a_server_that_stays_gone_still_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tolerance is bounded — a genuinely dead stack must still be said."""

        class Dead:
            def get_snapshot(self, snapshot_id: str) -> Snapshot:
                raise ApiUnreachableError("connection refused")

        clock = iter([0.0] + [float(i) for i in range(1, 500)])
        monkeypatch.setattr(cli_main.time, "sleep", _no_sleep)
        monkeypatch.setattr(cli_main.time, "monotonic", lambda: next(clock))
        with pytest.raises(typer.Exit) as exit_info:
            cli_main.wait_for_snapshot(cast(WadiApiClient, Dead()), "snap_x", grace_seconds=5.0)
        assert exit_info.value.exit_code == cli_main.EXIT_UNREACHABLE

    def test_the_giving_up_message_does_not_claim_the_run_died(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The run may still be going, and the old advice was wrong.

        "the wadi API is not answering / try: wadi up" against a healthy stack
        sends a reader to restart the very thing that is working.
        """

        class Dead:
            def get_snapshot(self, snapshot_id: str) -> Snapshot:
                raise ApiUnreachableError("connection refused")

        clock = iter([0.0] + [float(i) for i in range(1, 500)])
        monkeypatch.setattr(cli_main.time, "sleep", _no_sleep)
        monkeypatch.setattr(cli_main.time, "monotonic", lambda: next(clock))
        with pytest.raises(typer.Exit):
            cli_main.wait_for_snapshot(cast(WadiApiClient, Dead()), "snap_x", grace_seconds=5.0)
        # `problem()` writes to stderr through rich, which wraps: normalise
        # whitespace before asserting on prose.
        printed = " ".join(plain(capsys.readouterr().err).split())
        assert "may still be going" in printed
        assert "wadi status" in printed
        # The old advice restarted the very thing that was working.
        assert "wadi up" not in printed
