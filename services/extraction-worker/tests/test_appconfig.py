"""Application-config fact extraction tests (yml + properties, allowlist)."""

from pathlib import Path

from wadi_worker.appconfig import parse_app_config


def _write(build_root: Path, name: str, content: str) -> None:
    resources = build_root / "src" / "main" / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / name).write_text(content)


class TestYamlConfig:
    def test_identity_port_and_url_keys(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  application:
    name: petstore
server:
  port: 8080
inventory:
  url: http://inventory:8081
logging:
  level: DEBUG
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "petstore"
        assert facts.server_port == 8080
        assert facts.env == {
            "inventory.url": "http://inventory:8081",
            "server.port": "8080",
            "spring.application.name": "petstore",
        }  # logging.level is not network-relevant — allowlisted out

    def test_gateway_routes_parse_predicates_and_strip(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  cloud:
    gateway:
      routes:
        - id: inventory-route
          uri: lb://inventory
          predicates:
            - Path=/api/v1/inventory/**
          filters:
            - StripPrefix=2
        - id: fallback
          uri: http://legacy:8000
          predicates:
            - Path=/legacy/**,/old/**
""",
        )
        facts = parse_app_config(tmp_path)
        assert [
            (r.route_id, r.path_prefix, r.target_uri, r.strip_prefix) for r in facts.gateway_routes
        ] == [
            ("inventory-route", "/api/v1/inventory/**", "lb://inventory", 2),
            ("fallback", "/legacy/**", "http://legacy:8000", 0),
            ("fallback", "/old/**", "http://legacy:8000", 0),
        ]

    def test_discovery_locator_flag(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  cloud:
    gateway:
      discovery:
        locator:
          enabled: true
""",
        )
        assert parse_app_config(tmp_path).gateway_discovery_locator is True
        assert parse_app_config(tmp_path).gateway_routes == []

    def test_malformed_yaml_degrades_to_empty(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "spring: [unclosed")
        facts = parse_app_config(tmp_path)
        assert facts.env == {}
        assert facts.application_name is None

    def test_security_keys_survive(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: https://issuer.example.com
""",
        )
        facts = parse_app_config(tmp_path)
        # The KEY survives, as the auth evidence it is. Its value does not
        # reach `env`, which is published on the boundary (issue #28): the
        # same namespace holds `client-secret` and `user.password`.
        assert facts.security_keys == ["spring.security.oauth2.resourceserver.jwt.issuer-uri"]
        assert "spring.security.oauth2.resourceserver.jwt.issuer-uri" not in facts.env
        assert "https://issuer.example.com" not in facts.env.values()


class TestPropertiesConfig:
    def test_flat_properties(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.properties",
            """
# comment
spring.application.name=billing
server.port=9000
billing.audit.uri=http://audit:7000
unrelated.key=x
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "billing"
        assert facts.server_port == 9000
        assert facts.env["billing.audit.uri"] == "http://audit:7000"
        assert "unrelated.key" not in facts.env

    def test_non_numeric_port_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.properties", "server.port=${PORT}")
        assert parse_app_config(tmp_path).server_port is None


class TestMissingConfig:
    def test_no_file_is_empty_facts(self, tmp_path: Path) -> None:
        facts = parse_app_config(tmp_path)
        assert facts.env == {}
        assert facts.gateway_routes == []


class TestMultiDocumentYaml:
    """T1 (§5.2.5): a `---` multi-doc file used to silently zero ALL facts."""

    def test_base_document_parses_and_partial_is_recorded(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  application:
    name: petstore
server:
  port: 8080
---
spring:
  config:
    activate:
      on-profile: docker
server:
  port: 9090
""",
        )
        # Active set unknown -> the docker document MERGES with a note (T3);
        # its server.port override wins (Spring profile precedence).
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "petstore"
        assert facts.server_port == 9090
        assert "config-profile-doc-merged:docker" in facts.notes

        # Known active set selects exactly the matching documents.
        active = parse_app_config(tmp_path, active_profiles=["docker"])
        assert active.server_port == 9090
        assert "config-profile-doc-merged:docker" not in active.notes
        inactive = parse_app_config(tmp_path, active_profiles=["prod"])
        assert inactive.server_port == 8080

    def test_single_document_carries_no_note(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "spring:\n  application:\n    name: petstore\n")
        assert parse_app_config(tmp_path).notes == []


class TestProfileFileMerge:
    """T3: profile files MERGE — exactly the active set when known, else all
    with an honest note (over-approximation beats dropping declared config)."""

    def test_all_profiles_merge_when_active_set_unknown(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "spring:\n  application:\n    name: petstore\n")
        _write(tmp_path, "application-docker.yml", "server:\n  port: 9090\n")
        _write(tmp_path, "application-prod.properties", "server.port=9091\n")
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "petstore"
        # Alphabetical merge order: prod (properties) lands last and wins.
        assert facts.server_port == 9091
        assert facts.notes == [
            "config-profile-merged-all",
            "config-profile-merged:application-docker.yml",
            "config-profile-merged:application-prod.properties",
        ]

    def test_known_active_set_selects_exactly(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "server:\n  port: 8080\n")
        _write(tmp_path, "application-docker.yml", "server:\n  port: 9090\n")
        _write(tmp_path, "application-prod.yml", "server:\n  port: 9091\n")
        facts = parse_app_config(tmp_path, active_profiles=["docker"])
        assert facts.server_port == 9090
        assert facts.notes == ["config-profile-merged:application-docker.yml"]

    def test_profile_file_merges_even_without_base_config(self, tmp_path: Path) -> None:
        _write(tmp_path, "application-docker.yml", "server:\n  port: 9090\n")
        facts = parse_app_config(tmp_path)
        assert facts.server_port == 9090
        assert "config-profile-merged:application-docker.yml" in facts.notes


class TestT3GatewayDepth:
    def test_zuul_routes_with_strip_default_true(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
zuul:
  routes:
    users:
      path: /users/**
      serviceId: user-service
    ledger:
      path: /ledger/**
      url: http://ledger:9000
      stripPrefix: false
""",
        )
        facts = parse_app_config(tmp_path)
        by_id = {r.route_id: r for r in facts.gateway_routes}
        assert by_id["users"].target_uri == "lb://user-service"
        assert by_id["users"].strip_prefix == 1  # Zuul default: strip the prefix
        assert by_id["ledger"].target_uri == "http://ledger:9000"
        assert by_id["ledger"].strip_prefix == 0

    def test_scg_expanded_map_form(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  cloud:
    gateway:
      routes:
        - id: orders
          uri: lb://orders
          predicates:
            - name: Path
              args:
                patterns: /orders/**
          filters:
            - name: StripPrefix
              args:
                parts: 1
""",
        )
        facts = parse_app_config(tmp_path)
        [route] = facts.gateway_routes
        assert route.path_prefix == "/orders/**"
        assert route.target_uri == "lb://orders"
        assert route.strip_prefix == 1

    def test_unmodelled_gateway_shapes_are_noted_never_dropped(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  cloud:
    gateway:
      routes:
        - id: rewrite
          uri: lb://orders
          predicates:
            - Path=/api/**
            - Host=**.orders.example.com
          filters:
            - RewritePath=/api/(?<segment>.*), /$\\{segment}
""",
        )
        facts = parse_app_config(tmp_path)
        assert "gateway-filter-unmodelled:RewritePath" in facts.notes
        assert "gateway-predicate-unmodelled:Host" in facts.notes
        # The Path predicate itself still routes.
        assert facts.gateway_routes[0].path_prefix == "/api/**"


class TestConfigValuesNotPublished:
    """§5.2.18, issue #28: `env` and the routes are published on the boundary."""

    def test_only_routing_keys_are_carried_never_a_namespace(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  datasource:
    url: jdbc:postgresql://db:5432/shop?user=shop&password=hunter2
  security:
    user:
      password: hunter2
    oauth2:
      client:
        registration:
          shop:
            client-secret: hunter2
            redirect-uri: https://shop.example.test/login/oauth2/code/shop
  cloud:
    gateway:
      default-filters:
        - AddRequestHeader=X-Api-Key, hunter2
      httpclient:
        connect-timeout: 1000
inventory:
  url: http://inventory:8081
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.env == {"inventory.url": "http://inventory:8081"}
        assert facts.security_keys == [
            "spring.security.oauth2.client.registration.shop.client-secret",
            "spring.security.oauth2.client.registration.shop.redirect-uri",
            "spring.security.user.password",
        ]
        # Dropped by rule, so none of these is a parsing gap to note.
        assert facts.notes == []

    def test_credentials_leave_a_routing_value_and_the_address_stays(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.properties",
            """
billing.url=https://billing-user:hunter2@billing:9000/api
audit.uri=http://audit:7000/log?access_token=hunter2
partner.host=partner-user:hunter2@partner.example.test
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.env == {
            "audit.uri": "http://audit:7000/log",
            "billing.url": "https://billing:9000/api",
            "partner.host": "partner.example.test",
        }
        assert facts.notes == []

    def test_a_properties_line_separated_by_a_colon_or_a_space_keeps_its_value_out_of_the_key(
        self, tmp_path: Path
    ) -> None:
        # Java properties end a key at the first `=`, `:` or space. A parser
        # that knows only `=` splits a base64 value at its padding and puts
        # the value into the "key", which is published as auth evidence.
        _write(
            tmp_path,
            "application.properties",
            """
spring.security.user.password: aHVudGVyMg==
spring.security.user.name hunter2=x
billing.url: https://billing:9000/api?sig=aHVudGVyMg==
audit.uri http://audit:7000/log
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.security_keys == [
            "spring.security.user.name",
            "spring.security.user.password",
        ]
        assert facts.env == {
            "audit.uri": "http://audit:7000/log",
            "billing.url": "https://billing:9000/api",
        }

    def test_a_list_of_maps_under_a_routing_key_is_not_published_as_text(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
partners:
  url:
    - name: a
      password: hunter2
    - name: b
      password: hunter2
upstreams:
  host:
    - a.example.test
    - b.example.test
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.env == {"upstreams.host": "a.example.test,b.example.test"}
        assert facts.notes == []
        published = (facts.env, facts.notes, facts.security_keys, facts.gateway_routes)
        assert "hunter2" not in repr(published)

    def test_inseparable_credentials_withhold_the_value_and_say_so(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.properties",
            "reports.url=https://reports-user:hun/ter2@reports:8443/x\n",
        )
        facts = parse_app_config(tmp_path)
        assert facts.env == {}
        assert facts.notes == ["config-value-withheld:reports.url"]

    def test_gateway_route_targets_lose_their_credentials(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
spring:
  cloud:
    gateway:
      routes:
        - id: legacy
          uri: http://gateway-user:hunter2@legacy:8000
          predicates:
            - Path=/legacy/**
        - id: broken
          uri: http://gateway-user:hun/ter2@broken:8000
          predicates:
            - Path=/broken/**
zuul:
  routes:
    old:
      path: /old/**
      url: http://zuul-user:hunter2@old:8000
""",
        )
        facts = parse_app_config(tmp_path)
        assert [(r.route_id, r.path_prefix, r.target_uri) for r in facts.gateway_routes] == [
            ("legacy", "/legacy/**", "http://legacy:8000"),
            ("old", "/old/**", "http://old:8000"),
        ]
        # The route that could not be published is counted, by id.
        assert facts.notes == ["gateway-route-target-withheld:broken"]
        assert facts.env == {"zuul.routes.old.url": "http://old:8000"}


class TestT3DiscoveryNames:
    def test_eureka_and_consul_registration_names(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "application.yml",
            """
eureka:
  instance:
    appname: ts-order
spring:
  cloud:
    consul:
      discovery:
        service-name: order-svc
""",
        )
        facts = parse_app_config(tmp_path)
        assert facts.discovery_names == ["ts-order", "order-svc"]
