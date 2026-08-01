"""Shared enumerations for the contract models."""

from enum import StrEnum


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"


class Confidence(StrEnum):
    """Confidence tiers for recovered facts (§5.4). Ordered EXACT > HIGH > HEURISTIC > NONE."""

    EXACT = "exact"
    HIGH = "high"
    HEURISTIC = "heuristic"
    NONE = "none"


class Provenance(StrEnum):
    """Where a claim came from (§5.4). Never blended — every edge/fact carries one."""

    MACHINE_PROVEN = "machine-proven"
    CONFIG_RESOLVED = "config-resolved"
    HEURISTIC = "heuristic"
    LLM_GUESSED = "llm-guessed"
    HUMAN_ASSERTED = "human-asserted"
    FEDERATED = "federated"


class ServiceKind(StrEnum):
    """v1: service. Reserved for Phase 9 (§7): function, edge-worker, firmware."""

    SERVICE = "service"
    FUNCTION = "function"
    EDGE_WORKER = "edge-worker"
    FIRMWARE = "firmware"


class TriggerKind(StrEnum):
    """v1: http. Reserved (§7): queue, stream, schedule."""

    HTTP = "http"
    QUEUE = "queue"
    STREAM = "stream"
    SCHEDULE = "schedule"


class IcfgNodeKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    STATEMENT = "statement"
    BRANCH = "branch"
    LOOP = "loop"
    CALL = "call"
    RETURN = "return"


class IcfgEdgeKind(StrEnum):
    FLOW = "flow"
    TRUE_BRANCH = "true"
    FALSE_BRANCH = "false"
    CALL = "call"
    RETURN = "return"
    EXCEPTION = "exception"


class SinkKind(StrEnum):
    """Sink classification mirroring the ``sink=`` tag namespace."""

    DB = "db"
    HTTP_CLIENT = "http-client"
    MQ = "mq"


class MqDirection(StrEnum):
    PUBLISH = "publish"
    CONSUME = "consume"


class SourceVariant(StrEnum):
    """Whether an anchor refers to original repo text or a generated variant (§5.3).

    ``GENERATED`` marks preprocessor output (e.g. delombok'ed Java) — the text
    that was actually analyzed, served by source-on-demand with a badge.
    """

    ORIGINAL = "original"
    GENERATED = "generated"


class JobType(StrEnum):
    FETCH = "fetch"
    EXTRACT = "extract"
    STITCH = "stitch"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SnapshotStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
