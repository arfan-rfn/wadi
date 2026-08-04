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


class TargetKind(StrEnum):
    """What a stitched edge lands on (§5.4.2) — the three target kinds that
    keep partial coverage honest, plus the explicit undetermined fact (P10)."""

    ANALYZED = "analyzed"
    EXTERNAL = "external"
    PLACEHOLDER = "placeholder"
    UNDETERMINED = "undetermined"


class ServiceKind(StrEnum):
    """v1: service | library. Reserved for Phase 9 (§7): function, edge-worker, firmware.

    ``library`` (§5.2.6): an in-repo module other services depend on — never
    analyzed as a service (no endpoints, no own CPG); its sources join each
    dependent service's staged parse. Recorded so classification is queryable.
    """

    SERVICE = "service"
    LIBRARY = "library"
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
    """Intra-method flow labels plus interprocedural call/return.

    1.8.0 (§5.2.8): ``case``/``default`` (switch selector → arm, case values on
    the edge), ``fallthrough`` (case body → next arm), and ``exception``
    (try-tail → catch handler) gain writers; cycle-closing loop edges carry the
    edge-level ``back`` flag rather than a kind of their own (an edge can be
    both a ``true`` body edge and a back edge — do-while).
    """

    FLOW = "flow"
    TRUE_BRANCH = "true"
    FALSE_BRANCH = "false"
    CASE = "case"
    DEFAULT = "default"
    FALLTHROUGH = "fallthrough"
    CALL = "call"
    RETURN = "return"
    EXCEPTION = "exception"


class SinkKind(StrEnum):
    """Sink classification mirroring the ``sink=`` tag namespace."""

    DB = "db"
    HTTP_CLIENT = "http-client"
    HTTP_CLIENT_SUSPECTED = "http-client-suspected"
    MQ = "mq"


class CalleeUnboundReason(StrEnum):
    """Why a call node's target has no interior in the graph (§5.4.2 T5).

    These are *not* failures to report as errors. A Lombok accessor has no
    source body by construction; a JDK method is not the system's code. The
    reason exists so a consumer can render "no source to analyse, because X"
    rather than a node that dead-ends for no stated cause — which is
    indistinguishable from a hole in the map, and is what made a correct
    extraction read as data loss (P10).
    """

    LOMBOK_GENERATED = "lombok-generated"
    """Synthesized by Lombok; analysis runs on original source (§5.3) so no
    body exists to show. 92.9% of unbound calls on the train-ticket benchmark."""

    INHERITED_EXTERNAL = "inherited-external"
    """Declared by an external supertype (e.g. Spring Data ``CrudRepository``)."""

    COMPILER_GENERATED = "compiler-generated"
    """Enum ``values``/``valueOf`` — emitted by javac, absent from source."""

    THIRD_PARTY = "third-party"
    """Declaring type is in no staged source root (JDK, framework)."""

    AMBIGUOUS_OVERLOAD = "ambiguous-overload"
    """Several first-party overloads match and the receiver could not be
    bound to one — never guessed."""

    UNRESOLVED_RECEIVER = "unresolved-receiver"
    """First-party type declaring no such method: a static import attributed
    to the importing class, or an unbindable receiver type."""


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
