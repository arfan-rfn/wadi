"""Worker-side vocabulary liveness (§7, recorded 2026-08-05).

The StrEnum conversion makes "producer emits a code the registry lacks" a
pyright error. These tests cover the other direction — a registered code no
producer emits — which pyright cannot see, and which is how the registry
quietly accumulates fiction.

The check lives in the *service*, not in wadi-contracts: contracts must not
import a service (P1), so the dependency has to point this way.
"""

from wadi_contracts.enums import AuthGapCode, CfgAnomalyCode, ClientLibrary
from wadi_testing.vocabulary import assert_registry_is_live
from wadi_worker import auth_oracle, boundary, cfg_invariants


def test_every_cfg_anomaly_code_is_emitted() -> None:
    assert_registry_is_live(CfgAnomalyCode, cfg_invariants)


def test_every_client_library_is_detected() -> None:
    assert_registry_is_live(ClientLibrary, boundary)


def test_every_auth_gap_code_is_emitted() -> None:
    assert_registry_is_live(AuthGapCode, auth_oracle)
