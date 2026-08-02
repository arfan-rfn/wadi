"""Boundary-analyzer unit tests (real files, no network)."""

from pathlib import Path

from wadi_worker.boundary import discover_services

POM = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <artifactId>{artifact}</artifactId>
  <version>1.0.0</version>
  {extra}
</project>
"""


def write_pom(directory: Path, artifact: str, *, modules: list[str] | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    extra = ""
    if modules:
        module_tags = "".join(f"<module>{m}</module>" for m in modules)
        extra = f"<modules>{module_tags}</modules>"
    (directory / "pom.xml").write_text(POM.format(artifact=artifact, extra=extra))


class TestMavenDiscovery:
    def test_single_module_at_root(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "orders-service")
        services = discover_services(tmp_path)
        assert len(services) == 1
        assert services[0].name == "orders-service"
        assert services[0].build_root == "."
        assert services[0].build_system == "maven"
        assert services[0].languages == ["java"]

    def test_multi_module_aggregator_excluded(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["orders", "billing"])
        write_pom(tmp_path / "orders", "orders-service")
        write_pom(tmp_path / "billing", "billing-service")
        services = discover_services(tmp_path)
        assert [s.name for s in services] == ["billing-service", "orders-service"]
        assert {s.build_root for s in services} == {"orders", "billing"}

    def test_poms_under_target_and_hidden_dirs_ignored(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "svc")
        write_pom(tmp_path / "target" / "generated", "junk")
        write_pom(tmp_path / ".cache" / "x", "junk2")
        services = discover_services(tmp_path)
        assert [s.name for s in services] == ["svc"]

    def test_malformed_pom_skipped_not_fatal(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "good", "good-service")
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "pom.xml").write_text("<project><unclosed>")
        services = discover_services(tmp_path)
        assert [s.name for s in services] == ["good-service"]

    def test_empty_repo_yields_nothing(self, tmp_path: Path) -> None:
        assert discover_services(tmp_path) == []

    def test_pom_without_artifact_id_uses_directory_name(self, tmp_path: Path) -> None:
        directory = tmp_path / "mystery"
        directory.mkdir()
        (directory / "pom.xml").write_text(
            '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<modelVersion>4.0.0</modelVersion></project>"
        )
        services = discover_services(tmp_path)
        assert services[0].name == "mystery"


class TestComposeIdentity:
    def test_identity_by_build_context(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "orders", "orders-service")
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  orders:
    build: ./orders
    ports:
      - "9000:8080"
"""
        )
        services = discover_services(tmp_path)
        assert services[0].hostnames == ["orders"]
        assert services[0].ports == [8080]

    def test_identity_by_service_name_match(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "svc", "billing")
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  billing:
    image: acme/billing
    expose:
      - "8081"
"""
        )
        services = discover_services(tmp_path)
        assert services[0].hostnames == ["billing"]
        assert services[0].ports == [8081]

    def test_port_syntaxes(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "svc", "gateway")
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  gateway:
    build: ./svc
    ports:
      - "127.0.0.1:9000:8080"
      - "8443:8443/tcp"
      - 7000
      - target: 6000
        published: 6001
"""
        )
        services = discover_services(tmp_path)
        assert services[0].ports == [6000, 7000, 8080, 8443]

    def test_malformed_compose_degrades_gracefully(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "svc", "svc")
        (tmp_path / "docker-compose.yml").write_text("services: [not: {valid")
        services = discover_services(tmp_path)
        assert services[0].hostnames == []


class TestAppConfigWiring:
    def test_config_facts_attach_to_discovered_services(self, tmp_path: Path) -> None:
        write_pom(tmp_path / "orders", "orders")
        resources = tmp_path / "orders" / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        (resources / "application.yml").write_text(
            "spring:\n  application:\n    name: orders\nserver:\n  port: 8085\n"
        )
        write_pom(tmp_path / "billing", "billing")  # no config file

        services = discover_services(tmp_path)
        by_name = {s.name: s for s in services}
        assert by_name["orders"].config.application_name == "orders"
        assert by_name["orders"].config.server_port == 8085
        assert by_name["billing"].config.application_name is None
        assert by_name["billing"].config.env == {}
