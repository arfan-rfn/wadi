"""Lifecycle cleanup: MCP container reaping, pruning, and self-upgrade.

These cover the three ways the local stack used to accumulate state a user
could not get rid of: an MCP container that survived `wadi down` and pinned
the network open, images from superseded releases, and no upgrade path at all.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from support import plain
from typer.testing import CliRunner

import wadi_cli.main as cli_main
from wadi_cli import compose
from wadi_cli import upgrade as upgrade_support
from wadi_cli.client import CLI_VERSION
from wadi_cli.main import app

runner = CliRunner()

Images = list[tuple[str, str]]


class FakeCompleted:
    """Stands in for `subprocess.CompletedProcess` in command-shape assertions."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _record_commands(sink: list[list[str]], *, returncode: int = 0) -> Callable[..., FakeCompleted]:
    """A `subprocess.run` replacement that records argv and returns a result."""

    def run(command: list[str], **_kwargs: object) -> FakeCompleted:
        sink.append(command)
        return FakeCompleted(returncode)

    return run


def _no_compose_files() -> list[Path]:
    return []


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
        calls.append({"action": action, "profiles": profiles})

    def runtime_available() -> bool:
        return True

    monkeypatch.setattr(compose, "run_compose", fake_run_compose)
    monkeypatch.setattr(compose, "container_runtime_available", runtime_available)
    return calls


class TestDownReapsManagedContainers:
    def test_reaps_before_compose_down(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Order matters: compose cannot remove the network while an unmanaged
        container is still attached to it."""
        order: list[str] = []

        def fake_reap() -> list[str]:
            order.append("reap")
            return ["wadi-mcp-4242"]

        def fake_run_compose(action: list[str], **_kwargs: object) -> None:
            order.append(f"compose:{' '.join(action)}")

        monkeypatch.setattr(compose, "reap_managed_containers", fake_reap)
        monkeypatch.setattr(compose, "run_compose", fake_run_compose)
        result = runner.invoke(app, ["down"])

        assert result.exit_code == 0, result.output
        assert order == ["reap", "compose:down --remove-orphans"]
        # A killed MCP session is announced, never silent.
        assert "wadi-mcp-4242" in plain(result.output)

    def test_passes_every_profile_and_removes_orphans(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def reap_nothing() -> list[str]:
            return []

        monkeypatch.setattr(compose, "reap_managed_containers", reap_nothing)
        result = runner.invoke(app, ["down"])

        assert result.exit_code == 0, result.output
        assert compose_calls == [
            {"action": ["down", "--remove-orphans"], "profiles": compose.ALL_PROFILES}
        ]

    def test_unlabeled_leftovers_from_an_older_release_are_cleared_too(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The label sweep can't see containers started before the label existed —
        which is exactly the state an upgrading user is in."""

        def reap_nothing() -> list[str]:
            return []

        def stragglers() -> tuple[list[str], list[str]]:
            return ["admiring_panini"], []

        monkeypatch.setattr(compose, "reap_managed_containers", reap_nothing)
        monkeypatch.setattr(compose, "finish_network_teardown", stragglers)
        result = runner.invoke(app, ["down"])

        assert result.exit_code == 0, result.output
        assert "admiring_panini" in plain(result.output)

    def test_a_container_wadi_does_not_own_is_reported_not_killed(
        self, compose_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def reap_nothing() -> list[str]:
            return []

        def foreign_holder() -> tuple[list[str], list[str]]:
            return [], ["someone-elses-debugger"]

        monkeypatch.setattr(compose, "reap_managed_containers", reap_nothing)
        monkeypatch.setattr(compose, "finish_network_teardown", foreign_holder)
        result = runner.invoke(app, ["down"])

        assert result.exit_code == 0, result.output
        assert "someone-elses-debugger" in plain(result.output)


class TestNetworkTeardown:
    def test_removes_wadi_owned_stragglers_and_spares_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        removed: list[str] = []
        issued: list[list[str]] = []

        def attachments() -> list[tuple[str, str]]:
            return [
                ("admiring_panini", f"{compose.IMAGE_NAMESPACE}/mcp:0.5.2"),
                ("someone-elses-tool", "docker.io/library/alpine"),
            ]

        monkeypatch.setattr(compose, "network_attachments", attachments)
        monkeypatch.setattr(compose, "force_remove_container", removed.append)
        monkeypatch.setattr(compose.subprocess, "run", _record_commands(issued))
        stragglers, foreign = compose.finish_network_teardown()

        assert stragglers == ["admiring_panini"]
        assert foreign == ["someone-elses-tool"]
        # A foreign holder means the network stays: removing it would break them.
        assert issued == []

    def test_removes_the_network_once_nothing_wadi_owns_is_left(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        issued: list[list[str]] = []

        def attachments() -> list[tuple[str, str]]:
            return [("wadi-mcp-1", f"{compose.IMAGE_NAMESPACE}/mcp:0.5.2")]

        def remove(name: str) -> None:
            return None

        monkeypatch.setattr(compose, "network_attachments", attachments)
        monkeypatch.setattr(compose, "force_remove_container", remove)
        monkeypatch.setattr(compose.subprocess, "run", _record_commands(issued))
        compose.finish_network_teardown()

        assert issued == [["docker", "network", "rm", compose.NETWORK_NAME]]


class TestMcpContainerIsReapable:
    def test_run_is_named_labeled_and_on_the_compose_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        removed: list[str] = []

        monkeypatch.setattr(cli_main.subprocess, "run", _record_commands(commands))
        monkeypatch.setattr(compose, "force_remove_container", removed.append)
        result = runner.invoke(app, ["mcp"])

        assert result.exit_code == 0, result.output
        (command,) = commands
        assert command[:4] == ["docker", "run", "--rm", "-i"]
        # The label is what makes `wadi down` able to find it at all.
        assert f"{compose.MANAGED_LABEL}=true" in command
        assert compose.NETWORK_NAME in command
        assert command[-1] == f"ghcr.io/wadi-sh/mcp:{CLI_VERSION}"
        # The name it was started under is the name it gets cleaned up by.
        name = command[command.index("--name") + 1]
        assert removed == [name]

    def test_container_is_removed_even_when_docker_run_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`docker run --rm` only self-cleans on a clean container exit; an
        interrupted CLI must not leave the container holding the network."""
        removed: list[str] = []

        def explode(command: list[str], **_kwargs: object) -> FakeCompleted:
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_main.subprocess, "run", explode)
        monkeypatch.setattr(compose, "force_remove_container", removed.append)
        runner.invoke(app, ["mcp"])

        assert len(removed) == 1
        assert removed[0].startswith("wadi-mcp-")


class TestWadiImages:
    def test_excludes_the_kept_version_and_scopes_to_the_namespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[list[str]] = []

        def fake_docker(args: list[str], **_kwargs: object) -> str:
            captured.append(args)
            return (
                "ghcr.io/wadi-sh/joern:0.4.0\t2.43GB\n"
                "ghcr.io/wadi-sh/joern:0.5.2\t2.43GB\n"
                "ghcr.io/wadi-sh/mcp:0.4.0\t277MB\n"
                "\n"
            )

        monkeypatch.setattr(compose, "_docker", fake_docker)
        images = compose.wadi_images(exclude_version="0.5.2")

        assert images == [
            ("ghcr.io/wadi-sh/joern:0.4.0", "2.43GB"),
            ("ghcr.io/wadi-sh/mcp:0.4.0", "277MB"),
        ]
        # Pruning must never be able to reach a non-wadi image.
        assert f"reference={compose.IMAGE_NAMESPACE}/*" in captured[0]

    def test_a_version_that_is_a_prefix_of_another_is_not_confused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keeping `:0.5.2` must not also keep `:0.5.21`."""

        def fake_docker(args: list[str], **_kwargs: object) -> str:
            return "ghcr.io/wadi-sh/mcp:0.5.21\t1MB\nghcr.io/wadi-sh/mcp:0.5.2\t1MB\n"

        monkeypatch.setattr(compose, "_docker", fake_docker)
        assert compose.wadi_images(exclude_version="0.5.2") == [
            ("ghcr.io/wadi-sh/mcp:0.5.21", "1MB")
        ]


class TestStaleComposeFiles:
    def test_only_other_versions_are_stale(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
        (tmp_path / f"{CLI_VERSION}-docker-compose.yml").write_text("current")
        (tmp_path / "0.1.1-docker-compose.yml").write_text("old")
        (tmp_path / "0.1.1-docker-compose.expose-db.yml").write_text("old")
        (tmp_path / "unrelated.yml").write_text("not ours")

        stale = {path.name for path in compose.stale_compose_files()}
        assert stale == {"0.1.1-docker-compose.yml", "0.1.1-docker-compose.expose-db.yml"}


@pytest.fixture
def prunable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A runtime with exactly one superseded image and no stale files."""

    def runtime_available() -> bool:
        return True

    def one_old_image(*, exclude_version: str | None = None) -> Images:
        return [("ghcr.io/wadi-sh/joern:0.4.0", "2.43GB")]

    monkeypatch.setattr(compose, "container_runtime_available", runtime_available)
    monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(compose, "wadi_images", one_old_image)


class TestPruneCommand:
    def test_removes_superseded_images(
        self, prunable: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        removed: list[str] = []

        def fake_remove(references: list[str]) -> tuple[list[str], list[str]]:
            removed.extend(references)
            return references, []

        monkeypatch.setattr(compose, "remove_images", fake_remove)
        result = runner.invoke(app, ["prune", "--yes"])

        assert result.exit_code == 0, result.output
        assert removed == ["ghcr.io/wadi-sh/joern:0.4.0"]

    def test_removal_never_forces_and_never_touches_volumes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The analyzed artifacts are Tier 1 (§6) and live in the `wadi_*`
        volumes: no cleanup path may reach them. And an image backing a running
        container is reported, not ripped out with `--force`."""
        issued: list[list[str]] = []

        monkeypatch.setattr(compose.subprocess, "run", _record_commands(issued, returncode=1))
        removed, kept = compose.remove_images(["ghcr.io/wadi-sh/joern:0.4.0"])

        assert (removed, kept) == ([], ["ghcr.io/wadi-sh/joern:0.4.0"])
        assert issued == [["docker", "rmi", "ghcr.io/wadi-sh/joern:0.4.0"]]
        flattened = " ".join(arg for command in issued for arg in command)
        assert "volume" not in flattened
        assert "--force" not in flattened
        assert " -f " not in f" {flattened} "

    def test_declining_the_prompt_removes_nothing(
        self, prunable: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[list[str]] = []

        def fake_remove(references: list[str]) -> tuple[list[str], list[str]]:
            called.append(references)
            return references, []

        monkeypatch.setattr(compose, "remove_images", fake_remove)
        result = runner.invoke(app, ["prune"], input="n\n")

        assert result.exit_code == 0, result.output
        assert called == []

    def test_reports_images_kept_because_they_are_in_use(
        self, prunable: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def all_in_use(references: list[str]) -> tuple[list[str], list[str]]:
            return [], references

        monkeypatch.setattr(compose, "remove_images", all_in_use)
        result = runner.invoke(app, ["prune", "--yes"])

        assert result.exit_code == 0, result.output
        assert "still in use" in plain(result.output)


class TestVersionComparison:
    @pytest.mark.parametrize(
        ("candidate", "current", "newer"),
        [
            ("0.5.3", "0.5.2", True),
            ("0.6.0", "0.5.2", True),
            ("1.0.0", "0.9.9", True),
            ("0.5.2", "0.5.2", False),
            ("0.5.1", "0.5.2", False),
            # Plain string comparison gets these wrong ("0.5.10" < "0.5.9").
            ("0.5.10", "0.5.9", True),
            ("0.10.0", "0.9.0", True),
        ],
    )
    def test_versions_compare_numerically(self, candidate: str, current: str, newer: bool) -> None:
        assert upgrade_support.is_newer(candidate, current) is newer

    def test_a_prerelease_does_not_beat_its_own_release(self) -> None:
        assert upgrade_support.is_newer("0.5.2rc1", "0.5.2") is False

    def test_unparseable_versions_are_rejected(self) -> None:
        with pytest.raises(upgrade_support.UpgradeError):
            upgrade_support.parse_version("not-a-version")


class TestUpgradeChannelDetection:
    def test_prefers_the_channel_that_actually_installed_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def which(name: str) -> str:
            return f"/usr/bin/{name}"

        def installed_via(probe: list[str], needle: str) -> bool:
            return probe[0] == "pipx"

        monkeypatch.setattr(upgrade_support.shutil, "which", which)
        monkeypatch.setattr(upgrade_support, "installed_via", installed_via)
        assert upgrade_support.upgrade_command() == [
            "pipx",
            "upgrade",
            upgrade_support.PACKAGE_NAME,
        ]

    def test_a_formula_that_merely_ends_in_the_name_is_not_a_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`font-noto-sans-khudawadi` is a real Homebrew package; a substring
        test on the bare name `wadi` would claim wadi was brew-installed."""
        listing = "font-noto-sans-khudawadi\nwandio\nwail\n"

        def fake_run(probe: list[str], **_kwargs: object) -> FakeCompleted:
            result = FakeCompleted()
            result.stdout = listing
            return result

        monkeypatch.setattr(upgrade_support.subprocess, "run", fake_run)
        assert upgrade_support.installed_via(["brew", "list", "--formula"], "wadi") is False

    def test_a_real_listing_entry_is_a_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The `uv tool list` shape seen in practice: name, version, commands."""

        def fake_run(probe: list[str], **_kwargs: object) -> FakeCompleted:
            result = FakeCompleted()
            result.stdout = "wadi-sh v0.5.2\n- wadi\n"
            return result

        monkeypatch.setattr(upgrade_support.subprocess, "run", fake_run)
        assert upgrade_support.installed_via(["uv", "tool", "list"], "wadi-sh") is True

    def test_undetectable_install_returns_none_rather_than_guessing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guessing risks installing a second copy that shadows the real one."""

        def which(name: str) -> str | None:
            return None

        monkeypatch.setattr(upgrade_support.shutil, "which", which)
        assert upgrade_support.upgrade_command() is None


def _release(version: str) -> Callable[..., str]:
    def latest(**_kwargs: object) -> str:
        return version

    return latest


class TestUpgradeCommand:
    def test_up_to_date_still_offers_to_prune(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The common case today: already current, but old images piled up."""
        pruned: list[str] = []

        def runtime_available() -> bool:
            return True

        def one_old_image(*, exclude_version: str | None = None) -> Images:
            return [("ghcr.io/wadi-sh/joern:0.1.1", "2.43GB")]

        def fake_remove(references: list[str]) -> tuple[list[str], list[str]]:
            pruned.extend(references)
            return references, []

        monkeypatch.setattr(upgrade_support, "latest_released_version", _release(CLI_VERSION))
        monkeypatch.setattr(compose, "container_runtime_available", runtime_available)
        monkeypatch.setattr(compose, "wadi_images", one_old_image)
        monkeypatch.setattr(compose, "stale_compose_files", _no_compose_files)
        monkeypatch.setattr(compose, "remove_images", fake_remove)
        result = runner.invoke(app, ["upgrade", "--yes"])

        assert result.exit_code == 0, result.output
        assert "up to date" in plain(result.output)
        assert pruned == ["ghcr.io/wadi-sh/joern:0.1.1"]

    def test_check_reports_without_changing_anything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def must_not_run() -> list[str] | None:
            pytest.fail("--check must not plan an upgrade")

        monkeypatch.setattr(upgrade_support, "latest_released_version", _release("9.9.9"))
        monkeypatch.setattr(upgrade_support, "upgrade_command", must_not_run)
        result = runner.invoke(app, ["upgrade", "--check"])

        assert result.exit_code == 0, result.output
        assert "9.9.9" in plain(result.output)

    def test_upgrade_stops_the_stack_then_prunes_the_version_it_left(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The prune must keep the *new* version, not this process's stale one —
        otherwise it would delete the images `wadi up` is about to need."""
        steps: list[str] = []
        kept: list[str | None] = []

        def channel() -> list[str]:
            return ["uv", "tool", "upgrade"]

        def run_upgrade(command: list[str]) -> None:
            steps.append("upgrade")

        def runtime_available() -> bool:
            return True

        def fake_reap() -> list[str]:
            steps.append("reap")
            return []

        def fake_run_compose(action: list[str], **_kwargs: object) -> None:
            steps.append("down")

        def no_stragglers() -> tuple[list[str], list[str]]:
            return [], []

        def fake_images(*, exclude_version: str | None = None) -> Images:
            kept.append(exclude_version)
            return []

        monkeypatch.setattr(upgrade_support, "latest_released_version", _release("9.9.9"))
        monkeypatch.setattr(upgrade_support, "upgrade_command", channel)
        monkeypatch.setattr(upgrade_support, "run_upgrade", run_upgrade)
        monkeypatch.setattr(compose, "container_runtime_available", runtime_available)
        monkeypatch.setattr(compose, "reap_managed_containers", fake_reap)
        monkeypatch.setattr(compose, "run_compose", fake_run_compose)
        monkeypatch.setattr(compose, "finish_network_teardown", no_stragglers)
        monkeypatch.setattr(compose, "stale_compose_files", _no_compose_files)
        monkeypatch.setattr(compose, "wadi_images", fake_images)
        result = runner.invoke(app, ["upgrade", "--yes"])

        assert result.exit_code == 0, result.output
        assert steps == ["reap", "down", "upgrade"]
        assert kept == ["9.9.9"]

    def test_unknown_channel_tells_the_user_what_to_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_channel() -> list[str] | None:
            return None

        monkeypatch.setattr(upgrade_support, "latest_released_version", _release("9.9.9"))
        monkeypatch.setattr(upgrade_support, "upgrade_command", no_channel)
        result = runner.invoke(app, ["upgrade", "--yes"])

        assert result.exit_code == 3
        assert upgrade_support.PACKAGE_NAME in plain(result.output)
