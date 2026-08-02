"""Compose backend unit tests (no docker invocation)."""

import socket
from pathlib import Path

import pytest

from wadi_cli import compose


class TestComposeCommand:
    def test_command_shape(self) -> None:
        command = compose.compose_command(
            ["up", "--detach"], [Path("/data/a.yml"), Path("/data/b.yml")]
        )
        assert command == [
            "docker",
            "compose",
            "-p",
            "wadi",
            "-f",
            "/data/a.yml",
            "-f",
            "/data/b.yml",
            "up",
            "--detach",
        ]

    def test_profiles_precede_the_action_verb(self) -> None:
        command = compose.compose_command(
            ["up", "--detach"], [Path("/data/a.yml")], profiles=["frontend"]
        )
        assert command == [
            "docker",
            "compose",
            "-p",
            "wadi",
            "-f",
            "/data/a.yml",
            "--profile",
            "frontend",
            "up",
            "--detach",
        ]

    def test_all_profiles_match_the_embedded_compose(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ALL_PROFILES must track the profiles declared in the compose file —
        a drifted list would leave profile containers running after `wadi down`."""
        monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
        content = compose.render_compose_file().read_text()
        declared = {
            profile
            for line in content.splitlines()
            if "profiles:" in line
            for profile in line.split("[", 1)[1].rstrip("]").replace('"', "").split(",")
        }
        assert {p.strip() for p in declared} == set(compose.ALL_PROFILES)


class TestRenderComposeFile:
    def test_embedded_definition_rendered(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
        rendered = compose.render_compose_file()
        assert rendered.exists()
        content = rendered.read_text()
        # Invariants of the §13 design must hold in the embedded copy.
        assert "127.0.0.1:${WADI_API_PORT:-9234}:9234" in content
        assert "27017:27017" not in content  # DB ports never published by default

    def test_expose_db_overlay_rendered(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
        rendered = compose.render_compose_file("docker-compose.expose-db.yml")
        content = rendered.read_text()
        assert "9240" in content
        assert content.count("127.0.0.1:") == 3  # loopback-only debug ports

    def test_embedded_copy_matches_infra_source(self) -> None:
        """The CLI's embedded compose must equal the infra source of truth."""
        repo_root = Path(__file__).resolve().parents[2]
        infra = repo_root / "infra" / "docker-compose.yml"
        if not infra.exists():
            pytest.skip("infra compose not present (installed package)")
        embedded = repo_root / "cli" / "src" / "wadi_cli" / "resources" / "docker-compose.yml"
        assert embedded.read_text() == infra.read_text(), (
            "run 'make sync-compose' — cli/src/wadi_cli/resources/docker-compose.yml "
            "is out of date with infra/docker-compose.yml"
        )


class TestPortCheck:
    def test_free_port_passes(self) -> None:
        compose.check_port_free(0, "WADI_API_PORT")  # port 0 = ephemeral, always free

    def test_taken_port_names_override_variable(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.bind(("127.0.0.1", 0))
            taken_port = blocker.getsockname()[1]
            with pytest.raises(compose.PortInUseError, match="WADI_API_PORT"):
                compose.check_port_free(taken_port, "WADI_API_PORT")
