"""Pure URL/path matching primitives for the HTTP matcher (§5.4.2).

Everything here is deterministic and side-effect free — the property-tested
core of the matcher.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from wadi_contracts import Endpoint, HttpMethod, simplify_uri

_CONFIG_KEY = re.compile(r"\$\{(?P<key>[^}:]+)(?::(?P<default>[^}]*))?\}")
_AUTHORITY = re.compile(
    r"^(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?(?P<host>[^/:?#]+)(?::(?P<port>\d+))?(?P<path>/.*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedUrl:
    host: str
    port: int | None
    path: str


def _relaxed_env_name(key: str) -> str:
    """Spring relaxed binding (T3): property ``yas.services.customer`` binds
    from env var ``YAS_SERVICES_CUSTOMER`` — compose env is carried in its raw
    spelling, so the lookup bridges the two."""
    return key.upper().replace(".", "_").replace("-", "_")


def expand_config_keys(url: str, env: dict[str, str]) -> tuple[str, bool]:
    """Substitute ``${key}`` template variables from the caller's config facts.

    T3: lookups try the dotted key, then its relaxed-binding env-var spelling
    (compose ``environment:`` facts keep their raw names); expansion is
    multi-pass so nested placeholders (`${a}` -> `${b}/x`) resolve, bounded to
    stay total on cycles.

    Returns the expanded URL and whether every key resolved (an unresolved key
    without a default survives as a literal ``${key}`` — honest, and it will
    fail authority parsing rather than fabricate a host).
    """
    all_resolved = True

    def _substitute(match: re.Match[str]) -> str:
        nonlocal all_resolved
        key = match.group("key").strip()
        if key in env:
            return env[key]
        relaxed = _relaxed_env_name(key)
        if relaxed in env:
            return env[relaxed]
        default = match.group("default")
        if default is not None:
            return default
        all_resolved = False
        return match.group(0)

    expanded = url
    for _ in range(4):  # nested-placeholder bound: total even on cycles
        next_expanded = _CONFIG_KEY.sub(_substitute, expanded)
        if next_expanded == expanded:
            break
        expanded = next_expanded
    return expanded, all_resolved


def parse_url(url: str) -> ParsedUrl | None:
    """Split a candidate URL into authority + path. None = unparseable.

    Relative URLs (no host) and URLs whose host still contains template
    holes/keys are unparseable by design — a made-up host is worse than an
    honest unknown (P10).
    """
    stripped = url.strip()
    if not stripped or stripped.startswith("/"):
        return None
    match = _AUTHORITY.match(stripped)
    if match is None:
        return None
    host = match.group("host")
    if "{" in host or "$" in host or not host:
        return None
    port = int(match.group("port")) if match.group("port") else None
    return ParsedUrl(host=host, port=port, path=match.group("path") or "/")


def looks_external(host: str) -> bool:
    """Dotted FQDNs (and IPs handled upstream) read as external addresses;
    bare single-label names read as internal service names."""
    return "." in host


class PathQuality(StrEnum):
    """How well a call path matched an endpoint template (the P component)."""

    EXACT = "exact"
    HEURISTIC = "heuristic"


def path_match(call_path: str, endpoint_simplified_uri: str) -> PathQuality | None:
    """Segment-wise match of a call path against an endpoint identity form.

    Both sides are normalized through :func:`simplify_uri`. An endpoint
    ``{?}`` absorbing a call segment is what a template means → still EXACT.
    A call-side ``{?}`` (an unrecovered hole) absorbing an endpoint literal is
    the fuzzy direction → HEURISTIC. Any literal disagreement → no match.
    """
    call_segments = [s for s in simplify_uri(call_path).split("/") if s]
    endpoint_segments = [s for s in endpoint_simplified_uri.split("/") if s]
    if len(call_segments) != len(endpoint_segments):
        return None
    quality = PathQuality.EXACT
    for call_segment, endpoint_segment in zip(call_segments, endpoint_segments, strict=True):
        if endpoint_segment == "{?}":
            continue
        if call_segment == "{?}":
            quality = PathQuality.HEURISTIC
            continue
        if call_segment != endpoint_segment:
            return None
    return quality


@dataclass(frozen=True)
class EndpointMatch:
    endpoint: Endpoint
    path_quality: PathQuality
    verb_known: bool


def match_endpoints(
    path: str, verb: HttpMethod | None, endpoints: list[Endpoint]
) -> list[EndpointMatch]:
    """All endpoints a call path/verb can land on, deterministically ordered.

    An unknown verb matches any method (degraded downstream); a known verb
    must agree. Multiple matches are all returned — over-approximation is the
    correct answer for an architecture map (§5.2).
    """
    matches: list[EndpointMatch] = []
    for endpoint in sorted(endpoints, key=lambda e: e.id):
        if verb is not None and endpoint.http_method is not verb:
            continue
        quality = path_match(path, endpoint.simplified_uri)
        if quality is None:
            continue
        matches.append(
            EndpointMatch(endpoint=endpoint, path_quality=quality, verb_known=verb is not None)
        )
    return matches
