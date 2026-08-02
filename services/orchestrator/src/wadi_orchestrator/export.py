"""Snapshot artifact export (§14): every stored artifact as one NDJSON record.

The stream is deterministic (storage list methods return sorted results) and
ends with the :class:`ExportManifest` trailer carrying authoritative per-kind
counts — a reader that never sees the manifest knows the stream was truncated.
"""

from collections.abc import AsyncIterator

from wadi_contracts import ExportManifest, Snapshot, System
from wadi_orchestrator.state import AppState


def _record(kind: str, artifact_json: str) -> str:
    return '{"kind":"' + kind + '","artifact":' + artifact_json + "}\n"


async def export_stream(
    state: AppState, system: System, snapshot: Snapshot, wadi_version: str
) -> AsyncIterator[str]:
    counts: dict[str, int] = {}

    def emit(kind: str, artifact_json: str) -> str:
        counts[kind] = counts.get(kind, 0) + 1
        return _record(kind, artifact_json)

    yield emit("system", system.model_dump_json())
    yield emit("snapshot", snapshot.model_dump_json())

    boundaries = await state.artifacts.list_service_boundaries(snapshot.id)
    for boundary in boundaries:
        yield emit("service_boundary", boundary.model_dump_json())

    endpoints = await state.artifacts.list_endpoints_for_snapshot(snapshot.id)
    for endpoint in endpoints:
        yield emit("endpoint", endpoint.model_dump_json())
    # ICFGs are the large artifacts — loaded and released one at a time.
    for endpoint in endpoints:
        icfg = await state.artifacts.get_icfg(snapshot.id, endpoint.id)
        if icfg is not None:
            yield emit("icfg", icfg.model_dump_json())

    for call in await state.artifacts.list_remote_calls(snapshot.id):
        yield emit("remote_call", call.model_dump_json())
    for interaction in await state.artifacts.list_mq_interactions(snapshot.id):
        yield emit("mq_interaction", interaction.model_dump_json())
    for boundary in boundaries:
        for model in await state.artifacts.list_data_models(snapshot.id, boundary.service_id):
            yield emit("data_model", model.model_dump_json())
    for edge in await state.stitch.list_stitched_edges(snapshot.id):
        yield emit("stitched_edge", edge.model_dump_json())
    report = await state.stitch.get_coverage_report(snapshot.id)
    if report is not None:
        yield emit("coverage_report", report.model_dump_json())

    manifest = ExportManifest(
        wadi_version=wadi_version,
        system_id=system.id,
        snapshot_id=snapshot.id,
        artifact_counts=dict(sorted(counts.items())),
    )
    yield _record("manifest", manifest.model_dump_json())
