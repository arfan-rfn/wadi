"""The bulk-export contract between joern-platform (Scala) and the worker (§5.1).

``wadi.WadiPipeline.run`` writes one ``export.json`` per (service x language)
to the shared workspace volume; the worker validates it against these models.
Versioned like every wadi contract: additive change → minor bump; breaking →
major bump plus a matching change in the Scala exporter (both sides pin this
version and refuse mismatched majors).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

EXPORT_SCHEMA_VERSION = "2.0.0"
"""Reader migration note (1.x → 2.0.0): sinks became one row PER CANDIDATE
URL — ``node_id`` is no longer unique across sink rows (group by it); every
sink row carries ``call_id`` (the inner CALL node) and optional ``evidence`` /
``auth_propagation``; ``value_confidence`` gained ``high``; endpoints gained
``params``; new top-level ``security_rules`` and ``config_refs`` sections."""


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


class ExportCall(ExportModelBase):
    """Call metadata on a CALL cfg node."""

    callee_full_name: str
    callee_id: int | None = Field(
        default=None, description="Joern id of the callee method when it is in this export"
    )
    resolved: bool = Field(description="Static target known (incl. via DI pass)")
    via_di: bool = False


class ExportCfgNode(ExportModelBase):
    id: int
    kind: CfgNodeKind
    code: str
    line: int = Field(ge=0)
    line_end: int = Field(ge=0)
    call: ExportCall | None = None
    condition_code: str | None = Field(
        default=None, description="Branch/loop condition expression text"
    )


class ExportCfgEdgeLabel(StrEnum):
    FLOW = "flow"
    TRUE = "true"
    FALSE = "false"


class ExportCfgEdge(ExportModelBase):
    source: int
    target: int
    label: ExportCfgEdgeLabel = ExportCfgEdgeLabel.FLOW


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


class ExportEndpoint(ExportModelBase):
    method_id: int = Field(description="Handler method's Joern id")
    http_method: str
    uri: str
    auth_tags: list[str] = Field(
        default_factory=list[str],
        description="Registered auth= tags on the handler (raw annotation evidence)",
    )
    params: list[ExportEndpointParam] = Field(default_factory=list[ExportEndpointParam])


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


class ServiceExport(ExportModelBase):
    """The complete per-(service x language) export document."""

    export_schema_version: str = EXPORT_SCHEMA_VERSION
    language: str
    methods: list[ExportMethod]
    cfgs: list[ExportCfg]
    endpoints: list[ExportEndpoint]
    sinks: list[ExportSink]
    data_models: list[ExportDataModel] = Field(default_factory=list[ExportDataModel])
    security_rules: list[ExportSecurityRule] = Field(default_factory=list[ExportSecurityRule])
    config_refs: list[ExportConfigRef] = Field(default_factory=list[ExportConfigRef])

    def compatible_with_reader(self) -> bool:
        """Major versions must match between exporter and reader."""
        return self.export_schema_version.split(".", 1)[0] == EXPORT_SCHEMA_VERSION.split(".", 1)[0]
