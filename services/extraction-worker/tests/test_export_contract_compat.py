"""Pre-2.8.0 export documents must still parse (§5.2.10).

Snapshots are immutable and permanent, and `wadi export` bundles are consumed
by third parties, so a 2.7.0 document written by an older build has to stay
readable by this one. The sentinels it carries inside ``pattern`` are the very
spelling 2.8.0 replaced, which makes this the one place in the codebase that
still knows the old convention existed.
"""

from wadi_joern_client.export import (
    CONFIG_PREFIX,
    UNRESOLVABLE_PATTERN,
    ExportSecurityRule,
    RulePatternConfidence,
)

_ANCHOR = {"file": "src/SecurityConfig.java", "line": 21}


def _legacy(pattern: str) -> ExportSecurityRule:
    """A rule exactly as a 2.7.0 exporter wrote it: no call_id, no confidence."""
    return ExportSecurityRule.model_validate(
        {
            "pattern": pattern,
            "http_method": "POST",
            "access": 'hasRole("ADMIN")',
            "kind": "filter-chain",
            "anchor": _ANCHOR,
            "evidence": 'antMatchers(...).hasRole("ADMIN")',
        }
    )


class TestLegacySentinelsNormalize:
    def test_a_readable_pattern_becomes_exact(self) -> None:
        rule = _legacy("/api/v1/orders/**")
        assert rule.pattern == "/api/v1/orders/**"
        assert rule.pattern_confidence is RulePatternConfidence.EXACT
        assert rule.resolvable is True

    def test_the_unresolvable_sentinel_becomes_a_null_pattern(self) -> None:
        rule = _legacy(UNRESOLVABLE_PATTERN)
        assert rule.pattern is None
        assert rule.pattern_confidence is RulePatternConfidence.NONE
        assert rule.resolvable is False

    def test_the_config_prefix_keeps_its_binding_and_is_marked_config(self) -> None:
        # `@app.security` still names the binding the worker correlates; only
        # the way it announces itself changed.
        rule = _legacy(f"{CONFIG_PREFIX}app.security")
        assert rule.pattern == "@app.security"
        assert rule.pattern_confidence is RulePatternConfidence.CONFIG
        assert rule.resolvable is False

    def test_a_legacy_rule_has_no_site_and_says_so(self) -> None:
        # 0 is "this document predates site identity", which the oracle must be
        # able to tell apart from a real site — never a valid CPG id.
        assert _legacy("/x").call_id == 0


class TestCurrentDocumentsAreUntouched:
    def test_an_explicit_confidence_is_never_overridden(self) -> None:
        # A 2.8.0 document carrying a literal pattern with NONE confidence is
        # stating that the scope is unread even though a string is present —
        # the config-expansion case where the effect was unreadable. Inferring
        # EXACT from the string would silently re-claim it.
        rule = ExportSecurityRule.model_validate(
            {
                "call_id": 42,
                "pattern": "/api/v1/thing",
                "pattern_confidence": "none",
                "access": "hasAnyRole(roles)",
                "kind": "filter-chain",
                "anchor": _ANCHOR,
                "evidence": "x",
            }
        )
        assert rule.pattern == "/api/v1/thing"
        assert rule.pattern_confidence is RulePatternConfidence.NONE
        assert rule.resolvable is False

    def test_a_null_pattern_round_trips(self) -> None:
        rule = ExportSecurityRule.model_validate(
            {
                "call_id": 7,
                "pattern": None,
                "pattern_confidence": "none",
                "access": "permitAll()",
                "kind": "filter-chain",
                "anchor": _ANCHOR,
                "evidence": "x",
            }
        )
        restored = ExportSecurityRule.model_validate(rule.model_dump())
        assert restored.pattern is None
        assert restored.pattern_confidence is RulePatternConfidence.NONE
        assert restored.call_id == 7
