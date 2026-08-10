"""Contract versioning (architecture.md §7).

``SCHEMA_VERSION`` stamps every stored artifact. Evolution rules:
additive change → bump minor; breaking change → bump major and add a reader
migration note in the affected model's docstring. Snapshot keying means old
artifacts are never rewritten in place.
"""

SCHEMA_VERSION = "1.24.0"

TAG_REGISTRY_VERSION = "1.4.0"
"""Version of the tag vocabulary (see :mod:`wadi_contracts.tags`).

Packs may only emit registered tags; this version is recorded so federated
bundle ingestion can validate vocabulary compatibility at the door.
"""
