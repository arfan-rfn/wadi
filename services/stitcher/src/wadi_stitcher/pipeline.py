"""Stitcher pipeline (§5.4): config resolution → matching → truth → derived view.

Phases of one run, in a deliberate order:

1. LOAD       all Tier-1 artifacts of the snapshot (the stitcher never touches
              Joern or source — P2; it meets the worker only at MongoDB — P1).
2. PHONEBOOK  config resolution over every service's NetworkIdentity (§5.4.1).
3. MATCH      every RemoteCall fact through the matcher registry — at least
              one edge per fact, undetermined included (P10).
4. TRUTH      stitched edges land in Mongo first (Tier 1, §6) —
5. COVERAGE   then the coverage report —
6. DERIVED    and Neo4j last, as the rebuildable view. If the graph write
              fails, retry re-runs everything and converges (delete+rewrite
              everywhere); Tier 1 is never behind Tier 2.

A crash anywhere fails the stitch job → the snapshot fails (recorded
decision: an empty graph served as truth is worse than an absent one, §12).
Recovery is cheap: auto-retry, or an explicit restitch over the same stored
artifacts — never re-extraction.
"""

import logging
from dataclasses import dataclass

from wadi_contracts import Endpoint, StitchedEdge, UnresolvedCallEntry
from wadi_stitcher.coverage import (
    build_analysis_coverage,
    build_coverage_report,
    build_unmodelled_mechanisms,
)
from wadi_stitcher.matching import HintProvider, MatchContext, NullHintProvider, match_call
from wadi_stitcher.matching.base import MechanismMatcher
from wadi_stitcher.matching.http import HttpMatcher
from wadi_stitcher.phonebook import PhoneBook
from wadi_storage import ArtifactRepository, GraphRepository, StitchRepository

logger = logging.getLogger(__name__)

MATCHERS: tuple[MechanismMatcher, ...] = (HttpMatcher(),)
"""Ordered registry — mechanism-specific matchers (gRPC, §10) slot in ahead
of the catch-all HTTP matcher."""


@dataclass(frozen=True)
class StitchSummary:
    """What one stitch run produced — returned for logging/testing."""

    snapshot_id: str
    service_count: int
    endpoint_count: int
    remote_call_count: int
    mq_interaction_count: int
    edge_count: int
    analyzed: int
    external: int
    placeholder: int
    undetermined: int


class StitchPipeline:
    def __init__(
        self,
        artifacts: ArtifactRepository,
        stitch: StitchRepository,
        graph: GraphRepository,
        hints: HintProvider | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._stitch = stitch
        self._graph = graph
        self._hints: HintProvider = hints if hints is not None else NullHintProvider()

    async def run(self, snapshot_id: str) -> StitchSummary:
        # 1. LOAD
        boundaries = await self._artifacts.list_service_boundaries(snapshot_id)
        endpoints = await self._artifacts.list_endpoints_for_snapshot(snapshot_id)
        remote_calls = await self._artifacts.list_remote_calls(snapshot_id)
        mq_interactions = await self._artifacts.list_mq_interactions(snapshot_id)

        # 2. PHONEBOOK
        phonebook = PhoneBook.build(boundaries)
        endpoints_by_service: dict[str, list[Endpoint]] = {}
        for endpoint in endpoints:
            endpoints_by_service.setdefault(endpoint.service_id, []).append(endpoint)
        context = MatchContext(
            snapshot_id=snapshot_id,
            phonebook=phonebook,
            endpoints_by_service=endpoints_by_service,
            boundaries_by_service={b.service_id: b for b in boundaries},
        )

        # 3. MATCH — deterministic order: calls sorted by id. Unreachable and
        # suspected call facts are inventory, not map edges (§5.2.5): excluded
        # from matching, counted in the coverage report.
        stitchable = [c for c in remote_calls if c.reachable and not c.suspected]
        edges: list[StitchedEdge] = []
        unresolved: list[UnresolvedCallEntry] = []
        placeholder_names: dict[str, tuple[str, str]] = {}
        for call in sorted(stitchable, key=lambda c: c.id):
            outcome = match_call(call, context, MATCHERS, self._hints)
            edges.extend(outcome.edges)
            unresolved.extend(outcome.unresolved)
            placeholder_names.update(outcome.placeholder_names)
        edges.sort(key=lambda e: e.id)

        # 4. TRUTH (Tier 1 first)
        await self._stitch.replace_stitched_edges(snapshot_id, edges)

        # 5. COVERAGE
        report = build_coverage_report(
            snapshot_id,
            remote_calls=remote_calls,
            edges=edges,
            unresolved=unresolved,
            phonebook_conflicts=phonebook.conflicts,
            placeholder_names=placeholder_names,
            unmodelled_mechanisms=build_unmodelled_mechanisms(boundaries),
            analysis_coverage=build_analysis_coverage(boundaries),
        )
        await self._stitch.write_coverage_report(report)

        # 6. DERIVED (Tier 2 last)
        await self._graph.replace_snapshot(
            snapshot_id,
            boundaries=boundaries,
            endpoints=endpoints,
            remote_calls=stitchable,
            edges=edges,
            placeholders=report.placeholders,
        )

        summary = StitchSummary(
            snapshot_id=snapshot_id,
            service_count=len(boundaries),
            endpoint_count=len(endpoints),
            remote_call_count=len(remote_calls),
            mq_interaction_count=len(mq_interactions),
            edge_count=len(edges),
            analyzed=report.totals.analyzed,
            external=report.totals.external,
            placeholder=report.totals.placeholder,
            undetermined=report.totals.undetermined,
        )
        logger.info(
            "stitched %s: %d services, %d endpoints, %d call facts -> %d edges "
            "(%d analyzed, %d external, %d placeholder, %d undetermined)",
            snapshot_id,
            summary.service_count,
            summary.endpoint_count,
            summary.remote_call_count,
            summary.edge_count,
            summary.analyzed,
            summary.external,
            summary.placeholder,
            summary.undetermined,
        )
        return summary
