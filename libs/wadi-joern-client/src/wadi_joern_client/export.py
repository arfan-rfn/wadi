"""The bulk-export contract between joern-platform (Scala) and the worker (§5.1).

``wadi.WadiPipeline.run`` writes one ``export.json`` per (service x language)
to the shared workspace volume; the worker validates it against these models.
Versioned like every wadi contract: additive change → minor bump; breaking →
major bump plus a matching change in the Scala exporter (both sides pin this
version and refuse mismatched majors).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

EXPORT_SCHEMA_VERSION = "2.6.0"
"""Reader migration note (1.x → 2.0.0): sinks became one row PER CANDIDATE
URL — ``node_id`` is no longer unique across sink rows (group by it); every
sink row carries ``call_id`` (the inner CALL node) and optional ``evidence`` /
``auth_propagation``; ``value_confidence`` gained ``high``; endpoints gained
``params``; new top-level ``security_rules`` and ``config_refs`` sections.

2.1.0 (additive, §5.2.5): new top-level ``unreachable_sinks`` inventory
(http-client sinks outside the endpoint closure, with inline anchors — their
methods are not in the export); sink ``kind`` may be
``http-client-suspected`` (unresolved receiver type); ``mechanism`` may be
``webclient`` / ``unknown``.

2.2.0 (additive, §5.4.3): new top-level ``analysis_coverage`` counts —
production methods in the CPG vs. the endpoint-reachable subset; ``None``
when the export predates the metric (never conflated with zero, P10).

2.3.0 (additive, §5.2.7): endpoints carry ``request_schema`` /
``response_schema`` — recovered field-level wire shapes with honest
``unresolved``/``cycle``/``truncated`` terminals.

2.4.0 (additive, §5.4.2 T4): new top-level ``async_roots`` (non-endpoint
reachability roots); the closure is rooted at endpoints + async roots.

2.5.0 (additive, §5.2.8): cfg nodes carry ``construct_kind`` (which Java construct
this node is: if/switch/switch-arrow/for/foreach/while/do-while/try/catch/
finally/throw/break/continue/goto) and real ``line_end`` extents; a SWITCH is
a ``branch`` node keeping its selector as ``condition_code``; edge labels gain
``case`` (with ``case_values``), ``default``, ``fallthrough``, ``exception``,
plus a ``back`` flag on cycle-closing loop edges; catch/finally handlers are
graph nodes; sinks inside conditions/throws/for-headers attach to their
statement (their calls appear on branch/loop/statement nodes).

2.6.0 (additive, §5.4.2 T5): a call that binds to no method in the export
carries ``unbound_reason`` — why it dead-ends, so a consumer can tell a
Lombok-generated accessor (no source exists) from a hole in the map. On the
train-ticket benchmark 92.9% of unbound calls are ``lombok-generated``;
``None`` on every call that bound normally. 2.6.0 also carries the §5.2.8 T3
label corrections — a semantics change inside the existing edge vocabulary,
so no field moves: an ``if`` whose arm holds no statements labels its join
edge for that arm instead of dropping to ``flow`` (both arms empty stays
``flow``, a recorded non-representable), and an empty try body routes its
handlers as ``exception`` plus an explicit normal-completion edge."""


class ExportModelBase(BaseModel):
    # extra="forbid": a field the worker doesn't know means schema drift — fail loudly.
    model_config = ConfigDict(extra="forbid")


class ExportParam(ExportModelBase):
    name: str
    type_name: str | None = None


class ExportMethod(ExportModelBase):
    """One method in the endpoint-reachable closure."""

    id: int = Field(description="Joern node id — stable only within this export")
    full_name: str = Field(description="Fully-qualified name incl. signature")
    signature: str
    filename: str = Field(description="Path relative to the build root")
    line: int = Field(ge=0, description="0 = unknown (synthetic/library method)")
    line_end: int = Field(ge=0)
    code: str = Field(description="First line of the method definition")
    doc_comment: str | None = None
    return_type: str | None = None
    params: list[ExportParam] = Field(default_factory=list[ExportParam])
    tags: list[str] = Field(default_factory=list[str])


class CfgNodeKind(StrEnum):
    STATEMENT = "statement"
    BRANCH = "branch"
    LOOP = "loop"
    CALL = "call"
    RETURN = "return"


class UnboundReason(StrEnum):
    """Why a call binds to no method in the export (§5.4.2 T5).

    An unbindable call keeps its CFG node — deleting it would make the map lie
    about what runs — so the node needs a reason a human can act on. These are
    facts about *why analysis cannot open the callee*, not error codes.
    """

    LOMBOK_GENERATED = "lombok-generated"
    """Accessor/constructor synthesized by Lombok. Joern analyses the ORIGINAL
    source (``--delombok-mode types-only``, §5.3) so anchors stay on committed
    text — the body genuinely does not exist to show."""

    INHERITED_EXTERNAL = "inherited-external"
    """Declared by an external supertype (Spring Data ``CrudRepository.save``);
    the first-party type only inherits the name."""

    COMPILER_GENERATED = "compiler-generated"
    """``values``/``valueOf`` on an enum — emitted by javac, absent from source."""

    THIRD_PARTY = "third-party"
    """The declaring type is in no staged source root (JDK, framework)."""

    AMBIGUOUS_OVERLOAD = "ambiguous-overload"
    """First-party type declaring several overloads of this name; the receiver
    could not be bound to one, and P10 forbids guessing."""

    UNRESOLVED_RECEIVER = "unresolved-receiver"
    """First-party type in the CPG that declares no such method: a static
    import attributed to the importing class, or an unbindable receiver."""


class ExportCall(ExportModelBase):
    """Call metadata on a CALL cfg node."""

    callee_full_name: str
    callee_id: int | None = Field(
        default=None, description="Joern id of the callee method when it is in this export"
    )
    resolved: bool = Field(description="Static target known (incl. via DI pass)")
    via_di: bool = False
    unbound_reason: UnboundReason | None = Field(
        default=None,
        description=(
            "Why this call binds to no method in the export (§5.4.2 T5); None when it bound. "
            "Absent on pre-2.6.0 exports, which is not the same as 'it bound' (P10)."
        ),
    )


class ExportCfgNode(ExportModelBase):
    id: int
    kind: CfgNodeKind
    code: str
    line: int = Field(ge=0)
    line_end: int = Field(ge=0)
    construct_kind: str | None = Field(
        default=None,
        description=(
            "Which Java construct this node is (§5.2.8): if | switch | "
            "switch-arrow | for | foreach | while | do-while | try | catch | "
            "finally | throw | break | continue | goto. None = plain statement "
            "or exporter predates 2.5.0. (Named construct_kind because "
            "pydantic reserves `construct`.)"
        ),
    )
    call: ExportCall | None = None
    condition_code: str | None = Field(
        default=None,
        description="Branch/loop condition or switch selector expression text",
    )


class ExportCfgEdgeLabel(StrEnum):
    FLOW = "flow"
    TRUE = "true"
    FALSE = "false"
    CASE = "case"
    DEFAULT = "default"
    FALLTHROUGH = "fallthrough"
    EXCEPTION = "exception"


class ExportCfgEdge(ExportModelBase):
    source: int
    target: int
    label: ExportCfgEdgeLabel = ExportCfgEdgeLabel.FLOW
    case_values: list[str] = Field(
        default_factory=list[str],
        description="Stacked case labels on a `case` edge (source text of each value)",
    )
    back: bool = Field(
        default=False, description="Cycle-closing loop edge (§5.2.8 back-edge marking)"
    )


class ExportCfg(ExportModelBase):
    """Statement-coarsened CFG of one method."""

    method_id: int
    nodes: list[ExportCfgNode]
    edges: list[ExportCfgEdge]


class ExportEndpointParam(ExportModelBase):
    """One declared endpoint parameter (from mapping annotations)."""

    name: str
    location: str = Field(description="'path' | 'query' | 'body' | 'header'")
    type_name: str | None = None
    required: bool = True


class ExportTypeShape(ExportModelBase):
    """A recovered wire shape (§5.2.7) — mirrors the contract TypeShape."""

    kind: str = Field(description="object|scalar|array|map|cycle|truncated|unresolved")
    type_name: str
    fields: list["ExportFieldShape"] = Field(default_factory=lambda: [])
    element: "ExportTypeShape | None" = None


class ExportFieldShape(ExportModelBase):
    name: str = Field(description="Serialized name (@JsonProperty applied)")
    java_name: str | None = None
    shape: ExportTypeShape


class ExportEndpoint(ExportModelBase):
    method_id: int = Field(description="Handler method's Joern id")
    http_method: str
    uri: str
    auth_tags: list[str] = Field(
        default_factory=list[str],
        description="Registered auth= tags on the handler (raw annotation evidence)",
    )
    params: list[ExportEndpointParam] = Field(default_factory=list[ExportEndpointParam])
    request_schema: ExportTypeShape | None = None
    response_schema: ExportTypeShape | None = None


class SinkValueConfidence(StrEnum):
    EXACT = "exact"
    HIGH = "high"
    HEURISTIC = "heuristic"
    NONE = "none"


class ExportSink(ExportModelBase):
    """One candidate value for a tagged sink call site (db / http-client / mq:<broker>).

    Since 2.0.0 a multi-valued slice emits one row per candidate URL/topic:
    rows sharing ``node_id`` (and ``call_id``) are the same call site with
    branch-dependent targets (§5.2 over-approximation).
    """

    node_id: int = Field(description="The coarsened statement cfg node id of the sink site")
    call_id: int = Field(description="The inner CALL node id (exact dedup key per site)")
    method_id: int = Field(description="Method containing the sink")
    kind: str = Field(description="Registered sink tag value: db | http-client | mq:<broker>")
    value: str | None = Field(
        default=None, description="Sliced URL/topic candidate; None = undetermined (P10)"
    )
    value_confidence: SinkValueConfidence = SinkValueConfidence.NONE
    http_verb: str | None = None
    mechanism: str | None = Field(default=None, description="e.g. 'resttemplate'")
    evidence: str | None = Field(
        default=None, description="Human-readable slice trace behind this candidate"
    )
    auth_propagation: str | None = Field(
        default=None,
        description="'authorization-header' | 'feign-interceptor' when statically visible",
    )


class ExportAnchor(ExportModelBase):
    """A file:line evidence anchor for facts outside the method closure."""

    file: str
    line: int = Field(ge=0)


class ExportUnreachableSink(ExportSink):
    """An http-client sink outside the endpoint-reachable closure (§5.2.5).

    Excluded from the map by design; inventoried so the exclusion is queryable
    (P10) and cross-tool comparisons can reconcile counts. Anchors are inline
    because the enclosing method is not exported.
    """

    method_full_name: str
    file: str
    line: int = Field(ge=0)


class ExportSecurityRule(ExportModelBase):
    """One SecurityFilterChain DSL rule (collected CPG-wide; §5.1).

    Pattern → endpoint pairing is deliberately NOT done in Scala — wrong
    security facts are worse than absent ones (§12); the worker matches.
    """

    pattern: str = Field(description="Ant-style pattern, e.g. '/admin/**'")
    http_method: str | None = Field(default=None, description="Verb restriction, when present")
    access: str = Field(description="Raw access expression, e.g. \"hasRole('ADMIN')\"")
    kind: str = Field(description="'filter-chain'")
    anchor: ExportAnchor
    evidence: str = Field(description="First line of the rule's source text")


class ExportConfigRef(ExportModelBase):
    """One @Value("${key}") config-key reference found in code (§5.2.4)."""

    key: str
    default: str | None = None
    anchor: ExportAnchor
    context: str = Field(description="First line of the referencing declaration")


class ExportDataModel(ExportModelBase):
    entity: str
    fields: list[ExportParam] = Field(default_factory=list[ExportParam])
    persistence_framework: str
    storage_name: str | None = None


class ExportAnalysisCoverage(ExportModelBase):
    """Analysis-coverage counts (§5.4.3): production methods vs. the
    endpoint-reachable subset, computed in-CPG under identical filters
    (internal, non-synthetic, concrete, service-own sources)."""

    production_methods: int = Field(ge=0)
    reachable_production_methods: int = Field(ge=0)


class ExportAsyncRoot(ExportModelBase):
    """A non-endpoint reachability root (§5.4.2 T4): a method the framework
    invokes without an HTTP request. One row per (method, kind)."""

    method_id: int
    kind: str


class ServiceExport(ExportModelBase):
    """The complete per-(service x language) export document."""

    export_schema_version: str = EXPORT_SCHEMA_VERSION
    language: str
    methods: list[ExportMethod]
    cfgs: list[ExportCfg]
    endpoints: list[ExportEndpoint]
    async_roots: list[ExportAsyncRoot] = Field(
        default_factory=list[ExportAsyncRoot],
        description="Empty also when the exporter predates 2.4.0 (T4)",
    )
    sinks: list[ExportSink]
    unreachable_sinks: list[ExportUnreachableSink] = Field(
        default_factory=list[ExportUnreachableSink]
    )
    data_models: list[ExportDataModel] = Field(default_factory=list[ExportDataModel])
    security_rules: list[ExportSecurityRule] = Field(default_factory=list[ExportSecurityRule])
    config_refs: list[ExportConfigRef] = Field(default_factory=list[ExportConfigRef])
    analysis_coverage: ExportAnalysisCoverage | None = Field(
        default=None, description="None = exporter predates 2.2.0 (unknown, not zero — P10)"
    )

    def compatible_with_reader(self) -> bool:
        """Major versions must match between exporter and reader."""
        return self.export_schema_version.split(".", 1)[0] == EXPORT_SCHEMA_VERSION.split(".", 1)[0]
