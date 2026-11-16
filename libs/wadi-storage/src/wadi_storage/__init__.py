"""Wadi storage seam — the ONLY package importing DB drivers (architecture.md §9)."""

from wadi_storage.artifacts import ArtifactRepository, FlowMarks
from wadi_storage.chunking import (
    MONGO_MAX_DOC_BYTES,
    SAFE_PART_BYTES,
    OversizedItemError,
    needs_chunking,
    pack_items,
)
from wadi_storage.compose import (
    GRAPH_READ_TIMEOUT_SECONDS,
    EndpointOutbound,
    OutboundUnavailable,
    endpoint_outbound,
    endpoint_outbound_or_unavailable,
    entity_usage_view,
)
from wadi_storage.graph import GraphRepository, GraphStore, GraphStoreError
from wadi_storage.jobs import JobQueue
from wadi_storage.mongo import WadiDatabase, create_client
from wadi_storage.stitch import StitchRepository
from wadi_storage.systems import (
    DuplicateSystemNameError,
    SnapshotRepository,
    SystemRepository,
)

__all__ = [
    "GRAPH_READ_TIMEOUT_SECONDS",
    "MONGO_MAX_DOC_BYTES",
    "SAFE_PART_BYTES",
    "ArtifactRepository",
    "DuplicateSystemNameError",
    "EndpointOutbound",
    "FlowMarks",
    "GraphRepository",
    "GraphStore",
    "GraphStoreError",
    "JobQueue",
    "OutboundUnavailable",
    "OversizedItemError",
    "SnapshotRepository",
    "StitchRepository",
    "SystemRepository",
    "WadiDatabase",
    "create_client",
    "endpoint_outbound",
    "endpoint_outbound_or_unavailable",
    "entity_usage_view",
    "needs_chunking",
    "pack_items",
]
