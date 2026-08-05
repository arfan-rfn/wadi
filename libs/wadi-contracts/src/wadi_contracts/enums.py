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


class CfgAnomalyCode(StrEnum):
    """§5.2.8 M2 structural-invariant violation codes.

    Evaluated against the RAW exported CFG of every method on every snapshot —
    before the assembler's synthetic entry/exit patching, which would make
    reachability invariants vacuously true. Additive changes bump
    ``SCHEMA_VERSION`` minor.

    An enum rather than a string registry (§7, recorded 2026-08-05): pyright
    catches producer/registry drift in CI, which a runtime validator could
    only catch on a user's repository.
    """

    DISCONNECTED_NODE = "disconnected-node"
    """A node (beyond the method's entry statement) with no incoming raw edge:
    the assembler's synthetic patching would silently present it as a second
    entry point (§5.2.8 — the pre-M1 synchronized class)."""

    BRANCH_ARITY = "branch-arity"
    """A branch or loop that names NO outcome at all — no arm edge of any kind,
    or a switch with no case/default arm. Reformulated by §5.2.8 T3: a
    *missing* arm is no longer evidence of anything, since the arm may simply
    leave the method (the export is deliberately exit-free) and the assembler
    completes it against its exit node."""

    UNLABELED_ARM = "unlabeled-arm"
    """A ``flow`` edge among several successors of a branch or loop: the
    statement coarsening could not say which way control went (§5.2.8 T3).
    Kept countable apart from ``BRANCH_ARITY`` — naming no outcome and naming
    one badly are different defects. A construct whose ONLY successor is
    unlabeled is the recorded convergent case (``if (c) { }`` — one edge cannot
    carry two labels), not a finding."""

    LOOP_NO_BACK_EDGE = "loop-no-back-edge"
    """A loop with body edges but no cycle-closing back edge. Suppressed for
    empty-body loops (recorded §5.2.8 non-representable)."""

    DANGLING_EDGE = "dangling-edge"
    """An edge endpoint that references no exported node."""

    EXIT_UNREACHABLE = "exit-unreachable"
    """No return statement and every node has a successor: flow can never leave
    the method (a pure cycle) — either dead code or a graph bug."""


class AuthGapCode(StrEnum):
    """§5.2.10 auth-extraction gap codes — the independent oracle's findings.

    ``AuthCoverageSection`` counts what the auth layer *emitted*, so it can
    only see enforcement wadi already read; a construct dropped before
    emission contributes to none of its counters and leaves the endpoint
    looking cleanly authenticated. That is how 365 train-ticket-aitest
    endpoints published a confident wrong claim while the tracker read zero.

    These codes come from a second, deliberately dumb reading of the SOURCE
    TEXT that shares no code path with the CPG — so a gap here means "the file
    says something the graph did not", which no emission-derived counter can
    express. Never fatal: a gap is a queryable fact about how far to trust the
    auth answer (P10).

    An enum rather than a string registry (§7): pyright catches producer /
    registry drift in CI, which a runtime validator could only catch on a
    user's repository.
    """

    UNEMITTED_ACCESS_SITE = "unemitted-access-site"
    """A security config names more access calls than the export produced rule
    sites for. The signature of a chain shape the pass cannot read — the
    variable-receiver drop that this whole section exists for."""

    UNREAD_SECURITY_CONFIG = "unread-security-config"
    """A file that configures a filter chain produced NO rules at all. The
    strongest form of the gap above, and worth its own code: a partially-read
    config still governs, while a wholly-unread one means every endpoint under
    it is answered from some other chain — or from nothing."""

    UNRESOLVED_SCOPE = "unresolved-scope"
    """Sites that emitted but whose pattern could not be read
    (``pattern_confidence = none``). Not a drop — this is the system working —
    but it is the measured demand that schedules the next resolution tranche,
    and it must stay visible rather than being absorbed into ``withheld``."""

    REACTIVE_CHAIN = "reactive-chain"
    """WebFlux security (``ServerHttpSecurity`` / ``authorizeExchange`` /
    ``pathMatchers``) present in source. Tracked separately because a reactive
    service's rules are a different vocabulary, and counting them as ordinary
    unresolved scope would hide an entire stack behind a generic number."""


class ClientLibrary(StrEnum):
    """Client-library census vocabulary (§5.4.2).

    The worker detects these by deterministic import scan; presence is a fact,
    call counts are not claimed (an import is not a call — P10). See
    ``MODELLED_CLIENT_LIBRARIES`` for the subset wadi's sink passes model.
    """

    RESTTEMPLATE = "resttemplate"
    WEBCLIENT = "webclient"
    FEIGN = "feign"
    RESTCLIENT = "restclient"
    HTTP_INTERFACE = "http-interface"
    JDK_HTTPCLIENT = "jdk-httpclient"
    OKHTTP = "okhttp"
    RETROFIT = "retrofit"
    APACHE_HTTPCLIENT = "apache-httpclient"
    UNIREST = "unirest"


class UnresolvedReasonCode(StrEnum):
    """Versioned reason-code vocabulary (§5.4.2) — the queryable-gap registry.

    Additive changes bump ``SCHEMA_VERSION`` minor.

    Two removals, same reason — registered but never emitted, which for a gap
    registry is worse than absent: a consumer filtering for the code cannot
    tell "no such gaps" from "never implemented" (§7 liveness rule).

    * ``host-unresolvable`` (1.2.0): unresolved hosts classify as
      external/placeholder nodes instead.
    * ``unresolved-receiver-type`` (1.16.0): an HTTP-shaped call whose receiver
      javasrc2cpg could not resolve is a **suspected sink**, carried by
      ``RemoteCall.suspected`` and counted by
      ``CoverageTotals.suspected_call_sites`` — which the stitcher deliberately
      excludes from ``call_sites``. Emitting it here too would double-represent
      the same sites across two populations and break that reconciliation. A
      suspected sink is a call fact carrying a doubt; an unresolved entry is a
      resolution that failed. §5.4.2 keeps the name as prose for the mechanism.

    The ``unsupported-idiom:<name>`` prefix family (a *named* unmodelled
    construct; the slicer marks the idiom, the matcher lifts it into the code)
    is dynamic and therefore validated separately, not enumerated here.
    """

    URL_UNDETERMINED = "url-undetermined"
    URL_UNPARSEABLE = "url-unparseable"
    NO_ENDPOINT_MATCH = "no-endpoint-match"
    LOMBOK_GENERATED_INTERIOR = "lombok-generated-interior"
    SLICE_BUDGET_TRUNCATED = "slice-budget-truncated"
    BASE_UNDETERMINED = "base-undetermined"
    """A relative URL whose client base is not statically recoverable — the
    rootUri/baseUrl split (T2), added 1.5.0."""


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
