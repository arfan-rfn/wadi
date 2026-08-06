"""§5.2.10: the independent oracle must see what the emitting side cannot.

The regression these pin is not a wrong answer — it is a *missing* one. Every
case below is written so that it would PASS against the pre-2.8.0 pipeline if
the oracle merely re-read the export, and fails only if the oracle genuinely
reads the source instead.
"""

from pathlib import Path

from wadi_contracts.boundary import AuthExtractionGap
from wadi_contracts.enums import AuthGapCode
from wadi_joern_client.export import (
    ExportAnchor,
    ExportSecurityRule,
    RulePatternConfidence,
    ServiceExport,
)
from wadi_worker.auth_oracle import scan_auth_extraction

CONFIG = "src/main/java/com/acme/SecurityConfig.java"

_TRAIN_TICKET_SHAPE = """\
package com.acme;

@Configuration
public class SecurityConfig {
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.authorizeHttpRequests((authorize) -> {
            for (Rule rule : props.getAuthorizationRules()) {
                AuthorizedUrl url = authorize.requestMatchers(rule.getPaths());
                if (rule.getAuthorities().contains("permitAll")) {
                    url.permitAll();
                } else {
                    url.hasAnyRole("ADMIN");
                }
            }
            authorize.anyRequest().authenticated();
        });
        return http.build();
    }
}
"""


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def _export(*rules: ExportSecurityRule) -> ServiceExport:
    return ServiceExport(
        language="java",
        methods=[],
        cfgs=[],
        endpoints=[],
        sinks=[],
        security_rules=list(rules),
    )


def _rule(call_id: int, pattern: str | None, line: int = 1) -> ExportSecurityRule:
    return ExportSecurityRule(
        call_id=call_id,
        pattern=pattern,
        pattern_confidence=(RulePatternConfidence.EXACT if pattern else RulePatternConfidence.NONE),
        access="authenticated()",
        kind="filter-chain",
        anchor=ExportAnchor(file=CONFIG, line=line),
        evidence="x",
    )


def _codes(gaps: list[AuthExtractionGap] | None) -> set[str]:
    assert gaps is not None, "the tree was readable, so this must not be None"
    return {gap.code.value for gap in gaps}


class TestTheDropIsVisible:
    def test_the_exact_train_ticket_failure_is_reported(self, tmp_path: Path) -> None:
        # Three access calls in source; the pre-fix pipeline emitted only the
        # anyRequest() one, and every counter derived from emission read clean.
        _write(tmp_path, CONFIG, _TRAIN_TICKET_SHAPE)
        gaps = scan_auth_extraction(tmp_path, _export(_rule(1, "/**", line=16)))
        assert AuthGapCode.UNEMITTED_ACCESS_SITE.value in _codes(gaps)
        assert gaps is not None
        finding = next(g for g in gaps if g.code is AuthGapCode.UNEMITTED_ACCESS_SITE)
        # Source names permitAll, hasAnyRole and authenticated; only the last
        # was emitted, so exactly the two loop-body rules are missing — the
        # precise pair that made every admin route read as role-free.
        assert finding.count == 2
        assert finding.sample_sites, "a gap must point at where to look"

    def test_a_fully_read_config_is_clean(self, tmp_path: Path) -> None:
        _write(tmp_path, CONFIG, _TRAIN_TICKET_SHAPE)
        gaps = scan_auth_extraction(
            tmp_path, _export(_rule(1, "/a"), _rule(2, "/b"), _rule(3, "/c"), _rule(4, "/**"))
        )
        assert gaps == []

    def test_a_config_that_produced_nothing_gets_its_own_code(self, tmp_path: Path) -> None:
        # Stronger than a partial miss: every endpoint under this chain is now
        # answered by some other chain, or by nothing at all.
        _write(tmp_path, CONFIG, _TRAIN_TICKET_SHAPE)
        gaps = scan_auth_extraction(tmp_path, _export())
        assert AuthGapCode.UNREAD_SECURITY_CONFIG.value in _codes(gaps)

    def test_reactive_security_is_tracked_apart(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "src/main/java/com/acme/Reactive.java",
            """
            @Bean
            SecurityWebFilterChain f(ServerHttpSecurity http) {
                http.authorizeExchange(ex -> {
                    ex.pathMatchers("/admin").hasRole("ADMIN");
                    ex.anyExchange().authenticated();
                });
                return http.build();
            }
            """,
        )
        gaps = scan_auth_extraction(tmp_path, _export())
        assert AuthGapCode.REACTIVE_CHAIN.value in _codes(gaps)

    def test_emitted_but_unresolved_scopes_stay_countable(self, tmp_path: Path) -> None:
        # Not a drop — this is the system working — but it is the measured
        # demand that schedules the next tranche, so it must not be absorbed
        # into `withheld` and lost.
        _write(tmp_path, CONFIG, _TRAIN_TICKET_SHAPE)
        gaps = scan_auth_extraction(
            tmp_path, _export(_rule(1, None), _rule(2, None), _rule(3, None), _rule(4, "/**"))
        )
        assert AuthGapCode.UNRESOLVED_SCOPE.value in _codes(gaps)


class TestItReadsSourceNotVocabulary:
    def test_comments_are_not_access_calls(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            CONFIG,
            """
            public class SecurityConfig {
                // http.authorizeHttpRequests(a -> a.anyRequest().permitAll());
                /* .hasRole("GHOST") .denyAll() */
                SecurityFilterChain f(HttpSecurity http) {
                    http.authorizeHttpRequests(a -> a.anyRequest().authenticated());
                    return http.build();
                }
            }
            """,
        )
        assert scan_auth_extraction(tmp_path, _export(_rule(1, "/**"))) == []

    def test_a_spel_string_is_one_site_not_two(self, tmp_path: Path) -> None:
        # `.access("hasRole('X')")` is a single rule whose text names the role;
        # counting the quoted call again would invent a permanent false gap.
        _write(
            tmp_path,
            CONFIG,
            """
            public class SecurityConfig {
                SecurityFilterChain f(HttpSecurity http) {
                    http.authorizeHttpRequests(a ->
                        a.requestMatchers("/x").access("hasRole('X')"));
                    return http.build();
                }
            }
            """,
        )
        assert scan_auth_extraction(tmp_path, _export(_rule(1, "/x"))) == []

    def test_business_code_is_not_scanned(self, tmp_path: Path) -> None:
        # `access` and `authenticated` are ordinary words. Only files that
        # configure a chain are compared, or every service would report gaps.
        _write(
            tmp_path,
            "src/main/java/com/acme/Repo.java",
            "class Repo { void go() { db.access(); session.authenticated(); } }",
        )
        assert scan_auth_extraction(tmp_path, _export()) == []


class TestHonestUnknowns:
    def test_a_missing_tree_is_none_not_empty(self, tmp_path: Path) -> None:
        # None = never checked, [] = checked and clean. Conflating them is the
        # P10 violation this whole section exists to remove.
        assert scan_auth_extraction(tmp_path / "nope", _export()) is None

    def test_a_tree_with_no_security_config_is_clean(self, tmp_path: Path) -> None:
        _write(tmp_path, "src/main/java/com/acme/Plain.java", "class Plain {}")
        assert scan_auth_extraction(tmp_path, _export()) == []
