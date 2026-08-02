"""Export-bundle manifest (§14): the completeness trailer of the export stream."""

from pydantic import Field

from wadi_contracts.base import WadiModel
from wadi_contracts.timeutil import UtcDatetime, utc_now
from wadi_contracts.version import SCHEMA_VERSION


class ExportManifest(WadiModel):
    """The last record of the NDJSON export stream, written as ``manifest.json``.

    Streaming it LAST is the integrity mechanism (§14): a consumer that never
    sees the manifest knows the stream was truncated. ``artifact_counts`` is
    authoritative — a reader can verify it received every record.
    ``produced_at`` is the only field allowed to differ between two exports of
    the same snapshot (the determinism rule).
    """

    schema_version: str = SCHEMA_VERSION
    wadi_version: str = Field(
        min_length=1, description="Version of the orchestrator that produced this bundle"
    )
    system_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    produced_at: UtcDatetime = Field(default_factory=utc_now)
    artifact_counts: dict[str, int] = Field(
        default_factory=dict[str, int],
        description="Per-kind record counts, keyed by CONTRACT_MODELS artifact names",
    )
