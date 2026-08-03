"""Registry of exported contract models — drives JSON Schema export (§7, §14)."""

from pydantic import BaseModel

from wadi_contracts.boundary import ServiceBoundary
from wadi_contracts.comms import MqInteraction, RemoteCall
from wadi_contracts.datamodel import DataModel
from wadi_contracts.endpoint import Endpoint
from wadi_contracts.export import ExportManifest
from wadi_contracts.icfg import Icfg
from wadi_contracts.jobs import ExtractionJob
from wadi_contracts.stitching import CoverageReport, StitchedEdge
from wadi_contracts.system import Snapshot, System
from wadi_contracts.views import (
    RemoteEdgesView,
    ServiceSummary,
    SourceView,
    SystemGraphView,
)

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "system": System,
    "snapshot": Snapshot,
    "service_boundary": ServiceBoundary,
    "endpoint": Endpoint,
    "icfg": Icfg,
    "remote_call": RemoteCall,
    "mq_interaction": MqInteraction,
    "data_model": DataModel,
    "extraction_job": ExtractionJob,
    "stitched_edge": StitchedEdge,
    "coverage_report": CoverageReport,
    # API views (derived at read time, never stored — §7 note in views.py):
    "service_summary": ServiceSummary,
    "remote_edges_view": RemoteEdgesView,
    "source_view": SourceView,
    "system_graph": SystemGraphView,
    # Export-bundle trailer (derived at export time, never stored — §14):
    "export_manifest": ExportManifest,
}
"""Every published contract, keyed by its canonical artifact name."""
