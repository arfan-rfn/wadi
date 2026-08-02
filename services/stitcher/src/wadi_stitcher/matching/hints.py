"""Hint seam (§5.4 / Phase 4 design note).

Stitching hints ship in Phase 4, but the matcher's precedence must already
have a top tier for them: a hint hit short-circuits mechanism matching and
carries ``provenance=HUMAN_ASSERTED`` — provenance never blends (P7). Phase 2
ships only the null provider; the protocol is the seam Phase 4 fills.
"""

from typing import Protocol

from wadi_contracts import RemoteCall, StitchedEdge


class HintProvider(Protocol):
    """Resolves a call fact from human-asserted hints, if one anchors to it."""

    def edges_for(self, call: RemoteCall) -> list[StitchedEdge]:
        """Hint-asserted edges for this call; empty = no hint applies."""
        ...


class NullHintProvider:
    """Phase 2: no hints exist yet."""

    def edges_for(self, call: RemoteCall) -> list[StitchedEdge]:  # noqa: ARG002
        return []
