"""Compose lifecycle backend (§15).

The compose definition is embedded as a package resource with exact image
tags baked at release; it is rendered to the user data dir and driven via
``docker compose`` with the fixed project name ``wadi`` (§13: converging
re-runs, namespaced volumes, no clashes with other stacks).
"""

import importlib.resources
import shutil
import socket
import subprocess
from pathlib import Path

from wadi_cli.client import CLI_VERSION

PROJECT_NAME = "wadi"

# Every optional profile in the embedded compose file. `wadi down` passes them
# all so profile-started containers (e.g. the UI) are torn down too — compose
# ignores inactive profiles on `down`, so this is always safe.
ALL_PROFILES = ["frontend", "mcp-http"]


class ComposeError(RuntimeError):
    """A lifecycle command failed."""


class PortInUseError(ComposeError):
    """A wadi port is already taken; the message names the override variable."""


def data_dir() -> Path:
    return Path.home() / ".local" / "share" / "wadi"


def render_compose_file(name: str = "docker-compose.yml") -> Path:
    """Write an embedded compose definition to the data dir; returns its path."""
    resource = importlib.resources.files("wadi_cli") / "resources" / name
    content = resource.read_text(encoding="utf-8")
    target = data_dir() / f"{CLI_VERSION}-{name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def container_runtime_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "info"], capture_output=True, check=False, timeout=30)
    return probe.returncode == 0


def check_port_free(port: int, override_var: str) -> None:
    """Pre-check a port so failure names the WADI_* override, not a raw bind error."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise PortInUseError(
                f"port {port} is already in use — set {override_var} to use a different port"
            ) from exc


def compose_command(
    action: list[str], compose_files: list[Path], profiles: list[str] | None = None
) -> list[str]:
    file_args = [arg for path in compose_files for arg in ("-f", str(path))]
    # --profile is a global compose flag: it must precede the action verb.
    profile_args = [arg for profile in (profiles or []) for arg in ("--profile", profile)]
    return ["docker", "compose", "-p", PROJECT_NAME, *file_args, *profile_args, *action]


def run_compose(
    action: list[str],
    *,
    expose_db: bool = False,
    profiles: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    import os

    compose_files = [render_compose_file()]
    if expose_db:
        compose_files.append(render_compose_file("docker-compose.expose-db.yml"))
    command = compose_command(action, compose_files, profiles)
    result = subprocess.run(command, env={**os.environ, **(env or {})}, check=False)
    if result.returncode != 0:
        raise ComposeError(f"'{' '.join(command)}' exited with {result.returncode}")
