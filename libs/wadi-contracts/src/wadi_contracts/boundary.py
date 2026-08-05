"""ServiceBoundary — the discovered unit of analysis (§4, §7)."""

from typing import Self, cast

from pydantic import Field, field_validator, model_validator

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import AuthGapCode, CfgAnomalyCode, ClientLibrary, ServiceKind
from wadi_contracts.source import SourceAnchor
from wadi_contracts.tags import ASYNC_ROOT_KINDS

KNOWN_CLIENT_LIBRARIES: frozenset[str] = frozenset(lib.value for lib in ClientLibrary)
"""Value view of :class:`ClientLibrary`, derived so the two cannot drift."""

MODELLED_CLIENT_LIBRARIES: frozenset[ClientLibrary] = frozenset(
    {
        ClientLibrary.RESTTEMPLATE,
        ClientLibrary.WEBCLIENT,
        ClientLibrary.FEIGN,
        ClientLibrary.RESTCLIENT,
        ClientLibrary.HTTP_INTERFACE,
    }
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


CFG_ANOMALY_CODES: frozenset[str] = frozenset(code.value for code in CfgAnomalyCode)
"""Value view of :class:`CfgAnomalyCode`, derived so the two cannot drift.

The enum is the vocabulary (§7, recorded 2026-08-05); this alias exists for
callers that want the raw strings.
"""


class CfgAnomaly(WadiModel):
    """One structural-invariant violation family on a service's CFGs
    (§5.2.8 M2, schema 1.8.0). Never an error: the weird code lives in real
    repos, and a violated invariant is a queryable fact about how much the
    graph can be trusted (P10).
    """

    code: CfgAnomalyCode
    count: int = Field(ge=1, description="Occurrences across the service's methods")
    sample_sites: list[SourceAnchor] = Field(
        default_factory=list[SourceAnchor],
        max_length=5,
        description="Up to 5 example sites — examples, never the exhaustive list",
    )


AUTH_GAP_CODES: frozenset[str] = frozenset(code.value for code in AuthGapCode)
"""Value view of :class:`AuthGapCode`, derived so the two cannot drift."""


class AuthExtractionGap(WadiModel):
    """One auth-extraction gap family on a service (§5.2.10, schema 1.17.0).

    The independent oracle's finding: what the SOURCE TEXT says the auth layer
    should have read, minus what it emitted. Deliberately separate from
    ``EndpointAuth.evidence`` — evidence records enforcement wadi *found*,
    while this records enforcement it appears to have *missed*, and folding
    the second into the first would make a miss indistinguishable from a
    clean service.
    """

    code: AuthGapCode
    count: int = Field(ge=1, description="Occurrences across the service's sources")
    sample_sites: list[SourceAnchor] = Field(
        default_factory=list[SourceAnchor],
        max_length=5,
        description="Up to 5 example sites — examples, never the exhaustive list",
    )
    detail: str | None = Field(
        default=None,
        max_length=500,
        description="What the oracle saw versus what the export carried",
    )


class EndpointCollision(WadiModel):
    """Two endpoints of one service derived the SAME content-derived id
    (§7, recorded 2026-08-05, schema 1.18.0).

    Endpoint ids are ``hash(service, verb, simplified_uri)`` and the store
    upserts on ``(snapshot_id, service_id, id)``, so a collision does not
    merge — the second row *replaces* the first and the endpoint is gone. That
    is how three handlers of a real controller vanished with every honesty
    surface reading clean: the loss happens at the storage key, downstream of
    everything that counts.

    Recorded as a fact rather than resolved silently, because the alternatives
    are both worse. Failing the service would cost a whole map to one duplicate
    pair; picking a winner quietly is exactly the behaviour that hid the bug.
    A deterministic winner is kept so the snapshot stays reproducible, and the
    losers are named here with their handlers so the cause is one click away.

    **Cause-independent by design.** The 2026-08-05 instance came from URI
    truncation, but any future defect that makes two URIs equal — a bad
    normalizer, an over-eager simplification — lands here too. Expected empty
    in healthy operation; non-empty means endpoints were dropped.
    """

    endpoint_id: str = Field(min_length=1, description="The id both endpoints derived")
    http_method: str = Field(min_length=1)
    uri: str = Field(min_length=1, description="The simplified URI they collapsed onto")
    kept_handler: str = Field(
        min_length=1, description="Handler signature of the endpoint that was stored"
    )
    dropped_handlers: list[str] = Field(
        min_length=1, description="Handler signatures whose endpoints were lost to the collision"
    )


class QuarantinedFact(WadiModel):
    """A diagnostic fact whose vocabulary this build does not recognize
    (§7, recorded 2026-08-05, schema 1.16.0).

    Never fatal and never dropped. Diagnostic facts describe how well analysis
    read the code, not the code itself, so an unreadable one must not cost the
    map — but silently discarding it would be the exact gap the registries
    exist to prevent (P10, turned on wadi's own pipeline: a self-observation we
    cannot parse is itself a queryable fact).

    Expected **empty in all healthy operation**, unlike ``cfg_anomalies``,
    which is expected non-zero on real code forever. That difference is why it
    has its own home rather than sharing one: an always-zero signal folded into
    an always-noisy one stops being a signal. Non-empty on the fixtures or
    benchmarks fails CI, while a user's run only ever loses the one footnote.
    """

    registry: str = Field(
        min_length=1,
        description="Which vocabulary rejected it, e.g. 'CfgAnomalyCode' or 'async-root'",
    )
    value: str = Field(min_length=1, description="The raw unrecognized value, verbatim")
    count: int = Field(default=1, ge=1, description="Occurrences of this value")
    service_id: str | None = Field(
        default=None, description="Owning service; None on a snapshot-level artifact"
    )
    sample_anchor: SourceAnchor | None = Field(
        default=None, description="One example site, when the rejected fact carried one"
    )


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
    client_libraries: list[ClientLibrary] = Field(
        default_factory=list[ClientLibrary],
        description=(
            "HTTP client libraries detected by import scan (§5.4.2 census, "
            "ClientLibrary vocabulary). Presence facts only — an import is "
            "not a call (P10)"
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
    auth_extraction_gaps: list[AuthExtractionGap] | None = Field(
        default=None,
        description=(
            "§5.2.10 independent-oracle findings: auth constructs the source "
            "names that the export did not carry. None = never checked "
            "(library, extraction failed, pre-1.17 snapshot); [] = checked and "
            "clean — never conflated (P10)"
        ),
    )
    quarantined_facts: list[QuarantinedFact] = Field(
        default_factory=list[QuarantinedFact],
        description=(
            "Diagnostic facts whose vocabulary this build does not recognize "
            "(§7). Expected empty; non-empty means version drift, never a "
            "property of the analyzed code"
        ),
    )
    endpoint_collisions: list[EndpointCollision] = Field(
        default_factory=list[EndpointCollision],
        description=(
            "Endpoints of this service that derived the same content-derived "
            "id and so could not all be stored (§7). Expected empty; "
            "non-empty means endpoints were dropped"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _quarantine_unknown_vocabulary(cls, data: object) -> object:
        """Partition registry-governed diagnostic fields into recognized and
        quarantined, at BOTH doors, before field validation runs (§7).

        The write door is the Scala export: ``async-root`` kinds cross a
        language boundary no type system spans, so a pack newer than this
        contract would otherwise abort the snapshot — the exact 2026-08-05
        failure. The read door is a stored artifact or an imported export
        written by a different build: snapshots are immutable and permanent,
        so a 1.16 document must stay readable by 1.15 code (rollback) and by
        third-party consumers of ``wadi export``.

        Strictness stays where it belongs — the enum-typed fields still reject
        unknown values, and pyright still rejects unregistered producers. This
        only decides what happens to a value that has already crossed a
        boundary we do not control: it is set aside and named, never dropped.
        """
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, object], data)
        quarantined: list[dict[str, object]] = []
        service_id = payload.get("service_id")
        service_id = service_id if isinstance(service_id, str) else None

        def _keep(items: object, registry: str, key: str, known: frozenset[str]) -> object:
            if not isinstance(items, list):
                return items
            kept: list[object] = []
            for item in cast(list[dict[str, object] | object], items):
                # Only dict-shaped input can carry unrecognized vocabulary: a
                # value constructed in Python is enum-typed and pyright-checked,
                # so it cannot be unregistered by the time it reaches here.
                if not isinstance(item, dict):
                    kept.append(item)
                    continue
                as_dict = cast(dict[str, object], item)
                raw: object = as_dict.get(key)
                if isinstance(raw, str) and raw not in known:
                    anchor: object = None
                    sites = as_dict.get("sample_sites")
                    if isinstance(sites, list) and (listed := cast(list[object], sites)):
                        anchor = listed[0]
                    else:
                        anchor = as_dict.get("anchor")
                    quarantined.append(
                        {
                            "registry": registry,
                            "value": raw,
                            "count": 1,
                            "service_id": service_id,
                            "sample_anchor": anchor,
                        }
                    )
                    continue
                kept.append(as_dict)
            return kept

        if "cfg_anomalies" in payload:
            payload["cfg_anomalies"] = _keep(
                payload["cfg_anomalies"], "CfgAnomalyCode", "code", CFG_ANOMALY_CODES
            )
        if "auth_extraction_gaps" in payload:
            payload["auth_extraction_gaps"] = _keep(
                payload["auth_extraction_gaps"], "AuthGapCode", "code", AUTH_GAP_CODES
            )
        if "async_roots" in payload:
            payload["async_roots"] = _keep(
                payload["async_roots"], "async-root", "kind", frozenset(ASYNC_ROOT_KINDS)
            )
        if isinstance(libraries := payload.get("client_libraries"), list):
            recognized = [
                lib
                for lib in cast(list[object], libraries)
                if not (isinstance(lib, str) and lib not in KNOWN_CLIENT_LIBRARIES)
            ]
            for lib in cast(list[object], libraries):
                if isinstance(lib, str) and lib not in KNOWN_CLIENT_LIBRARIES:
                    quarantined.append(
                        {
                            "registry": "ClientLibrary",
                            "value": lib,
                            "count": 1,
                            "service_id": service_id,
                            "sample_anchor": None,
                        }
                    )
            payload["client_libraries"] = recognized

        if quarantined:
            existing = payload.get("quarantined_facts")
            prior = cast(list[object], existing) if isinstance(existing, list) else []
            payload["quarantined_facts"] = [*prior, *quarantined]
        return payload
