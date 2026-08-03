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
        assert (
            facts.env["spring.security.oauth2.resourceserver.jwt.issuer-uri"]
            == "https://issuer.example.com"
        )


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
