"""The publication rule for config values, case by case (§5.2.18, issue #28)."""

import pytest

from wadi_worker.config_values import (
    is_jdbc_url,
    is_key_name,
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
            # A path variable is not a placeholder, and the route keeps it.
            "http://users:8080/users/{id}",
            "${base}/users/{id}",
            "http://${host}/users/{id}/orders",
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
            ("http://audit:7000/log?access_token=abc", "http://audit:7000/log"),
            ("http://a/x?page=2&api_key=abc&sort=asc", "http://a/x"),
            ("http://a/x?password=abc#frag", "http://a/x"),
            ("http://a/x;jsessionid=1?apiKey=abc", "http://a/x"),
            # No list of secret parameter names is complete, so none is kept.
            ("https://h/api?code=abc", "https://h/api"),
            ("https://h/api?jwt=abc&session=def", "https://h/api"),
            ("https://h/cb#access_token=abc", "https://h/cb"),
            ("https://h/api?password=abc#def", "https://h/api"),
            ("http://a/x?page=2&sort=asc", "http://a/x"),
            ("https://u:p@h/api?token=abc", "https://h/api"),
            # A placeholder keeps its closing brace.
            ("${API_URL:http://h/api?token=abc}", "${API_URL:http://h/api}"),
            ("${A:${B:http://h/api?token=abc}}", "${A:${B:http://h/api}}"),
            # A placeholder inside the query goes with it.
            ("http://h/api?apiKey=${API_KEY}", "http://h/api"),
            ("http://h/api?apiKey=${API_KEY}&page=2", "http://h/api"),
        ],
    )
    def test_the_query_fragment_and_matrix_parameters_are_dropped(
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
            # The first host of a list is not the user-info of the second.
            "http://a:80,u:p@b:80",
            # A connection string is not an address.
            "Server=db; Password=abc",
            "Password=abc;Server=db",
            # A value that runs past the query: a space or a comma inside it.
            "https://h/api?password=abc def",
            "https://h/api?ids=1,2&token=abc",
            # What follows the comma is not a new address, so the query runs
            # on past it and the value cannot be cut at a safe place.
            "https://api/v1?scope=read,abc",
            "${X:http://h?k=a,abc}",
            "http://x/?k=a,abc",
            "http://h/x#a,abc",
            "http://h/x;a=1,abc",
            # A comma after a query may open the next address of a list or sit
            # inside the query, and text alone cannot tell which.
            "http://a/x?t=abc,http://b/y?t=def",
            "http://a/x?t=abc, https://b/y",
            "http://auth?cb=https://a/x,https://hooks.example/T0/SECRET",
            "http://h?scope=read,s3cret://x",
            "http://h#frag,abc://SECRET",
            "http://h;jsessionid=X,ab://SECRET",
            "host:8080?x=1,host2:8080",
            # Spring joins text after a placeholder's default onto its query.
            "${A:http://h?token=ab}cd",
            "${A:http://h?token=ab},cd",
            "{http://h?token=ab}cd",
            "${A:http://h?x=1}/path",
            "http://h?x={a,b}",
            # A closing brace that closes nothing, or an opening one left open.
            "http://h?t=a}b${c",
            "http://h/}x",
            "${A:{b}",
            # Text that is no address at all.
            "{'name': 'a', 'password': 'abc'}",
            # Nothing left once the user-info is gone.
            "@project.url@",
            "",
        ],
    )
    def test_a_value_that_cannot_be_read_as_an_address_is_withheld(self, value: str) -> None:
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


class TestKeyNames:
    @pytest.mark.parametrize(
        "name",
        ["inventory.url", "SPRING_DATASOURCE_URL", "zuul.routes.orders.url", "hosts[0].url"],
    )
    def test_a_config_key_or_an_environment_name_reads_as_a_key(self, name: str) -> None:
        assert is_key_name(name)

    @pytest.mark.parametrize(
        "name",
        ["spring.security.user.password: abc", "audit abc.url", "a=b.url", ""],
    )
    def test_text_that_holds_more_than_a_key_does_not(self, name: str) -> None:
        assert not is_key_name(name)


class TestPublishableEntries:
    def test_an_entry_whose_key_does_not_read_as_a_key_is_dropped(self) -> None:
        published, withheld = publishable_entries([("audit: abc.url", "http://audit:7000")])
        assert published == {}
        assert withheld == []

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
