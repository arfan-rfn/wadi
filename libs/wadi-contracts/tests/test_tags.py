"""Tag registry tests — the vocabulary is a contract, not a convention (§7)."""

import pytest

from wadi_contracts.endpoint import AuthMechanismKind
from wadi_contracts.tags import (
    AUTH_ENFORCEMENT_KINDS,
    AUTH_MECHANISM_KINDS,
    Tag,
    TagValidationError,
    parse_tag,
    registered_namespaces,
    validate_tag,
)


class TestParseTag:
    @pytest.mark.parametrize(
        ("raw", "namespace", "value"),
        [
            ("endpoint=GET /orders", "endpoint", "GET /orders"),
            ("endpoint=POST /orders/{id}/items", "endpoint", "POST /orders/{id}/items"),
            ("sink=db", "sink", "db"),
            ("sink=http-client", "sink", "http-client"),
            ("sink=mq:kafka", "sink", "mq:kafka"),
            ("sink=mq:rabbitmq", "sink", "mq:rabbitmq"),
            ("model=Order", "model", "Order"),
            ("model=com.acme.Order", "model", "com.acme.Order"),
            (
                "auth=annotation:@PreAuthorize(\"hasRole('ADMIN')\")",
                "auth",
                "annotation:@PreAuthorize(\"hasRole('ADMIN')\")",
            ),
            ('auth=jsr250:@RolesAllowed({"ADMIN"})', "auth", 'jsr250:@RolesAllowed({"ADMIN"})'),
            (
                "auth-rule=*|/admin/**|hasRole('ADMIN')",
                "auth-rule",
                "*|/admin/**|hasRole('ADMIN')",
            ),
            ("auth-rule=GET|/stock/**|permitAll", "auth-rule", "GET|/stock/**|permitAll"),
            (
                "token-propagation=authorization-header",
                "token-propagation",
                "authorization-header",
            ),
            ("token-propagation=feign-interceptor", "token-propagation", "feign-interceptor"),
        ],
    )
    def test_valid(self, raw: str, namespace: str, value: str) -> None:
        tag = parse_tag(raw)
        assert tag == Tag(namespace=namespace, value=value)
        assert str(tag) == raw

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "endpoint",
            "endpoint=",
            "=GET /orders",
            "unknown=thing",
            "endpoint=FETCH /orders",  # not an HTTP method
            "endpoint=GET orders",  # missing leading slash
            "endpoint=get /orders",  # lowercase method
            "sink=redis",  # unregistered sink kind
            "sink=mq:",  # empty broker
            "sink=mq:Kafka",  # broker must be lowercase token
            "model=1Order",  # not an identifier
            "model=",
            "auth=@PreAuthorize('x')",  # missing source prefix
            "auth=spring:@Secured",  # unknown source
            "auth=annotation:PreAuthorize",  # raw text must start with '@'
            "auth-rule=/admin/**|hasRole('ADMIN')",  # missing verb component
            "auth-rule=FETCH|/x|permitAll",  # not an HTTP verb or '*'
            "auth-rule=GET||permitAll",  # empty pattern
            "token-propagation=cookie",  # unregistered propagation kind
        ],
    )
    def test_invalid(self, raw: str) -> None:
        with pytest.raises(TagValidationError):
            parse_tag(raw)

    def test_value_may_contain_equals(self) -> None:
        # partition on first '=' only; keeps future namespaces safe.
        with pytest.raises(TagValidationError):
            # still invalid namespace, but must not crash on the second '='
            parse_tag("unknown=a=b")


class TestRegistry:
    def test_registered_namespaces(self) -> None:
        assert registered_namespaces() == frozenset(
            {
                "endpoint",
                "sink",
                "model",
                "auth",
                "auth-rule",
                "auth-mechanism",
                "auth-enforcement",
                "token-propagation",
                "async-root",
            }
        )

    def test_async_root_kinds(self) -> None:
        assert parse_tag("async-root=scheduled").value == "scheduled"
        assert parse_tag("async-root=framework-callback").namespace == "async-root"
        with pytest.raises(TagValidationError, match="async-root"):
            parse_tag("async-root=cron")

    def test_validate_tag_unknown_namespace_names_known_ones(self) -> None:
        with pytest.raises(TagValidationError, match="endpoint"):
            validate_tag("nope", "x")


class TestAuthNamespaces:
    """§5.2.9 — the auth vocabularies are derived from the contract enums, so a
    new enum member is registered by construction and cannot drift."""

    def test_mechanism_kinds_track_the_enum(self) -> None:
        assert frozenset(kind.value for kind in AuthMechanismKind) == AUTH_MECHANISM_KINDS

    def test_enforcement_kinds_exclude_the_declarative_sources(self) -> None:
        # annotations / DSL rules / config keys travel in their own namespaces;
        # this one exists for gating constructs that have no rule behind them.
        assert "interceptor" in AUTH_ENFORCEMENT_KINDS
        assert "chain-bypass" in AUTH_ENFORCEMENT_KINDS
        assert AUTH_ENFORCEMENT_KINDS.isdisjoint({"annotation", "security-dsl", "config"})

    @pytest.mark.parametrize(
        "raw",
        [
            "auth-mechanism=oauth2-resource-server:oauth2ResourceServer(oauth2 -> oauth2.jwt())",
            "auth-mechanism=custom-filter:JWTFilter",
            "auth-mechanism=http-basic:httpBasic()!disabled in chain",
        ],
    )
    def test_mechanism_values_accepted(self, raw: str) -> None:
        assert parse_tag(raw).namespace == "auth-mechanism"

    @pytest.mark.parametrize(
        "raw",
        [
            "auth-mechanism=jwt:whatever",  # not a registered kind
            "auth-mechanism=custom-filter",  # missing the raw text
        ],
    )
    def test_mechanism_values_rejected(self, raw: str) -> None:
        with pytest.raises(TagValidationError, match="auth-mechanism"):
            parse_tag(raw)

    def test_enforcement_value_accepted(self) -> None:
        tag = parse_tag("auth-enforcement=interceptor|/api/**|AuthInterceptor.preHandle")
        assert tag.value.startswith("interceptor|")

    def test_enforcement_unresolvable_pattern_is_expressible(self) -> None:
        # The whole point: a guard whose scope we cannot read is still stated.
        assert parse_tag("auth-enforcement=servlet-filter|{?}|TokenFilter").namespace == (
            "auth-enforcement"
        )

    def test_enforcement_rejects_a_declarative_kind(self) -> None:
        with pytest.raises(TagValidationError, match="auth-enforcement"):
            parse_tag("auth-enforcement=annotation|/x|@PreAuthorize")

    def test_auth_rule_accepts_the_unresolvable_pattern_form(self) -> None:
        # §5.2.9: a rule read but not resolved is emitted as '{?}' so it can
        # withhold the claim — dropping it is what manufactured wrong answers.
        assert parse_tag('auth-rule=POST|{?}|hasAnyRole(admin, "USER")').namespace == "auth-rule"
