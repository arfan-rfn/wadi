"""The HTTP matcher: URL-shaped mechanisms (RestTemplate, WebClient, Feign, …).

Classification per call fact (§5.4.2, recorded decisions):

- ``url=None`` → UNDETERMINED (reason ``url-undetermined``, or
  ``lombok-generated-interior`` when the slicer's marker says so).
- URL that cannot yield a host (relative, template hole in the authority,
  unresolved ``${key}``) → UNDETERMINED, ``url-unparseable``.
- Host resolves via the phone book:
  - candidate is an analyzed service → endpoint match → ANALYZED edge(s);
    no endpoint matches → UNDETERMINED, ``no-endpoint-match`` — the service
    is known but the endpoint is not; fabricating one would be a false edge.
  - candidate is config-known with no analyzed service → PLACEHOLDER.
- Host unknown to every namespace: dotted/IP → EXTERNAL; bare single label →
  PLACEHOLDER at HEURISTIC (user decision — internal-looking names land on
  the "grant access" to-do list; dotted hosts are real external deps).

Edge confidence = min(U url recovery, R resolution, P path/verb); provenance
is a single orthogonal value (P7): heuristic anywhere → HEURISTIC, phone book
consulted → CONFIG_RESOLVED, no config involved (external literal) →
MACHINE_PROVEN.
"""

import ipaddress

from wadi_contracts import (
    Confidence,
    Provenance,
    RemoteCall,
    StitchedEdge,
    TargetKind,
    UnresolvedCallEntry,
    placeholder_service_id,
)
from wadi_stitcher.matching.base import (
    BASE_UNDETERMINED_MARKER,
    BUDGET_TRUNCATED_MARKER,
    LOMBOK_BLOCKED_MARKER,
    UNSUPPORTED_IDIOM_MARKER_PREFIX,
    MatchContext,
    MatchOutcome,
    confidence_min,
)
from wadi_stitcher.matching.paths import (
    PathQuality,
    expand_config_keys,
    looks_external,
    match_endpoints,
    parse_url,
)
from wadi_stitcher.phonebook import HostResolution, ResolutionKind, ResolvedTarget


def _idiom_marker(evidence: str | None) -> str | None:
    """Extract `[unsupported-idiom:<name>]` from slice evidence, as the
    reason code (the whole bracketed token minus brackets)."""
    if not evidence:
        return None
    start = evidence.find(f"[{UNSUPPORTED_IDIOM_MARKER_PREFIX}")
    if start < 0:
        return None
    end = evidence.find("]", start)
    if end < 0:
        return None
    return evidence[start + 1 : end]


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


_RESOLVED_VIA = {
    ResolutionKind.COMPOSE_HOSTNAME: "compose-service",
    ResolutionKind.APPLICATION_NAME: "discovery-name",
    ResolutionKind.GATEWAY_ROUTE: "gateway-route",
    ResolutionKind.PORT_HEURISTIC: "port-heuristic",
}


class HttpMatcher:
    """Matches every URL-shaped mechanism; register mechanism-specific
    matchers (gRPC etc.) ahead of this one."""

    def matches_mechanism(self, mechanism: str) -> bool:  # noqa: ARG002
        return True  # last resort in the registry: all Phase 2 mechanisms are HTTP

    def match(self, call: RemoteCall, ctx: MatchContext) -> MatchOutcome:
        if call.url is None:
            if call.evidence and LOMBOK_BLOCKED_MARKER in call.evidence:
                reason_code = "lombok-generated-interior"
            elif call.evidence and BUDGET_TRUNCATED_MARKER in call.evidence:
                reason_code = "slice-budget-truncated"
            elif (idiom := _idiom_marker(call.evidence)) is not None:
                reason_code = idiom
            else:
                reason_code = "url-undetermined"
            return self._undetermined(
                call, reason_code, call.evidence or "target is runtime-only (P10)"
            )

        expanded, keys_resolved = expand_config_keys(call.url, ctx.caller_env(call.service_id))
        parsed = parse_url(expanded)
        if parsed is None:
            # Named causes beat the generic parse failure (T2): the slicer's
            # markers say WHY the URL is holed.
            if call.evidence and BASE_UNDETERMINED_MARKER in call.evidence:
                return self._undetermined(
                    call,
                    "base-undetermined",
                    f"relative URL, client base not statically recoverable: {expanded!r}",
                )
            if (idiom := _idiom_marker(call.evidence)) is not None:
                return self._undetermined(call, idiom, f"unmodelled idiom holed: {expanded!r}")
            detail = (
                "authority still carries unresolved config keys"
                if not keys_resolved
                else ("relative or template-holed URL has no resolvable authority")
            )
            return self._undetermined(call, "url-unparseable", f"{detail}: {expanded!r}")
        used_config_keys = expanded != call.url

        resolution = ctx.phonebook.resolve(parsed.host, parsed.port, parsed.path)
        if resolution is None:
            if _is_ip(parsed.host) or looks_external(parsed.host):
                return self._external(call, parsed.host, parsed.port)
            return self._bare_hostname_placeholder(call, parsed.host)
        return self._resolved(call, ctx, resolution, parsed.path, used_config_keys)

    # --- outcomes -------------------------------------------------------------------

    def _resolved(
        self,
        call: RemoteCall,
        ctx: MatchContext,
        resolution: HostResolution,
        path: str,
        used_config_keys: bool,
    ) -> MatchOutcome:
        outcome = MatchOutcome()
        resolution_tier = self._resolution_tier(resolution)
        heuristic_resolution = resolution.ambiguous or (
            resolution.kind is ResolutionKind.PORT_HEURISTIC
        )
        ordered = sorted(
            resolution.candidates,
            key=lambda c: (c.service_id is None, c.service_id or "", c.logical_name),
        )
        for candidate in ordered:
            if candidate.service_id is None:
                edge = self._placeholder_edge(call, candidate, resolution, resolution_tier)
                outcome.edges.append(edge)
                assert edge.target_service_id is not None
                outcome.placeholder_names[edge.target_service_id] = (
                    candidate.logical_name,
                    _RESOLVED_VIA[resolution.kind],
                )
                continue
            effective_path = candidate.rewritten_path or path
            # T3: the target's servlet context-path prefixes every endpoint it
            # serves — strip it from the call path before matching.
            context_path = self._context_path(ctx, candidate.service_id)
            if context_path and effective_path.startswith(context_path + "/"):
                effective_path = effective_path.removeprefix(context_path)
            elif context_path and effective_path == context_path:
                effective_path = "/"
            matches = match_endpoints(
                effective_path,
                call.http_verb,
                ctx.endpoints_by_service.get(candidate.service_id, []),
            )
            if not matches:
                boundary = ctx.boundaries_by_service.get(candidate.service_id)
                target_name = boundary.name if boundary is not None else candidate.service_id
                entry_outcome = self._undetermined(
                    call,
                    "no-endpoint-match",
                    f"{resolution.evidence}; resolved to service {target_name!r} but no "
                    f"endpoint matched {effective_path!r}"
                    + (f" {call.http_verb.value}" if call.http_verb else ""),
                )
                outcome.edges.extend(entry_outcome.edges)
                outcome.unresolved.extend(entry_outcome.unresolved)
                continue
            for match in matches:
                path_tier = self._path_tier(match.path_quality, match.verb_known)
                confidence = confidence_min(call.url_confidence, resolution_tier, path_tier)
                heuristic_anywhere = heuristic_resolution or confidence is Confidence.HEURISTIC
                outcome.edges.append(
                    StitchedEdge.create(
                        snapshot_id=call.snapshot_id,
                        service_id=call.service_id,
                        remote_call_id=call.id,
                        mechanism=call.mechanism,
                        http_verb=call.http_verb,
                        url=call.url,
                        target_kind=TargetKind.ANALYZED,
                        target_service_id=match.endpoint.service_id,
                        target_endpoint_id=match.endpoint.id,
                        confidence=confidence,
                        provenance=Provenance.HEURISTIC
                        if heuristic_anywhere
                        else Provenance.CONFIG_RESOLVED,
                        evidence=resolution.evidence
                        + (" (via config key)" if used_config_keys else ""),
                    )
                )
        return outcome

    def _placeholder_edge(
        self,
        call: RemoteCall,
        candidate: ResolvedTarget,
        resolution: HostResolution,
        resolution_tier: Confidence,
    ) -> StitchedEdge:
        heuristic = resolution.ambiguous or resolution.kind is ResolutionKind.PORT_HEURISTIC
        return StitchedEdge.create(
            snapshot_id=call.snapshot_id,
            service_id=call.service_id,
            remote_call_id=call.id,
            mechanism=call.mechanism,
            http_verb=call.http_verb,
            url=call.url,
            target_kind=TargetKind.PLACEHOLDER,
            target_service_id=placeholder_service_id(candidate.logical_name),
            confidence=confidence_min(call.url_confidence, resolution_tier),
            provenance=Provenance.HEURISTIC if heuristic else Provenance.CONFIG_RESOLVED,
            evidence=resolution.evidence,
        )

    def _external(self, call: RemoteCall, host: str, port: int | None) -> MatchOutcome:
        normalized = host.lower() + (f":{port}" if port is not None else "")
        exact = call.url_confidence is Confidence.EXACT
        return MatchOutcome(
            edges=[
                StitchedEdge.create(
                    snapshot_id=call.snapshot_id,
                    service_id=call.service_id,
                    remote_call_id=call.id,
                    mechanism=call.mechanism,
                    http_verb=call.http_verb,
                    url=call.url,
                    target_kind=TargetKind.EXTERNAL,
                    external_host=normalized,
                    confidence=call.url_confidence,
                    provenance=Provenance.MACHINE_PROVEN if exact else Provenance.HEURISTIC,
                    evidence=f"host {normalized!r} matches no analyzed or configured service",
                )
            ]
        )

    def _bare_hostname_placeholder(self, call: RemoteCall, host: str) -> MatchOutcome:
        """User decision: unregistered internal-looking names become
        placeholders — the operational 'grant access to this repo' list."""
        name = host.lower()
        return MatchOutcome(
            placeholder_names={placeholder_service_id(name): (name, "bare-hostname")},
            edges=[
                StitchedEdge.create(
                    snapshot_id=call.snapshot_id,
                    service_id=call.service_id,
                    remote_call_id=call.id,
                    mechanism=call.mechanism,
                    http_verb=call.http_verb,
                    url=call.url,
                    target_kind=TargetKind.PLACEHOLDER,
                    target_service_id=placeholder_service_id(name),
                    confidence=Confidence.HEURISTIC,
                    provenance=Provenance.HEURISTIC,
                    evidence=f"bare hostname {name!r} is unknown to compose/discovery config "
                    "— assumed to be an unregistered internal service",
                )
            ],
        )

    def _undetermined(self, call: RemoteCall, reason_code: str, reason: str) -> MatchOutcome:
        edge = StitchedEdge.create(
            snapshot_id=call.snapshot_id,
            service_id=call.service_id,
            remote_call_id=call.id,
            mechanism=call.mechanism,
            http_verb=call.http_verb,
            target_kind=TargetKind.UNDETERMINED,
            confidence=Confidence.NONE,
            provenance=Provenance.MACHINE_PROVEN,
            evidence=reason,
        )
        return MatchOutcome(
            edges=[edge],
            unresolved=[
                UnresolvedCallEntry(
                    remote_call_id=call.id,
                    service_id=call.service_id,
                    site=call.site,
                    reason_code=reason_code,
                    reason=reason,
                )
            ],
        )

    # --- tiers ----------------------------------------------------------------------

    @staticmethod
    def _context_path(ctx: MatchContext, service_id: str) -> str:
        boundary = ctx.boundaries_by_service.get(service_id)
        if boundary is None:
            return ""
        env = boundary.network.env
        raw = env.get("server.servlet.context-path", "") or env.get(
            "SERVER_SERVLET_CONTEXT_PATH", ""
        )
        return raw.rstrip("/") if raw.startswith("/") else ""

    @staticmethod
    def _resolution_tier(resolution: HostResolution) -> Confidence:
        if resolution.indirect:
            return Confidence.HIGH
        if resolution.ambiguous or resolution.kind is ResolutionKind.PORT_HEURISTIC:
            return Confidence.HEURISTIC
        if resolution.via_gateway or resolution.port_mismatch:
            return Confidence.HIGH
        return Confidence.EXACT

    @staticmethod
    def _path_tier(quality: PathQuality, verb_known: bool) -> Confidence:
        if quality is PathQuality.HEURISTIC:
            return Confidence.HEURISTIC
        return Confidence.EXACT if verb_known else Confidence.HIGH
