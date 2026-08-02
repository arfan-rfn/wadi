"""Cross-language golden test for the two-service fixture (petstore-system).

Consumes the REAL sbt-produced exports (one per Maven module, exactly as
production analyzes each build root): parses under export schema 2.0.0 and
assembles into contract artifacts, proving the §5.2.4 slicing scenarios
survive the Scala → Python boundary.
"""

import json
from pathlib import Path

import pytest

from wadi_contracts import Confidence
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
        assert petstore.export_schema_version == "2.0.0"
        assert petstore.compatible_with_reader()

    def test_config_key_candidate_assembles(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        config_calls = [c for c in result.remote_calls if c.url and "${inventory.url}" in c.url]
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
        multi_nodes = [
            node for icfg in result.icfgs for node in icfg.nodes if len(node.remote_call_ids) == 2
        ]
        assert multi_nodes, "the branch-dependent site must carry both candidates"
        assert set(multi_nodes[0].remote_call_ids) == {c.id for c in event_calls}

    def test_runtime_only_target_is_honest_none(self, petstore: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "a" * 16).assemble(petstore)
        undetermined = [c for c in result.remote_calls if c.url is None]
        assert len(undetermined) == 1
        assert undetermined[0].url_confidence is Confidence.NONE

    def test_config_refs_arrive(self, petstore: ServiceExport) -> None:
        assert [ref.key for ref in petstore.config_refs] == ["inventory.url"]
        assert "PetServiceImpl.java" in petstore.config_refs[0].anchor.file


class TestInventoryModule:
    def test_endpoints_assemble(self, inventory: ServiceExport) -> None:
        result = Assembler(snapshot_id="snap_g", service_id="svc_" + "b" * 16).assemble(inventory)
        uris = {(e.http_method.value, e.simplified_uri) for e in result.endpoints}
        assert uris == {
            ("GET", "/stock/{?}"),
            ("GET", "/api/v1/inventory/stock/{?}"),
            ("POST", "/admin/restock"),
        }
