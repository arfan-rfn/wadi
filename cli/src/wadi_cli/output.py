"""Human (Rich table) vs machine (JSON) rendering for read commands (§15)."""

import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)


def print_models(
    models: Sequence[BaseModel],
    *,
    as_json: bool,
    title: str,
    columns: dict[str, str],
) -> None:
    """Render models as a Rich table (human) or a JSON array (machines).

    ``columns`` maps column header -> dotted attribute path.
    """
    if as_json:
        console.print_json(json.dumps([m.model_dump(mode="json") for m in models]))
        return
    table = Table(title=title)
    for header in columns:
        table.add_column(header)
    for model in models:
        table.add_row(*(_render_value(_dig(model, path)) for path in columns.values()))
    console.print(table)


def _dig(model: BaseModel, dotted: str) -> Any:
    value: Any = model
    for part in dotted.split("."):
        value = getattr(value, part)
    return value


def _render_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)  # type: ignore[reportUnknownVariableType]
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())  # type: ignore[reportUnknownVariableType]
    return str(value)


def problem(
    headline: str,
    *,
    detail: str | None = None,
    recover: Sequence[str] = (),
    note: str | None = None,
) -> None:
    """Report a failure the way a colleague would: what, why, what to do next.

    Every CLI error used to be `error_console.print(f"[red]{exc}[/red]")` — the
    raw exception, in red, and nothing else. That reads as an accusation rather
    than help: a wall of git output for a bad path, "is the stack up?" for a
    stack that is up, and never once a next step. A user who hits an error is
    already stuck; the message is the only thing standing between them and
    being unstuck.

    Shape, in order:
      ``headline`` — what failed, in plain words, no exception class names.
      ``detail``   — the underlying reason when there is one worth showing.
                     Indented so it reads as evidence, not as more shouting.
      ``note``     — what is true DESPITE the failure ("the analysis is still
                     running"), which is often the thing that stops a user
                     making it worse by retrying.
      ``recover``  — runnable commands, in the order to try them. A suggestion
                     the user has to translate into a command is half an answer.
    """
    error_console.print(f"[red]✗[/red] {headline}")
    if detail:
        for line in detail.strip().splitlines():
            error_console.print(f"  [dim]{line.strip()}[/dim]")
    if note:
        error_console.print(f"  [yellow]{note}[/yellow]")
    if recover:
        error_console.print("\n  [bold]Try:[/bold]")
        for command in recover:
            # soft_wrap: a suggested command is meant to be COPIED. Rich's
            # default wrapping breaks a long path across lines mid-token, which
            # turns a runnable line into one the user has to reassemble by hand.
            # Let the terminal reflow it instead.
            error_console.print(f"    [cyan]{command}[/cyan]", soft_wrap=True)
