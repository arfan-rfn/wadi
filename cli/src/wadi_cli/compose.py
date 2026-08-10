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

# The compose-created network. `wadi mcp` joins it directly (§13) because the
# MCP server reaches Mongo/Neo4j by service name, like every other component.
NETWORK_NAME = f"{PROJECT_NAME}_default"

# Every optional profile in the embedded compose file. `wadi down` passes them
# all so profile-started containers (e.g. the UI) are torn down too — compose
# ignores inactive profiles on `down`, so this is always safe.
ALL_PROFILES = ["frontend", "mcp-http"]

# Containers wadi starts *outside* compose — today only the `wadi mcp` stdio
# passthrough — carry this label. Compose cannot see them: it tears down only
# containers it created, then fails to remove the network they still hold open
# ("Resource is still in use"), leaving the MCP server attached to a stack whose
# databases are gone. `wadi down` therefore reaps by this label first.
# Faking compose's own labels does not work — `down --remove-orphans` still
# ignores containers compose did not create (verified against compose v5.3.0).
MANAGED_LABEL = "sh.wadi.managed"

# The image namespace owned by a release (§13 release artifacts). Everything
# under it is wadi's to prune; nothing else is ever touched.
IMAGE_NAMESPACE = "ghcr.io/wadi-sh"


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


def _docker(args: list[str], *, timeout: float = 120) -> str:
    """Run a plain `docker` command and return stdout, raising on failure."""
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )
    if result.returncode != 0:
        raise ComposeError(f"'docker {' '.join(args)}' failed: {result.stderr.strip()}")
    return result.stdout


def managed_containers() -> list[str]:
    """Names of wadi-labeled containers that compose does not manage."""
    output = _docker(
        ["ps", "-a", "--filter", f"label={MANAGED_LABEL}=true", "--format", "{{.Names}}"]
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def force_remove_container(name: str) -> None:
    """Best-effort removal of one container by name; a missing one is success."""
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False, timeout=120)


def reap_managed_containers() -> list[str]:
    """Remove every wadi-labeled non-compose container; returns what was removed.

    Called before `compose down` because such a container both survives the
    teardown and holds the network open. Nothing is lost by removing one: it is
    a stdio MCP server whose Mongo and Neo4j are about to disappear.
    """
    names = managed_containers()
    for name in names:
        force_remove_container(name)
    return names


def network_attachments() -> list[tuple[str, str]]:
    """(name, image) of every container still attached to the wadi network.

    Empty when the network is already gone — a torn-down stack is not an error.
    """
    result = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            NETWORK_NAME,
            "--format",
            "{{range .Containers}}{{.Name}}\n{{end}}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        return []
    attachments: list[tuple[str, str]] = []
    for name in (line.strip() for line in result.stdout.splitlines()):
        if not name:
            continue
        inspected = subprocess.run(
            ["docker", "inspect", name, "--format", "{{.Config.Image}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        attachments.append((name, inspected.stdout.strip()))
    return attachments


def finish_network_teardown() -> tuple[list[str], list[str]]:
    """Clear anything still holding the wadi network open; returns (removed, foreign).

    Compose leaves the network behind whenever a container it did not create is
    still attached, and says only "Resource is still in use". The label sweep in
    :func:`reap_managed_containers` covers containers *this* CLI started, but not
    ones left by an older release that predates the label — which is exactly the
    state an upgrading user is in. So after compose has run, anything still
    attached and recognisably wadi's (its own image namespace) is removed too.

    Containers that are **not** wadi's are never touched: they are returned so
    the caller can say whose they are instead of silently killing them.
    """
    removed: list[str] = []
    foreign: list[str] = []
    for name, image in network_attachments():
        if image.startswith(IMAGE_NAMESPACE):
            force_remove_container(name)
            removed.append(name)
        else:
            foreign.append(name)
    if not foreign:
        subprocess.run(
            ["docker", "network", "rm", NETWORK_NAME],
            capture_output=True,
            check=False,
            timeout=120,
        )
    return removed, foreign


def wadi_images(*, exclude_version: str | None = None) -> list[tuple[str, str]]:
    """Wadi-owned images as (reference, size) pairs, newest-listed first.

    Scoped to :data:`IMAGE_NAMESPACE` so pruning can never reach an unrelated
    image. Untagged (`<none>`) leftovers of previous builds are included — they
    are wadi's own, and they are pure waste.
    """
    output = _docker(
        [
            "images",
            "--filter",
            f"reference={IMAGE_NAMESPACE}/*",
            "--format",
            "{{.Repository}}:{{.Tag}}\t{{.Size}}",
        ]
    )
    images: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        reference, _, size = line.partition("\t")
        if exclude_version is not None and reference.endswith(f":{exclude_version}"):
            continue
        images.append((reference, size.strip()))
    return images


def remove_images(references: list[str]) -> tuple[list[str], list[str]]:
    """Remove images by reference; returns (removed, kept).

    Deliberately never passes `--force`: an image still backing a container is
    left alone and reported, rather than yanked out from under a running stack.
    Volumes are never touched here — they hold the analyzed artifacts (Tier 1),
    which no cleanup path may ever remove implicitly.
    """
    removed: list[str] = []
    kept: list[str] = []
    for reference in references:
        result = subprocess.run(
            ["docker", "rmi", reference], capture_output=True, text=True, check=False, timeout=300
        )
        (removed if result.returncode == 0 else kept).append(reference)
    return removed, kept


def stale_compose_files() -> list[Path]:
    """Rendered compose files in the data dir from other CLI versions."""
    directory = data_dir()
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*-docker-compose*.yml")
        if not path.name.startswith(f"{CLI_VERSION}-")
    )


def port_published_by_wadi(port: int) -> bool:
    """Is this port published by a container of OUR compose project?

    Asks docker rather than probing the socket: something else answering on
    9234 is a conflict, and wadi's own orchestrator answering on it is not,
    and nothing observable at the TCP layer separates those two.
    """
    try:
        listing = _docker(
            [
                "ps",
                "--filter",
                f"label=com.docker.compose.project={PROJECT_NAME}",
                "--format",
                "{{.Ports}}",
            ],
            timeout=20,
        )
    except (ComposeError, subprocess.SubprocessError, OSError):
        # No docker, no answer — fall back to treating the port as contested,
        # which is the safe direction: it fails loudly instead of colliding.
        return False
    return f":{port}->" in listing


def check_port_free(port: int, override_var: str) -> None:
    """Pre-check a port so failure names the WADI_* override, not a raw bind error.

    Two things this must NOT call a conflict, both hit in practice:

    * **Our own running stack.** §13 makes re-runs converging, and a bare bind
      test broke that for every command that pre-checks: with the stack up, its
      orchestrator holds the API port, so `wadi up` refused to run at all and
      the only route to changing a flag was `wadi down` first.
    * **A socket a dead client left behind.** A stopped dev server that had
      been talking to the API kept the port unbindable after the listener was
      gone — `lsof` showed ESTABLISHED/CLOSED entries and no LISTEN, while the
      bind still returned EADDRINUSE. ``SO_REUSEADDR`` is the remedy, and it is
      correct here regardless: this socket never accepts a connection, it only
      asks whether a listener could exist.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            if port_published_by_wadi(port):
                return
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
