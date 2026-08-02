"""Export-bundle writer: the §14 on-disk layout, built from the NDJSON stream.

The whole stream is consumed and verified against its manifest trailer BEFORE
anything is written — the common failure (a truncated stream) can never leave
a half-written bundle on disk.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SINGLE_FILES: dict[str, str] = {
    "system": "system.json",
    "snapshot": "snapshot.json",
    "coverage_report": "coverage_report.json",
}

ARRAY_FILES: dict[str, str] = {
    "service_boundary": "service_boundaries.json",
    "endpoint": "endpoints.json",
    "remote_call": "remote_calls.json",
    "mq_interaction": "mq_interactions.json",
    "data_model": "data_models.json",
    "stitched_edge": "stitched_edges.json",
}


class ExportStreamError(RuntimeError):
    """The export stream was truncated, inconsistent, or unintelligible."""


def write_bundle(records: Iterator[dict[str, Any]], target: Path) -> dict[str, int]:
    """Consume the export stream, verify the manifest trailer, write the layout.

    Returns the per-kind counts (matching the manifest's authoritative ones).
    """
    singles: dict[str, Any] = {}
    arrays: dict[str, list[Any]] = {kind: [] for kind in ARRAY_FILES}
    icfgs: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    manifest: dict[str, Any] | None = None

    for record in records:
        kind = record.get("kind")
        artifact = record.get("artifact")
        if not isinstance(kind, str) or artifact is None:
            raise ExportStreamError(f"malformed export record: {record!r:.200}")
        if kind == "manifest":
            manifest = artifact
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ARRAY_FILES:
            arrays[kind].append(artifact)
        elif kind == "icfg":
            icfgs.append(artifact)
        elif kind in SINGLE_FILES:
            singles[kind] = artifact
        else:
            # extra="forbid" philosophy: an unknown kind means the server is
            # newer than this CLI — fail loudly, never drop silently.
            raise ExportStreamError(
                f"unknown export record kind {kind!r} — is the CLI older than the server?"
            )

    if manifest is None:
        raise ExportStreamError("stream ended without a manifest — it was truncated (§14)")
    declared = manifest.get("artifact_counts")
    received = dict(sorted(counts.items()))
    if declared != received:
        raise ExportStreamError(
            f"manifest declares {declared} but the stream carried {received} — incomplete export"
        )

    target.mkdir(parents=True, exist_ok=True)
    _write(target / "manifest.json", manifest)
    for kind, filename in SINGLE_FILES.items():
        if kind in singles:
            _write(target / filename, singles[kind])
    for kind, filename in ARRAY_FILES.items():
        _write(target / filename, arrays[kind])
    if icfgs:
        (target / "icfgs").mkdir(exist_ok=True)
        for icfg in icfgs:
            endpoint_id = icfg.get("endpoint_id")
            if not isinstance(endpoint_id, str) or not endpoint_id:
                raise ExportStreamError("icfg record without an endpoint_id")
            _write(target / "icfgs" / f"{endpoint_id}.json", icfg)
    return counts


def _write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")
