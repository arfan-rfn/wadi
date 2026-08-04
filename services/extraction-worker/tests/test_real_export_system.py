"""Cross-language golden test for the two-service fixture (petstore-system).

Consumes the REAL sbt-produced exports (one per Maven module, exactly as
production analyzes each build root): parses under export schema 2.0.0 and
assembles into contract artifacts, proving the §5.2.4 slicing scenarios
survive the Scala → Python boundary.
"""

import json
from pathlib import Path

import pytest

from wadi_contracts import AuthEvidenceKind, Confidence, HttpMethod
from wadi_joern_client.export import ServiceExport
from wadi_worker.assembler import Assembler

EXPORT_ROOT = (
    Path(__file__).resolve().parents[3] / "joern-platform" / "target" / "petstore-system-export"
)

pytestmark = pytest.mark.skipif(
    not (EXPORT_ROOT / "petstore" / "export.json").exists(),
    reason="petstore-system export not present — run `sbt test` in joern-platform first",
)


def _load(module: str) -> ServiceExport:
    raw = json.loads((EXPORT_ROOT / module / "export.json").read_text())
    return ServiceExport.model_validate(raw)


@pytest.fixture(scope="module")
def petstore() -> ServiceExport:
    return _load("petstore")


@pytest.fixture(scope="module")
def inventory() -> ServiceExport:
    return _load("inventory")


class TestPetstoreModule:
    def test_parses_under_schema_2(self, petstore: ServiceExport) -> None:
        assert petstore.export_schema_version == "2.6.0"
        assert petstore.compatible_with_reader()

    def test_analysis_coverage_matches_pinned_conformance(
        self, petstore: ServiceExport, inventory: ServiceExport
    ) -> None:
        """§5.4.3: the counts pinned in PetstoreSystemConformanceTest arrive
        intact across the language boundary."""
        assert petstore.analysis_coverage is not None
        assert petstore.analysis_coverage.production_methods == 53
        assert petstore.analysis_coverage.reachable_production_methods == 50
        assert inventory.analysis_coverage is not None
        assert inventory.analysis_coverage.production_methods == 10
        assert inventory.analysis_coverage.reachable_production_methods == 10

    def test_async_roots_arrive_with_registry_kinds(self, petstore: ServiceExport) -> None:
        """§5.4.2 T4: roots cross the language boundary and their kinds are
        registry vocabulary."""
        from wadi_contracts.tags import ASYNC_ROOT_KINDS

        assert petstore.async_roots, "the T4 fixtures must produce async roots"
        kinds = {r.kind for r in petstore.async_roots}
        assert kinds <= ASYNC_ROOT_KINDS
        assert {"scheduled", "event-listener", "kafka-listener", "application-runner"} <= kinds
        methods = {m.id for m in petstore.methods}
        assert all(r.method_id in methods for r in petstore.async_roots)

    def test_config_key_candidate_assembles(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        config_calls = [
            c
            for c in result.remote_calls
            if c.url and "${inventory.url}" in c.url and c.mechanism == "resttemplate"
        ]
        assert len(config_calls) == 1
        call = config_calls[0]
        assert call.url == "${inventory.url}/stock/{?}"
        assert call.url_confidence is Confidence.HIGH
        assert call.evidence is not None
        assert "@Value" in call.evidence

    def test_branch_candidates_are_separate_facts_on_one_site(
        self, petstore: ServiceExport
    ) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        event_calls = [c for c in result.remote_calls if c.url and c.url.endswith("/events")]
        assert {c.url for c in event_calls} == {
            "http://inventory:8081/events",
            "https://audit.example.com/events",
        }
        event_ids = {c.id for c in event_calls}
        multi_nodes = [
            node
            for icfg in result.icfgs
            for node in icfg.nodes
            if set(node.remote_call_ids) == event_ids
        ]
        assert multi_nodes, "the branch-dependent site must carry both candidates"

    def test_runtime_only_target_is_honest_none(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        undetermined = [c for c in result.remote_calls if c.url is None]
        assert len(undetermined) == 1
        assert undetermined[0].url_confidence is Confidence.NONE

    def test_config_refs_arrive(self, petstore: ServiceExport) -> None:
        keys = sorted(ref.key for ref in petstore.config_refs)
        # Five T2 probe classes @Value the api key; PetServiceImpl @Values the
        # base key (the feign url=${key} attribute references it too); the T3
        # probes reference the compose-env-only and profile-only keys.
        assert keys == ["inventory.api.url"] * 5 + [
            "inventory.profile.url",
            "inventory.url",
            "inventory.url",
            "petstore.services.inventory",
        ]
        by_key = {ref.key: ref for ref in petstore.config_refs}
        assert "PetServiceImpl.java" in by_key["inventory.url"].anchor.file

    def test_exchange_verb_and_long_concat_assemble(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        reserve = [c for c in result.remote_calls if c.url and "/stock/reserve/" in c.url]
        # Two idioms hit the reserve endpoint: the long-concat exchange (T1)
        # and the RequestEntity-form exchange (T2).
        assert len(reserve) == 2
        by_url = {c.url: c for c in reserve}
        concat = by_url["http://inventory/stock/reserve/{?}/{?}"]
        assert concat.http_verb is HttpMethod.PUT
        assert concat.url_confidence is Confidence.HIGH
        assert concat.reachable
        assert not concat.suspected
        entity = by_url["${inventory.api.url}/stock/reserve/{?}/1"]
        assert entity.http_verb is HttpMethod.PUT
        assert entity.url_confidence is Confidence.HIGH

    def test_webclient_chain_assembles_with_mechanism(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        webclient = [c for c in result.remote_calls if c.mechanism == "webclient"]
        # The T1 absolute chain + the T2 base-undetermined probe.
        assert len(webclient) == 2
        call = next(c for c in webclient if c.url == "http://inventory:8081/admin/restock")
        assert call.http_verb is HttpMethod.POST
        mystery = next(c for c in webclient if c.url == "{?}/mystery/{?}")
        assert mystery.url_confidence is Confidence.HEURISTIC

    def test_suspected_sink_is_a_countable_maybe(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        suspected = [c for c in result.remote_calls if c.suspected]
        assert len(suspected) == 1
        call = suspected[0]
        assert call.mechanism == "unknown"
        assert call.url == "http://billing:9999/charge/{?}"
        assert call.reachable

    def test_unreachable_sink_is_inventoried(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        unreachable = [c for c in result.remote_calls if not c.reachable]
        assert len(unreachable) == 1
        call = unreachable[0]
        assert call.url == "https://audit.example.com/orphaned/{?}"
        assert "OrphanedAuditNotifier" in call.method.signature
        assert "OrphanedAuditNotifier.java" in call.site.file

    def test_owner_scoped_field_yields_one_candidate(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        billing = [c for c in result.remote_calls if c.url and "/billing-events" in c.url]
        assert [c.url for c in billing] == ["http://billing:9082/billing-events"]


class TestEndpointParams:
    def test_params_assemble_into_the_contract(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        by_uri = {e.simplified_uri: e for e in result.endpoints}
        [path_param] = by_uri["/pets/{?}"].params
        assert (path_param.name, path_param.location.value, path_param.required) == (
            "id",
            "path",
            True,
        )
        [query_param] = by_uri["/pets"].params
        assert (query_param.name, query_param.location.value, query_param.required) == (
            "owner",
            "query",
            False,
        )


class TestFeign:
    def test_feign_call_becomes_a_high_confidence_fact(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        feign_calls = [c for c in result.remote_calls if c.mechanism == "feign"]
        # T2 feign completeness: base + inherited + method= + constant-name + url=${key}.
        assert len(feign_calls) == 5
        call = next(
            c for c in feign_calls if c.url == "http://inventory/api/v1/inventory/stock/{id}"
        )
        assert call.url_confidence is Confidence.HIGH
        assert call.auth_propagation == "feign-interceptor"


class TestInventoryModule:
    def test_endpoints_assemble(self, inventory: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "b" * 16).assemble(inventory)
        uris = {(e.http_method.value, e.simplified_uri) for e in result.endpoints}
        assert uris == {
            ("GET", "/stock/{?}"),
            ("GET", "/api/v1/inventory/stock/{?}"),
            ("GET", "/api/v1/inventory/reserved/{?}"),
            ("GET", "/api/v1/inventory/audit/{?}"),
            ("POST", "/admin/restock"),
            ("PUT", "/stock/reserve/{?}/{?}"),
        }

    def test_auth_merges_annotation_and_chain(self, inventory: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "b" * 16).assemble(inventory)
        by_uri = {e.simplified_uri: e for e in result.endpoints}

        restock = by_uri["/admin/restock"].auth
        assert restock.authenticated is True
        assert restock.roles == ["ADMIN"]
        kinds = {e.kind for e in restock.evidence}
        assert kinds == {AuthEvidenceKind.ANNOTATION, AuthEvidenceKind.SECURITY_DSL}

        stock = by_uri["/stock/{?}"].auth
        assert stock.authenticated is False  # permitAll, with evidence
        assert stock.mechanism == "spring-security"


class TestProviderContracts:
    """§5.2.7 (M5): wire shapes survive the Scala -> Python boundary."""

    def test_response_shape_assembles_with_jackson_semantics(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        by_uri = {(e.http_method.value, e.full_uri): e for e in result.endpoints}
        details = by_uri[("GET", "/catalog/pets/{id}")]
        assert details.response_schema is not None
        assert details.response_schema.kind.value == "object"
        names = [f.name for f in details.response_schema.fields]
        assert "display_name" in names  # @JsonProperty rename
        assert "internalNote" not in names  # @JsonIgnore omitted
        renamed = next(f for f in details.response_schema.fields if f.name == "display_name")
        assert renamed.java_name == "name"

    def test_request_schema_and_cycle_and_unresolved(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        by_uri = {(e.http_method.value, e.full_uri): e for e in result.endpoints}
        create = by_uri[("POST", "/catalog/pets")]
        assert create.request_schema is not None
        assert {f.name for f in create.request_schema.fields} == {"name", "breed"}
        tree = by_uri[("GET", "/catalog/tree")]
        assert tree.response_schema is not None
        children = next(f for f in tree.response_schema.fields if f.name == "children")
        assert children.shape.kind.value == "array"
        assert children.shape.element is not None
        assert children.shape.element.kind.value == "cycle"
        vendor = by_uri[("GET", "/catalog/vendor")]
        assert vendor.response_schema is not None
        assert vendor.response_schema.kind.value == "unresolved"
        assert vendor.response_schema.fields == []
