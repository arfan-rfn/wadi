"""Stitcher-side vocabulary liveness (§7, recorded 2026-08-05).

``UNRESOLVED_REASON_CODES`` is the P10 queryable-gap registry: a consumer
filters it to ask "which gaps does wadi admit to?". A code registered but
never emitted answers that question with fiction — indistinguishable from
"no such gaps" — which is exactly why ``host-unresolvable`` was removed in
1.2.0 and ``unresolved-receiver-type`` in 1.16.0.
"""

from wadi_contracts.enums import UnresolvedReasonCode
from wadi_stitcher.matching import http
from wadi_testing.vocabulary import assert_registry_is_live


def test_every_unresolved_reason_code_is_emitted() -> None:
    assert_registry_is_live(UnresolvedReasonCode, http)
