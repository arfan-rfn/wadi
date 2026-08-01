"""Extraction jobs — the Mongo-backed queue contract (§3, §7).

Claims are lease-based with heartbeat: an expired lease requeues the job, so a
worker crash mid-extraction never strands it.
"""

from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import WadiModel
from wadi_contracts.enums import JobStatus, JobType
from wadi_contracts.timeutil import UtcDatetime, utc_now
from wadi_contracts.version import SCHEMA_VERSION


class JobClaim(WadiModel):
    worker_id: str = Field(min_length=1)
    claimed_at: UtcDatetime
    lease_expires_at: UtcDatetime
    heartbeat_at: UtcDatetime

    @model_validator(mode="after")
    def _lease_after_claim(self) -> Self:
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("lease_expires_at must be after claimed_at")
        return self


class ExtractionJob(WadiModel):
    schema_version: str = SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^job_[0-9a-f]{16,32}$")
    type: JobType
    snapshot_id: str = Field(min_length=1)
    service_id: str | None = Field(
        default=None, description="Set for extract jobs; None for fetch/stitch"
    )
    status: JobStatus = JobStatus.PENDING
    claim: JobClaim | None = None
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    error: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _status_claim_consistency(self) -> Self:
        if self.status is JobStatus.RUNNING and self.claim is None:
            raise ValueError("a running job must carry a claim")
        if self.status is JobStatus.FAILED and self.error is None:
            raise ValueError("a failed job must carry an error message")
        return self
