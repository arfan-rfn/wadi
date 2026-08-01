"""The `wadi` command (§15): compose-wrapper + REST client, nothing more.

Exit codes (stable, documented): 0 success · 1 analysis/job failed ·
2 usage error (click's default) · 3 stack/API unreachable.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Annotated

import typer

from wadi_cli import compose
from wadi_cli.client import (
    CLI_VERSION,
    ApiError,
    ApiUnreachableError,
    WadiApiClient,
)
from wadi_cli.output import console, error_console, print_models
from wadi_contracts import RepoSource, Snapshot, SnapshotStatus

EXIT_ANALYSIS_FAILED = 1
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
    error_console.print(f"[red]{exc}[/red]")
    return typer.Exit(EXIT_UNREACHABLE)


def _fail_api(exc: ApiError) -> "typer.Exit":
    error_console.print(f"[red]{exc}[/red]")
    return typer.Exit(EXIT_ANALYSIS_FAILED)


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
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_UNREACHABLE) from exc
    try:
        compose.run_compose(["up", "--detach", "--wait"], expose_db=expose_db)
    except compose.ComposeError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_UNREACHABLE) from exc
    console.print(f"[green]wadi is up[/green] — API at http://127.0.0.1:{api_port}")


@app.command()
def down() -> None:
    """Stop the local wadi stack."""
    try:
        compose.run_compose(["down"])
    except compose.ComposeError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_UNREACHABLE) from exc


@app.command()
def status() -> None:
    """Show stack container status and API health."""
    try:
        compose.run_compose(["ps"])
    except compose.ComposeError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_UNREACHABLE) from exc
    with _api_client() as client:
        try:
            health = client.healthz()
        except ApiUnreachableError:
            error_console.print("[yellow]API not reachable[/yellow]")
            raise typer.Exit(EXIT_UNREACHABLE) from None
        console.print(f"API: [green]{health['status']}[/green] (v{health['version']})")


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
            error_console.print(f"[red]path does not exist: {target}[/red]")
            raise typer.Exit(2)
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
                system = existing
                console.print(f"using existing system [bold]{system.name}[/bold] ({system.id})")
            snapshot = client.analyze(system.id)
        except ApiUnreachableError as exc:
            raise _fail_unreachable(exc) from exc
        except ApiError as exc:
            raise _fail_api(exc) from exc

        console.print(f"snapshot [bold]{snapshot.id}[/bold] started")
        if not wait:
            if output_json:
                console.print_json(snapshot.model_dump_json())
            return

        final = _wait_for_snapshot(client, snapshot.id)
        if output_json:
            console.print_json(final.model_dump_json())
        if final.status is not SnapshotStatus.SUCCEEDED:
            error_console.print(f"[red]analysis {final.status.value}: {final.error}[/red]")
            raise typer.Exit(EXIT_ANALYSIS_FAILED)
        console.print("[green]analysis succeeded[/green]")


def _wait_for_snapshot(
    client: WadiApiClient, snapshot_id: str, poll_seconds: float = 2.0
) -> Snapshot:
    with console.status("analyzing…"):
        while True:
            try:
                snapshot = client.get_snapshot(snapshot_id)
            except ApiUnreachableError as exc:
                raise _fail_unreachable(exc) from exc
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


# --- mcp -----------------------------------------------------------------------


@mcp_app.callback()
def mcp(ctx: typer.Context) -> None:
    """Run the MCP server over stdio (container passthrough, §15)."""
    if ctx.invoked_subcommand is not None:
        return
    command = ["docker", "run", "-i", "--rm", "--network", "wadi_default", MCP_IMAGE]
    raise typer.Exit(subprocess.run(command, check=False).returncode)


@mcp_app.command("install")
def mcp_install() -> None:
    """Print the MCP config snippet for coding agents."""
    snippet = {"mcpServers": {"wadi": {"command": "wadi", "args": ["mcp"]}}}
    console.print_json(json.dumps(snippet))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
