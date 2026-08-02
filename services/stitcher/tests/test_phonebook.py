"""PhoneBook unit tests: precedence, conflicts, gateway rewrite, determinism."""

import random

from hypothesis import given
from hypothesis import strategies as st

from wadi_contracts import GatewayRoute, NetworkIdentity, ServiceBoundary
from wadi_stitcher.phonebook import PhoneBook, ResolutionKind
from wadi_testing.builders import make_service, make_snapshot, make_system


def _svc(
    build_root: str,
    *,
    hostnames: list[str] | None = None,
    application_name: str | None = None,
    discovery_names: list[str] | None = None,
    ports: list[int] | None = None,
    server_port: int | None = None,
    gateway_routes: list[GatewayRoute] | None = None,
) -> ServiceBoundary:
    snapshot = make_snapshot(make_system())
    base = make_service(snapshot, build_root)
    return base.model_copy(
        update={
            "network": NetworkIdentity(
                hostnames=hostnames or [],
                ports=ports or [],
                application_name=application_name,
                discovery_names=discovery_names or [],
                server_port=server_port,
                gateway_routes=gateway_routes or [],
            )
        }
    )


class TestPrecedence:
    def test_compose_hostname_resolves(self) -> None:
        inventory = _svc("services/inventory", hostnames=["inventory"])
        book = PhoneBook.build([inventory])
        resolution = book.resolve("inventory", None, "/stock/1")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.COMPOSE_HOSTNAME
        assert resolution.candidates[0].service_id == inventory.service_id
        assert not resolution.ambiguous

    def test_application_name_resolves(self) -> None:
        inventory = _svc("services/inventory", application_name="ts-inventory-service")
        book = PhoneBook.build([inventory])
        resolution = book.resolve("ts-inventory-service", None, "/stock/1")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.APPLICATION_NAME

    def test_discovery_name_resolves(self) -> None:
        inventory = _svc("services/inventory", discovery_names=["inventory-svc"])
        book = PhoneBook.build([inventory])
        resolution = book.resolve("INVENTORY-SVC", None, "/x")  # case-insensitive
        assert resolution is not None
        assert resolution.candidates[0].service_id == inventory.service_id

    def test_compose_beats_application_name(self) -> None:
        by_compose = _svc("services/a", hostnames=["orders"])
        by_name = _svc("services/b", application_name="orders")
        book = PhoneBook.build([by_compose, by_name])
        resolution = book.resolve("orders", None, "/x")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.COMPOSE_HOSTNAME
        assert resolution.candidates[0].service_id == by_compose.service_id
        # ...and the shadowing is visible, never silent (P10).
        assert any("compose wins by precedence" in c for c in book.conflicts)

    def test_unknown_host_is_none(self) -> None:
        book = PhoneBook.build([_svc("services/a", hostnames=["a"])])
        assert book.resolve("billing", None, "/x") is None

    def test_port_heuristic_unique_owner(self) -> None:
        inventory = _svc("services/inventory", server_port=8081)
        book = PhoneBook.build([inventory, _svc("services/other", server_port=9000)])
        resolution = book.resolve("localhost", 8081, "/x")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.PORT_HEURISTIC
        assert resolution.candidates[0].service_id == inventory.service_id

    def test_port_heuristic_requires_unique_owner(self) -> None:
        a = _svc("services/a", server_port=8080)
        b = _svc("services/b", ports=[8080])
        book = PhoneBook.build([a, b])
        assert book.resolve("localhost", 8080, "/x") is None

    def test_port_heuristic_never_applies_to_named_hosts(self) -> None:
        a = _svc("services/a", server_port=8080)
        book = PhoneBook.build([a])
        assert book.resolve("unknown-name", 8080, "/x") is None

    def test_port_mismatch_degrades_but_resolves(self) -> None:
        inventory = _svc("services/inventory", hostnames=["inventory"], server_port=8081)
        book = PhoneBook.build([inventory])
        resolution = book.resolve("inventory", 9999, "/x")
        assert resolution is not None
        assert resolution.port_mismatch

    def test_unknown_port_side_no_mismatch(self) -> None:
        inventory = _svc("services/inventory", hostnames=["inventory"])  # no known ports
        book = PhoneBook.build([inventory])
        resolution = book.resolve("inventory", 9999, "/x")
        assert resolution is not None
        assert not resolution.port_mismatch


class TestConflicts:
    def test_intra_namespace_conflict_yields_all_candidates(self) -> None:
        a = _svc("services/a", hostnames=["orders"])
        b = _svc("services/b", hostnames=["orders"])
        book = PhoneBook.build([a, b])
        resolution = book.resolve("orders", None, "/x")
        assert resolution is not None
        assert resolution.ambiguous
        assert {c.service_id for c in resolution.candidates} == {a.service_id, b.service_id}
        assert any("claimed by multiple services" in c for c in book.conflicts)

    def test_no_conflicts_when_clean(self) -> None:
        book = PhoneBook.build([_svc("services/a", hostnames=["a"])])
        assert book.conflicts == ()


class TestGateway:
    def _gateway(self) -> ServiceBoundary:
        return _svc(
            "services/gateway",
            hostnames=["gateway"],
            gateway_routes=[
                GatewayRoute(
                    path_prefix="/api/v1/inventory/**",
                    target_uri="http://inventory:8081",
                    strip_prefix=2,
                ),
                GatewayRoute(path_prefix="/api/**", target_uri="lb://fallback-service"),
            ],
        )

    def test_longest_prefix_wins_and_strips(self) -> None:
        gateway = self._gateway()
        inventory = _svc("services/inventory", hostnames=["inventory"])
        book = PhoneBook.build([gateway, inventory])
        resolution = book.resolve("gateway", None, "/api/v1/inventory/stock/5")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.GATEWAY_ROUTE
        assert resolution.via_gateway
        candidate = resolution.candidates[0]
        assert candidate.service_id == inventory.service_id
        assert candidate.rewritten_path == "/inventory/stock/5"

    def test_route_to_unanalyzed_target_is_config_known_placeholder(self) -> None:
        book = PhoneBook.build([self._gateway()])
        resolution = book.resolve("gateway", None, "/api/v1/inventory/stock/5")
        assert resolution is not None
        assert resolution.candidates[0].service_id is None
        assert resolution.candidates[0].logical_name == "inventory"

    def test_lb_target_resolves_by_name(self) -> None:
        gateway = self._gateway()
        fallback = _svc("services/fallback", application_name="fallback-service")
        book = PhoneBook.build([gateway, fallback])
        resolution = book.resolve("gateway", None, "/api/other/thing")
        assert resolution is not None
        assert resolution.candidates[0].service_id == fallback.service_id

    def test_no_route_match_falls_back_to_direct(self) -> None:
        gateway = self._gateway()
        book = PhoneBook.build([gateway])
        resolution = book.resolve("gateway", None, "/healthz")
        assert resolution is not None
        assert resolution.kind is ResolutionKind.COMPOSE_HOSTNAME
        assert resolution.candidates[0].service_id == gateway.service_id

    def test_gateway_cycle_terminates(self) -> None:
        looping = _svc(
            "services/loop",
            hostnames=["loop"],
            gateway_routes=[GatewayRoute(path_prefix="/**", target_uri="http://loop:8080")],
        )
        book = PhoneBook.build([looping])
        resolution = book.resolve("loop", None, "/anything")
        assert resolution is not None  # depth cap ends the recursion


class TestDeterminism:
    @given(st.randoms())
    def test_build_order_does_not_change_resolution(self, rng: random.Random) -> None:
        boundaries = [
            _svc("services/a", hostnames=["a"], application_name="svc-a"),
            _svc("services/b", hostnames=["b"], server_port=8082),
            _svc("services/c", hostnames=["shared"]),
            _svc("services/d", hostnames=["shared"]),
        ]
        shuffled = boundaries.copy()
        rng.shuffle(shuffled)
        reference, permuted = PhoneBook.build(boundaries), PhoneBook.build(shuffled)
        assert reference.conflicts == permuted.conflicts
        for host, port in (("a", None), ("svc-a", None), ("shared", None), ("localhost", 8082)):
            assert reference.resolve(host, port, "/x") == permuted.resolve(host, port, "/x")
