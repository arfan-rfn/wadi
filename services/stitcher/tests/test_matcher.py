"""Matcher unit tests: the 27-combination confidence table, all four target
kinds, provenance selection, hints, and determinism (§5.4.2)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wadi_contracts import (
    Confidence,
    Endpoint,
    GatewayRoute,
    HttpMethod,
    NetworkIdentity,
    Provenance,
    RemoteCall,
    ServiceBoundary,
    Snapshot,
    StitchedEdge,
    TargetKind,
    placeholder_service_id,
)
from wadi_stitcher.matching import MatchContext, match_call
from wadi_stitcher.matching.base import (
    BUDGET_TRUNCATED_MARKER,
    LOMBOK_BLOCKED_MARKER,
    confidence_min,
)
from wadi_stitcher.matching.http import HttpMatcher
from wadi_stitcher.matching.paths import PathQuality, path_match
from wadi_stitcher.phonebook import PhoneBook
from wadi_testing.builders import (
    make_endpoint,
    make_remote_call,
    make_service,
    make_snapshot,
    make_system,
)

MATCHERS = (HttpMatcher(),)


def _network(**kwargs: object) -> NetworkIdentity:
    return NetworkIdentity.model_validate(kwargs)


def _context(
    snapshot: Snapshot,
    boundaries: list[ServiceBoundary],
    endpoints: list[Endpoint],
) -> MatchContext:
    endpoints_by_service: dict[str, list[Endpoint]] = {}
    for endpoint in endpoints:
        endpoints_by_service.setdefault(endpoint.service_id, []).append(endpoint)
    return MatchContext(
        snapshot_id=snapshot.id,
        phonebook=PhoneBook.build(boundaries),
        endpoints_by_service=endpoints_by_service,
        boundaries_by_service={b.service_id: b for b in boundaries},
    )


class TestPathMatch:
    @pytest.mark.parametrize(
        ("call_path", "endpoint_uri", "expected"),
        [
            ("/stock/5", "/stock/{?}", PathQuality.EXACT),  # endpoint template absorbs
            ("/stock/{?}", "/stock/{?}", PathQuality.EXACT),
            ("/stock/{?}", "/stock/current", PathQuality.HEURISTIC),  # call hole vs literal
            ("/stock/5", "/stock/5/deep", None),  # length mismatch
            ("/stock/5", "/orders/{?}", None),  # literal disagreement
            ("/Stock/5", "/stock/{?}", None),  # paths are case-sensitive
        ],
    )
    def test_table(self, call_path: str, endpoint_uri: str, expected: PathQuality | None) -> None:
        assert path_match(call_path, endpoint_uri) == expected

    @given(st.lists(st.sampled_from(["a", "b", "{x}", "5"]), min_size=1, max_size=6))
    def test_simplified_self_match_is_exact(self, segments: list[str]) -> None:
        # Any path matches its own identity form exactly (idempotence).
        from wadi_contracts import simplify_uri

        path = "/" + "/".join(segments)
        assert path_match(path, simplify_uri(path)) is PathQuality.EXACT


class TestConfidenceComposition:
    """The full U x R x P table: edge confidence = min of the three tiers."""

    @pytest.mark.parametrize("u", [Confidence.EXACT, Confidence.HIGH, Confidence.HEURISTIC])
    @pytest.mark.parametrize("r_mode", ["exact", "gateway", "ambiguous"])
    @pytest.mark.parametrize("p_mode", ["exact", "verb_unknown", "call_hole"])
    def test_all_combinations(self, u: Confidence, r_mode: str, p_mode: str) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/petstore")

        # R component setup.
        target_a = make_service(snapshot, "services/inventory").model_copy(
            update={"network": _network(hostnames=["inventory"])}
        )
        boundaries = [caller, target_a]
        host = "inventory"
        call_path = "/stock/5" if p_mode != "call_hole" else "/stock/{?}"
        if r_mode == "gateway":
            gateway = make_service(snapshot, "services/gateway").model_copy(
                update={
                    "network": _network(
                        hostnames=["gateway"],
                        gateway_routes=[
                            GatewayRoute(
                                path_prefix="/inv/**",
                                target_uri="http://inventory:8081",
                                strip_prefix=1,
                            )
                        ],
                    )
                }
            )
            boundaries.append(gateway)
            host = "gateway"
            call_path = "/inv" + call_path
            r_tier = Confidence.HIGH
        elif r_mode == "ambiguous":
            twin = make_service(snapshot, "services/inventory-twin").model_copy(
                update={"network": _network(hostnames=["inventory"])}
            )
            boundaries.append(twin)
            r_tier = Confidence.HEURISTIC
        else:
            r_tier = Confidence.EXACT

        # P component setup. Endpoint /stock/current gives the call-side hole
        # a literal to absorb; /stock/{id} covers the exact cases.
        endpoint_uri = "/stock/current" if p_mode == "call_hole" else "/stock/{id}"
        verb = None if p_mode == "verb_unknown" else HttpMethod.GET
        p_tier = {
            "exact": Confidence.EXACT,
            "verb_unknown": Confidence.HIGH,
            "call_hole": Confidence.HEURISTIC,
        }[p_mode]

        target_endpoint = make_endpoint(snapshot, target_a, uri=endpoint_uri)
        call = make_remote_call(
            snapshot,
            caller,
            url=f"http://{host}{call_path}",
            confidence=u,
            http_verb=verb,
        )
        ctx = _context(snapshot, boundaries, [target_endpoint])

        outcome = match_call(call, ctx, MATCHERS)
        analyzed = [e for e in outcome.edges if e.target_kind is TargetKind.ANALYZED]
        assert analyzed, f"expected an analyzed edge for {r_mode}/{p_mode}"
        expected = confidence_min(u, r_tier, p_tier)
        target_edge = next(e for e in analyzed if e.target_endpoint_id == target_endpoint.id)
        assert target_edge.confidence is expected, (
            f"U={u} R={r_tier}({r_mode}) P={p_tier}({p_mode}): "
            f"expected {expected}, got {target_edge.confidence}"
        )
        # Provenance never blends with confidence (P7): a single value, chosen
        # by whether any heuristic step participated.
        heuristic_involved = Confidence.HEURISTIC in (u, r_tier, p_tier)
        assert target_edge.provenance is (
            Provenance.HEURISTIC if heuristic_involved else Provenance.CONFIG_RESOLVED
        )


class TestTargetKinds:
    def _base(self) -> tuple[Snapshot, ServiceBoundary]:
        snapshot = make_snapshot(make_system())
        return snapshot, make_service(snapshot, "services/petstore")

    def test_external_fqdn(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(
            snapshot, caller, url="https://api.stripe.com/v1/charges", confidence=Confidence.EXACT
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.EXTERNAL
        assert edge.external_host == "api.stripe.com"
        assert edge.confidence is Confidence.EXACT
        assert edge.provenance is Provenance.MACHINE_PROVEN

    def test_external_with_port_and_heuristic_url(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(
            snapshot, caller, url="http://api.vendor.io:9443/x", confidence=Confidence.HEURISTIC
        )
        [edge] = match_call(call, _context(snapshot, [caller], []), MATCHERS).edges
        assert edge.external_host == "api.vendor.io:9443"
        assert edge.provenance is Provenance.HEURISTIC

    def test_bare_hostname_becomes_placeholder(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url="http://billing/invoices")
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.PLACEHOLDER
        assert edge.target_service_id == placeholder_service_id("billing")
        assert edge.confidence is Confidence.HEURISTIC
        assert edge.provenance is Provenance.HEURISTIC
        assert edge.target_service_id is not None
        assert outcome.placeholder_names[edge.target_service_id] == ("billing", "bare-hostname")

    def test_config_known_placeholder_via_gateway(self) -> None:
        snapshot, caller = self._base()
        gateway = make_service(snapshot, "services/gateway").model_copy(
            update={
                "network": _network(
                    hostnames=["gateway"],
                    gateway_routes=[
                        GatewayRoute(path_prefix="/pay/**", target_uri="lb://payment-service")
                    ],
                )
            }
        )
        call = make_remote_call(snapshot, caller, url="http://gateway/pay/checkout")
        outcome = match_call(call, _context(snapshot, [caller, gateway], []), MATCHERS)
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.PLACEHOLDER
        assert outcome.placeholder_names[edge.target_service_id or ""] == (
            "payment-service",
            "gateway-route",
        )

    def test_url_none_is_undetermined_with_reason(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url=None)
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.UNDETERMINED
        assert edge.confidence is Confidence.NONE
        [entry] = outcome.unresolved
        assert entry.reason_code == "url-undetermined"
        assert entry.remote_call_id == call.id

    def test_lombok_blocked_reason_is_machine_readable(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url=None).model_copy(
            update={"evidence": f"getBaseUrl() <- {LOMBOK_BLOCKED_MARKER} of Config.baseUrl"}
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "lombok-generated-interior"

    def test_budget_truncated_reason_is_machine_readable(self) -> None:
        # T1 (§5.2.5): a starved slice is a budget fact, not a semantic unknown.
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url=None).model_copy(
            update={"evidence": f"slice: … \n  [{BUDGET_TRUNCATED_MARKER}]"}
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "slice-budget-truncated"

    def test_relative_url_unparseable(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url="/stock/5")
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "url-unparseable"

    def test_base_undetermined_marker_names_the_cause(self) -> None:
        # T2 (rootUri/baseUrl split): the slicer said WHY the URL is holed.
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url="{?}/mystery/{?}").model_copy(
            update={
                "evidence": ("slice: …\n  relative URL, base not recoverable [base-undetermined]")
            }
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "base-undetermined"

    def test_unsupported_idiom_marker_becomes_the_reason_code(self) -> None:
        # T2: a NAMED unmodelled construct is countable per idiom.
        snapshot, caller = self._base()
        call = make_remote_call(snapshot, caller, url=None).model_copy(
            update={"evidence": "slice: …\n  System.getenv(…) -> opaque [unsupported-idiom:getenv]"}
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "unsupported-idiom:getenv"

    def test_template_hole_in_authority_unparseable(self) -> None:
        snapshot, caller = self._base()
        call = make_remote_call(
            snapshot, caller, url="{?}/stock/{?}", confidence=Confidence.HEURISTIC
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "url-unparseable"

    def test_resolved_service_without_matching_endpoint_is_undetermined(self) -> None:
        snapshot, caller = self._base()
        inventory = make_service(snapshot, "services/inventory").model_copy(
            update={"network": _network(hostnames=["inventory"])}
        )
        other_endpoint = make_endpoint(snapshot, inventory, uri="/completely/other")
        call = make_remote_call(snapshot, caller, url="http://inventory:8081/stock/5")
        outcome = match_call(
            call, _context(snapshot, [caller, inventory], [other_endpoint]), MATCHERS
        )
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.UNDETERMINED  # never fabricate (P10)
        [entry] = outcome.unresolved
        assert entry.reason_code == "no-endpoint-match"
        assert "inventory" in entry.reason

    def test_verb_mismatch_is_no_endpoint_match(self) -> None:
        snapshot, caller = self._base()
        inventory = make_service(snapshot, "services/inventory").model_copy(
            update={"network": _network(hostnames=["inventory"])}
        )
        get_endpoint = make_endpoint(snapshot, inventory, uri="/stock/{id}")  # GET
        call = make_remote_call(
            snapshot, caller, url="http://inventory/stock/5", http_verb=HttpMethod.DELETE
        )
        outcome = match_call(
            call, _context(snapshot, [caller, inventory], [get_endpoint]), MATCHERS
        )
        assert outcome.unresolved[0].reason_code == "no-endpoint-match"

    def test_ambiguous_host_yields_edge_per_candidate(self) -> None:
        snapshot, caller = self._base()
        a = make_service(snapshot, "services/a").model_copy(
            update={"network": _network(hostnames=["orders"])}
        )
        b = make_service(snapshot, "services/b").model_copy(
            update={"network": _network(hostnames=["orders"])}
        )
        endpoint_a = make_endpoint(snapshot, a, uri="/orders/{id}")
        endpoint_b = make_endpoint(snapshot, b, uri="/orders/{id}")
        call = make_remote_call(
            snapshot, caller, url="http://orders/orders/5", confidence=Confidence.EXACT
        )
        outcome = match_call(
            call, _context(snapshot, [caller, a, b], [endpoint_a, endpoint_b]), MATCHERS
        )
        assert len(outcome.edges) == 2
        assert all(e.confidence is Confidence.HEURISTIC for e in outcome.edges)
        assert {e.target_endpoint_id for e in outcome.edges} == {endpoint_a.id, endpoint_b.id}


class TestConfigKeyExpansion:
    def test_key_resolves_from_caller_env(self) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/petstore").model_copy(
            update={"network": _network(env={"inventory.url": "http://inventory:8081"})}
        )
        inventory = make_service(snapshot, "services/inventory").model_copy(
            update={"network": _network(hostnames=["inventory"])}
        )
        endpoint = make_endpoint(snapshot, inventory, uri="/stock/{id}")
        call = make_remote_call(
            snapshot, caller, url="${inventory.url}/stock/{?}", confidence=Confidence.HIGH
        )
        outcome = match_call(call, _context(snapshot, [caller, inventory], [endpoint]), MATCHERS)
        [edge] = outcome.edges
        assert edge.target_kind is TargetKind.ANALYZED
        assert edge.target_endpoint_id == endpoint.id
        assert "via config key" in (edge.evidence or "")

    def test_unresolved_key_stays_honest(self) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/petstore")  # env empty
        call = make_remote_call(
            snapshot, caller, url="${inventory.url}/stock/{?}", confidence=Confidence.HIGH
        )
        outcome = match_call(call, _context(snapshot, [caller], []), MATCHERS)
        assert outcome.unresolved[0].reason_code == "url-unparseable"
        assert "unresolved config keys" in outcome.unresolved[0].reason


class TestHints:
    def test_hint_short_circuits_and_is_human_asserted(self) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/petstore")
        inventory = make_service(snapshot, "services/inventory")
        endpoint = make_endpoint(snapshot, inventory, uri="/stock/{id}")
        call = make_remote_call(snapshot, caller, url=None)  # matcher alone: undetermined

        class OneHint:
            def edges_for(self, call: RemoteCall) -> list[StitchedEdge]:
                return [
                    StitchedEdge.create(
                        snapshot_id=call.snapshot_id,
                        service_id=call.service_id,
                        remote_call_id=call.id,
                        mechanism=call.mechanism,
                        target_kind=TargetKind.ANALYZED,
                        target_service_id=endpoint.service_id,
                        target_endpoint_id=endpoint.id,
                        confidence=Confidence.EXACT,
                        provenance=Provenance.HUMAN_ASSERTED,
                    )
                ]

        outcome = match_call(
            call, _context(snapshot, [caller, inventory], [endpoint]), MATCHERS, OneHint()
        )
        [edge] = outcome.edges
        assert edge.provenance is Provenance.HUMAN_ASSERTED
        assert edge.target_kind is TargetKind.ANALYZED
        assert outcome.unresolved == []


class TestDeterminism:
    def test_repeat_runs_identical(self) -> None:
        snapshot = make_snapshot(make_system())
        caller = make_service(snapshot, "services/petstore")
        a = make_service(snapshot, "services/a").model_copy(
            update={"network": _network(hostnames=["orders"])}
        )
        b = make_service(snapshot, "services/b").model_copy(
            update={"network": _network(hostnames=["orders"])}
        )
        endpoints = [
            make_endpoint(snapshot, a, uri="/orders/{id}"),
            make_endpoint(snapshot, b, uri="/orders/{id}"),
        ]
        call = make_remote_call(snapshot, caller, url="http://orders/orders/5")
        first = match_call(call, _context(snapshot, [caller, a, b], endpoints), MATCHERS)
        second = match_call(call, _context(snapshot, [b, caller, a], endpoints), MATCHERS)
        assert [e.id for e in first.edges] == [e.id for e in second.edges]
