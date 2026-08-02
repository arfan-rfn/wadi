"""Model base classes: strictness and the artifact envelope (§7)."""

from pydantic import BaseModel, ConfigDict, Field

from wadi_contracts.timeutil import UtcDatetime, utc_now
from wadi_contracts.version import SCHEMA_VERSION


class WadiModel(BaseModel):
    """Base for every contract model.

    ``extra="forbid"`` — an unknown field is a schema-version mismatch or a
    writer bug; either way it must fail loudly, never be silently dropped.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SnapshotEnvelope(WadiModel):
    """Envelope for snapshot-scoped artifacts with no owning service (P9).

    ``schema_version`` + snapshot key + tz-aware UTC creation time. Most
    artifacts belong to one service and use :class:`ArtifactEnvelope`; a few
    (e.g. the coverage report, §5.4) describe the whole snapshot.
    """

    schema_version: str = SCHEMA_VERSION
    snapshot_id: str
    created_at: UtcDatetime = Field(default_factory=utc_now)


class ArtifactEnvelope(SnapshotEnvelope):
    """Common envelope carried by every per-service stored artifact (P9)."""

    service_id: str
