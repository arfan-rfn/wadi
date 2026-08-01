"""Time policy (P9): every timestamp is timezone-aware UTC at millisecond precision.

Models must use :data:`UtcDatetime` for datetime fields — it rejects naive
datetimes at validation time and normalizes any aware datetime to UTC, so a
stored artifact can never carry an ambiguous or local-time value.

Precision is truncated to milliseconds because BSON datetimes are
millisecond-precision: without this rule, an artifact would not round-trip
identically through storage, and equality between in-memory and stored
artifacts would silently break.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime, PlainSerializer, TypeAdapter
from pydantic.functional_validators import AfterValidator


def utc_now() -> datetime:
    """The one sanctioned way to take a timestamp (UTC, millisecond precision).

    Truncates here as well as in validation: default-factory values skip
    validation, so this must produce policy-conforming values directly.
    """
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond - now.microsecond % 1000)


def _to_utc(value: datetime) -> datetime:
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=utc_value.microsecond - utc_value.microsecond % 1000)


def _serialize_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


UtcDatetime = Annotated[
    AwareDatetime,
    AfterValidator(_to_utc),
    PlainSerializer(_serialize_iso, return_type=str, when_used="json"),
]
"""Timezone-aware datetime, normalized to UTC, serialized as ISO-8601."""

_UTC_DATETIME_ADAPTER: TypeAdapter[datetime] = TypeAdapter(UtcDatetime)


def ensure_utc(value: datetime) -> datetime:
    """Validate a bare datetime against the UtcDatetime policy (for non-model code)."""
    return _UTC_DATETIME_ADAPTER.validate_python(value)
