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
