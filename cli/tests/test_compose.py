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


class TestJoernServiceDefinition:
    """Guards on the wadi-joern service — both invariants here were live bugs."""

    def _joern_block(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
        monkeypatch.setattr(compose, "data_dir", lambda: tmp_path)
        content = compose.render_compose_file().read_text()
        start = content.index("  wadi-joern:")
        return content[start : content.index("\n  orchestrator:", start)]

    def test_healthcheck_never_submits_a_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """POST /query is a REPL *evaluation*: it permanently binds a `resN` val
        and its compiled wrapper class in the shared interpreter. As a probe
        running every 10s it leaked ~0.9MiB a shot, exhausted the heap within
        hours, and killed the server mid-analysis. A probe must only read.
        """
        block = self._joern_block(monkeypatch, tmp_path)
        # The probe command itself, not the prose around it.
        (probe,) = [line for line in block.splitlines() if line.strip().startswith("test:")]
        assert "/query" not in probe
        assert "/result/" in probe

    def test_heap_is_sized_against_the_container_limit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Without this the JVM takes its ergonomic default — 25% of mem_limit,
        1.5g of 6g — which is far too little for a multi-service CPG."""
        block = self._joern_block(monkeypatch, tmp_path)
        assert "MaxRAMPercentage" in block


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
