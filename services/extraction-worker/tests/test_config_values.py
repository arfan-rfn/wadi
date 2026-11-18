"""The publication rule for config values, case by case (§5.2.18, issue #28)."""

import pytest

from wadi_worker.config_values import (
    is_jdbc_url,
    is_security_key,
    publishable_entries,
    strip_credentials,
)


class TestStripCredentials:
    @pytest.mark.parametrize(
        "value",
        [
            "http://inventory:8081",
            "lb://inventory",
            "https://billing.example.test/api/v1",
            "inventory",
            "8081",
            "/inventory-api",
            # Placeholders are how nested keys resolve; they must pass through.
            "http://${inventory.host}:${inventory.port}/api",
            "${INVENTORY_URL:http://inventory:8081}",
            "http://a:8080,http://b:8080",
        ],
    )
    def test_a_value_without_credentials_is_published_as_written(self, value: str) -> None:
        assert strip_credentials(value) == value

    @pytest.mark.parametrize(
        ("value", "published"),
        [
            ("https://user:pw@billing:9000/api", "https://billing:9000/api"),
            ("https://user@billing:9000/api", "https://billing:9000/api"),
            ("https://:pw@billing:9000", "https://billing:9000"),
            # A password holding an `@` goes with the rest of the user-info.
            ("https://user:p@ss@billing:9000/api", "https://billing:9000/api"),
            ("postgres://shop:pw@db:5432/shop", "postgres://db:5432/shop"),
            ("mongodb://shop:pw@m1:27017,m2:27017/shop", "mongodb://m1:27017,m2:27017/shop"),
            ("http://${user}:${password}@inventory:8081", "http://inventory:8081"),
            ("http://u:p@a:8080,http://v:q@b:8080", "http://a:8080,http://b:8080"),
            ("${API_URL:https://user:pw@api.example.test}", "${API_URL:https://api.example.test}"),
            # A bare host can carry user-info too.
            ("user:pw@partner.example.test", "partner.example.test"),
        ],
    )
    def test_user_info_is_removed_and_the_address_kept(self, value: str, published: str) -> None:
        assert strip_credentials(value) == published

    @pytest.mark.parametrize(
        ("value", "published"),
        [
            ("http://audit:7000/log?access_token=abc", "http://audit:7000/log?access_token="),
            ("http://a/x?page=2&api_key=abc&sort=asc", "http://a/x?page=2&api_key=&sort=asc"),
            ("http://a/x?password=abc#frag", "http://a/x?password=#frag"),
            ("http://a/x?client_secret=abc&sig=def", "http://a/x?client_secret=&sig="),
            ("http://a/x?Authorization=Bearer", "http://a/x?Authorization="),
            ("http://a/x;jsessionid=1?apiKey=abc", "http://a/x;jsessionid=1?apiKey="),
            ("http://a/x?page=2&sort=asc", "http://a/x?page=2&sort=asc"),
        ],
    )
    def test_a_secret_query_value_is_blanked_and_its_name_kept(
        self, value: str, published: str
    ) -> None:
        assert strip_credentials(value) == published

    @pytest.mark.parametrize(
        "value",
        [
            # An unencoded `/`, `?` or `#` in a password ends the authority
            # early, so what follows `://` is half a password and the real
            # host sits after the `@`. Neither half is safe to publish.
            "https://user:pa/ss@reports:8443/x",
            "https://user:pa?ss@reports:8443",
            "https://user:pa#ss@reports:8443",
            "jdbc:oracle:thin:scott/tiger@db:1521:orcl",
            # Nothing left once the user-info is gone.
            "@project.url@",
            "",
        ],
    )
    def test_a_value_whose_credentials_cannot_be_separated_is_withheld(self, value: str) -> None:
        assert strip_credentials(value) is None


class TestKeyAndValueClasses:
    @pytest.mark.parametrize(
        "name",
        [
            "spring.security.user.password",
            "spring.security.oauth2.client.registration.shop.client-secret",
            "SPRING_SECURITY_USER_PASSWORD",
            "SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI",
            "Spring.Security.user.name",
        ],
    )
    def test_the_security_namespace_in_either_spelling(self, name: str) -> None:
        assert is_security_key(name)

    @pytest.mark.parametrize(
        "name", ["spring.securityx.url", "app.spring.security.url", "SECURITY_URL", "server.port"]
    )
    def test_a_neighbouring_key_is_not_the_security_namespace(self, name: str) -> None:
        assert not is_security_key(name)

    @pytest.mark.parametrize(
        "value",
        [
            "jdbc:postgresql://db:5432/shop",
            "JDBC:mysql://db/shop?user=u&password=p",
            "jdbc:sqlserver://db;user=sa;password=p",
            "${DB_URL:jdbc:h2:mem:shop}",
        ],
    )
    def test_a_jdbc_url_in_any_position(self, value: str) -> None:
        assert is_jdbc_url(value)

    def test_an_http_url_is_not_jdbc(self) -> None:
        assert not is_jdbc_url("http://jdbcproxy:8080/api")


class TestPublishableEntries:
    def test_dropped_by_rule_is_not_a_gap_and_withheld_is(self) -> None:
        published, withheld = publishable_entries(
            [
                ("inventory.url", "http://u:p@inventory:8081"),
                ("spring.datasource.url", "jdbc:postgresql://db/shop?password=p"),
                ("spring.security.oauth2.resourceserver.jwt.issuer-uri", "https://idp"),
                ("reports.url", "https://u:pa/ss@reports"),
            ]
        )
        assert published == {"inventory.url": "http://inventory:8081"}
        # Only the entry a reader could have routed by is counted as withheld.
        assert withheld == ["reports.url"]
