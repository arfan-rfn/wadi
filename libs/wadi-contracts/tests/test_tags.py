"""Tag registry tests — the vocabulary is a contract, not a convention (§7)."""

import pytest

from wadi_contracts.tags import (
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
            {"endpoint", "sink", "model", "auth", "auth-rule", "token-propagation", "async-root"}
        )

    def test_async_root_kinds(self) -> None:
        assert parse_tag("async-root=scheduled").value == "scheduled"
        assert parse_tag("async-root=framework-callback").namespace == "async-root"
        with pytest.raises(TagValidationError, match="async-root"):
            parse_tag("async-root=cron")

    def test_validate_tag_unknown_namespace_names_known_ones(self) -> None:
        with pytest.raises(TagValidationError, match="endpoint"):
            validate_tag("nope", "x")
