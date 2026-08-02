"""Auth-evidence merge (§5.2 step 5): three sources, one structured result.

Sources: security-annotation tags (in-graph), SecurityFilterChain DSL rules
(in-graph, matched here — never in Scala, §12), and ``spring.security.*``
config keys (config analyzer). Every claim carries its evidence; conflicting
evidence keeps ``authenticated=None`` with everything attached — wrong
security facts are worse than absent ones (§12). Framework-neutral by
construction: the function consumes raw strings and anchors, nothing
Spring-typed leaks into the contract (goal 9).
"""

import re

from wadi_contracts import (
    AuthEvidence,
    AuthEvidenceKind,
    EndpointAuth,
    HttpMethod,
    SourceAnchor,
)
from wadi_joern_client.export import ExportSecurityRule

_ROLE_PATTERNS = (
    re.compile(r"hasRole\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    re.compile(r"hasAuthority\(\s*['\"](?:ROLE_)?([^'\"]+)['\"]\s*\)"),
)
_MULTI_ROLE_PATTERNS = (
    re.compile(r"hasAnyRole\(([^)]*)\)"),
    re.compile(r"hasAnyAuthority\(([^)]*)\)"),
    re.compile(r"@RolesAllowed\(([^)]*)\)"),
    re.compile(r"@Secured\(([^)]*)\)"),
)
_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")


def merge_endpoint_auth(
    *,
    full_uri: str,
    http_method: HttpMethod,
    auth_tags: list[str],
    security_rules: list[ExportSecurityRule],
    handler_anchor: SourceAnchor,
    config_env: dict[str, str],
) -> EndpointAuth:
    evidence: list[AuthEvidence] = []
    requires_auth: set[bool] = set()
    roles: list[str] = []

    for raw_tag in auth_tags:
        detail = raw_tag.removeprefix("auth=")
        payload = detail.split(":", 1)[-1]
        evidence.append(
            AuthEvidence(kind=AuthEvidenceKind.ANNOTATION, detail=detail, anchor=handler_anchor)
        )
        if "@PermitAll" in payload:
            requires_auth.add(False)
        else:
            requires_auth.add(True)
            roles.extend(_extract_roles(payload))

    matched_rule = _first_matching_rule(full_uri, http_method, security_rules)
    if matched_rule is not None:
        evidence.append(
            AuthEvidence(
                kind=AuthEvidenceKind.SECURITY_DSL,
                detail=f"{matched_rule.pattern} -> {matched_rule.access}",
                anchor=SourceAnchor(
                    file=matched_rule.anchor.file,
                    start_line=max(matched_rule.anchor.line, 1),
                    end_line=max(matched_rule.anchor.line, 1),
                ),
            )
        )
        if "permitAll" in matched_rule.access:
            requires_auth.add(False)
        else:
            requires_auth.add(True)
            roles.extend(_extract_roles(matched_rule.access))

    security_keys = sorted(k for k in config_env if k.startswith("spring.security."))
    for key in security_keys[:5]:  # evidence, not claims — keep it bounded
        evidence.append(
            AuthEvidence(kind=AuthEvidenceKind.CONFIG, detail=f"{key}={config_env[key]}")
        )

    if not evidence:
        return EndpointAuth()  # honest unknown (P10)

    authenticated: bool | None
    if requires_auth == {True}:
        authenticated = True
    elif requires_auth == {False}:
        authenticated = False
    else:
        # Conflict or config-only evidence: over-approximate, never assert (§12).
        authenticated = None

    deduped_roles = sorted(dict.fromkeys(roles))
    return EndpointAuth(
        authenticated=authenticated,
        roles=deduped_roles,
        mechanism="spring-security",
        evidence=evidence,
    )


def _extract_roles(expression: str) -> list[str]:
    """Best-effort role extraction; unparseable expressions stay evidence-only."""
    roles: list[str] = []
    for pattern in _ROLE_PATTERNS:
        roles.extend(pattern.findall(expression))
    for pattern in _MULTI_ROLE_PATTERNS:
        for group in pattern.findall(expression):
            roles.extend(quoted.removeprefix("ROLE_") for quoted in _QUOTED.findall(group))
    return [role.removeprefix("ROLE_") for role in roles]


def _first_matching_rule(
    full_uri: str, http_method: HttpMethod, rules: list[ExportSecurityRule]
) -> ExportSecurityRule | None:
    """Spring chain semantics: the first declared rule that matches wins."""
    for rule in rules:
        if rule.http_method is not None and rule.http_method.upper() != http_method.value:
            continue
        if _ant_match(rule.pattern, full_uri):
            return rule
    return None


def _ant_match(pattern: str, path: str) -> bool:
    """Ant-style matching: ``**`` any segments (incl. none), ``*`` one segment,
    ``?`` one char. Endpoint template segments (``{id}``) match any single
    pattern segment — over-approximation is the honest direction (§5.2)."""
    return _match_segments([s for s in pattern.split("/") if s], [s for s in path.split("/") if s])


def _match_segments(pattern: list[str], path: list[str]) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_match_segments(rest, path[i:]) for i in range(len(path) + 1))
    if not path:
        return False
    return _match_one(head, path[0]) and _match_segments(rest, path[1:])


def _match_one(pattern_segment: str, path_segment: str) -> bool:
    if path_segment.startswith("{") and path_segment.endswith("}"):
        return True  # a path template can carry any value
    regex = re.escape(pattern_segment).replace(r"\*", "[^/]*").replace(r"\?", ".")
    return re.fullmatch(regex, path_segment) is not None
