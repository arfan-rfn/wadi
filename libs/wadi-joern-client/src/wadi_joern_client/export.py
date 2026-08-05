"""The bulk-export contract between joern-platform (Scala) and the worker (§5.1).

``wadi.WadiPipeline.run`` writes one ``export.json`` per (service x language)
to the shared workspace volume; the worker validates it against these models.
Versioned like every wadi contract: additive change → minor bump; breaking →
major bump plus a matching change in the Scala exporter (both sides pin this
version and refuse mismatched majors).
"""

from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXPORT_SCHEMA_VERSION = "2.10.0"
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
handlers as ``exception`` plus an explicit normal-completion edge.

2.7.0 (additive, §5.2.9): security rules gained ``chain_id``/``chain_pattern``
so first-match-wins applies within a chain rather than across a pooled list,
and a rule whose pattern could not be read now arrives with ``pattern="{?}"``
instead of being dropped — the change that stops an unreadable rule from
falling through to a later ``permitAll``. New top-level ``auth_enforcements``
section for gating constructs that carry no rule at all (chain bypasses,
interceptors, servlet filters, aspects, in-handler checks). Readers of 2.6.0
still parse: both additions default to empty/None.

2.8.0 (§5.2.10): a security rule is now a **site record**. It gained
``call_id`` (the access call's CPG id — rows sharing it are one site with
several patterns), ``pattern`` became nullable, and ``pattern_confidence``
(``exact``/``config``/``none``) replaces the ``{?}`` sentinel. The reason is
structural, not cosmetic: with the sentinel living inside a required field,
only a code path that had already resolved a matcher could emit it, so a chain
whose SHAPE was unreadable (the ``AuthorizedUrl`` parked in a local variable,
which config-driven Spring code must do) erased its site instead of degrading
it — 365 train-ticket-aitest endpoints published as confidently authenticated
with zero roles and zero withheld claims. Every detected access site now emits
a row, asserted by an export-time invariant. Pre-2.8.0 documents still parse:
the sentinels are normalized into the new fields on load.

2.9.0 (additive, §5.2.7 amended): wire shapes carry ``origin``
(``declared``/``return-expression``). A handler declaring a RAW wrapper —
``public HttpEntity query(...)``, which train-ticket-aitest writes 376 times
against 9 generic ones — leaves no type argument to unwrap, so the shape
terminated at ``unresolved`` on 274 of 365 endpoints. The payload is instead
read from the return expression (``ok(expr)``, ``new ResponseEntity<>(expr,
…)``), and ``origin`` keeps that inference distinguishable from a shape the
signature actually declared (P7). Recovery never overrides a declared generic
and yields nothing unless every return agrees. Pre-2.9.0 documents still
parse: ``origin`` defaults to ``declared``, which is what they were.

2.10.0 (additive, §5.2.11 T4): http-client sinks carry
``auth_propagation_state`` (``forwarded`` | ``not-forwarded`` |
``undetermined``). ``auth_propagation`` names the MECHANISM and was null on
382/382 train-ticket-aitest calls, because the only detector looked for a
literal ``"Authorization"`` anywhere in the enclosing method — which on that
corpus appears solely inside ``JWTUtil``, where inbound tokens are READ and no
outbound sink exists. The forwarding idiom it missed is
``new HttpEntity(body, headers)`` (5 sites), and the far more common shape is
``new HttpEntity(null)`` (98 sites): a provable NEGATIVE, which the old
nullable field could not express apart from "we did not look". Resolution is
per CALL SITE, because one method routinely builds both. Pre-2.10.0 documents
still parse as ``undetermined``, which is what a null meant."""


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
    """The receiver's TYPE is a javasrc2cpg sentinel — unbindable, so nothing
    downstream can name the callee."""

    DECLARED_NOT_BOUND = "declared-not-bound"
    """The first-party type declares exactly this method and the call still did
    not bind. The one actionable bucket (§5.2.11 T5): every other code here
    describes something analysis cannot see; this describes something it saw
    and failed to connect."""

    NOT_DECLARED = "not-declared"
    """A first-party type in the CPG that declares no such method — a static
    import attributed to the importing class (``ok(…)`` from
    ``ResponseEntity.ok``). Not a hole: the callee is real and elsewhere."""

    UNPARSEABLE_CALLEE = "unparseable-callee"
    """The callee name carries no type qualifier to split on."""


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
    origin: str = Field(
        default="declared",
        description="declared|return-expression (§5.2.7); absent on pre-2.9.0 exports",
    )
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
    auth_propagation_state: str = Field(
        default="undetermined",
        description=(
            "forwarded | not-forwarded | undetermined (§5.2.11 T4). "
            "'undetermined' on pre-2.10.0 exports, which is what they meant"
        ),
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


CONFIG_PREFIX = "@"
"""A rule whose patterns live in config, not code (§5.2.9 D5).

The value is ``@<@ConfigurationProperties prefix>``. Distinct from
``UNRESOLVABLE_PATTERN`` on purpose: one says "unreadable", this says
"readable, but not from the Java" — the worker correlates it against the
parsed config tree and recovers the real rules.
"""

UNRESOLVABLE_PATTERN = "{?}"
"""Legacy spelling of "read but unresolvable" (pre-2.8.0; §5.2.9).

Superseded by ``pattern=None`` + ``RulePatternConfidence.NONE`` (§5.2.10): a
sentinel inside a REQUIRED field can only be produced by a code path that
already succeeded structurally, which is exactly why an unreadable chain
*shape* erased its site instead of degrading it. Retained so the worker keeps
reading pre-2.8.0 exports, and normalized away on load.
"""


class RulePatternConfidence(StrEnum):
    """How well a rule's scope could be read (§5.2.10).

    Mirrors ``SinkValueConfidence``, and for the same reason: resolution
    failure must degrade a FIELD, never erase the site. ``CONFIG`` is not a
    lesser ``EXACT`` — it says "readable, but not from the Java", and the
    worker recovers the real patterns by correlating the binding against the
    parsed config tree.
    """

    EXACT = "exact"
    CONFIG = "config"
    NONE = "none"


class ExportSecurityRule(ExportModelBase):
    """One SecurityFilterChain DSL rule (collected CPG-wide; §5.1).

    Pattern → endpoint pairing is deliberately NOT done in Scala — wrong
    security facts are worse than absent ones (§12); the worker matches.

    Since 2.8.0 (§5.2.10) this is a **site record**, not merely a rule: every
    access call the vocabulary detects produces at least one row, keyed by
    ``call_id``, whether or not any of its facts could be resolved. Rows
    sharing a ``call_id`` are one site with several patterns
    (``requestMatchers("/a", "/b")``), the same way sink rows share
    ``node_id``. The invariant that makes the drop impossible — every detected
    access site appears here — is asserted at export time, because a pass that
    cannot drop cannot regress.
    """

    call_id: int = Field(
        default=0,
        description=(
            "2.8.0: CPG id of the access call — the SITE identity. Rows sharing "
            "it are one call site with several patterns. 0 in pre-2.8.0 exports"
        ),
    )
    pattern: str | None = Field(
        default=None,
        description=(
            "Ant-style pattern, e.g. '/admin/**'. None = the site was detected "
            "and its scope could not be read (2.8.0; formerly '{?}')"
        ),
    )
    pattern_confidence: RulePatternConfidence = Field(
        default=RulePatternConfidence.NONE,
        description="2.8.0: how the pattern was obtained — exact | config | none",
    )
    http_method: str | None = Field(default=None, description="Verb restriction, when present")
    access: str = Field(description="Raw access expression, e.g. \"hasRole('ADMIN')\"")
    kind: str = Field(description="'filter-chain'")
    chain_id: str | None = Field(
        default=None,
        description=(
            "2.7.0: the bean/override that declared this rule. First-match-wins "
            "applies WITHIN a chain — a service with several chains must not have "
            "its rules pooled into one list (§5.2.9)"
        ),
    )
    chain_pattern: str | None = Field(
        default=None,
        description="2.7.0: chain-level securityMatcher/antMatcher scope, when declared",
    )
    anchor: ExportAnchor
    evidence: str = Field(description="First line of the rule's source text")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_pattern(cls, data: object) -> object:
        """Pre-2.8.0 exports carry the sentinels inside ``pattern`` (§5.2.10).

        Normalized on load rather than handled at every read site, so exactly
        one place in the codebase knows the old spelling existed.
        """
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        if "pattern_confidence" in values:
            return values
        pattern = values.get("pattern")
        if not isinstance(pattern, str):
            return values
        if pattern == UNRESOLVABLE_PATTERN:
            values["pattern"] = None
            values["pattern_confidence"] = RulePatternConfidence.NONE
        elif pattern.startswith(CONFIG_PREFIX):
            values["pattern_confidence"] = RulePatternConfidence.CONFIG
        else:
            values["pattern_confidence"] = RulePatternConfidence.EXACT
        return values

    @property
    def resolvable(self) -> bool:
        """True only when this rule's scope is known well enough to match on.

        A ``CONFIG`` pattern counts as UNresolvable here: until the worker has
        correlated it against config it is exactly as unreadable as a missing
        one, and treating it otherwise would let it match nothing and fall
        through — the §5.2.9 failure mode.
        """
        return self.pattern_confidence is RulePatternConfidence.EXACT


class ExportAuthPolicy(ExportModelBase):
    """Request-level policy that is not an authorization rule (2.8.0; §5.2.10).

    CORS, CSRF and rejection handling — the third category a ``SecurityConfig``
    declares, and the one wadi had no vocabulary for. CORS alone is the second
    most common construct across the 76 security configs measured.

    Deliberately NOT an input to ``EndpointAuth``: a CORS policy decides which
    ORIGIN may call, not which principal, and folding it into ``authenticated``
    would answer a different question than the one asked. These are published
    so the question becomes answerable at all (P10) — absent facts made
    present, never facts made wrong.
    """

    kind: str = Field(
        description="cors | csrf-disabled | csrf-exempt | entry-point | access-denied"
    )
    scope: str = Field(description="Path scope; '{?}' = read but unresolvable")
    detail: str = Field(description="Origins, or the source text of the decision")
    anchor: ExportAnchor


class ExportAuthorityModel(ExportModelBase):
    """What a grant MEANS and where it is minted (2.8.0; §5.2.10 T7).

    ``role-hierarchy`` | ``authority-defaults`` | ``jwt-claim-converter`` |
    ``user-details-service``.

    None of these gate a request, so none withholds a claim. Two of them can
    still falsify a role list wadi already publishes: under
    ``ROLE_ADMIN > ROLE_USER`` an endpoint reported as requiring ``[USER]`` is
    also reachable by ADMIN, and a ``GrantedAuthorityDefaults`` prefix rewires
    the very ``hasRole`` → authority mapping the role/authority split assumes.
    A role list that under-states who can get in is a confident wrong security
    fact, so the worker marks it incomplete rather than hiding the cause.
    """

    kind: str
    detail: str
    anchor: ExportAnchor


class ExportAuthExtraction(ExportModelBase):
    """What the auth vocabulary saw versus what it emitted (2.8.0; §5.2.10).

    The in-graph half of the no-drop invariant. ``access_calls_seen`` counts
    every access-vocabulary name in the CPG with no scope test applied, so it
    cannot be talked down by the same predicate that decides emission.

    The two counts are NOT expected to be equal — ``access``, ``authenticated``
    and ``anonymous`` are ordinary words, and a business method named
    ``access()`` raises the first without belonging in the second. The GAP is
    the signal, reconciled worker-side against an independent source-text
    oracle so an unreadable chain shape announces itself as a number instead of
    publishing a confident wrong claim.
    """

    access_calls_seen: int = Field(default=0, ge=0)
    rule_sites_emitted: int = Field(default=0, ge=0)


class ExportAuthEnforcement(ExportModelBase):
    """A gating construct with no security-framework rule behind it (§5.2.9).

    Chain bypasses, interceptors, servlet filters, aspects and in-handler
    checks. These carry no access call, which is precisely why the rule pass
    cannot see them — and an endpoint guarded by something wadi cannot read is
    the one a reader most needs told about.
    """

    kind: str = Field(description="An AuthEvidenceKind value, e.g. 'chain-bypass'")
    pattern: str = Field(description="Path scope; '{?}' = read but unresolvable")
    detail: str = Field(description="Source text or the implementing class")
    anchor: ExportAnchor


class ExportAuthMechanism(ExportModelBase):
    """How the service authenticates (§5.2.9 D4).

    ``active=False`` is a mechanism present in source but switched off
    (``httpBasic().disable()``) — recorded rather than dropped, because "basic
    auth is explicitly off here" is a fact a reader wants.
    """

    kind: str = Field(description="An AuthMechanismKind value, e.g. 'jwt-bearer'")
    detail: str = Field(description="Source text or the implementing filter class")
    active: bool = True
    inactive_reason: str | None = None
    anchor: ExportAnchor


class ExportMethodSecurity(ExportModelBase):
    """Whether method-security annotations are ENFORCED (§5.2.9 D6).

    ``present=False`` means no enabling annotation was found, which is NOT the
    same as disabled: enablement could live in XML or a parent config outside
    this CPG. The worker treats that as unresolved and withholds, rather than
    either believing an inert annotation or dismissing a real one.
    """

    present: bool
    style: str | None = None
    pre_post: bool = False
    secured: bool = False
    jsr250: bool = False
    evidence: str | None = None
    anchor: ExportAnchor | None = None


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
    auth_enforcements: list[ExportAuthEnforcement] = Field(
        default_factory=list[ExportAuthEnforcement],
        description="2.7.0 (§5.2.9): gating constructs with no security rule behind them",
    )
    auth_mechanisms: list[ExportAuthMechanism] = Field(
        default_factory=list[ExportAuthMechanism],
        description="2.7.0 (§5.2.9): how the service authenticates",
    )
    method_security: ExportMethodSecurity | None = Field(
        default=None,
        description="2.7.0 (§5.2.9): whether security annotations are enforced; None pre-2.7.0",
    )
    config_refs: list[ExportConfigRef] = Field(default_factory=list[ExportConfigRef])
    analysis_coverage: ExportAnalysisCoverage | None = Field(
        default=None, description="None = exporter predates 2.2.0 (unknown, not zero — P10)"
    )
    auth_extraction: ExportAuthExtraction | None = Field(
        default=None,
        description="2.8.0 (§5.2.10): detected-vs-emitted auth sites; None pre-2.8.0",
    )
    auth_policies: list[ExportAuthPolicy] = Field(
        default_factory=list[ExportAuthPolicy],
        description="2.8.0 (§5.2.10): CORS / CSRF / rejection handling, service-level",
    )
    auth_authorities: list[ExportAuthorityModel] = Field(
        default_factory=list[ExportAuthorityModel],
        description="2.8.0 (§5.2.10 T7): what a grant means and where it is minted",
    )

    def compatible_with_reader(self) -> bool:
        """Major versions must match between exporter and reader."""
        return self.export_schema_version.split(".", 1)[0] == EXPORT_SCHEMA_VERSION.split(".", 1)[0]
