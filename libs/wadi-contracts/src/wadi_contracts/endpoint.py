"""Endpoint — the per-route artifact with structured auth (§7, goal 9)."""

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import HttpMethod, TriggerKind
from wadi_contracts.ids import endpoint_id, simplify_uri
from wadi_contracts.source import MethodRef, SourceAnchor


class ParamLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    BODY = "body"
    HEADER = "header"


class EndpointParam(WadiModel):
    name: str = Field(min_length=1)
    location: ParamLocation
    type_name: str | None = None
    required: bool = True


class ShapeKind(StrEnum):
    """The recovered wire-shape node kinds (§5.2.7). ``unresolved``/``cycle``/
    ``truncated`` are honest terminals — never fabricated fields (P10)."""

    OBJECT = "object"
    SCALAR = "scalar"
    ARRAY = "array"
    MAP = "map"
    CYCLE = "cycle"
    TRUNCATED = "truncated"
    UNRESOLVED = "unresolved"

    ALWAYS_NULL = "always-null"
    """Every construction of the enclosing type sets this field to `null`, so
    the wire value is always null. Distinct from `unresolved`, which says the
    type could not be determined: this says there is no value to determine.
    TrainTicket writes whole services this way, and reporting them as
    unresolved claimed an analysis failure about code that states plainly it
    sends no payload."""


class FieldShape(WadiModel):
    """One serialized field: the WIRE name (Jackson renames applied)."""

    name: str = Field(min_length=1, description="Serialized name (@JsonProperty applied)")
    java_name: str | None = Field(
        default=None, description="The Java field name, when it differs from the wire name"
    )
    shape: "TypeShape"


class ShapeOrigin(StrEnum):
    """Which evidence the shape was read from (§5.2.7, amended 2026-08-05).

    ``declared`` is the signature — the strongest evidence, and the only one
    used until a raw wrapper (`public HttpEntity query(...)`) leaves nothing to
    unwrap. ``return_expression`` means the payload came from what the handler
    returns, which is still symbolic truth but rests on a weaker premise: one
    return path standing for the whole contract. P7 keeps the two legible
    rather than blending them.
    """

    DECLARED = "declared"
    RETURN_EXPRESSION = "return-expression"


class StatusOrigin(StrEnum):
    """How a declared status was read (§5.2.7 T9)."""

    BUILDER = "builder"
    """The `ResponseEntity` builder's own name fixes it: `noContent()` is 204."""

    EXPLICIT = "explicit"
    """A constant the handler names: `new ResponseEntity<>(body, CREATED)`."""

    ANNOTATION = "annotation"
    """`@ResponseStatus` on the handler, which REPLACES what the body implies."""

    DEFAULT = "default"
    """Nothing was named and the return type is not a `ResponseEntity`, so the
    framework decides: Spring serializes the value with 200. Kept distinct from
    `builder` because the code did not say it — and claimed only where the
    status is NOT under program control, since guessing 200 for a handler that
    controls its own status would dress a guess as a framework rule."""


class EndpointStatus(WadiModel):
    """One HTTP status a handler's own code names (§5.2.7 T9)."""

    code: int = Field(ge=100, le=599)
    origin: StatusOrigin
    detail: str = Field(description="The source text that named it")
    anchor: SourceAnchor


class TypeShape(WadiModel):
    """A recovered request/response shape (§5.2.7): the wire contract, walked
    from in-CPG type structure with honest terminals."""

    kind: ShapeKind
    origin: ShapeOrigin = Field(
        default=ShapeOrigin.DECLARED,
        description="Evidence the shape was read from; nested shapes are always declared",
    )
    type_name: str = Field(min_length=1, description="Declared type, e.g. 'com.acme.Pet'")
    fields: list[FieldShape] = Field(
        default_factory=list[FieldShape], description="kind=object only; @JsonIgnore omitted"
    )
    element: "TypeShape | None" = Field(
        default=None, description="Element shape for kind=array; value shape for kind=map"
    )


class AuthEvidenceKind(StrEnum):
    """What kind of construct enforces (or could enforce) access (§5.2.9).

    The first three are declarative sources; the rest are enforcement points
    that gate requests without a security-framework rule behind them. All are
    framework-neutral by construction — a FastAPI ``Security(...)`` dependency
    or an Express middleware maps onto the same vocabulary (goal 9).
    """

    ANNOTATION = "annotation"
    SECURITY_DSL = "security-dsl"
    CONFIG = "config"
    CHAIN_BYPASS = "chain-bypass"
    INTERCEPTOR = "interceptor"
    SERVLET_FILTER = "servlet-filter"
    ASPECT = "aspect"
    IN_HANDLER = "in-handler"
    GATEWAY = "gateway"

    AUTHORITY_MODEL = "authority-model"
    """A construct that changes what a GRANT MEANS rather than gating a request
    (§5.2.10 T7): a ``RoleHierarchy``, a ``GrantedAuthorityDefaults`` prefix, a
    JWT claim→authority converter, a ``UserDetailsService``.

    It never gates on its own, so it never withholds a claim. What it does is
    make a reported role list *incomplete*: under ``ROLE_ADMIN > ROLE_USER`` an
    endpoint published as requiring ``[USER]`` is also reachable by ADMIN, and
    a role list that quietly under-states who can get in is exactly the kind of
    confident-but-wrong security fact §12 rates worse than an absent one.
    Carried as PARTIAL evidence so the incompleteness is visible on the
    endpoint that has it."""


class AuthEffect(StrEnum):
    """What an enforcement point does to a request that reaches it.

    ``UNKNOWN`` is a first-class answer, not a placeholder: an enforcement we
    can see but cannot interpret must say so, because the alternative is
    leaving the endpoint reading as unprotected (§5.2.9).
    """

    REQUIRE_AUTHENTICATED = "require-authenticated"
    REQUIRE_ROLES = "require-roles"
    REQUIRE_AUTHORITIES = "require-authorities"
    PERMIT_ALL = "permit-all"
    DENY_ALL = "deny-all"
    UNKNOWN = "unknown"


class AuthResolution(StrEnum):
    """How completely an enforcement point was read.

    ``OPAQUE`` is what withholds an endpoint's claim (§5.2.9): the construct
    was detected but its effect or scope could not be determined.
    """

    RESOLVED = "resolved"
    PARTIAL = "partial"
    OPAQUE = "opaque"


class _ActiveFlagged(WadiModel):
    """Mixin for facts that can be present but switched off.

    A disabled mechanism (``httpBasic().disable()``) or an inert annotation
    family (``@PreAuthorize`` without ``@EnableMethodSecurity``) is recorded
    rather than dropped — but it never gates anything, and it never withholds
    a claim. Turning something off always carries its reason (P10).
    """

    active: bool = Field(default=True, description="False when present in source but not in effect")
    inactive_reason: str | None = Field(
        default=None,
        description="Why it is not in effect, e.g. 'disabled in chain' — required when inactive",
    )

    @model_validator(mode="after")
    def _inactive_states_why(self) -> Self:
        if self.active and self.inactive_reason is not None:
            raise ValueError("inactive_reason is only meaningful when active=False")
        if not self.active and not self.inactive_reason:
            raise ValueError("active=False requires an inactive_reason (P10 — never a silent off)")
        return self


class AuthEvidence(_ActiveFlagged):
    """One enforcement point that gates — or could gate — this endpoint (§5.2.9).

    Every claim carries its source, and every construct that *could* gate a
    request is recorded here whether or not its effect could be determined.
    That is what makes the claim rule on :class:`EndpointAuth` safe: a rule we
    failed to read is present as ``resolution=opaque`` rather than absent.

    **Reader migration (pre-1.13.0 artifacts):** records written before the
    enforcement model carry no ``effect``/``resolution``, so they default to
    ``unknown``/``resolved`` — honest about what was recorded (the effect was
    never stored) while preserving the claim those artifacts were written with.
    """

    kind: AuthEvidenceKind
    detail: str = Field(min_length=1, description="e.g. '@PreAuthorize(\"hasRole('ADMIN')\")'")
    anchor: SourceAnchor | None = None
    effect: AuthEffect = Field(
        default=AuthEffect.UNKNOWN, description="What this does to a request that reaches it"
    )
    resolution: AuthResolution = Field(
        default=AuthResolution.RESOLVED, description="How completely it was read"
    )
    roles: list[str] = Field(
        default_factory=list[str], description="Roles required, ROLE_ prefix stripped"
    )
    authorities: list[str] = Field(
        default_factory=list[str], description="Authorities required, when distinct from roles"
    )
    expression: str | None = Field(
        default=None, description="Raw access expression / SpEL, preserved verbatim"
    )
    pattern: str | None = Field(
        default=None,
        description="Path pattern this is scoped to; '{?}' means read but unresolvable",
    )
    http_method: HttpMethod | None = Field(
        default=None, description="Verb restriction; None means the rule applies to every verb"
    )


class AuthMechanismKind(StrEnum):
    """How a caller proves identity — distinct from what it is then allowed to do."""

    JWT_BEARER = "jwt-bearer"
    OPAQUE_TOKEN = "opaque-token"
    HTTP_BASIC = "http-basic"
    FORM_LOGIN = "form-login"
    OAUTH2_LOGIN = "oauth2-login"
    OAUTH2_RESOURCE_SERVER = "oauth2-resource-server"
    SAML2 = "saml2"
    X509 = "x509"
    REMEMBER_ME = "remember-me"
    CUSTOM_FILTER = "custom-filter"
    STATELESS_SESSION = "stateless-session"


class AuthMechanism(_ActiveFlagged):
    """One authentication mechanism configured on the service that serves this endpoint.

    A custom filter is only ever promoted past ``CUSTOM_FILTER`` on evidence
    inside the filter itself — naming a mechanism from a class name would be
    exactly the fabricated security fact §12 forbids.
    """

    kind: AuthMechanismKind
    detail: str = Field(min_length=1, description="Raw source text or filter class name")
    anchor: SourceAnchor | None = None


class EndpointAuth(WadiModel):
    """Structured authorization state of an endpoint (§5.2.9).

    ``authenticated`` is tri-state (P10): True/False are *claims backed by
    fully-read enforcement*; None means honestly unknown — never defaulted to
    False. The distinction between None and False is load-bearing: None says
    "we did not read everything that guards this", False says "we read it all
    and nothing guards this". Collapsing them is the failure mode this model
    exists to prevent.

    ``denied`` refines the True case rather than replacing it. ``denyAll()``
    admits nobody, so "a request must be authenticated to pass" is still true
    of it — but a route no caller can reach is not the same fact as a working
    protected route, and rendering the two identically tells an auditor a dead
    endpoint is live. It is a separate boolean, not a fourth value of
    ``authenticated``, so every existing reader of the tri-state keeps working.
    """

    authenticated: bool | None = None
    denied: bool = Field(
        default=False,
        description="A read rule denies EVERY caller (denyAll); the endpoint is unreachable",
    )
    roles: list[str] = Field(default_factory=list[str])
    authorities: list[str] = Field(
        default_factory=list[str],
        description="Authorities required, when the rule names authorities rather than roles",
    )
    mechanism: str | None = Field(
        default=None,
        description="Framework family, e.g. 'spring-security'; see mechanisms[] for how auth works",
    )
    mechanisms: list[AuthMechanism] = Field(
        default_factory=list[AuthMechanism],
        description="How authentication is performed on this endpoint's service",
    )
    evidence: list[AuthEvidence] = Field(
        default_factory=list[AuthEvidence],
        description="Every enforcement point in scope — read or not (§5.2.9)",
    )

    @property
    def unread_enforcement(self) -> list[AuthEvidence]:
        """Active enforcement points whose effect could not be determined.

        Non-empty is exactly the condition under which no claim may be made,
        and it is what the UI renders to explain a withheld answer.
        """
        return [
            item
            for item in self.evidence
            if item.active and item.resolution is AuthResolution.OPAQUE
        ]

    @model_validator(mode="after")
    def _claims_are_earned(self) -> Self:
        """The §5.2.9 claim rule, as a contract guarantee.

        Enforcement is a conjunction, so an unread gate can only ADD a
        requirement — never remove one. That asymmetry is what makes this
        checkable without re-deriving the claim here:

        * ``authenticated=False`` — "we read everything and nothing guards
          this" — is incompatible with ANY unread gate. This is the dangerous
          direction and the one that produced real wrong answers.
        * ``authenticated=True`` survives an unread gate, which could only make
          the endpoint more restricted. The single exception is an unread
          ``chain-bypass``: bypasses remove enforcement, so one could flip a
          protected answer to open.
        """
        if self.authenticated is None:
            return self
        if not self.evidence:
            raise ValueError(
                "an authenticated=True/False claim requires at least one piece of evidence; "
                "use authenticated=None for unknown (P10)"
            )
        blocking = [
            item
            for item in self.unread_enforcement
            if not self.authenticated or item.kind is AuthEvidenceKind.CHAIN_BYPASS
        ]
        if blocking:
            raise ValueError(
                f"an authenticated={self.authenticated} claim cannot coexist with enforcement "
                f"that was detected but not read ({blocking[0].kind.value}: "
                f"{blocking[0].detail!r}); §5.2.9 requires the claim be withheld "
                "(authenticated=None) so an unreadable guard never falls through to a "
                "permissive answer"
            )
        return self

    @model_validator(mode="after")
    def _denial_is_a_read_claim(self) -> Self:
        """`denied` refines a positive claim; it can never stand on its own.

        A denial is something we READ (`denyAll()` is as explicit as a rule
        gets), so it cannot coexist with a withheld or open answer — those say
        we could not read the guards, or read them all and found none.
        """
        if self.denied and self.authenticated is not True:
            raise ValueError(
                "denied=True requires authenticated=True: a denial is a rule that was read, "
                f"so it cannot accompany authenticated={self.authenticated}"
            )
        return self


class Endpoint(ArtifactEnvelope):
    """One REST endpoint of one service within a snapshot."""

    id: str = Field(pattern=r"^ep_[0-9a-f]{16}$")
    http_method: HttpMethod
    full_uri: str = Field(min_length=1, description="Route as written, e.g. /orders/{orderId}")
    simplified_uri: str = Field(min_length=1, description="Identity form, e.g. /orders/{?}")
    params: list[EndpointParam] = Field(default_factory=list[EndpointParam])
    response_type: str | None = None
    declared_statuses: list[EndpointStatus] = Field(
        default_factory=list[EndpointStatus],
        description=(
            "HTTP statuses the handler's own code NAMES (§5.2.7 T9). Named "
            "`declared_` because it is not the set this endpoint can answer "
            "with: a 500 from an uncaught exception, a 403 from the security "
            "layer and a 404 from the dispatcher appear in no handler source. "
            "An empty list means nothing was named, never that the endpoint "
            "cannot fail (P10)"
        ),
    )
    request_schema: TypeShape | None = Field(
        default=None,
        description="Field-level @RequestBody shape (§5.2.7); None = no body or pre-1.6",
    )
    response_schema: TypeShape | None = Field(
        default=None,
        description="Field-level response shape, wrappers unwrapped (§5.2.7)",
    )
    auth: EndpointAuth = Field(default_factory=EndpointAuth)
    handler: MethodRef
    trigger: TriggerKind = TriggerKind.HTTP

    @field_validator("full_uri", mode="before")
    @classmethod
    def _root_anchor(cls, value: object) -> object:
        """A route is the same route with or without its leading slash.

        Spring accepts ``@RequestMapping("api/v1/x")`` and routes it exactly as
        ``/api/v1/x``, so the two spellings are one endpoint — ``endpoint_id``
        has always agreed, hashing ``simplify_uri`` which anchors the root. Only
        the published ``full_uri`` disagreed, and a consumer matching it
        literally against a caller's URL missed those routes (§5.2.11).

        Normalizing here rather than rejecting is deliberate: snapshots written
        before this rule hold the verbatim form, and they must stay readable.
        The coercion is idempotent and leaves ``simplified_uri`` and the id
        untouched, so old and new snapshots still join on identity.

        A URI whose head is an unresolved hole or a config template is left
        alone — we do not know what it expands to, and asserting a leading
        slash in front of it would invent information analysis does not have
        (P10). Mirrors ``SpringPacks.rootAnchored`` on the Scala side.
        """
        if not isinstance(value, str) or not value or value.startswith("/"):
            return value
        if value.startswith(("{", "$")) or "://" in value:
            return value
        return "/" + value

    @model_validator(mode="after")
    def _enforce_identity(self) -> Self:
        expected_uri = simplify_uri(self.full_uri)
        if self.simplified_uri != expected_uri:
            raise ValueError(
                f"simplified_uri {self.simplified_uri!r} does not match "
                f"simplify_uri(full_uri) = {expected_uri!r}"
            )
        expected_id = endpoint_id(self.service_id, self.http_method.value, self.full_uri)
        if self.id != expected_id:
            raise ValueError(
                f"endpoint id {self.id!r} is not the content-derived id {expected_id!r} "
                "(identity-stability rule, §7)"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        service_id: str,
        http_method: HttpMethod,
        full_uri: str,
        handler: MethodRef,
        params: list[EndpointParam] | None = None,
        response_type: str | None = None,
        declared_statuses: list[EndpointStatus] | None = None,
        request_schema: TypeShape | None = None,
        response_schema: TypeShape | None = None,
        auth: EndpointAuth | None = None,
        trigger: TriggerKind = TriggerKind.HTTP,
    ) -> "Endpoint":
        """Construct an endpoint with its derived id and simplified URI computed."""
        return cls(
            snapshot_id=snapshot_id,
            service_id=service_id,
            id=endpoint_id(service_id, http_method.value, full_uri),
            http_method=http_method,
            full_uri=full_uri,
            simplified_uri=simplify_uri(full_uri),
            params=params or [],
            response_type=response_type,
            declared_statuses=declared_statuses or [],
            request_schema=request_schema,
            response_schema=response_schema,
            auth=auth or EndpointAuth(),
            handler=handler,
            trigger=trigger,
        )
