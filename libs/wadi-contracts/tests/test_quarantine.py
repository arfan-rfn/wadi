"""Quarantine of unrecognized vocabulary at both doors (§7, 2026-08-05).

The incident these tests exist for: a diagnostic footnote about one method
aborted the analysis of twenty services. Strictness stays where it catches
our bugs (enum-typed fields, pyright-checked producers); a value that has
already crossed a boundary we do not control is set aside and named instead.
"""

import json

import pytest

from wadi_contracts.boundary import ServiceBoundary
from wadi_contracts.enums import CfgAnomalyCode, ClientLibrary
from wadi_testing.builders import make_service, make_snapshot, make_system


def _boundary_payload() -> dict[str, object]:
    snapshot = make_snapshot(make_system())
    return json.loads(make_service(snapshot, "services/a").model_dump_json())


class TestWriteDoor:
    """The Scala export: `async-root` kinds cross a language boundary no type
    system spans, so a pack newer than this contract must not abort the run."""

    def test_unknown_async_root_kind_is_quarantined_not_fatal(self) -> None:
        payload = _boundary_payload()
        payload["async_roots"] = [
            {
                "kind": "sqs-listener",
                "method_signature": "com.acme.A.onMessage:void()",
                "anchor": {"file": "src/A.java", "start_line": 4, "end_line": 4},
            }
        ]
        boundary = ServiceBoundary.model_validate(payload)

        assert boundary.async_roots == []
        assert len(boundary.quarantined_facts) == 1
        fact = boundary.quarantined_facts[0]
        assert fact.registry == "async-root"
        assert fact.value == "sqs-listener"
        assert fact.sample_anchor is not None
        assert fact.sample_anchor.start_line == 4

    def test_recognized_kinds_alongside_unknown_are_kept(self) -> None:
        payload = _boundary_payload()
        payload["async_roots"] = [
            {
                "kind": "scheduled",
                "method_signature": "com.acme.A.tick:void()",
                "anchor": {"file": "src/A.java", "start_line": 1, "end_line": 1},
            },
            {
                "kind": "sqs-listener",
                "method_signature": "com.acme.A.onMessage:void()",
                "anchor": {"file": "src/A.java", "start_line": 9, "end_line": 9},
            },
        ]
        boundary = ServiceBoundary.model_validate(payload)

        assert [root.kind for root in boundary.async_roots] == ["scheduled"]
        assert [f.value for f in boundary.quarantined_facts] == ["sqs-listener"]


class TestReadDoor:
    """A stored artifact written by a different build. Snapshots are immutable
    and permanent, so a 1.16 document must stay readable by 1.15 code."""

    def test_unknown_cfg_anomaly_code_does_not_break_the_read(self) -> None:
        payload = _boundary_payload()
        payload["cfg_anomalies"] = [
            {"code": "branch-arity", "count": 2, "sample_sites": []},
            {
                "code": "a-code-from-the-future",
                "count": 1,
                "sample_sites": [{"file": "src/B.java", "start_line": 7, "end_line": 7}],
            },
        ]
        boundary = ServiceBoundary.model_validate(payload)

        assert boundary.cfg_anomalies is not None
        assert [a.code for a in boundary.cfg_anomalies] == [CfgAnomalyCode.BRANCH_ARITY]
        fact = boundary.quarantined_facts[0]
        assert fact.registry == "CfgAnomalyCode"
        assert fact.value == "a-code-from-the-future"
        assert fact.sample_anchor is not None
        assert fact.sample_anchor.file == "src/B.java"

    def test_unknown_client_library_is_quarantined(self) -> None:
        payload = _boundary_payload()
        payload["client_libraries"] = ["resttemplate", "some-future-client"]
        boundary = ServiceBoundary.model_validate(payload)

        assert boundary.client_libraries == [ClientLibrary.RESTTEMPLATE]
        assert [f.value for f in boundary.quarantined_facts] == ["some-future-client"]

    def test_quarantine_carries_the_owning_service(self) -> None:
        payload = _boundary_payload()
        payload["client_libraries"] = ["some-future-client"]
        boundary = ServiceBoundary.model_validate(payload)
        assert boundary.quarantined_facts[0].service_id == boundary.service_id


class TestStrictnessIsPreserved:
    """Quarantine must not become a way for constitutive facts to degrade."""

    def test_none_stays_distinct_from_empty(self) -> None:
        # `cfg_anomalies=None` means never checked; quarantining must not turn
        # that into "checked and clean" (P10, §5.2.8).
        payload = _boundary_payload()
        payload["cfg_anomalies"] = None
        assert ServiceBoundary.model_validate(payload).cfg_anomalies is None

    def test_a_clean_boundary_quarantines_nothing(self) -> None:
        assert ServiceBoundary.model_validate(_boundary_payload()).quarantined_facts == []

    def test_enum_field_still_rejects_unknown_when_built_directly(self) -> None:
        from wadi_contracts.boundary import CfgAnomaly

        with pytest.raises(ValueError, match="a-code-from-the-future"):
            CfgAnomaly.model_validate({"code": "a-code-from-the-future", "count": 1})
