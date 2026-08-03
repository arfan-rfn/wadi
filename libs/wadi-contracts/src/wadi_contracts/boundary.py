"""ServiceBoundary — the discovered unit of analysis (§4, §7)."""

from typing import Self

from pydantic import Field, field_validator, model_validator

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import ServiceKind
from wadi_contracts.source import SourceAnchor
from wadi_contracts.tags import ASYNC_ROOT_KINDS

KNOWN_CLIENT_LIBRARIES: frozenset[str] = frozenset(
    {
        "resttemplate",
        "webclient",
        "feign",
        "restclient",
        "http-interface",
        "jdk-httpclient",
        "okhttp",
        "retrofit",
        "apache-httpclient",
        "unirest",
    }
)
"""Client-library census vocabulary (§5.4.2) — versioned like the tag registry.

The worker detects these by deterministic import scan; presence is a fact,
call counts are not claimed (an import is not a call — P10)."""

MODELLED_CLIENT_LIBRARIES: frozenset[str] = frozenset(
    {"resttemplate", "webclient", "feign", "restclient", "http-interface"}
)
"""The subset wadi's sink passes currently model. A census hit outside this
set becomes an ``unmodelled_mechanisms`` coverage entry — a zero-edge system
must be distinguishable from a correct zero-edge answer (§5.4.2, the yas
RestClient lesson — closed by T2's RestClient support, schema 1.5)."""


class GatewayRoute(WadiModel):
    """One gateway routing rule extracted from config (§5.4.1 phone-book input).

    Only populated on services that ARE gateways (Spring Cloud Gateway routes
    in application.yml). The stitcher re-resolves ``target_uri`` through the
    phone book after applying the prefix rewrite.
    """

    route_id: str | None = Field(default=None, description="Config route id, when present")
    path_prefix: str = Field(min_length=1, description="Matched prefix, e.g. '/api/v1/orders/**'")
    target_uri: str = Field(
        min_length=1,
        description="Forward target, e.g. 'lb://ts-order-service' or 'http://orders:8080'",
    )
    strip_prefix: int = Field(default=0, ge=0, description="StripPrefix filter segment count")
    anchor: SourceAnchor | None = Field(
        default=None, description="Where in config this route is declared (evidence)"
    )


class NetworkIdentity(WadiModel):
    """How this service is addressed at runtime, as far as statics can see.

    Raw config facts extracted by the worker at extraction time (P2/P6 split:
    the worker extracts, the stitcher resolves). All fields best-effort — an
    absent fact is honest, never guessed (P10).
    """

    hostnames: list[str] = Field(default_factory=list[str])
    ports: list[int] = Field(default_factory=list[int])
    env: dict[str, str] = Field(
        default_factory=dict[str, str],
        description=(
            "Network-relevant config keys: flattened application.* allowlist "
            "(profiles merged, T3) plus compose environment/env_file entries "
            "in their raw env-var spelling — the stitcher's relaxed-binding "
            "lookup bridges ${dotted.keys} to SCREAMING_SNAKE names (§5.4.2)"
        ),
    )
    config_notes: list[str] = Field(
        default_factory=list[str],
        description=(
            "Machine-readable notes about config parsing for this service "
            "(§5.4.2, T3): 'config-profile-merged:<file>' / "
            "'config-profile-doc-merged:<profiles>' (profile config merged "
            "over the base) | 'config-profile-merged-all' (active set unknown "
            "— every profile merged, over-approximation) | "
            "'gateway-filter-unmodelled:<name>' / "
            "'gateway-predicate-unmodelled:<name>' (gateway shape perceived "
            "but not modelled)"
        ),
    )
    application_name: str | None = Field(
        default=None, description="spring.application.name (or equivalent declared identity)"
    )
    discovery_names: list[str] = Field(
        default_factory=list[str],
        description="Names this service registers under in service discovery (Eureka/Consul)",
    )
    server_port: int | None = Field(
        default=None, ge=1, le=65535, description="Configured listen port (server.port)"
    )
    gateway_routes: list[GatewayRoute] = Field(
        default_factory=list[GatewayRoute],
        description="Routing rules when this service is a gateway; empty otherwise",
    )
    gateway_discovery_locator: bool = Field(
        default=False,
        description=(
            "Spring Cloud Gateway discovery locator: '/{service-name}/**' "
            "forwards to that service by its discovery name"
        ),
    )


class AnalysisCoverage(WadiModel):
    """Per-service analysis-coverage counts (§5.4.3, schema 1.5.0).

    How much of this service's own production code the endpoint-reachable
    closure walks. The denominator mirrors the closure's method filters
    (internal, non-synthetic, concrete, service-own sources — staged
    library code excluded); the numerator is the closure intersected with the
    same set. Computed in-CPG at export time; absence of this fact on a
    boundary means "unknown" (extraction failed / pre-metric snapshot), which
    is never conflated with zero (P10).
    """

    production_methods: int = Field(ge=0, description="Denominator: the service's own methods")
    reachable_methods: int = Field(
        ge=0, description="Numerator: methods in >=1 endpoint's reachable closure"
    )

    @model_validator(mode="after")
    def _reachable_within_production(self) -> Self:
        if self.reachable_methods > self.production_methods:
            raise ValueError(
                f"reachable_methods {self.reachable_methods} exceeds "
                f"production_methods {self.production_methods} — the numerator "
                "is defined as a subset of the denominator (§5.4.3)"
            )
        return self


CFG_ANOMALY_CODES: frozenset[str] = frozenset(
    {
        # A node (beyond the method's entry statement) with no incoming raw
        # edge: the assembler's synthetic patching would silently present it
        # as a second entry point (§5.2.8 — the pre-M1 synchronized class).
        "disconnected-node",
        # An if node missing a true or false successor, or a switch node with
        # no case/default arm edge — the branch cannot be read as a branch.
        "branch-arity",
        # A loop with body edges but no cycle-closing back edge. Suppressed
        # for empty-body loops (recorded §5.2.8 non-representable).
        "loop-no-back-edge",
        # An edge endpoint that references no exported node.
        "dangling-edge",
        # No return statement and every node has a successor: flow can never
        # leave the method (a pure cycle) — either dead code or a graph bug.
        "exit-unreachable",
    }
)
"""§5.2.8 M2 structural-invariant violation codes.

Evaluated against the RAW exported CFG of every method on every snapshot —
before the assembler's synthetic entry/exit patching, which would make
reachability invariants vacuously true. Additive changes bump
``SCHEMA_VERSION`` minor.
"""


class CfgAnomaly(WadiModel):
    """One structural-invariant violation family on a service's CFGs
    (§5.2.8 M2, schema 1.8.0). Never an error: the weird code lives in real
    repos, and a violated invariant is a queryable fact about how much the
    graph can be trusted (P10).
    """

    code: str
    count: int = Field(ge=1, description="Occurrences across the service's methods")
    sample_sites: list[SourceAnchor] = Field(
        default_factory=list[SourceAnchor],
        max_length=5,
        description="Up to 5 example sites — examples, never the exhaustive list",
    )

    @field_validator("code")
    @classmethod
    def _registered_code(cls, value: str) -> str:
        if value not in CFG_ANOMALY_CODES:
            allowed = " | ".join(sorted(CFG_ANOMALY_CODES))
            raise ValueError(f"cfg-anomaly code must be {allowed}, got {value!r}")
        return value


class AsyncRoot(WadiModel):
    """A non-endpoint reachability root (§5.4.2 T4, schema 1.7.0): a method
    the framework invokes without an HTTP request — scheduled jobs, event and
    message listeners, boot runners, ``@Bean`` factories, framework callbacks.
    The reachable closure (and therefore coverage, sinks, and stitched edges)
    is rooted at endpoints plus these; a controller-less service is non-empty
    exactly through this list.
    """

    kind: str = Field(min_length=1, description="Registry kind, e.g. 'scheduled' (tags.py)")
    method_signature: str = Field(min_length=1, description="Fully-qualified method signature")
    anchor: SourceAnchor

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in ASYNC_ROOT_KINDS:
            allowed = " | ".join(sorted(ASYNC_ROOT_KINDS))
            raise ValueError(f"async-root kind must be {allowed}, got {value!r}")
        return value


class ServiceBoundary(ArtifactEnvelope):
    """One discovered service within a snapshot.

    The envelope's ``service_id`` is this service's own stable id
    (content-derived from repo + build root, §7).
    """

    name: str = Field(min_length=1, description="Display name (e.g. compose/module name)")
    repo: str = Field(min_length=1, description="Normalized repo source this service lives in")
    build_root: str = Field(
        min_length=1, description="Path of the build root relative to the repo root ('.' = root)"
    )
    languages: list[str] = Field(min_length=1, description="e.g. ['java']")
    build_system: str = Field(min_length=1, description="e.g. 'maven', 'gradle'")
    network: NetworkIdentity = Field(default_factory=NetworkIdentity)
    kind: ServiceKind = ServiceKind.SERVICE
    library_roots: list[str] = Field(
        default_factory=list[str],
        description=(
            "Build roots of in-repo library modules whose sources were staged "
            "into this service's parse (§5.2.6 source union); empty for "
            "kind=library and for services with no in-repo dependencies"
        ),
    )
    extraction_error: str | None = Field(
        default=None,
        description=(
            "Set when this service's CPG extraction failed (§5.2.6 per-service "
            "isolation): the error, recorded as a queryable fact (P10). The "
            "service then has no endpoints/calls — absence with a stated cause, "
            "never silence"
        ),
    )
    client_libraries: list[str] = Field(
        default_factory=list[str],
        description=(
            "HTTP client libraries detected by import scan (§5.4.2 census, "
            "KNOWN_CLIENT_LIBRARIES vocabulary). Presence facts only — an "
            "import is not a call (P10)"
        ),
    )
    analysis_coverage: AnalysisCoverage | None = Field(
        default=None,
        description=(
            "Analysis-coverage counts (§5.4.3). None = fact unavailable "
            "(library, extraction failed, or pre-1.5 snapshot) — never zero"
        ),
    )
    async_roots: list[AsyncRoot] = Field(
        default_factory=list[AsyncRoot],
        description=(
            "Non-endpoint reachability roots (§5.4.2 T4). Empty also for "
            "pre-1.7 snapshots — absence of the fact, not proof of none"
        ),
    )
    cfg_anomalies: list[CfgAnomaly] | None = Field(
        default=None,
        description=(
            "§5.2.8 M2 structural-invariant violations across this service's "
            "method CFGs. None = never checked (library, extraction failed, "
            "pre-1.8 snapshot); [] = checked and clean — never conflated (P10)"
        ),
    )

    @field_validator("client_libraries")
    @classmethod
    def _registered_client_libraries(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in KNOWN_CLIENT_LIBRARIES]
        if unknown:
            raise ValueError(
                f"unregistered client libraries {unknown!r}; the vocabulary is "
                "KNOWN_CLIENT_LIBRARIES"
            )
        return value
