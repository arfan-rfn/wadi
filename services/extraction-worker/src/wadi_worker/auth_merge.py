"""Auth enforcement merge (§5.2.9): everything that could gate, one claim.

The predecessor asked "what auth evidence did we find?" and treated an empty
answer as license to claim. That is what let a SecurityConfig rule wadi could
not read fall through to a later ``permitAll()`` and publish
``authenticated=False`` for a route requiring ROLE_ADMIN — the wrong-fact
outcome §12 exists to prevent.

This module asks the other question: **what could gate a request to this
endpoint, and did we read all of it?** Every gating construct becomes one
:class:`AuthEvidence` record carrying its effect, how completely it was read,
and whether it is even in effect. The claim then follows one rule, which the
contract itself enforces:

    authenticated is a claim only when every enforcement whose scope could
    cover this endpoint is fully resolved and active. One opaque in-scope
    enforcement withholds it.

Framework-neutral by construction: the function consumes raw strings, patterns
and anchors — nothing Spring-typed reaches the contract (goal 9).
"""

import re
from collections import defaultdict

from wadi_contracts import (
    AuthEffect,
    AuthEvidence,
    AuthEvidenceKind,
    AuthMechanism,
    AuthMechanismKind,
    AuthResolution,
    HttpMethod,
    SourceAnchor,
)
from wadi_contracts.endpoint import EndpointAuth
from wadi_joern_client.export import (
    CONFIG_PREFIX,
    UNRESOLVABLE_PATTERN,
    ExportAuthEnforcement,
    ExportAuthMechanism,
    ExportMethodSecurity,
    ExportSecurityRule,
    RulePatternConfidence,
)

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
_ARGUMENTS = re.compile(r"\(([^)]*)\)")

#: Access expressions that grant everyone through.
_PERMISSIVE = ("permitAll", "@PermitAll", "anonymous")

#: Which ``@EnableMethodSecurity`` flag governs which annotation family.
_ANNOTATION_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("@PreAuthorize", "@PostAuthorize", "@PreFilter", "@PostFilter"), "pre_post"),
    (("@Secured",), "secured"),
    (("@RolesAllowed", "@PermitAll", "@DenyAll"), "jsr250"),
)


def merge_endpoint_auth(
    *,
    full_uri: str,
    http_method: HttpMethod,
    auth_tags: list[str],
    security_rules: list[ExportSecurityRule],
    handler_anchor: SourceAnchor,
    config_env: dict[str, str],
    auth_enforcements: list[ExportAuthEnforcement] | None = None,
    auth_mechanisms: list[ExportAuthMechanism] | None = None,
    method_security: ExportMethodSecurity | None = None,
    config_structured: dict[str, list[dict[str, object]]] | None = None,
) -> EndpointAuth:
    """Collect every enforcement in scope, then derive the claim from it."""
    evidence: list[AuthEvidence] = []
    evidence.extend(_annotation_evidence(auth_tags, handler_anchor, method_security))
    evidence.extend(_bypass_evidence(auth_enforcements or [], full_uri))
    evidence.extend(_enforcement_evidence(auth_enforcements or [], full_uri))
    evidence.extend(
        _rule_evidence(security_rules, full_uri, http_method, config_structured or {}, config_env)
    )
    evidence.extend(_config_evidence(config_env))

    if not evidence:
        return EndpointAuth()  # honest unknown (P10)

    mechanisms = _mechanisms(auth_mechanisms or [])
    gating = [item for item in evidence if item.active and _gates(item)]
    withheld = EndpointAuth(
        authenticated=None,
        mechanism="spring-security",
        mechanisms=mechanisms,
        evidence=evidence,
    )
    if not gating:
        # Config keys and inert annotations only — informative, never a claim.
        return withheld

    # Enforcement composes rather than conflicts: a chain that permits all
    # still runs method security on top, so ANY requirement makes auth
    # required. A chain BYPASS is the exception — nothing runs at all.
    bypassed = any(item.kind is AuthEvidenceKind.CHAIN_BYPASS for item in gating)
    readable = [item for item in gating if item.resolution is not AuthResolution.OPAQUE]
    requiring = [item for item in readable if item.effect is not AuthEffect.PERMIT_ALL]

    if _opacity_could_change_the_answer(gating, requiring, bypassed=bypassed):
        return withheld

    authenticated = bool(requiring) and not bypassed
    roles = sorted({role for item in requiring for role in item.roles})
    authorities = sorted({name for item in requiring for name in item.authorities})
    # `denyAll()` admits nobody, so the endpoint is unreachable rather than
    # merely protected. Only a rule that actually applies counts — a bypassed
    # chain never runs it, and an unread rule cannot be claimed as a denial.
    denied = authenticated and any(item.effect is AuthEffect.DENY_ALL for item in requiring)
    return EndpointAuth(
        authenticated=authenticated,
        denied=denied,
        roles=roles,
        authorities=authorities,
        mechanism="spring-security",
        mechanisms=mechanisms,
        evidence=evidence,
    )


def _opacity_could_change_the_answer(
    gating: list[AuthEvidence], requiring: list[AuthEvidence], *, bypassed: bool
) -> bool:
    """Would reading the unreadable guards flip the claim? (§5.2.9)

    Withholding on ANY opaque guard is too blunt and costs real answers: an
    unreadable `@PreAuthorize` next to a chain rule that already demands ADMIN
    cannot make the endpoint *less* protected, so the claim stands and only the
    role list is uncertain. Enforcement is a conjunction — an unknown gate can
    add a requirement, never remove one.

    So opacity is decisive in exactly two shapes:

    * nothing readable requires auth yet, so an unread guard is the difference
      between "open" and "protected" — this is the train-ticket case, where a
      dropped rule let a route publish as evidenced-open; and
    * the unread guard is a chain BYPASS, the one construct that *removes*
      enforcement and so could flip a protected answer to open.
    """
    opaque = [item for item in gating if item.resolution is AuthResolution.OPAQUE]
    if not opaque:
        return False
    if any(item.kind is AuthEvidenceKind.CHAIN_BYPASS for item in opaque):
        return True
    return not (requiring and not bypassed)


def _gates(item: AuthEvidence) -> bool:
    """Config keys describe the service; they do not gate a request."""
    return item.kind is not AuthEvidenceKind.CONFIG


# --------------------------------------------------------------------------
# evidence collection
# --------------------------------------------------------------------------


def _annotation_evidence(
    auth_tags: list[str],
    handler_anchor: SourceAnchor,
    method_security: ExportMethodSecurity | None,
) -> list[AuthEvidence]:
    evidence: list[AuthEvidence] = []
    for raw_tag in auth_tags:
        detail = raw_tag.removeprefix("auth=")
        payload = detail.split(":", 1)[-1]
        effect, roles, authorities, resolution = _read_access(payload)
        active, inactive_reason, resolution = _annotation_activity(
            payload, method_security, resolution
        )
        evidence.append(
            AuthEvidence(
                kind=AuthEvidenceKind.ANNOTATION,
                detail=detail,
                anchor=handler_anchor,
                effect=effect,
                resolution=resolution,
                roles=roles,
                authorities=authorities,
                expression=payload,
                active=active,
                inactive_reason=inactive_reason,
            )
        )
    return evidence


def _annotation_activity(
    payload: str,
    method_security: ExportMethodSecurity | None,
    resolution: AuthResolution,
) -> tuple[bool, str | None, AuthResolution]:
    """Is this annotation actually enforced? (§5.2.9 D6)

    An annotation whose family is switched off is inert — recorded, marked, and
    excluded from the claim. Three input states, deliberately distinguished:

    * ``None`` — the export predates the field, so there is nothing to apply.
      Behave as before rather than retroactively withholding on every stored
      artifact.
    * ``present=False`` — the exporter looked and found no enabling annotation.
      In Spring Boot method security is off unless switched on, so the
      annotation is probably inert; but it can also be enabled from XML or a
      parent config outside this CPG. We withhold instead of guessing in either
      direction: believing it invents enforcement, dismissing it hides a policy
      the author wrote.
    * ``present=True`` — the flags decide, per that annotation's family.
    """
    flag = next(
        (name for markers, name in _ANNOTATION_FAMILIES if any(m in payload for m in markers)),
        None,
    )
    if flag is None or method_security is None:
        return True, None, resolution
    if not method_security.present:
        return True, None, AuthResolution.OPAQUE
    if not getattr(method_security, flag):
        style = method_security.style or "method security"
        return False, f"{flag.replace('_', '')}Enabled=false on {style}", resolution
    return True, None, resolution


def _bypass_evidence(
    enforcements: list[ExportAuthEnforcement], full_uri: str
) -> list[AuthEvidence]:
    """Paths that skip the filter chain entirely — nothing runs on them."""
    evidence: list[AuthEvidence] = []
    for enforcement in enforcements:
        if enforcement.kind != AuthEvidenceKind.CHAIN_BYPASS.value:
            continue
        unresolvable = enforcement.pattern == UNRESOLVABLE_PATTERN
        if not unresolvable and not _ant_match(enforcement.pattern, full_uri):
            continue
        evidence.append(
            AuthEvidence(
                kind=AuthEvidenceKind.CHAIN_BYPASS,
                detail=f"{enforcement.pattern} bypasses the security chain",
                anchor=_anchor_of(enforcement),
                effect=AuthEffect.PERMIT_ALL,
                resolution=AuthResolution.OPAQUE if unresolvable else AuthResolution.RESOLVED,
                pattern=enforcement.pattern,
            )
        )
    return evidence


def _enforcement_evidence(
    enforcements: list[ExportAuthEnforcement], full_uri: str
) -> list[AuthEvidence]:
    """Interceptors, servlet filters, aspects, in-handler checks.

    Deliberately never interpreted into an effect: a guard we can see but
    cannot read must withhold the endpoint's claim, which is the whole point of
    detecting it. Reading it as "no auth" is what a missing detector does.
    """
    evidence: list[AuthEvidence] = []
    for enforcement in enforcements:
        if enforcement.kind == AuthEvidenceKind.CHAIN_BYPASS.value:
            continue
        try:
            kind = AuthEvidenceKind(enforcement.kind)
        except ValueError:
            continue
        unresolvable = enforcement.pattern == UNRESOLVABLE_PATTERN
        if not unresolvable and not _in_scope(kind, enforcement.pattern, full_uri):
            continue
        evidence.append(
            AuthEvidence(
                kind=kind,
                detail=enforcement.detail,
                anchor=_anchor_of(enforcement),
                effect=AuthEffect.UNKNOWN,
                resolution=AuthResolution.OPAQUE,
                pattern=enforcement.pattern,
            )
        )
    return evidence


#: HTTP verbs, for shape-inferring a config rule's method restriction.
_VERBS = frozenset(method.value for method in HttpMethod)


def _expand_config_rules(
    rule: ExportSecurityRule, config_structured: dict[str, list[dict[str, object]]]
) -> list[ExportSecurityRule] | None:
    """A ``@prefix`` rule → the concrete rules its config actually declares.

    yas binds ``@ConfigurationProperties(prefix="app.security")`` and loops over
    the bound rules, so its whole policy lives in ``application.yaml`` and not
    one literal pattern appears in the Java (§5.2.9 D5).

    The entries are read by SHAPE rather than by field name — a list of strings
    that look like paths is the pattern list, a list of HTTP verbs is the method
    restriction, a truthy ``permit*`` flag is permitAll — so the next project
    that spells its keys differently still resolves. Returns None when nothing
    correlates, which leaves the enforcement opaque and withholds the claim.
    """
    prefix = (rule.pattern or "").removeprefix(CONFIG_PREFIX)
    if not prefix:
        return None
    entries = next(
        (
            value
            for key, value in config_structured.items()
            if key == prefix or key.startswith(f"{prefix}.")
        ),
        None,
    )
    if not entries:
        return None

    expanded: list[ExportSecurityRule] = []
    for entry in entries:
        patterns: list[str] = []
        verbs: list[str] = []
        roles: list[str] = []
        permit = False
        for key, value in entry.items():
            if isinstance(value, bool):
                permit = permit or (value and "permit" in key.lower())
            elif isinstance(value, list):
                items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
                strings = [str(item) for item in items]
                if all(s.startswith("/") for s in strings):
                    patterns.extend(strings)
                elif all(s.upper() in _VERBS for s in strings):
                    verbs.extend(s.upper() for s in strings)
                else:
                    roles.extend(strings)
            elif isinstance(value, str) and value.startswith("/"):
                patterns.append(value)
        if not patterns:
            continue
        access = "permitAll()" if permit else f"hasAnyRole({', '.join(repr(r) for r in roles)})"
        for pattern in patterns:
            for verb in verbs or [None]:
                expanded.append(
                    rule.model_copy(
                        update={
                            "pattern": pattern,
                            # Recovered from config, so the scope IS now known —
                            # without this the rule stays unresolvable and every
                            # config-defined policy withholds forever (§5.2.10).
                            "pattern_confidence": RulePatternConfidence.EXACT,
                            "http_method": verb,
                            "access": access,
                        }
                    )
                )
    return expanded or None


#: Spring property placeholder, with its optional `:default`.
_PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _resolve_placeholders(pattern: str, config_env: dict[str, str]) -> str | None:
    """``/api/${admin.path}/**`` → the real path, or None if a key is unknown.

    Returning None (rather than the raw text) is the whole point. A pattern
    still holding ``${…}`` matches no endpoint literally, so leaving it
    "resolved" would make the rule govern nothing and let the endpoint fall
    through to whatever permissive rule comes next — the §5.2.9 failure mode
    reached by a new road. An unresolved placeholder is an unread scope, and
    unread scopes withhold.
    """
    missing = False

    def _substitute(match: re.Match[str]) -> str:
        nonlocal missing
        # group(2) is absent when the placeholder declares no `:default`.
        default: str | None = match.group(2)
        value = config_env.get(match.group(1), default)
        if value is None:
            missing = True
            return match.group(0)
        return value

    resolved = _PLACEHOLDER.sub(_substitute, pattern)
    return None if missing else resolved


def _rule_evidence(
    security_rules: list[ExportSecurityRule],
    full_uri: str,
    http_method: HttpMethod,
    config_structured: dict[str, list[dict[str, object]]],
    config_env: dict[str, str],
) -> list[AuthEvidence]:
    """The governing filter-chain rule, resolved per chain (§5.2.9).

    First-match-wins applies WITHIN a chain. When several chains could govern
    the endpoint and nothing says which, that ambiguity is itself opaque —
    picking one would be a guess about which policy runs.
    """
    expanded: list[ExportSecurityRule] = []
    for rule in security_rules:
        if rule.pattern_confidence is RulePatternConfidence.CONFIG:
            recovered = _expand_config_rules(rule, config_structured)
            # No correlation: the rule stays as-is and reads as unresolvable,
            # which withholds rather than falling through.
            expanded.extend(recovered if recovered is not None else [rule])
        else:
            expanded.append(rule)
    expanded = [_with_resolved_placeholders(rule, config_env) for rule in expanded]
    chains = _chains_governing(expanded, full_uri)
    if not chains:
        return []
    evidence: list[AuthEvidence] = []
    ambiguous = len(chains) > 1
    for rules in chains:
        for matched in _matching_rules(full_uri, http_method, rules):
            unresolvable = not matched.resolvable
            effect, roles, authorities, resolution = _read_access(matched.access)
            if unresolvable or ambiguous:
                resolution = AuthResolution.OPAQUE
            detail = (
                "a security rule's path could not be read"
                if unresolvable
                else f"{matched.pattern} -> {matched.access}"
            )
            evidence.append(
                AuthEvidence(
                    kind=AuthEvidenceKind.SECURITY_DSL,
                    detail=detail,
                    anchor=SourceAnchor(
                        file=matched.anchor.file,
                        start_line=max(matched.anchor.line, 1),
                        end_line=max(matched.anchor.line, 1),
                    ),
                    effect=effect,
                    resolution=resolution,
                    roles=roles,
                    authorities=authorities,
                    expression=matched.access,
                    pattern=matched.pattern,
                    http_method=HttpMethod(matched.http_method.upper())
                    if matched.http_method
                    else None,
                )
            )
    return evidence


def _with_resolved_placeholders(
    rule: ExportSecurityRule, config_env: dict[str, str]
) -> ExportSecurityRule:
    """A ``${…}`` pattern resolved against config, or downgraded to unread."""
    if rule.pattern is None or "${" not in rule.pattern:
        return rule
    resolved = _resolve_placeholders(rule.pattern, config_env)
    if resolved is None:
        return rule.model_copy(
            update={"pattern": None, "pattern_confidence": RulePatternConfidence.NONE}
        )
    return rule.model_copy(update={"pattern": resolved})


def _chains_governing(
    security_rules: list[ExportSecurityRule], full_uri: str
) -> list[list[ExportSecurityRule]]:
    """Group rules by their declaring chain, keeping only chains in scope."""
    grouped: dict[str, list[ExportSecurityRule]] = defaultdict(list)
    for rule in security_rules:
        grouped[rule.chain_id or ""].append(rule)
    in_scope: list[list[ExportSecurityRule]] = []
    for rules in grouped.values():
        scope = next((rule.chain_pattern for rule in rules if rule.chain_pattern), None)
        if scope is None or any(_ant_match(part, full_uri) for part in scope.split(",")):
            in_scope.append(rules)
    return in_scope


def _config_evidence(config_env: dict[str, str]) -> list[AuthEvidence]:
    """``spring.security.*`` keys — context about the service, not a gate."""
    keys = sorted(key for key in config_env if key.startswith("spring.security."))
    return [
        AuthEvidence(
            kind=AuthEvidenceKind.CONFIG,
            detail=f"{key}={config_env[key]}",
            effect=AuthEffect.UNKNOWN,
        )
        for key in keys[:5]  # evidence, not claims — keep it bounded
    ]


def _mechanisms(exported: list[ExportAuthMechanism]) -> list[AuthMechanism]:
    mechanisms: list[AuthMechanism] = []
    for mechanism in exported:
        try:
            kind = AuthMechanismKind(mechanism.kind)
        except ValueError:
            continue
        mechanisms.append(
            AuthMechanism(
                kind=kind,
                detail=mechanism.detail,
                anchor=_anchor_of(mechanism),
                active=mechanism.active,
                inactive_reason=mechanism.inactive_reason if not mechanism.active else None,
            )
        )
    return mechanisms


def _anchor_of(record: ExportAuthEnforcement | ExportAuthMechanism) -> SourceAnchor:
    return SourceAnchor(
        file=record.anchor.file,
        start_line=max(record.anchor.line, 1),
        end_line=max(record.anchor.line, 1),
    )


# --------------------------------------------------------------------------
# access-expression reading
# --------------------------------------------------------------------------


def _read_access(
    expression: str,
) -> tuple[AuthEffect, list[str], list[str], AuthResolution]:
    """An access expression → what it does, to whom, and how sure we are.

    Note what does NOT make this opaque. An unreadable *expression* still tells
    us a gate exists and is not permissive, so "authentication is required" is
    sound even when the roles behind a custom SpEL guard
    (``@PreAuthorize("@guard.check(#id)")``) are unreadable — the incomplete
    part is the role list, reported as ``PARTIAL``. Opacity is reserved for an
    unreadable *scope*: not knowing WHICH rule governs is what produced the
    wrong permissive answers, because that is what makes the walk fall through.
    """
    if any(marker in expression for marker in _PERMISSIVE):
        return AuthEffect.PERMIT_ALL, [], [], AuthResolution.RESOLVED
    if "denyAll" in expression or "@DenyAll" in expression:
        return AuthEffect.DENY_ALL, [], [], AuthResolution.RESOLVED
    named = _extract_roles(expression)
    partial = _has_unresolved_arguments(expression)
    if named:
        # Roles and authorities are different things in Spring — `hasRole("X")`
        # matches the authority `ROLE_X`, `hasAuthority("X")` matches `X` — so
        # the values land in separate lists rather than being pooled under
        # "roles" and quietly losing which kind of grant is required.
        authority_scoped = "hasAuthority" in expression or "hasAnyAuthority" in expression
        effect = AuthEffect.REQUIRE_AUTHORITIES if authority_scoped else AuthEffect.REQUIRE_ROLES
        resolution = AuthResolution.PARTIAL if partial else AuthResolution.RESOLVED
        if authority_scoped:
            return effect, [], named, resolution
        return effect, named, [], resolution
    if _requires_identity(expression):
        return AuthEffect.REQUIRE_AUTHENTICATED, [], [], AuthResolution.RESOLVED
    # A gate whose condition we cannot read: it still gates, and it is not
    # permissive, so auth is required — we just cannot name the roles.
    return AuthEffect.REQUIRE_AUTHENTICATED, [], [], AuthResolution.PARTIAL


def _requires_identity(expression: str) -> bool:
    return any(
        marker in expression
        for marker in ("authenticated", "fullyAuthenticated", "rememberMe", "hasIpAddress")
    )


def _has_unresolved_arguments(expression: str) -> bool:
    """True when an argument survived as a bare reference instead of a literal."""
    for group in _ARGUMENTS.findall(expression):
        for argument in group.split(","):
            candidate = argument.strip()
            if candidate and not candidate.startswith(("'", '"')):
                return True
    return False


def _extract_roles(expression: str) -> list[str]:
    """Best-effort role extraction; unparseable expressions stay evidence-only."""
    roles: list[str] = []
    for pattern in _ROLE_PATTERNS:
        roles.extend(pattern.findall(expression))
    for pattern in _MULTI_ROLE_PATTERNS:
        for group in pattern.findall(expression):
            roles.extend(quoted.removeprefix("ROLE_") for quoted in _QUOTED.findall(group))
    return sorted(dict.fromkeys(role.removeprefix("ROLE_") for role in roles))


def _matching_rules(
    full_uri: str, http_method: HttpMethod, rules: list[ExportSecurityRule]
) -> list[ExportSecurityRule]:
    """Spring chain semantics: the first declared rule that matches wins.

    A rule whose pattern could not be read is a fork in that walk — it may be
    the governing rule, or control may pass to whatever comes next. Both
    candidates are returned, and both become evidence, because which one is
    reported changes the answer:

    * unreadable-`hasRole` followed by `permitAll()` really is uncertain
      between protected and open, so the claim is withheld;
    * unreadable-`hasRole` followed by `authenticated()` is protected either
      way, so the claim survives (only the role list is uncertain).

    Returning just the unreadable rule would collapse the second case into the
    first and withhold an answer that was never in doubt.
    """
    matched: list[ExportSecurityRule] = []
    for rule in rules:
        if rule.http_method is not None and rule.http_method.upper() != http_method.value:
            continue
        if not rule.resolvable or rule.pattern is None:
            matched.append(rule)
            continue  # the fork: keep walking for the alternative branch
        if _governs(rule.pattern, full_uri):
            matched.append(rule)
            return matched
    return matched


def _governs(pattern: str, full_uri: str) -> bool:
    """Does this rule decide THIS endpoint — not merely a request it could serve?

    Ant matching over-approximates on purpose (§5.2): an endpoint's ``{orderId}``
    template segment matches any literal, so ``/orders/legacy`` "matches"
    ``/orders/{orderId}``. That direction is honest for a wildcard rule, which
    really does cover the whole template. It is wrong for a LITERAL rule: at
    runtime Spring routes ``/orders/legacy`` to the more specific
    ``@GetMapping("/orders/legacy")`` handler, so a literal rule governs that
    endpoint and not its templated sibling. Letting it match both attaches
    ``denyAll()`` to a live route and reports it as unreachable — a wrong
    security fact in the §12 sense, and the direction over-approximation is
    NOT safe in: it withdraws an endpoint that really is reachable.

    A rule written WITH a template (``antMatchers("/orders/{orderId}")``) is
    not literal either: it covers the whole parameterised route, and the
    variable name in the rule need not match the one on the handler.
    """
    if not any(marker in pattern for marker in ("*", "?", "{")):
        return pattern == full_uri
    return _ant_match(pattern, full_uri)


def _in_scope(kind: AuthEvidenceKind, pattern: str, full_uri: str) -> bool:
    """Does this enforcement cover this endpoint?

    An in-handler check is scoped to the ONE endpoint that contains it, so it
    is matched exactly rather than ant-style. Ant matching over-approximates on
    purpose (§5.2) — a `{orderId}` template segment matches any literal — which
    is right for a path *pattern* and wrong here: it attached the guard written
    inside `/orders/export` to `/orders/{orderId}` as well.
    """
    if kind is AuthEvidenceKind.IN_HANDLER:
        return pattern == full_uri
    return _ant_match(pattern, full_uri)


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
