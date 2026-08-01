"""Wadi extraction worker (architecture.md §5.2)."""

from wadi_worker.assembler import AssembledArtifacts, Assembler
from wadi_worker.boundary import DiscoveredService, discover_services
from wadi_worker.pipeline import CpgqlJoernExtractor, ExtractionPipeline, JoernExtractor

__all__ = [
    "AssembledArtifacts",
    "Assembler",
    "CpgqlJoernExtractor",
    "DiscoveredService",
    "ExtractionPipeline",
    "JoernExtractor",
    "discover_services",
]
