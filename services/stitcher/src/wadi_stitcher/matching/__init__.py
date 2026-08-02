"""Remote-call ↔ endpoint matching (§5.4.2): pluggable per-mechanism rules
over one shared confidence/provenance core."""

from wadi_stitcher.matching.base import MatchContext, MechanismMatcher, match_call
from wadi_stitcher.matching.hints import HintProvider, NullHintProvider

__all__ = [
    "HintProvider",
    "MatchContext",
    "MechanismMatcher",
    "NullHintProvider",
    "match_call",
]
