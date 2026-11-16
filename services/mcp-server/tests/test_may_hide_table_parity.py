"""The two copies of the may-hide-project-code table agree (pre-landing review, adversarial #3).

MCP `endpoint_detail` and the frontend's Data list each decide which
unopenable calls may hide a repository call, from a table keyed by
`CalleeUnboundReason`. Each side is checked total over the enum by its own
type system; nothing else made them agree, so one edited entry would give the
two surfaces different caveats for one endpoint (C5). This reads the
TypeScript table as text, because the frontend is not importable here.
"""

import re
from pathlib import Path

from wadi_mcp.service import MAY_HIDE_PROJECT_CODE

_TS = Path(__file__).resolve().parents[3] / "frontend" / "lib" / "wadi" / "entity-access.ts"
_TABLE = re.compile(r"const MAY_HIDE_PROJECT_CODE = \{(?P<body>.*?)\} as const", re.DOTALL)
_ENTRY = re.compile(r'"(?P<reason>[a-z-]+)":\s*(?P<hides>true|false)')


def _typescript_table() -> dict[str, bool]:
    match = _TABLE.search(_TS.read_text())
    assert match is not None, f"MAY_HIDE_PROJECT_CODE not found in {_TS}"
    return {m["reason"]: m["hides"] == "true" for m in _ENTRY.finditer(match["body"])}


def test_the_frontend_and_mcp_tables_agree_entry_for_entry() -> None:
    python = {reason.value: hides for reason, hides in MAY_HIDE_PROJECT_CODE.items()}
    assert _typescript_table() == python
