"""Stitcher pipeline (§5.4).

Phase 1 skeleton: reads every artifact in the snapshot (proving the read
path), performs no matching, writes nothing to Neo4j. Phase 2 replaces the
body of :meth:`StitchPipeline.run` with config resolution, remote-call ↔
endpoint matching with confidence tiers, Neo4j population, and the coverage
report — the module boundary and job wiring stay exactly as they are.
"""

import logging
from dataclasses import dataclass

from wadi_storage import ArtifactRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StitchSummary:
    """What the pipeline saw — returned for logging/testing, not yet stored."""

    snapshot_id: str
    service_count: int
    endpoint_count: int
    remote_call_count: int
    mq_interaction_count: int


class StitchPipeline:
    def __init__(self, artifacts: ArtifactRepository) -> None:
        self._artifacts = artifacts

    async def run(self, snapshot_id: str) -> StitchSummary:
        boundaries = await self._artifacts.list_service_boundaries(snapshot_id)
        endpoint_count = 0
        for boundary in boundaries:
            endpoints = await self._artifacts.list_endpoints(snapshot_id, boundary.service_id)
            endpoint_count += len(endpoints)
        remote_calls = await self._artifacts.list_remote_calls(snapshot_id)
        mq_interactions = await self._artifacts.list_mq_interactions(snapshot_id)
        summary = StitchSummary(
            snapshot_id=snapshot_id,
            service_count=len(boundaries),
            endpoint_count=endpoint_count,
            remote_call_count=len(remote_calls),
            mq_interaction_count=len(mq_interactions),
        )
        logger.info(
            "stitch skeleton over %s: %d services, %d endpoints, %d remote calls, %d MQ",
            snapshot_id,
            summary.service_count,
            summary.endpoint_count,
            summary.remote_call_count,
            summary.mq_interaction_count,
        )
        return summary
