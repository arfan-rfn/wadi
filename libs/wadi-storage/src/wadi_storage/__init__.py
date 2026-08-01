"""Wadi storage seam — the ONLY package importing DB drivers (architecture.md §9)."""

from wadi_storage.artifacts import ArtifactRepository
from wadi_storage.chunking import (
    MONGO_MAX_DOC_BYTES,
    SAFE_PART_BYTES,
    OversizedItemError,
    needs_chunking,
    pack_items,
)
from wadi_storage.graph import GraphStore
from wadi_storage.jobs import JobQueue
from wadi_storage.mongo import WadiDatabase, create_client
from wadi_storage.systems import (
    DuplicateSystemNameError,
    SnapshotRepository,
    SystemRepository,
)

__all__ = [
    "MONGO_MAX_DOC_BYTES",
    "SAFE_PART_BYTES",
    "ArtifactRepository",
    "DuplicateSystemNameError",
    "GraphStore",
    "JobQueue",
    "OversizedItemError",
    "SnapshotRepository",
    "SystemRepository",
    "WadiDatabase",
    "create_client",
    "needs_chunking",
    "pack_items",
]
