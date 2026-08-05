"""Schema export tests: every contract model publishes a valid JSON Schema."""

import json
from pathlib import Path

from wadi_contracts.registry import CONTRACT_MODELS
from wadi_contracts.schema_export import CROSS_LANGUAGE_VOCABULARIES, export


class TestExport:
    def test_writes_one_schema_per_model_plus_index(self, tmp_path: Path) -> None:
        written = export(tmp_path)
        names = {p.name for p in written}
        assert "index.json" in names
        assert len(written) == len(CONTRACT_MODELS) + len(CROSS_LANGUAGE_VOCABULARIES) + 1
        for model_name in CONTRACT_MODELS:
            assert f"{model_name}.schema.json" in names

    def test_schemas_are_valid_json_with_ids(self, tmp_path: Path) -> None:
        export(tmp_path)
        for model_name in CONTRACT_MODELS:
            schema = json.loads((tmp_path / f"{model_name}.schema.json").read_text())
            assert schema["$schema"].startswith("https://json-schema.org/")
            assert model_name in schema["$id"]
            assert "properties" in schema

    def test_index_records_versions(self, tmp_path: Path) -> None:
        export(tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["schema_version"]
        assert index["tag_registry_version"]
        assert set(index["schemas"]) == set(CONTRACT_MODELS)

    def test_export_is_deterministic(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        export(dir_a)
        export(dir_b)
        for path_a in sorted(p for p in dir_a.rglob("*") if p.is_file()):
            path_b = dir_b / path_a.relative_to(dir_a)
            assert path_a.read_text() == path_b.read_text()

    def test_cross_language_vocabularies_published(self, tmp_path: Path) -> None:
        """§7: the Scala/Python vocabulary handoff — the contract publishes the
        registry as data, the pack's conformance test diffs against it."""
        export(tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert set(index["vocabularies"]) == set(CROSS_LANGUAGE_VOCABULARIES)
        for name, expected in CROSS_LANGUAGE_VOCABULARIES.items():
            published = json.loads((tmp_path / "vocabulary" / f"{name}.json").read_text())
            assert published["name"] == name
            assert published["values"] == sorted(expected)

    def test_artifact_envelope_fields_present(self, tmp_path: Path) -> None:
        export(tmp_path)
        endpoint_schema = json.loads((tmp_path / "endpoint.schema.json").read_text())
        for field in ("schema_version", "snapshot_id", "service_id", "created_at"):
            assert field in endpoint_schema["properties"]
