"""System / Snapshot / comms / jobs model tests."""

import pytest
from pydantic import ValidationError

from wadi_contracts.comms import MqInteraction, RemoteCall
from wadi_contracts.enums import (
    Confidence,
    JobStatus,
    JobType,
    MqDirection,
    SnapshotStatus,
)
from wadi_contracts.ids import method_id, mq_interaction_id, remote_call_id
from wadi_contracts.jobs import ExtractionJob, JobClaim
from wadi_contracts.source import MethodRef, SourceAnchor
from wadi_contracts.system import RepoSource, Snapshot, System
from wadi_contracts.timeutil import utc_now

SNAP = "snap_" + "0" * 16
SYS = "sys_" + "0" * 16
JOB = "job_" + "0" * 16
SHA = "a" * 40


class TestRepoSource:
    @pytest.mark.parametrize(
        ("source", "is_local"),
        [
            ("https://github.com/acme/shop.git", False),
            ("git@github.com:acme/shop.git", False),
            ("ssh://git@github.com/acme/shop", False),
            ("/Users/dev/shop", True),
            (".", True),
            ("../shop", True),
            ("C:/dev/shop", True),
        ],
    )
    def test_is_local(self, source: str, is_local: bool) -> None:
        assert RepoSource(source=source).is_local is is_local


class TestSystem:
    def test_valid(self) -> None:
        system = System(
            id=SYS,
            name="shop",
            repos=[RepoSource(source="https://github.com/acme/shop.git", branch="main")],
        )
        assert system.repos[0].branch == "main"

    def test_requires_at_least_one_repo(self) -> None:
        with pytest.raises(ValidationError):
            System(id=SYS, name="shop", repos=[])

    def test_rejects_duplicate_repo_sources(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            System(
                id=SYS,
                name="shop",
                repos=[
                    RepoSource(source="https://github.com/acme/shop.git"),
                    RepoSource(source="https://github.com/acme/shop.git"),
                ],
            )

    def test_rejects_bad_id_shape(self) -> None:
        with pytest.raises(ValidationError):
            System(id="not-a-system-id", name="shop", repos=[RepoSource(source=".")])


class TestSnapshot:
    def test_valid(self) -> None:
        snap = Snapshot(
            id=SNAP,
            system_id=SYS,
            commits={"github.com/acme/shop": SHA},
        )
        assert snap.status is SnapshotStatus.PENDING

    def test_rejects_short_sha(self) -> None:
        with pytest.raises(ValidationError, match="SHA"):
            Snapshot(id=SNAP, system_id=SYS, commits={"repo": "abc123"})

    def test_rejects_uppercase_sha(self) -> None:
        with pytest.raises(ValidationError, match="SHA"):
            Snapshot(id=SNAP, system_id=SYS, commits={"repo": "A" * 40})

    def test_rejects_empty_commit_set(self) -> None:
        with pytest.raises(ValidationError):
            Snapshot(id=SNAP, system_id=SYS, commits={})


class TestRemoteCall:
    def _base(self, svc_id: str, url: str | None, confidence: Confidence) -> RemoteCall:
        sig = "com.acme.Client.call()"
        return RemoteCall(
            snapshot_id=SNAP,
            service_id=svc_id,
            id=remote_call_id(svc_id, "src/Client.java", 12, url or "<undetermined>"),
            site=SourceAnchor(file="src/Client.java", start_line=12, end_line=12),
            method=MethodRef(id=method_id(svc_id, sig), signature=sig),
            mechanism="resttemplate",
            url=url,
            url_confidence=confidence,
        )

    def test_resolved_url(self, svc_id: str) -> None:
        call = self._base(svc_id, "http://svc-b:8080/orders/{id}", Confidence.HIGH)
        assert call.url_confidence is Confidence.HIGH

    def test_undetermined_target_is_first_class(self, svc_id: str) -> None:
        call = self._base(svc_id, None, Confidence.NONE)
        assert call.url is None

    def test_url_none_with_confidence_rejected(self, svc_id: str) -> None:
        with pytest.raises(ValidationError, match="NONE"):
            self._base(svc_id, None, Confidence.HIGH)

    def test_url_with_confidence_none_rejected(self, svc_id: str) -> None:
        with pytest.raises(ValidationError, match="confidence above NONE"):
            self._base(svc_id, "http://svc-b/x", Confidence.NONE)


class TestMqInteraction:
    def test_publish(self, svc_id: str) -> None:
        sig = "com.acme.Publisher.send()"
        interaction = MqInteraction(
            snapshot_id=SNAP,
            service_id=svc_id,
            id=mq_interaction_id(svc_id, "src/P.java", 9, "publish", "orders"),
            direction=MqDirection.PUBLISH,
            broker="kafka",
            topic="orders",
            topic_confidence=Confidence.EXACT,
            site=SourceAnchor(file="src/P.java", start_line=9, end_line=9),
            method=MethodRef(id=method_id(svc_id, sig), signature=sig),
        )
        assert interaction.direction is MqDirection.PUBLISH

    def test_undetermined_topic_honesty(self, svc_id: str) -> None:
        sig = "com.acme.Publisher.send()"
        with pytest.raises(ValidationError, match="NONE"):
            MqInteraction(
                snapshot_id=SNAP,
                service_id=svc_id,
                id=mq_interaction_id(svc_id, "src/P.java", 9, "publish", "<undetermined>"),
                direction=MqDirection.PUBLISH,
                broker="kafka",
                topic=None,
                topic_confidence=Confidence.HIGH,
                site=SourceAnchor(file="src/P.java", start_line=9, end_line=9),
                method=MethodRef(id=method_id(svc_id, sig), signature=sig),
            )


class TestExtractionJob:
    def test_lifecycle_shapes(self) -> None:
        job = ExtractionJob(id=JOB, type=JobType.EXTRACT, snapshot_id=SNAP, service_id="svc_x")
        assert job.status is JobStatus.PENDING
        assert job.attempts == 0

    def test_running_requires_claim(self) -> None:
        with pytest.raises(ValidationError, match="claim"):
            ExtractionJob(
                id=JOB,
                type=JobType.EXTRACT,
                snapshot_id=SNAP,
                status=JobStatus.RUNNING,
            )

    def test_failed_requires_error(self) -> None:
        with pytest.raises(ValidationError, match="error"):
            ExtractionJob(
                id=JOB,
                type=JobType.EXTRACT,
                snapshot_id=SNAP,
                status=JobStatus.FAILED,
            )

    def test_claim_lease_ordering(self) -> None:
        now = utc_now()
        with pytest.raises(ValidationError, match="lease_expires_at"):
            JobClaim(
                worker_id="w1",
                claimed_at=now,
                lease_expires_at=now,
                heartbeat_at=now,
            )
