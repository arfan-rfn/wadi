"""JSON Schema export from the contract models (§7, §14).

One ``<name>.schema.json`` per contract model plus an ``index.json`` recording
schema and tag-registry versions. These files are a published release artifact
and feed frontend TS type generation; CI fails if generated outputs are stale.

Also emits ``vocabulary/*.json`` — the cross-language vocabulary handoff (§7,
recorded 2026-08-05). Vocabularies a Scala pack emits and a Python contract
validates have no type system spanning them, so the contract publishes the
registry as data and the pack's conformance test asserts equality against it.
The contract is the source of truth; the pack conforms (the day-zero tag rule).
"""

import json
from pathlib import Path
from typing import Any

from wadi_contracts.registry import CONTRACT_MODELS
from wadi_contracts.tags import ASYNC_ROOT_KINDS
from wadi_contracts.version import SCHEMA_VERSION, TAG_REGISTRY_VERSION

CROSS_LANGUAGE_VOCABULARIES: dict[str, frozenset[str]] = {
    "async_root_kinds": ASYNC_ROOT_KINDS,
}
"""Registries emitted by a Scala pack and validated by a Python contract.

Each is published to ``schemas/vocabulary/<name>.json`` for the pack-side
conformance test. Adding a vocabulary here is what puts it under the gate."""


def export(out_dir: Path) -> list[Path]:
    """Write all contract schemas to ``out_dir``; returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tag_registry_version": TAG_REGISTRY_VERSION,
        "schemas": {},
    }
    for name, model in sorted(CONTRACT_MODELS.items()):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://trywadi.com/schemas/{SCHEMA_VERSION}/{name}.schema.json"
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        written.append(path)
        index["schemas"][name] = path.name
    index["vocabularies"] = {}
    vocab_dir = out_dir / "vocabulary"
    vocab_dir.mkdir(parents=True, exist_ok=True)
    for name, values in sorted(CROSS_LANGUAGE_VOCABULARIES.items()):
        path = vocab_dir / f"{name}.json"
        payload = {
            "name": name,
            "schema_version": SCHEMA_VERSION,
            "values": sorted(values),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        written.append(path)
        index["vocabularies"][name] = f"vocabulary/{path.name}"

    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    written.append(index_path)
    return written
