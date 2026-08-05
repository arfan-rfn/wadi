"""StitchedEdge / CoverageReport tests: kind-honesty, identity, envelope."""

import pytest
from pydantic import ValidationError

from wadi_contracts.boundary import CFG_ANOMALY_CODES, AnalysisCoverage, CfgAnomaly
from wadi_contracts.enums import CfgAnomalyCode, Confidence, Provenance, TargetKind
from wadi_contracts.ids import (
    endpoint_id,
    placeholder_service_id,
    remote_call_id,
    remote_edge_id,
)
from wadi_contracts.registry import CONTRACT_MODELS
from wadi_contracts.source import SourceAnchor
from wadi_contracts.stitching import (
    CoverageReport,
    CoverageTotals,
    PlaceholderEntry,
    ServiceCfgAnomalyEntry,
    ServiceCoverageEntry,
    StitchedEdge,
    UnresolvedCallEntry,
    edge_target_key,
)

SNAPSHOT = "snap_" + "0" * 16


@pytest.fixture
def rc_id(svc_id: str) -> str:
    return remote_call_id(svc_id, "src/A.java", 24, "http://inventory:8081/stock/{?}")


@pytest.fixture
def target_ep_id() -> str:
    return endpoint_id("svc_" + "b" * 16, "GET", "/stock/{id}")


def make_analyzed(svc_id: str, rc_id: str, target_ep_id: str, **overrides: object) -> StitchedEdge:
    kwargs: dict[str, object] = {
        "snapshot_id": SNAPSHOT,
        "service_id": svc_id,
        "remote_call_id": rc_id,
        "mechanism": "resttemplate",
        "target_kind": TargetKind.ANALYZED,
        "target_service_id": "svc_" + "b" * 16,
        "target_endpoint_id": target_ep_id,
        "url": "http://inventory:8081/stock/{?}",
        "confidence": Confidence.EXACT,
        "provenance": Provenance.CONFIG_RESOLVED,
    }
    kwargs.update(overrides)
    return StitchedEdge.create(**kwargs)  # type: ignore[arg-type]


class TestStitchedEdgeCreate:
    def test_analyzed_derives_id(self, svc_id: str, rc_id: str, target_ep_id: str) -> None:
        edge = make_analyzed(svc_id, rc_id, target_ep_id)
        assert edge.id == remote_edge_id(rc_id, target_ep_id)
        assert edge.id.startswith("re_")

    def test_distinct_targets_distinct_ids(
        self, svc_id: str, rc_id: str, target_ep_id: str
    ) -> None:
        analyzed = make_analyzed(svc_id, rc_id, target_ep_id)
        external = StitchedEdge.create(
            snapshot_id=SNAPSHOT,
            service_id=svc_id,
            remote_call_id=rc_id,
            mechanism="resttemplate",
            target_kind=TargetKind.EXTERNAL,
            external_host="api.stripe.com",
            url="https://api.stripe.com/v1/charges",
            confidence=Confidence.EXACT,
            provenance=Provenance.MACHINE_PROVEN,
        )
        assert analyzed.id != external.id

    def test_id_is_stable_across_snapshots(
        self, svc_id: str, rc_id: str, target_ep_id: str
    ) -> None:
        a = make_analyzed(svc_id, rc_id, target_ep_id, snapshot_id="snap_a")
        b = make_analyzed(svc_id, rc_id, target_ep_id, snapshot_id="snap_b")
        assert a.id == b.id

    def test_placeholder_shape(self, svc_id: str, rc_id: str) -> None:
        ph = placeholder_service_id("billing")
        edge = StitchedEdge.create(
            snapshot_id=SNAPSHOT,
            service_id=svc_id,
            remote_call_id=rc_id,
            mechanism="resttemplate",
            target_kind=TargetKind.PLACEHOLDER,
            target_service_id=ph,
            url="http://billing/invoices",
            confidence=Confidence.HEURISTIC,
            provenance=Provenance.HEURISTIC,
        )
        assert edge.target_service_id == ph
        assert edge.id == remote_edge_id(rc_id, f"placeholder:{ph}")

    def test_undetermined_shape(self, svc_id: str, rc_id: str) -> None:
        edge = StitchedEdge.create(
            snapshot_id=SNAPSHOT,
            service_id=svc_id,
            remote_call_id=rc_id,
            mechanism="resttemplate",
            target_kind=TargetKind.UNDETERMINED,
            confidence=Confidence.NONE,
            provenance=Provenance.MACHINE_PROVEN,
            evidence="url recovered from DB row — runtime-only",
        )
        assert edge.url is None
        assert edge.id == remote_edge_id(rc_id, "undetermined")


class TestKindHonesty:
    def test_analyzed_requires_endpoint(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="ANALYZED"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.ANALYZED,
                target_service_id="svc_" + "b" * 16,
                confidence=Confidence.EXACT,
                provenance=Provenance.CONFIG_RESOLVED,
            )

    def test_analyzed_rejects_placeholder_service_id(
        self, svc_id: str, rc_id: str, target_ep_id: str
    ) -> None:
        with pytest.raises(ValidationError, match="svc_"):
            make_analyzed(
                svc_id, rc_id, target_ep_id, target_service_id=placeholder_service_id("x")
            )

    def test_placeholder_rejects_svc_id(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="ph_"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.PLACEHOLDER,
                target_service_id="svc_" + "b" * 16,
                confidence=Confidence.HEURISTIC,
                provenance=Provenance.HEURISTIC,
            )

    def test_external_requires_host(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="external_host"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.EXTERNAL,
                confidence=Confidence.EXACT,
                provenance=Provenance.MACHINE_PROVEN,
            )

    def test_matched_edges_reject_none_confidence(
        self, svc_id: str, rc_id: str, target_ep_id: str
    ) -> None:
        with pytest.raises(ValidationError, match="NONE"):
            make_analyzed(svc_id, rc_id, target_ep_id, confidence=Confidence.NONE)

    def test_undetermined_rejects_target_fields(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="UNDETERMINED"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.UNDETERMINED,
                external_host="api.stripe.com",
                confidence=Confidence.NONE,
                provenance=Provenance.MACHINE_PROVEN,
            )

    def test_undetermined_rejects_matched_confidence(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="confidence NONE"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.UNDETERMINED,
                confidence=Confidence.HEURISTIC,
                provenance=Provenance.HEURISTIC,
            )

    def test_undetermined_rejects_config_provenance(self, svc_id: str, rc_id: str) -> None:
        with pytest.raises(ValidationError, match="provenance"):
            StitchedEdge.create(
                snapshot_id=SNAPSHOT,
                service_id=svc_id,
                remote_call_id=rc_id,
                mechanism="resttemplate",
                target_kind=TargetKind.UNDETERMINED,
                confidence=Confidence.NONE,
                provenance=Provenance.CONFIG_RESOLVED,
            )

    def test_tampered_id_rejected(self, svc_id: str, rc_id: str, target_ep_id: str) -> None:
        edge = make_analyzed(svc_id, rc_id, target_ep_id)
        with pytest.raises(ValidationError, match="derived id"):
            StitchedEdge.model_validate({**edge.model_dump(), "id": "re_" + "f" * 16})


class TestIdDerivations:
    def test_placeholder_id_normalizes_case_and_space(self) -> None:
        assert placeholder_service_id(" Billing ") == placeholder_service_id("billing")

    def test_placeholder_id_prefix(self) -> None:
        assert placeholder_service_id("billing").startswith("ph_")

    def test_remote_edge_id_domain_separated(self) -> None:
        rc = "rc_" + "a" * 16
        assert remote_edge_id(rc, "x") != remote_edge_id(rc, "y")

    def test_edge_target_key_shapes(self) -> None:
        assert (
            edge_target_key(
                target_kind=TargetKind.EXTERNAL,
                target_endpoint_id=None,
                target_service_id=None,
                external_host="api.stripe.com:443",
            )
            == "external:api.stripe.com:443"
        )
        assert (
            edge_target_key(
                target_kind=TargetKind.UNDETERMINED,
                target_endpoint_id=None,
                target_service_id=None,
                external_host=None,
            )
            == "undetermined"
        )


class TestCoverageReport:
    def test_snapshot_envelope_has_no_service_id(self) -> None:
        report = CoverageReport(
            snapshot_id=SNAPSHOT,
            totals=CoverageTotals(
                call_sites=3, edges=3, analyzed=1, external=1, placeholder=0, undetermined=1
            ),
        )
        assert "service_id" not in report.model_dump()
        assert report.applied_hint_ids == []
        assert report.stale_hint_ids == []

    def test_unresolved_entry_requires_reason(self, svc_id: str) -> None:
        with pytest.raises(ValidationError):
            UnresolvedCallEntry(
                remote_call_id="rc_" + "a" * 16,
                service_id=svc_id,
                site=SourceAnchor(file="src/A.java", start_line=1, end_line=1),
                reason_code="",
                reason="",
            )

    def test_placeholder_entry_requires_callers(self) -> None:
        with pytest.raises(ValidationError):
            PlaceholderEntry(
                placeholder_id=placeholder_service_id("billing"),
                name="billing",
                resolved_via="bare-hostname",
                call_count=1,
                caller_service_ids=[],
            )


class TestRegistryExports:
    def test_new_models_registered(self) -> None:
        assert CONTRACT_MODELS["stitched_edge"] is StitchedEdge
        assert CONTRACT_MODELS["coverage_report"] is CoverageReport
        assert "remote_edges_view" in CONTRACT_MODELS


class TestAnalysisCoverage:
    """§5.4.3 invariants: the numerator is a subset of the denominator, and
    unknown is structurally distinct from zero."""

    def test_reachable_cannot_exceed_production(self) -> None:
        with pytest.raises(ValidationError, match="exceeds"):
            AnalysisCoverage(production_methods=3, reachable_methods=4)

    def test_entry_counts_travel_together(self) -> None:
        with pytest.raises(ValidationError, match="both be set or unset"):
            ServiceCoverageEntry(service_id="svc_x", name="x", production_methods=3)

    def test_entry_percent_requires_counts(self) -> None:
        with pytest.raises(ValidationError, match="unknown is never a percentage"):
            ServiceCoverageEntry(service_id="svc_x", name="x", coverage_percent=50.0)

    def test_unknown_entry_is_valid(self) -> None:
        entry = ServiceCoverageEntry(service_id="svc_x", name="x")
        assert entry.production_methods is None
        assert entry.coverage_percent is None


class TestCfgAnomalies:
    """§5.2.8 M2: registered codes only; unchecked is never conflated with clean."""

    def test_registered_code_accepted(self) -> None:
        anomaly = CfgAnomaly(code=CfgAnomalyCode.LOOP_NO_BACK_EDGE, count=2)
        assert anomaly.code in CFG_ANOMALY_CODES

    def test_unregistered_code_rejected(self) -> None:
        # The write path is enum-typed, so pyright rejects an unregistered code
        # before it can run (§7, recorded 2026-08-05). This asserts the runtime
        # half — the same rejection for untyped input arriving as a raw mapping.
        with pytest.raises(ValidationError):
            CfgAnomaly.model_validate({"code": "made-up-code", "count": 1})

    def test_sample_sites_capped_at_five(self) -> None:
        anchor = SourceAnchor(file="src/A.java", start_line=1, end_line=1)
        with pytest.raises(ValidationError, match="at most 5"):
            CfgAnomaly(code=CfgAnomalyCode.BRANCH_ARITY, count=6, sample_sites=[anchor] * 6)

    def test_unchecked_service_cannot_carry_anomalies(self) -> None:
        with pytest.raises(ValidationError, match="unchecked service"):
            ServiceCfgAnomalyEntry(
                service_id="svc_x",
                name="x",
                checked=False,
                anomalies=[CfgAnomaly(code=CfgAnomalyCode.BRANCH_ARITY, count=1)],
            )

    def test_checked_and_clean_is_valid(self) -> None:
        entry = ServiceCfgAnomalyEntry(service_id="svc_x", name="x", checked=True)
        assert entry.anomalies == []


class TestReasonCodeFamily:
    """1.5.0: base-undetermined + the unsupported-idiom:<name> prefix family."""

    def test_base_undetermined_registered(self) -> None:
        entry = UnresolvedCallEntry(
            remote_call_id="rc_" + "a" * 16,
            service_id="svc_" + "a" * 16,
            site=SourceAnchor(file="src/A.java", start_line=1, end_line=1),
            reason_code="base-undetermined",
            reason="relative URL, base not recoverable",
        )
        assert entry.reason_code == "base-undetermined"

    def test_idiom_family_accepts_named_slugs(self) -> None:
        entry = UnresolvedCallEntry(
            remote_call_id="rc_" + "a" * 16,
            service_id="svc_" + "a" * 16,
            site=SourceAnchor(file="src/A.java", start_line=1, end_line=1),
            reason_code="unsupported-idiom:getenv",
            reason="named unmodelled construct",
        )
        assert entry.reason_code == "unsupported-idiom:getenv"

    def test_idiom_family_rejects_empty_slug(self) -> None:
        with pytest.raises(ValidationError, match="unregistered"):
            UnresolvedCallEntry(
                remote_call_id="rc_" + "a" * 16,
                service_id="svc_" + "a" * 16,
                site=SourceAnchor(file="src/A.java", start_line=1, end_line=1),
                reason_code="unsupported-idiom:",
                reason="empty slug is not a name",
            )
