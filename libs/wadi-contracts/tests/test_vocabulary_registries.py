"""Every registered vocabulary value survives producer -> model -> storage (§7).

The 2026-08-05 incident: `unlabeled-arm` had a fully-tested emitter and a
fully-tested aggregator, and shipped broken because no test crossed the join
between them. Per-code coverage of the whole path is what closes that seam —
a new code cannot be added without this test exercising it.
"""

import json

import pytest

from wadi_contracts.boundary import CfgAnomaly, ServiceBoundary
from wadi_contracts.enums import CfgAnomalyCode, ClientLibrary, UnresolvedReasonCode
from wadi_contracts.source import SourceAnchor
from wadi_contracts.stitching import UnresolvedCallEntry
from wadi_testing.builders import make_service, make_snapshot, make_system


def _anchor() -> SourceAnchor:
    return SourceAnchor(file="src/main/java/A.java", start_line=1, end_line=1)


class TestCfgAnomalyCodes:
    @pytest.mark.parametrize("code", list(CfgAnomalyCode))
    def test_code_round_trips_through_model_and_json(self, code: CfgAnomalyCode) -> None:
        anomaly = CfgAnomaly(code=code, count=1, sample_sites=[_anchor()])
        restored = CfgAnomaly.model_validate(json.loads(anomaly.model_dump_json()))
        assert restored.code is code

    @pytest.mark.parametrize("code", list(CfgAnomalyCode))
    def test_code_survives_the_owning_artifact(self, code: CfgAnomalyCode) -> None:
        # The join the incident slipped through: an anomaly is only ever stored
        # as part of a ServiceBoundary, so per-code coverage has to reach here.
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot, "services/a").model_copy(
            update={"cfg_anomalies": [CfgAnomaly(code=code, count=1)]}
        )
        restored = ServiceBoundary.model_validate(json.loads(boundary.model_dump_json()))
        assert restored.cfg_anomalies is not None
        assert restored.cfg_anomalies[0].code is code


class TestClientLibraries:
    @pytest.mark.parametrize("library", list(ClientLibrary))
    def test_library_survives_the_owning_artifact(self, library: ClientLibrary) -> None:
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot, "services/a").model_copy(
            update={"client_libraries": [library]}
        )
        restored = ServiceBoundary.model_validate(json.loads(boundary.model_dump_json()))
        assert restored.client_libraries == [library]


class TestUnresolvedReasonCodes:
    @pytest.mark.parametrize("code", list(UnresolvedReasonCode))
    def test_code_round_trips(self, code: UnresolvedReasonCode) -> None:
        entry = UnresolvedCallEntry(
            remote_call_id="rc_" + "0" * 16,
            service_id="svc_" + "0" * 16,
            site=_anchor(),
            reason_code=code.value,
            reason="probe",
        )
        restored = UnresolvedCallEntry.model_validate(json.loads(entry.model_dump_json()))
        assert restored.reason_code == code.value

    def test_unsupported_idiom_family_is_accepted(self) -> None:
        # The one dynamic member of this vocabulary (§5.4.2): a NAMED unmodelled
        # construct. Enumerating it is impossible, so it is validated by prefix.
        entry = UnresolvedCallEntry(
            remote_call_id="rc_" + "0" * 16,
            service_id="svc_" + "0" * 16,
            site=_anchor(),
            reason_code="unsupported-idiom:webclient-builder-chain",
            reason="probe",
        )
        assert entry.reason_code.startswith("unsupported-idiom:")

    def test_bare_prefix_without_a_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unregistered reason_code"):
            UnresolvedCallEntry(
                remote_call_id="rc_" + "0" * 16,
                service_id="svc_" + "0" * 16,
                site=_anchor(),
                reason_code="unsupported-idiom:",
                reason="probe",
            )
