"""Matcher core: per-mechanism rules over shared tier/provenance machinery.

Every ``RemoteCall`` fact yields at least one edge (P10 — nothing is silently
dropped): resolved calls land on analyzed/external/placeholder targets;
everything else becomes an explicit UNDETERMINED edge paired with a
machine-readable :class:`~wadi_contracts.UnresolvedCallEntry` for the
coverage report.

Precedence: hints (HUMAN_ASSERTED, Phase 4 — null provider today) →
first mechanism matcher that claims the call's mechanism.
"""

from dataclasses import dataclass, field
from typing import Protocol

from wadi_contracts import (
    Confidence,
    Endpoint,
    RemoteCall,
    ServiceBoundary,
    StitchedEdge,
    UnresolvedCallEntry,
)
from wadi_stitcher.matching.hints import HintProvider, NullHintProvider
from wadi_stitcher.phonebook import PhoneBook

# The M3 URL slicer emits this marker verbatim when a Lombok-generated method
# interior blocked resolution — the coverage report counts these individually
# (recorded decision: accepted limitations stay queryable, never just prose).
LOMBOK_BLOCKED_MARKER = "lombok-generated interior"

# The T1 slicer emits this marker when a resolution was cut short by the slice
# budget (§5.2.5): a starved slice is a budget fact, not a semantic unknown —
# it must be countable separately or budget bugs hide inside honest unknowns.
BUDGET_TRUNCATED_MARKER = "slice-budget-truncated"

_CONFIDENCE_ORDER = (Confidence.EXACT, Confidence.HIGH, Confidence.HEURISTIC, Confidence.NONE)


def confidence_min(*tiers: Confidence) -> Confidence:
    """The weakest tier wins: EXACT > HIGH > HEURISTIC > NONE."""
    return max(tiers, key=_CONFIDENCE_ORDER.index)


@dataclass(frozen=True)
class MatchContext:
    """Everything a matcher may consult; immutable during one stitch run."""

    snapshot_id: str
    phonebook: PhoneBook
    endpoints_by_service: dict[str, list[Endpoint]]
    boundaries_by_service: dict[str, ServiceBoundary]

    def caller_env(self, service_id: str) -> dict[str, str]:
        boundary = self.boundaries_by_service.get(service_id)
        return boundary.network.env if boundary is not None else {}


@dataclass
class MatchOutcome:
    """Edges plus the coverage entries for anything that stayed unresolved.

    ``placeholder_names`` maps placeholder ids to (display name, resolved_via)
    — the coverage report and graph nodes need names the edge rows don't carry.
    """

    edges: list[StitchedEdge] = field(default_factory=list[StitchedEdge])
    unresolved: list[UnresolvedCallEntry] = field(default_factory=list[UnresolvedCallEntry])
    placeholder_names: dict[str, tuple[str, str]] = field(
        default_factory=dict[str, tuple[str, str]]
    )

    def merge(self, other: "MatchOutcome") -> None:
        self.edges.extend(other.edges)
        self.unresolved.extend(other.unresolved)
        self.placeholder_names.update(other.placeholder_names)


class MechanismMatcher(Protocol):
    """One communication mechanism's identity scheme (§10: gRPC would match on
    service/method names instead of URLs; the tier machinery is shared)."""

    def matches_mechanism(self, mechanism: str) -> bool: ...

    def match(self, call: RemoteCall, ctx: MatchContext) -> MatchOutcome: ...


def match_call(
    call: RemoteCall,
    ctx: MatchContext,
    matchers: tuple[MechanismMatcher, ...],
    hints: HintProvider | None = None,
) -> MatchOutcome:
    """Resolve one call fact. Hints outrank everything (Phase 4 top tier)."""
    hint_edges = (hints or NullHintProvider()).edges_for(call)
    if hint_edges:
        return MatchOutcome(edges=sorted(hint_edges, key=lambda e: e.id))
    for matcher in matchers:
        if matcher.matches_mechanism(call.mechanism):
            outcome = matcher.match(call, ctx)
            outcome.edges.sort(key=lambda e: e.id)
            return outcome
    raise ValueError(f"no matcher claims mechanism {call.mechanism!r} (registry bug)")
