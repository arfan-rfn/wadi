"""Wadi data contracts — the single source of truth (architecture.md §7)."""

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.boundary import NetworkIdentity, ServiceBoundary
from wadi_contracts.comms import MqInteraction, RemoteCall
from wadi_contracts.datamodel import DataModel, DataModelField, DataModelRelation
from wadi_contracts.endpoint import (
    AuthEvidence,
    AuthEvidenceKind,
    Endpoint,
    EndpointAuth,
    EndpointParam,
    ParamLocation,
)
from wadi_contracts.enums import (
    Confidence,
    HttpMethod,
    IcfgEdgeKind,
    IcfgNodeKind,
    JobStatus,
    JobType,
    MqDirection,
    Provenance,
    ServiceKind,
    SinkKind,
    SnapshotStatus,
    SourceVariant,
    TriggerKind,
)
from wadi_contracts.icfg import (
    BranchCondition,
    Icfg,
    IcfgEdge,
    IcfgNode,
    MethodInfo,
    MethodParam,
    OperandOrigin,
    OperandRef,
)
from wadi_contracts.ids import (
    data_model_id,
    endpoint_id,
    method_id,
    mq_interaction_id,
    normalize_repo_source,
    remote_call_id,
    service_id,
    simplify_uri,
)
from wadi_contracts.jobs import ExtractionJob, JobClaim
from wadi_contracts.registry import CONTRACT_MODELS
from wadi_contracts.source import MethodRef, SourceAnchor
from wadi_contracts.system import RepoSource, Snapshot, System
from wadi_contracts.tags import (
    TAG_REGISTRY_VERSION,
    Tag,
    TagValidationError,
    parse_tag,
    registered_namespaces,
    validate_tag,
)
from wadi_contracts.timeutil import UtcDatetime, ensure_utc, utc_now
from wadi_contracts.version import SCHEMA_VERSION
from wadi_contracts.views import ServiceSummary

__all__ = [
    "CONTRACT_MODELS",
    "SCHEMA_VERSION",
    "TAG_REGISTRY_VERSION",
    "ArtifactEnvelope",
    "AuthEvidence",
    "AuthEvidenceKind",
    "BranchCondition",
    "Confidence",
    "DataModel",
    "DataModelField",
    "DataModelRelation",
    "Endpoint",
    "EndpointAuth",
    "EndpointParam",
    "ExtractionJob",
    "HttpMethod",
    "Icfg",
    "IcfgEdge",
    "IcfgEdgeKind",
    "IcfgNode",
    "IcfgNodeKind",
    "JobClaim",
    "JobStatus",
    "JobType",
    "MethodInfo",
    "MethodParam",
    "MethodRef",
    "MqDirection",
    "MqInteraction",
    "NetworkIdentity",
    "OperandOrigin",
    "OperandRef",
    "ParamLocation",
    "Provenance",
    "RemoteCall",
    "RepoSource",
    "ServiceBoundary",
    "ServiceKind",
    "ServiceSummary",
    "SinkKind",
    "Snapshot",
    "SnapshotStatus",
    "SourceAnchor",
    "SourceVariant",
    "System",
    "Tag",
    "TagValidationError",
    "TriggerKind",
    "UtcDatetime",
    "WadiModel",
    "data_model_id",
    "endpoint_id",
    "ensure_utc",
    "method_id",
    "mq_interaction_id",
    "normalize_repo_source",
    "parse_tag",
    "registered_namespaces",
    "remote_call_id",
    "service_id",
    "simplify_uri",
    "utc_now",
    "validate_tag",
]
