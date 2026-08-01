"""Cross-language golden test: the REAL Scala export feeds the Python assembler.

`sbt test` in joern-platform writes `target/petstore-export/export.json` from
the spring-petstore-mini fixture. If that file exists (locally after running
sbt, or in CI where the Scala job runs first), this test proves the two sides
of the §5.1 contract actually fit — not just that each side matches its own
idea of the schema.
"""

import json
from pathlib import Path

import pytest

from wadi_contracts import Confidence, IcfgNodeKind, SinkKind
from wadi_joern_client import ServiceExport
from wadi_worker.assembler import Assembler

EXPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "joern-platform"
    / "target"
    / "petstore-export"
    / "export.json"
)

pytestmark = pytest.mark.skipif(
    not EXPORT_PATH.exists(),
    reason="real Joern export not present — run `sbt test` in joern-platform first",
)


@pytest.fixture(scope="module")
def real_export() -> ServiceExport:
    return ServiceExport.model_validate(json.loads(EXPORT_PATH.read_text()))


class TestRealExportContract:
    def test_parses_against_the_python_contract(self, real_export: ServiceExport) -> None:
        assert real_export.language == "java"
        assert real_export.compatible_with_reader()
        assert len(real_export.endpoints) == 3

    def test_assembles_into_valid_artifacts(self, real_export: ServiceExport) -> None:
        assembler = Assembler(snapshot_id="snap_real", service_id="svc_" + "c" * 16)
        result = assembler.assemble(real_export)

        uris = {e.simplified_uri for e in result.endpoints}
        assert uris == {"/pets/{?}", "/pets", "/owners"}

        # Every ICFG passes full contract validation (done at construction)
        # and has a resolvable explicit root.
        for icfg in result.icfgs:
            root = icfg.root_entry()
            assert root.method_info is not None

    def test_di_crossing_visible_in_assembled_icfg(self, real_export: ServiceExport) -> None:
        assembler = Assembler(snapshot_id="snap_real", service_id="svc_" + "c" * 16)
        result = assembler.assemble(real_export)
        get_pet = next(e for e in result.endpoints if e.simplified_uri == "/pets/{?}")
        icfg = next(g for g in result.icfgs if g.endpoint_id == get_pet.id)
        signatures = {n.method.signature for n in icfg.nodes}
        assert any("PetServiceImpl" in s for s in signatures)  # crossed the interface

    def test_sinks_survive_the_full_path(self, real_export: ServiceExport) -> None:
        assembler = Assembler(snapshot_id="snap_real", service_id="svc_" + "c" * 16)
        result = assembler.assemble(real_export)
        assert len(result.remote_calls) == 1
        call = result.remote_calls[0]
        assert call.url is not None
        assert "/stock/" in call.url
        assert call.url_confidence is Confidence.HEURISTIC

        get_pet = next(e for e in result.endpoints if e.simplified_uri == "/pets/{?}")
        icfg = next(g for g in result.icfgs if g.endpoint_id == get_pet.id)
        sink_kinds = {n.sink for n in icfg.nodes if n.sink is not None}
        assert sink_kinds == {SinkKind.DB, SinkKind.HTTP_CLIENT}

    def test_branch_conditions_present(self, real_export: ServiceExport) -> None:
        assembler = Assembler(snapshot_id="snap_real", service_id="svc_" + "c" * 16)
        result = assembler.assemble(real_export)
        get_pet = next(e for e in result.endpoints if e.simplified_uri == "/pets/{?}")
        icfg = next(g for g in result.icfgs if g.endpoint_id == get_pet.id)
        branches = [n for n in icfg.nodes if n.kind is IcfgNodeKind.BRANCH]
        assert branches
        assert any(n.condition is not None for n in branches)
