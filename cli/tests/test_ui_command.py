"""`wadi ui` tests: profile activation, health wait, browser open."""

import webbrowser

import pytest
from support import plain
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli import compose
from wadi_cli.main import app

runner = CliRunner()


@pytest.fixture
def compose_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_run_compose(
        action: list[str],
        *,
        expose_db: bool = False,
        profiles: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        calls.append({"action": action, "profiles": profiles, "expose_db": expose_db})

    def fake_wait(url: str, timeout_seconds: float = 60.0) -> bool:
        return True

    monkeypatch.setattr(compose, "run_compose", fake_run_compose)
    monkeypatch.setattr(compose, "container_runtime_available", lambda: True)
    monkeypatch.setattr(cli_main, "_wait_for_ui", fake_wait)
    return calls


class TestUiCommand:
    def test_starts_frontend_profile_and_opens_browser(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []

        def fake_open(url: str) -> bool:
            opened.append(url)
            return True

        monkeypatch.setattr(webbrowser, "open", fake_open)
        result = runner.invoke(app, ["ui"])
        assert result.exit_code == 0, result.output
        assert compose_calls == [
            {"action": ["up", "--detach", "--wait"], "profiles": ["frontend"], "expose_db": False}
        ]
        assert opened == ["http://127.0.0.1:9235"]
        assert "http://127.0.0.1:9235" in plain(result.output)

    def test_no_open_skips_browser(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []

        def fake_open(url: str) -> bool:
            opened.append(url)
            return True

        monkeypatch.setattr(webbrowser, "open", fake_open)
        result = runner.invoke(app, ["ui", "--no-open"])
        assert result.exit_code == 0
        assert opened == []

    def test_respects_port_override(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WADI_UI_PORT", "9333")
        result = runner.invoke(app, ["ui", "--no-open"])
        assert result.exit_code == 0
        assert "http://127.0.0.1:9333" in plain(result.output)

    def test_no_runtime_exits_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(compose, "container_runtime_available", lambda: False)
        result = runner.invoke(app, ["ui"])
        assert result.exit_code == 3


class TestDownIncludesProfiles:
    def test_down_passes_all_profiles(self, compose_calls: list[dict[str, object]]) -> None:
        result = runner.invoke(app, ["down"])
        assert result.exit_code == 0
        assert compose_calls == [
            {"action": ["down"], "profiles": compose.ALL_PROFILES, "expose_db": False}
        ]
