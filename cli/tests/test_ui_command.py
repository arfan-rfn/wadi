"""`wadi ui` tests: profile activation, health wait, browser open."""

import webbrowser

import pytest
from support import plain
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli import compose
from wadi_cli.main import app

runner = CliRunner()


def _no_stragglers() -> tuple[list[str], list[str]]:
    """`wadi down`'s third teardown step shells out to docker; stub it like the
    other two so this stays a unit test (see cli/tests/conftest.py)."""
    return ([], [])


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
    def test_down_passes_all_profiles(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reaping shells out to docker; stub it so this stays a unit test.
        monkeypatch.setattr(compose, "reap_managed_containers", list)
        monkeypatch.setattr(compose, "finish_network_teardown", _no_stragglers)
        result = runner.invoke(app, ["down"])
        assert result.exit_code == 0
        assert compose_calls == [
            {
                "action": ["down", "--remove-orphans"],
                "profiles": compose.ALL_PROFILES,
                "expose_db": False,
            }
        ]


class TestVersionSkewIsVisible:
    """Two CLIs on one machine quietly fight over one stack.

    Each release renders a compose file pinning ITS OWN images under the same
    project name, so whichever CLI ran last recreates every container on its
    own version — silently. `wadi status` made it worse by printing the images
    the compose file pins rather than the ones the containers run, so a stack
    on 0.8.1 reported 0.8.2.

    What that cost: a 0.8.2 stack wrote artifacts at schema 1.25.0, a 0.8.1 CLI
    recreated the stack on 0.8.1 images, and the older orchestrator 500'd on
    its own data — `ref` is not one of its shape kinds and `type_defs` is not
    one of its fields. It read as a wadi bug from every angle.

    The API's reported version is the one fact here that cannot lie.
    """

    def test_a_mismatch_is_called_out_with_its_consequence(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli_main.warn_on_version_skew("0.8.1")
        printed = " ".join(plain(capsys.readouterr().err).split())
        assert cli_main.CLI_VERSION in printed
        assert "0.8.1" in printed
        # Not just "they differ" — what it will DO, and what it risks.
        assert "recreate the stack" in printed
        assert "may not be readable" in printed

    def test_a_matching_stack_says_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli_main.warn_on_version_skew(cli_main.CLI_VERSION)
        assert plain(capsys.readouterr().err).strip() == ""
