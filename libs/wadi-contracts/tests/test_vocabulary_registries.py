"""Every registered vocabulary value survives producer -> model -> storage (§7).

The 2026-08-05 incident: `unlabeled-arm` had a fully-tested emitter and a
fully-tested aggregator, and shipped broken because no test crossed the join
between them. Per-code coverage of the whole path is what closes that seam —
a new code cannot be added without this test exercising it.
"""

import json

import pytest

from wadi_contracts.boundary import CfgAnomaly, ServiceBoundary
from wadi_contracts.comms import Reachability, RemoteCall, TokenPropagation
from wadi_contracts.endpoint import (
    EndpointStatus,
    ShapeKind,
    ShapeOrigin,
    StatusOrigin,
    TypeShape,
)
from wadi_contracts.enums import (
    CalleeUnboundReason,
    CfgAnomalyCode,
    ClientLibrary,
    IcfgNodeKind,
    UnresolvedReasonCode,
)
from wadi_contracts.icfg import IcfgNode
from wadi_contracts.source import MethodRef, SourceAnchor
from wadi_contracts.stitching import UnresolvedCallEntry
from wadi_testing.builders import (
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)


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


class TestShapeVocabularies:
    """§5.2.7 T8/T9 vocabularies. `always-null` is the one that matters most:
    it exists ONLY to be distinguishable from `unresolved`, so a serialization
    that collapsed the two would silently undo the distinction it was added for.
    """

    @pytest.mark.parametrize("kind", list(ShapeKind))
    def test_shape_kind_round_trips(self, kind: ShapeKind) -> None:
        shape = TypeShape(kind=kind, type_name="com.acme.Thing")
        restored = TypeShape.model_validate(json.loads(shape.model_dump_json()))
        assert restored.kind is kind

    @pytest.mark.parametrize("origin", list(ShapeOrigin))
    def test_shape_origin_round_trips(self, origin: ShapeOrigin) -> None:
        shape = TypeShape(kind=ShapeKind.OBJECT, origin=origin, type_name="com.acme.Thing")
        restored = TypeShape.model_validate(json.loads(shape.model_dump_json()))
        assert restored.origin is origin

    @pytest.mark.parametrize("origin", list(StatusOrigin))
    def test_status_origin_round_trips(self, origin: StatusOrigin) -> None:
        status = EndpointStatus(code=200, origin=origin, detail="ok(...)", anchor=_anchor())
        restored = EndpointStatus.model_validate(json.loads(status.model_dump_json()))
        assert restored.origin is origin


class TestRemoteCallVocabularies:
    """§5.2.11 T2/T4. Both of these REFINE an older boolean, and both have a
    validator keeping them consistent with it — so a value that cannot survive
    the round trip would surface as a contradiction rather than a wrong answer.
    """

    @pytest.mark.parametrize("reachability", list(Reachability))
    def test_reachability_round_trips(self, reachability: Reachability) -> None:
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot, "services/petstore")
        call = make_remote_call(
            snapshot,
            boundary,
            reachable=reachability is Reachability.ENDPOINT,
            reachability=reachability,
        )
        restored = RemoteCall.model_validate(json.loads(call.model_dump_json()))
        assert restored.reachability is reachability

    @pytest.mark.parametrize("state", list(TokenPropagation))
    def test_token_propagation_round_trips(self, state: TokenPropagation) -> None:
        snapshot = make_snapshot(make_system())
        boundary = make_service(snapshot, "services/petstore")
        call = make_remote_call(snapshot, boundary).model_copy(
            update={
                "auth_propagation_state": state,
                # A named mechanism only ever accompanies `forwarded`; the
                # contract rejects the pair otherwise.
                "auth_propagation": (
                    "authorization-header" if state is TokenPropagation.FORWARDED else None
                ),
            }
        )
        restored = RemoteCall.model_validate(json.loads(call.model_dump_json()))
        assert restored.auth_propagation_state is state


class TestUnboundReasonVocabulary:
    """§5.4.2 T5 / §5.2.11 T7. The export maps these EXPLICITLY rather than by
    value coercion, so a value the contract knows and the worker does not is a
    real drift — this pins the contract half.
    """

    @pytest.mark.parametrize("reason", list(CalleeUnboundReason))
    def test_unbound_reason_round_trips(self, reason: CalleeUnboundReason) -> None:
        node = IcfgNode(
            id="m1:n1",
            kind=IcfgNodeKind.CALL,
            anchor=_anchor(),
            source_text="service.find(id);",
            method=MethodRef(id="m_" + "0" * 16, signature="com.acme.A.b:void()"),
            # A reason without a callee is rejected by the contract: the reason
            # explains why THAT callee has no interior, so it is meaningless
            # without one.
            callee=MethodRef(id="m_" + "1" * 16, signature="com.acme.C.d:void()"),
            callee_unbound_reason=reason,
        )
        restored = IcfgNode.model_validate(json.loads(node.model_dump_json()))
        assert restored.callee_unbound_reason is reason
