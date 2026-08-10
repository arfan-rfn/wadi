"""The `wadi` command (§15): compose-wrapper + REST client, nothing more.

Exit codes (stable, documented): 0 success · 1 analysis/job failed ·
2 usage error (click's default) · 3 stack/API unreachable.
"""

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from wadi_cli import compose
from wadi_cli import upgrade as upgrade_support
from wadi_cli.client import (
    CLI_VERSION,
    ApiError,
    ApiTimeoutError,
    ApiUnreachableError,
    WadiApiClient,
)
from wadi_cli.export_writer import ExportStreamError, write_bundle
from wadi_cli.output import console, error_console, print_models, problem
from wadi_contracts import RepoSource, Snapshot, SnapshotStatus

EXIT_ANALYSIS_FAILED = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3

MCP_IMAGE = f"ghcr.io/wadi-sh/mcp:{CLI_VERSION}"

app = typer.Typer(
    name="wadi",
    help="Analyze a microservice system and serve its ground-truth architecture.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
mcp_app = typer.Typer(
    help="Run or install the wadi MCP server (stdio).", invoke_without_command=True
)
app.add_typer(mcp_app, name="mcp")

JsonFlag = Annotated[bool, typer.Option("--output-json", "--json", help="Emit JSON")]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"wadi {CLI_VERSION}")
        raise typer.Exit()


@app.callback()
def app_options(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the CLI version and exit.",
        ),
    ] = False,
) -> None:
    pass


def _api_client() -> WadiApiClient:
    base_url = os.environ.get("WADI_API_URL", "http://127.0.0.1:9234")
    token = os.environ.get("WADI_API_TOKEN")
    return WadiApiClient(base_url, token=token)


def _fail_unreachable(exc: ApiUnreachableError) -> "typer.Exit":
    problem(
        "the wadi API is not answering",
        detail=str(exc),
        recover=["wadi up", "wadi status"],
    )
    return typer.Exit(EXIT_UNREACHABLE)


def _fail_timeout(exc: ApiTimeoutError, *, still_running: str | None = None) -> "typer.Exit":
    """A timeout is the CLIENT giving up, not the server failing.

    `still_running` is the command that shows what the server is doing, and it
    is the important half: the request may have succeeded, so a blind retry can
    duplicate work — `analyze` would start a second snapshot alongside the
    first.
    """
    problem(
        f"no response within {exc.seconds:g}s — the request may still be running",
        detail=f"{exc.base_url}{exc.path}",
        note=(
            "The stack is probably fine; this call outlived the client's patience, "
            "not the server's. Check before retrying — a retry may duplicate the work."
        ),
        recover=[still_running] if still_running else ["wadi status"],
    )
    return typer.Exit(EXIT_UNREACHABLE)


def _fail_api(exc: ApiError) -> "typer.Exit":
    """Turn the server's detail into something a reader can act on.

    The raw detail is often a wall of git output. Keep it — it is the evidence
    — but lead with what it MEANS and follow with what to do.
    """
    headline, recover = _read_api_failure(exc)
    problem(headline, detail=exc.detail, recover=recover)
    return typer.Exit(EXIT_ANALYSIS_FAILED)


def _fail_compose(exc: "compose.ComposeError", *, doing: str) -> "typer.Exit":
    """A container-runtime failure, phrased as what the user was trying to do.

    The raw text is `'docker compose ...' failed: <stderr>` — accurate and
    useless on its own. Most of these are one of three things, and all three
    have a first move the user can run.
    """
    detail = str(exc)
    lowered = detail.lower()
    if "cannot connect to the docker daemon" in lowered or "is the docker daemon" in lowered:
        return _compose_problem(
            f"cannot {doing} — Docker is not running",
            detail,
            ["open -a Docker   # or start your container runtime", "docker info"],
        )
    if "port is already allocated" in lowered or "address already in use" in lowered:
        return _compose_problem(
            f"cannot {doing} — a port wadi needs is taken",
            detail,
            ["wadi status", "wadi down", "lsof -i :9234 -i :9235"],
        )
    return _compose_problem(f"cannot {doing}", detail, ["wadi status", "docker ps -a"])


def _compose_problem(headline: str, detail: str, recover: list[str]) -> "typer.Exit":
    problem(headline, detail=detail, recover=recover)
    return typer.Exit(EXIT_UNREACHABLE)


def _read_api_failure(exc: ApiError) -> tuple[str, list[str]]:
    """Known server failures, phrased as the user's problem rather than ours."""
    detail = exc.detail
    if "repository unreachable" in detail:
        source = _source_in(detail)
        where = f" at {source}" if source else ""
        if "has a null OID" in detail or "not a git repository" in detail:
            return (
                f"the repository{where} could not be read — its git metadata looks damaged",
                [
                    f"git -C {source} fsck" if source else "git fsck",
                    "git remote prune origin   # in that checkout",
                    "wadi analyze --repo <url> --name <new-name>   # analyze the remote instead",
                ],
            )
        return (
            f"the repository{where} could not be reached",
            [
                f"git ls-remote {source}" if source else "git ls-remote <url>",
                "wadi analyze --repo <url> --name <new-name>",
            ],
        )
    if exc.status_code == 404:
        return ("that does not exist on this stack", ["wadi systems", "wadi snapshots <system>"])
    return (f"the API rejected the request ({exc.status_code})", [])


def _source_flags(sources: list[str]) -> str:
    """Re-render the sources as the flags that would ask for them again."""
    return " ".join(f"--repo {s}" if "://" in s or s.endswith(".git") else str(s) for s in sources)


def _free_name(client: WadiApiClient, wanted: str) -> str:
    """A name that is actually free, so the suggestion is runnable as printed.

    Suggesting a name that also collides would send the user round the same
    loop — the whole point of this message is to end it.
    """
    for suffix in range(2, 12):
        candidate = f"{wanted}-{suffix}"
        try:
            if client.get_system_by_name(candidate) is None:
                return candidate
        except (ApiError, ApiUnreachableError, ApiTimeoutError):
            return candidate
    return f"{wanted}-new"


def _source_in(detail: str) -> str | None:
    """The path/URL out of a `git clone` failure, for a runnable suggestion."""
    match = re.search(r"git clone --mirror\s+(\S+)", detail)
    return match.group(1) if match else None


def _percent_label(percent: float | None) -> str:
    # None = no ratio exists (0 production methods), distinct from 0% (P10).
    return f"{percent}%" if percent is not None else "n/a"


# --- lifecycle -----------------------------------------------------------------


@app.command()
def up(
    expose_db: Annotated[
        bool,
        typer.Option(
            "--expose-db",
            help="Also publish Mongo/Neo4j on loopback debug ports (9240-9242)",
        ),
    ] = False,
) -> None:
    """Start the local wadi stack (pinned images, project name 'wadi')."""
    if not compose.container_runtime_available():
        error_console.print(
            "[red]No usable container runtime found — install/start Docker Desktop, "
            "Podman, or OrbStack.[/red]"
        )
        raise typer.Exit(EXIT_UNREACHABLE)
    api_port = int(os.environ.get("WADI_API_PORT", "9234"))
    try:
        compose.check_port_free(api_port, "WADI_API_PORT")
    except compose.PortInUseError as exc:
        problem(
            "a port wadi needs is already in use",
            detail=str(exc),
            recover=[
                "wadi status   # is a wadi stack already running?",
                f"WADI_API_PORT={api_port + 10} wadi up   # or move wadi's port",
            ],
        )
        raise typer.Exit(EXIT_UNREACHABLE) from exc
    try:
        compose.run_compose(["up", "--detach", "--wait"], expose_db=expose_db)
    except compose.ComposeError as exc:
        raise _fail_compose(exc, doing="start the stack") from exc
    console.print(f"[green]wadi is up[/green] — API at http://127.0.0.1:{api_port}")


def _tear_down_stack() -> None:
    """Stop everything wadi started and release the network.

    Shared by `wadi down` and `wadi upgrade` — an upgrade that left the old
    stack half-standing would pin the very images it is about to prune.
    """
    # Reap first: a `wadi mcp` container is attached to the compose network but
    # invisible to compose, so leaving it up both strands an MCP server on a
    # stack whose databases are being removed and blocks the network teardown
    # with "Resource is still in use" (§13).
    reaped = compose.reap_managed_containers()
    for name in reaped:
        console.print(f"stopped MCP server [cyan]{name}[/cyan] — its databases are going down")
    compose.run_compose(["down", "--remove-orphans"], profiles=compose.ALL_PROFILES)
    # Second layer: containers left by a release that predates the label — the
    # state an upgrading user is in — still hold the network open.
    stragglers, foreign = compose.finish_network_teardown()
    for name in stragglers:
        console.print(f"removed leftover wadi container [cyan]{name}[/cyan]")
    if foreign:
        error_console.print(
            f"[yellow]{compose.NETWORK_NAME} is still in use by containers wadi does not "
            f"own ({', '.join(foreign)}) — left running, so the network remains.[/yellow]"
        )


@app.command()
def down() -> None:
    """Stop the local wadi stack (including profile services like the UI)."""
    try:
        _tear_down_stack()
    except compose.ComposeError as exc:
        raise _fail_compose(exc, doing="stop the stack") from exc


@app.command()
def ui(
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Don't open the browser automatically")
    ] = False,
) -> None:
    """Start the web UI (compose `frontend` profile) and open it in the browser.

    Converges with a running stack: core services already up are untouched.
    """
    if not compose.container_runtime_available():
        error_console.print(
            "[red]No usable container runtime found — install/start Docker Desktop, "
            "Podman, or OrbStack.[/red]"
        )
        raise typer.Exit(EXIT_UNREACHABLE)
    ui_port = int(os.environ.get("WADI_UI_PORT", "9235"))
    url = f"http://127.0.0.1:{ui_port}"
    try:
        compose.run_compose(["up", "--detach", "--wait"], profiles=["frontend"])
    except compose.ComposeError as exc:
        raise _fail_compose(exc, doing="start the UI") from exc
    if not _wait_for_ui(url):
        error_console.print(
            f"[yellow]the UI container is up but {url} is not answering yet — "
            "give it a few seconds and reload[/yellow]"
        )
    console.print(f"[green]wadi UI is up[/green] — {url}")
    if not no_open:
        import webbrowser

        webbrowser.open(url)


def _wait_for_ui(url: str, timeout_seconds: float = 60.0) -> bool:
    import httpx

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
        except httpx.TransportError:
            time.sleep(1.0)
            continue
        if response.status_code < 500:
            return True
        time.sleep(1.0)
    return False


def _prune_old_versions(*, keep_version: str, assume_yes: bool) -> None:
    """Remove wadi images and rendered compose files from other versions.

    Images and files only — **never volumes**. The analyzed artifacts are Tier 1
    (§6) and live in the `wadi_*` volumes; no cleanup path may discard them as a
    side effect of a version bump.
    """
    try:
        images = compose.wadi_images(exclude_version=keep_version)
    except compose.ComposeError as exc:
        raise _fail_compose(exc, doing="list images") from exc
    files = compose.stale_compose_files()
    if not images and not files:
        console.print(f"nothing to prune — only {keep_version} artifacts are present")
        return

    for reference, size in images:
        console.print(f"  {reference}  [dim]{size}[/dim]")
    for path in files:
        console.print(f"  {path}  [dim]compose file[/dim]")
    if not assume_yes and not typer.confirm(
        f"remove {len(images)} image(s) and {len(files)} file(s)? (volumes are never touched)"
    ):
        console.print("nothing removed")
        return

    removed, kept = compose.remove_images([reference for reference, _ in images])
    for path in files:
        path.unlink(missing_ok=True)
    console.print(f"[green]removed {len(removed)} image(s), {len(files)} file(s)[/green]")
    if kept:
        # Almost always "still used by a running container" — worth saying out
        # loud rather than forcing, so a live stack is never pulled apart.
        console.print(f"[yellow]kept {len(kept)} image(s) still in use: {', '.join(kept)}[/yellow]")


@app.command()
def prune(
    assume_yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Don't ask for confirmation")
    ] = False,
) -> None:
    """Remove images and compose files left behind by older wadi versions.

    Every release publishes a full image set, so upgrades accumulate multi-GB
    copies of images nothing references any more. Analysis data is never
    touched: it lives in the `wadi_*` volumes, which this command does not
    consider.
    """
    if not compose.container_runtime_available():
        error_console.print(
            "[red]No usable container runtime found — install/start Docker Desktop, "
            "Podman, or OrbStack.[/red]"
        )
        raise typer.Exit(EXIT_UNREACHABLE)
    _prune_old_versions(keep_version=CLI_VERSION, assume_yes=assume_yes)


@app.command()
def upgrade(
    check: Annotated[
        bool, typer.Option("--check", help="Only report whether a newer version exists")
    ] = False,
    prune_old: Annotated[
        bool,
        typer.Option("--prune/--no-prune", help="Also remove the old version's images"),
    ] = True,
    assume_yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Don't ask for confirmation")
    ] = False,
) -> None:
    """Upgrade wadi to the latest release and clean up the old version.

    One version spans the release set (§15), so this upgrades the CLI package
    through whichever channel installed it — which brings the new pinned image
    tags — then prunes the images the previous version left behind. Run
    `wadi up` afterwards to pull and start the new stack.
    """
    try:
        latest = upgrade_support.latest_released_version()
    except upgrade_support.UpgradeError as exc:
        problem(
            "could not check for a newer wadi",
            detail=str(exc),
            note="Your installed version keeps working; only the check failed.",
            recover=["wadi --version", "uv tool upgrade wadi-sh --reinstall-package wadi-sh"],
        )
        raise typer.Exit(EXIT_UNREACHABLE) from exc

    if not upgrade_support.is_newer(latest, CLI_VERSION):
        console.print(f"[green]wadi {CLI_VERSION} is up to date[/green]")
        if prune_old and not check:
            _prune_old_versions(keep_version=CLI_VERSION, assume_yes=assume_yes)
        return

    console.print(f"wadi [cyan]{CLI_VERSION}[/cyan] → [green]{latest}[/green] available")
    if check:
        return

    command = upgrade_support.upgrade_command()
    if command is None:
        error_console.print(
            "[yellow]Could not tell how wadi was installed — upgrade it with your "
            f"installer (e.g. `uv tool upgrade {upgrade_support.PACKAGE_NAME}`), "
            "then run `wadi up`.[/yellow]"
        )
        raise typer.Exit(EXIT_UNREACHABLE)

    if not assume_yes and not typer.confirm(f"stop the stack and run `{' '.join(command)}`?"):
        console.print("upgrade cancelled")
        return

    # Stop the old stack before swapping versions: its containers pin the old
    # images (blocking the prune) and would otherwise keep serving artifacts to
    # a CLI that now expects the new contracts. A stack that won't stop is a
    # warning, not a failure — the package upgrade itself is still worth doing.
    if compose.container_runtime_available():
        try:
            _tear_down_stack()
        except compose.ComposeError as exc:
            error_console.print(f"[yellow]could not stop the stack: {exc}[/yellow]")

    try:
        upgrade_support.run_upgrade(command)
    except upgrade_support.UpgradeError as exc:
        problem(
            "the upgrade command failed",
            detail=str(exc),
            note="Old images were left in place, so the version you have still runs.",
            recover=[" ".join(command), "wadi up"],
        )
        raise typer.Exit(EXIT_UNREACHABLE) from exc

    # A zero exit is not evidence. `uv tool upgrade` prints "Nothing to upgrade"
    # and exits 0 when its cached index shows nothing newer, and the old code
    # took that as success — it pruned the images of the version still
    # installed and announced an upgrade that had not happened. Ask the
    # executable what it is now.
    actual = upgrade_support.installed_version()
    if actual is None:
        error_console.print(
            "[yellow]could not confirm the upgrade — `wadi` is not on PATH to ask.[/yellow]\n"
            f"Check with `wadi --version`; it should report {latest}. "
            "Old images were left in place."
        )
        raise typer.Exit(EXIT_UNREACHABLE)
    if upgrade_support.is_newer(latest, actual):
        error_console.print(
            f"[red]the installer reported success but wadi is still {actual}.[/red]\n"
            f"'{' '.join(command)}' exited 0 without installing {latest} — most often a "
            "stale package index right after a release.\n"
            f"Try `{' '.join(command)}` again, or install {latest} explicitly. "
            "Old images were left in place, so the current version still runs."
        )
        raise typer.Exit(EXIT_UNREACHABLE)

    if prune_old and compose.container_runtime_available():
        # Only now: pruning removes the images of every other version, so doing
        # it on an unverified upgrade strands the user on a release whose images
        # were just deleted.
        _prune_old_versions(keep_version=actual, assume_yes=assume_yes)
    console.print(f"[green]upgraded to {actual}[/green] — run `wadi up` to start the new stack")


@app.command()
def status() -> None:
    """Show stack container status (profiles included) and API health."""
    try:
        compose.run_compose(["ps"], profiles=compose.ALL_PROFILES)
    except compose.ComposeError as exc:
        raise _fail_compose(exc, doing="read stack status") from exc
    with _api_client() as client:
        try:
            health = client.healthz()
        except ApiUnreachableError:
            problem(
                "the stack is running but its API is not answering yet",
                note="Containers can be up before the orchestrator finishes starting.",
                recover=["wadi status   # try again in a few seconds", "wadi up"],
            )
            raise typer.Exit(EXIT_UNREACHABLE) from None
        console.print(f"API: [green]{health['status']}[/green] (v{health['version']})")
        _warn_on_version_skew(health["version"])


def _warn_on_version_skew(api_version: str) -> None:
    """Say when the CLI and the running stack are different releases.

    Each CLI renders a compose file pinning *its own* version's images under
    one project name, so two CLIs on a machine quietly fight over one stack:
    whichever ran last recreates every container on its own release. Nothing
    said so. `wadi status` even printed the NEW version's images, because
    `compose ps` reports what the compose file pins rather than what the
    containers are actually running.

    That is how a 0.8.1 stack came to be serving data a 0.8.2 stack had
    written, and 500ing on it — a forward-compatibility break that read to
    everyone involved as a wadi bug. The API's own reported version is the one
    fact here that cannot lie, so it is what this compares against.
    """
    if api_version == CLI_VERSION:
        return
    error_console.print(
        f"[yellow]⚠ this CLI is {CLI_VERSION} but the stack is running {api_version}.[/yellow]"
    )
    error_console.print(
        "  [dim]Each release pins its own images, so `wadi up` from this CLI will "
        "recreate the stack on " + CLI_VERSION + ". Artifacts written by a NEWER "
        "stack may not be readable by an older one.[/dim]"
    )


# --- analyze --------------------------------------------------------------------


@app.command()
def analyze(
    path: Annotated[
        Path | None,
        typer.Argument(help="Local repository path to analyze (default: current directory)"),
    ] = None,
    repo: Annotated[
        list[str] | None,
        typer.Option("--repo", help="Git URL to analyze (repeatable; alternative to PATH)"),
    ] = None,
    name: Annotated[
        str | None, typer.Option(help="System name (default: directory / repo name)")
    ] = None,
    branch: Annotated[str | None, typer.Option(help="Branch for --repo sources")] = None,
    wait: Annotated[bool, typer.Option("--wait", help="Block until the run finishes")] = False,
    output_json: JsonFlag = False,
) -> None:
    """Register a system (or reuse it by name) and start an analysis snapshot."""
    sources: list[RepoSource] = []
    if repo:
        sources = [RepoSource(source=url, branch=branch) for url in repo]
        default_name = repo[0].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    else:
        target = (path or Path.cwd()).resolve()
        if not target.exists():
            problem(
                f"no such path: {target}",
                note="`analyze` takes a LOCAL path; use --repo for a git URL.",
                recover=[
                    f"wadi analyze {Path.cwd()}",
                    "wadi analyze --repo https://github.com/<org>/<repo>.git",
                ],
            )
            raise typer.Exit(EXIT_USAGE)
        sources = [RepoSource(source=str(target), branch=branch)]
        default_name = target.name
    system_name = name or default_name

    with _api_client() as client:
        try:
            existing = client.get_system_by_name(system_name)
            if existing is None:
                system = client.create_system(system_name, sources)
                console.print(f"registered system [bold]{system.name}[/bold] ({system.id})")
            else:
                # Reuse is by NAME, and the name is derived from the source when
                # --name is absent. Silently reusing a system registered from a
                # DIFFERENT source analyzed something the user did not ask for:
                # `--repo <github url>` cloned a local checkout of the same name
                # and failed on it, with nothing in the output saying why.
                registered = [r.source for r in existing.repos]
                asked = [r.source for r in sources]
                if sorted(registered) != sorted(asked):
                    suggestion = _free_name(client, system_name)
                    problem(
                        f"a system named '{system_name}' already exists, "
                        "registered from a different source",
                        detail=(
                            "registered: " + ", ".join(registered) + "\n"
                            "you asked for: " + ", ".join(asked)
                        ),
                        note=(
                            "Reusing it would analyze the registered source, not the one you named."
                        ),
                        recover=[
                            f"wadi analyze {_source_flags(asked)} --name {suggestion}",
                            f"wadi snapshots {system_name}   # what the existing system has",
                        ],
                    )
                    # A usage problem, like "path does not exist": the user
                    # fixes it by changing the invocation, not by retrying.
                    raise typer.Exit(EXIT_USAGE)
                system = existing
                console.print(f"using existing system [bold]{system.name}[/bold] ({system.id})")
            snapshot = client.analyze(system.id)
        except ApiTimeoutError as exc:
            # A retry here starts a SECOND snapshot beside the one already
            # running, so point at the check rather than at the command.
            raise _fail_timeout(exc, still_running=f"wadi snapshots {system_name}") from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc

        console.print(f"snapshot [bold]{snapshot.id}[/bold] started")
        if not wait:
            if output_json:
                console.print_json(snapshot.model_dump_json())
            return

        final = wait_for_snapshot(client, snapshot.id)
        if output_json:
            console.print_json(final.model_dump_json())
        if final.status is not SnapshotStatus.SUCCEEDED:
            # The snapshot exists and holds partial results, so the recovery
            # is to look at it — not to re-run blind.
            problem(
                f"analysis {final.status.value}",
                detail=final.error,
                recover=[
                    f"wadi coverage {final.id}",
                    "docker compose -p wadi logs extraction-worker --tail 50",
                ],
            )
            raise typer.Exit(EXIT_ANALYSIS_FAILED)
        console.print("[green]analysis succeeded[/green]")


"""How long polling tolerates a server it cannot reach before giving up.

A single failed poll is not a verdict on the run. The analysis proceeds in the
orchestrator whether or not this process managed to ask about it, and on a
real 4.5-minute analysis one dropped keep-alive connection 64 seconds in ended
the wait with "the wadi API is not answering — try: wadi up", against a stack
that was up and a snapshot that went on to succeed. Reporting a healthy run as
a failure is worse than waiting a little longer to be sure.
"""
UNREACHABLE_GRACE_SECONDS = 60.0


def wait_for_snapshot(
    client: WadiApiClient,
    snapshot_id: str,
    poll_seconds: float = 2.0,
    grace_seconds: float = UNREACHABLE_GRACE_SECONDS,
) -> Snapshot:
    """Block until the run reaches a terminal state, surviving a flaky link.

    Transport failures and client timeouts are both retried within the grace
    window and reported while it lasts, so a reader sees that contact was lost
    rather than watching a spinner that means two different things. Only a
    server that stays unreachable for the whole window ends the wait, and it
    says the run may still be going — because it may well be.
    """
    lost_contact_at: float | None = None
    with console.status("analyzing…") as status:
        while True:
            try:
                snapshot = client.get_snapshot(snapshot_id)
            except (ApiTimeoutError, ApiUnreachableError) as exc:
                now = time.monotonic()
                if lost_contact_at is None:
                    lost_contact_at = now
                waited = now - lost_contact_at
                if waited >= grace_seconds:
                    problem(
                        "lost contact with the wadi API while the run was in progress",
                        detail=f"{exc} (no response for {waited:.0f}s)",
                        recover=[
                            "wadi status",
                            f"wadi snapshots {snapshot_id}   # the run may still be going",
                        ],
                    )
                    raise typer.Exit(EXIT_UNREACHABLE) from exc
                status.update(f"analyzing… (reconnecting, {waited:.0f}s without a reply)")
                time.sleep(poll_seconds)
                continue
            if lost_contact_at is not None:
                lost_contact_at = None
                status.update("analyzing…")
            if snapshot.status in (SnapshotStatus.SUCCEEDED, SnapshotStatus.FAILED):
                return snapshot
            time.sleep(poll_seconds)


# --- reads ---------------------------------------------------------------------


@app.command()
def systems(output_json: JsonFlag = False) -> None:
    """List registered systems."""
    with _api_client() as client:
        try:
            items = client.list_systems()
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
    print_models(
        items,
        as_json=output_json,
        title="Systems",
        columns={"ID": "id", "Name": "name", "Created": "created_at"},
    )


@app.command()
def snapshots(system_id: str, output_json: JsonFlag = False) -> None:
    """List a system's snapshots (newest first)."""
    with _api_client() as client:
        try:
            items = client.list_snapshots(system_id)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
    print_models(
        items,
        as_json=output_json,
        title="Snapshots",
        columns={"ID": "id", "Status": "status", "Created": "created_at", "Error": "error"},
    )


@app.command()
def services(snapshot_id: str, output_json: JsonFlag = False) -> None:
    """List the services discovered in a snapshot."""
    with _api_client() as client:
        try:
            items = client.list_services(snapshot_id)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
    print_models(
        items,
        as_json=output_json,
        title="Services",
        columns={
            "Service ID": "service_id",
            "Name": "name",
            "Build root": "build_root",
            "Languages": "languages",
            "Build": "build_system",
            "Endpoints": "endpoint_count",
        },
    )


@app.command()
def endpoints(snapshot_id: str, service_id: str, output_json: JsonFlag = False) -> None:
    """List a service's endpoints."""
    with _api_client() as client:
        try:
            items = client.list_endpoints(snapshot_id, service_id)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
    print_models(
        items,
        as_json=output_json,
        title="Endpoints",
        columns={
            "ID": "id",
            "Method": "http_method",
            "URI": "full_uri",
            "Auth": "auth.authenticated",
            "Handler": "handler.signature",
        },
    )


@app.command()
def coverage(snapshot_id: str, output_json: JsonFlag = False) -> None:
    """Show what the stitched map knows it doesn't know (check this first)."""
    with _api_client() as client:
        try:
            report = client.get_coverage(snapshot_id)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
    if output_json:
        console.print_json(report.model_dump_json())
        return
    totals = report.totals
    console.print(
        f"[bold]Coverage for {snapshot_id}[/bold]\n"
        f"  call sites: {totals.call_sites}   edges: {totals.edges}\n"
        f"  analyzed: {totals.analyzed}   external: {totals.external}   "
        f"placeholder: {totals.placeholder}   undetermined: {totals.undetermined}\n"
        f"  by confidence: {totals.by_confidence}"
    )
    if report.analysis_coverage is not None:
        section = report.analysis_coverage
        console.print(
            "\n[bold]Analysis coverage[/bold] (reachable/production methods — low is a "
            "finding, not an error):\n"
            f"  snapshot: {section.reachable_methods}/{section.production_methods} "
            f"({_percent_label(section.coverage_percent)})"
        )
        for service in section.services:
            if service.production_methods is None:
                console.print(f"  - {service.name}: unknown (no coverage fact)")
            else:
                console.print(
                    f"  - {service.name}: {service.reachable_methods}/"
                    f"{service.production_methods} ({_percent_label(service.coverage_percent)})"
                )
    if report.unmodelled_mechanisms:
        console.print(
            "\n[bold yellow]Unmodelled client libraries[/bold yellow] "
            "(present in code, no sink pass models them):"
        )
        for mechanism in report.unmodelled_mechanisms:
            console.print(f"  - {mechanism.mechanism} in {len(mechanism.service_ids)} service(s)")
    if report.cfg_anomalies is not None:
        if report.cfg_anomalies.total_by_code:
            console.print(
                "\n[bold yellow]CFG anomalies[/bold yellow] "
                "(structural invariants violated — §5.2.8; facts, not errors):"
            )
            for code, count in report.cfg_anomalies.total_by_code.items():
                console.print(f"  - {code}: {count}")
            unchecked = [s.name for s in report.cfg_anomalies.services if not s.checked]
            if unchecked:
                console.print(f"  - never checked: {', '.join(unchecked)}")
        else:
            console.print("\n[bold]CFG anomalies[/bold]: none (all invariants hold)")
    if report.placeholders:
        console.print("\n[bold]Placeholder services[/bold] (grant access to analyze them):")
        for placeholder in report.placeholders:
            console.print(
                f"  - {placeholder.name} ({placeholder.resolved_via}, "
                f"{placeholder.call_count} call(s))"
            )
    if report.external_apis:
        console.print("\n[bold]External APIs[/bold]:")
        for external in report.external_apis:
            console.print(f"  - {external.host} ({external.call_count} call(s))")
    if report.unresolved:
        console.print("\n[bold]Unresolved calls[/bold]:")
        for entry in report.unresolved:
            console.print(
                f"  - {entry.site.file}:{entry.site.start_line} [{entry.reason_code}] "
                f"{entry.reason}"
            )
    if report.phonebook_conflicts:
        console.print("\n[bold yellow]Config conflicts[/bold yellow]:")
        for conflict in report.phonebook_conflicts:
            console.print(f"  - {conflict}")


@app.command()
def export(
    snapshot_id: str,
    out_dir: Annotated[
        Path, typer.Option("--dir", help="Target directory for the bundle (created if missing)")
    ],
    force: Annotated[
        bool, typer.Option("--force", help="Write into a non-empty directory")
    ] = False,
    output_json: JsonFlag = False,
) -> None:
    """Write the snapshot's full artifact bundle as schema-valid JSON files (§14)."""
    target = out_dir.expanduser()
    if target.exists() and any(target.iterdir()) and not force:
        raise typer.BadParameter(
            f"{target} is not empty — pass --force to write into it anyway", param_hint="--dir"
        )
    with _api_client() as client:
        try:
            counts = write_bundle(client.iter_export(snapshot_id), target)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
        except ExportStreamError as exc:
            problem(
                "the export did not finish",
                detail=str(exc),
                note="Any files already written are incomplete — re-run rather than use them.",
                recover=[f"wadi coverage {snapshot_id}", "wadi status"],
            )
            raise typer.Exit(EXIT_ANALYSIS_FAILED) from exc
    if output_json:
        console.print_json(
            json.dumps({"snapshot_id": snapshot_id, "dir": str(target), "artifact_counts": counts})
        )
    else:
        console.print(f"exported {sum(counts.values())} artifacts for {snapshot_id} to {target}")
        for kind in sorted(counts):
            console.print(f"  {kind}: {counts[kind]}")


@app.command()
def restitch(
    snapshot_id: str,
    wait: Annotated[bool, typer.Option("--wait", help="Wait for the restitch to finish")] = False,
    output_json: JsonFlag = False,
) -> None:
    """Re-run stitching over a snapshot's stored artifacts (no re-extraction)."""
    with _api_client() as client:
        try:
            snapshot = client.restitch(snapshot_id)
        except ApiTimeoutError as exc:
            raise _fail_timeout(exc) from exc
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc
        if wait:
            snapshot = wait_for_snapshot(client, snapshot_id)
    if output_json:
        console.print_json(snapshot.model_dump_json())
    else:
        console.print(f"snapshot {snapshot_id}: {snapshot.status.value}")
    if snapshot.status is SnapshotStatus.FAILED:
        problem(
            "restitch failed",
            detail=snapshot.error,
            recover=[
                f"wadi coverage {snapshot.id}",
                "docker compose -p wadi logs stitcher --tail 50",
            ],
        )
        raise typer.Exit(EXIT_ANALYSIS_FAILED)


# --- mcp -----------------------------------------------------------------------


@contextmanager
def _unwind_on_termination() -> Generator[None]:
    """Turn SIGTERM/SIGHUP into a normal unwind so `finally` blocks still run.

    Python's default SIGTERM disposition kills the process outright, skipping
    cleanup — which is exactly how MCP containers were being orphaned when an
    agent stopped its server.
    """

    def _unwind(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous: dict[int, object] = {}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            previous[sig] = signal.signal(sig, _unwind)
        except (ValueError, OSError):  # non-main thread, or unsupported platform
            continue
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]


@mcp_app.callback()
def mcp(ctx: typer.Context) -> None:
    """Run the MCP server over stdio (container passthrough, §15)."""
    if ctx.invoked_subcommand is not None:
        return
    # Named and labeled so the container is always reapable. `docker run --rm`
    # cleans up only when the container exits on its own; when this process is
    # killed instead, the container is left attached to the compose network,
    # where it survives `wadi down` and blocks the network from being removed.
    # Three layers cover that: normal exit, the signal unwind below, and
    # `wadi down` reaping by label.
    container = f"wadi-mcp-{os.getpid()}"
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        compose.NETWORK_NAME,
        "--name",
        container,
        "--label",
        f"{compose.MANAGED_LABEL}=true",
        MCP_IMAGE,
    ]
    with _unwind_on_termination():
        try:
            code = subprocess.run(command, check=False).returncode
        finally:
            compose.force_remove_container(container)
    raise typer.Exit(code)


@mcp_app.command("install")
def mcp_install() -> None:
    """Print the MCP config snippet for coding agents."""
    snippet = {"mcpServers": {"wadi": {"command": "wadi", "args": ["mcp"]}}}
    console.print_json(json.dumps(snippet))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
