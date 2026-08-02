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
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "petstore"
        assert facts.server_port == 8080
        assert "config-multi-doc-partial" in facts.notes

    def test_single_document_carries_no_note(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "spring:\n  application:\n    name: petstore\n")
        assert parse_app_config(tmp_path).notes == []


class TestProfileFileNotes:
    """Profile-specific files are not merged (T3) — the skip is queryable, not silent."""

    def test_profile_files_are_recorded(self, tmp_path: Path) -> None:
        _write(tmp_path, "application.yml", "spring:\n  application:\n    name: petstore\n")
        _write(tmp_path, "application-docker.yml", "server:\n  port: 9090\n")
        _write(tmp_path, "application-prod.properties", "server.port=9091\n")
        facts = parse_app_config(tmp_path)
        assert facts.application_name == "petstore"
        assert facts.notes == [
            "config-profile-files-skipped:application-docker.yml",
            "config-profile-files-skipped:application-prod.properties",
        ]

    def test_profile_files_recorded_even_without_base_config(self, tmp_path: Path) -> None:
        _write(tmp_path, "application-docker.yml", "server:\n  port: 9090\n")
        facts = parse_app_config(tmp_path)
        assert facts.env == {}
        assert facts.notes == ["config-profile-files-skipped:application-docker.yml"]
