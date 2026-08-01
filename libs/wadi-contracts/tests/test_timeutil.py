"""Time policy tests (P9): naive datetimes are rejected everywhere."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from wadi_contracts.base import ArtifactEnvelope
from wadi_contracts.timeutil import ensure_utc, utc_now


class TestUtcNow:
    def test_is_aware_utc(self) -> None:
        now = utc_now()
        assert now.tzinfo is UTC

    def test_millisecond_precision(self) -> None:
        # Default-factory timestamps skip validation, so utc_now() itself
        # must conform to the storage-precision policy.
        assert utc_now().microsecond % 1000 == 0


class TestEnsureUtc:
    def test_rejects_naive(self) -> None:
        with pytest.raises(ValidationError):
            ensure_utc(datetime(2026, 7, 31, 12, 0, 0))  # noqa: DTZ001

    def test_normalizes_offset_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        value = ensure_utc(datetime(2026, 7, 31, 7, 0, 0, tzinfo=eastern))
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)
        assert value.hour == 12

    def test_truncates_to_millisecond_precision(self) -> None:
        # BSON stores milliseconds; the contract truncates so artifacts
        # round-trip through storage with exact equality.
        value = ensure_utc(datetime(2026, 7, 31, 12, 0, 0, 123_456, tzinfo=UTC))
        assert value.microsecond == 123_000


class TestEnvelope:
    def test_rejects_naive_created_at(self) -> None:
        with pytest.raises(ValidationError, match="created_at"):
            ArtifactEnvelope(
                snapshot_id="snap",
                service_id="svc",
                created_at=datetime(2026, 7, 31),  # type: ignore[arg-type]  # noqa: DTZ001
            )

    def test_serializes_created_at_as_utc_iso(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        envelope = ArtifactEnvelope(
            snapshot_id="snap",
            service_id="svc",
            created_at=datetime(2026, 7, 31, 7, 0, 0, tzinfo=eastern),
        )
        dumped = envelope.model_dump(mode="json")
        assert dumped["created_at"] == "2026-07-31T12:00:00+00:00"

    def test_defaults(self) -> None:
        envelope = ArtifactEnvelope(snapshot_id="snap", service_id="svc")
        assert envelope.schema_version
        assert envelope.created_at.tzinfo is not None

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="unexpected_field"):
            ArtifactEnvelope.model_validate(
                {"snapshot_id": "s", "service_id": "svc", "unexpected_field": 1}
            )
