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


def write_pom(
    directory: Path,
    artifact: str,
    *,
    modules: list[str] | None = None,
    dependencies: list[str] | None = None,
    java_source: str | None = "@RestController class App {}",
) -> None:
    """Write a pom; non-aggregators get a Java source (no-Java modules are
    skipped by discovery, §5.2.6). Default source carries a service marker.
    """
    directory.mkdir(parents=True, exist_ok=True)
    extra = ""
    if modules:
        module_tags = "".join(f"<module>{m}</module>" for m in modules)
        extra = f"<modules>{module_tags}</modules>"
    if dependencies:
        dep_tags = "".join(
            f"<dependency><groupId>g</groupId><artifactId>{d}</artifactId></dependency>"
            for d in dependencies
        )
        extra += f"<dependencies>{dep_tags}</dependencies>"
    (directory / "pom.xml").write_text(POM.format(artifact=artifact, extra=extra))
    if not modules and java_source is not None:
        source_dir = directory / "src" / "main" / "java"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "App.java").write_text(java_source)


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
        source_dir = directory / "src" / "main" / "java"
        source_dir.mkdir(parents=True)
        (source_dir / "App.java").write_text("@RestController class App {}")
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


class TestNameCollisions:
    """T1 (§5.2.5): TrainTicket's two gateways both declare artifactId 'gateway'."""

    def test_colliding_artifact_ids_fall_back_to_directory_names(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["ts-gateway", "ts-new-gateway", "ts-order"])
        write_pom(tmp_path / "ts-gateway", "gateway")
        write_pom(tmp_path / "ts-new-gateway", "gateway")
        write_pom(tmp_path / "ts-order", "ts-order-service")
        services = discover_services(tmp_path)
        by_root = {s.build_root: s.name for s in services}
        assert by_root["ts-gateway"] == "ts-gateway"
        assert by_root["ts-new-gateway"] == "ts-new-gateway"
        # Non-colliding names keep the artifactId.
        assert by_root["ts-order"] == "ts-order-service"

    def test_unique_artifact_ids_are_untouched(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["a", "b"])
        write_pom(tmp_path / "a", "svc-a")
        write_pom(tmp_path / "b", "svc-b")
        assert {s.name for s in discover_services(tmp_path)} == {"svc-a", "svc-b"}


class TestModuleClassification:
    """§5.2.6: service vs library vs skipped, and transitive library roots."""

    def test_shared_library_is_classified_and_staged_transitively(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["svc", "libA", "libB"])
        write_pom(tmp_path / "svc", "svc", dependencies=["libA"])
        # libA -> libB: the lib->lib chain (yas payment-paypal shape).
        write_pom(tmp_path / "libA", "libA", dependencies=["libB"], java_source="class A {}")
        write_pom(tmp_path / "libB", "libB", java_source="class B {}")
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["svc"].kind == "service"
        assert by_root["libA"].kind == "library"
        assert by_root["libB"].kind == "library"
        assert by_root["svc"].library_roots == ["libA", "libB"]
        assert by_root["libA"].library_roots == []

    def test_module_with_service_markers_is_never_a_library(self, tmp_path: Path) -> None:
        # payment -> payment-paypal where the dep HAS controllers: not staged.
        write_pom(tmp_path, "parent", modules=["a", "b"])
        write_pom(tmp_path / "a", "a", dependencies=["b"])
        write_pom(tmp_path / "b", "b")  # default source carries @RestController
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["b"].kind == "service"
        assert by_root["a"].library_roots == []

    def test_no_java_module_is_skipped(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["svc", "frontend"])
        write_pom(tmp_path / "svc", "svc")
        write_pom(tmp_path / "frontend", "frontend", java_source=None)
        assert [s.build_root for s in discover_services(tmp_path)] == ["svc"]


class TestServiceMarkerBoundaries:
    """§5.2.6: @ControllerAdvice (yas common-library) is library code — the
    @Controller marker must match on a word boundary, never by substring."""

    def test_controller_advice_does_not_flip_a_library_to_service(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["svc", "shared"])
        write_pom(tmp_path / "svc", "svc", dependencies=["shared"])
        write_pom(
            tmp_path / "shared",
            "shared",
            java_source="@ControllerAdvice class Handler {}",
        )
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["shared"].kind == "library"
        assert by_root["svc"].library_roots == ["shared"]

    def test_rest_controller_advice_is_not_a_marker_either(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["svc", "shared"])
        write_pom(tmp_path / "svc", "svc", dependencies=["shared"])
        write_pom(
            tmp_path / "shared",
            "shared",
            java_source="@RestControllerAdvice class Handler {}",
        )
        assert {s.build_root: s.kind for s in discover_services(tmp_path)}["shared"] == "library"

    def test_real_controller_still_marks_a_service(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "parent", modules=["svc", "shared"])
        write_pom(tmp_path / "svc", "svc", dependencies=["shared"])
        write_pom(
            tmp_path / "shared",
            "shared",
            java_source='@Controller class Web { @GetMapping("/x") void x() {} }',
        )
        assert {s.build_root: s.kind for s in discover_services(tmp_path)}["shared"] == "service"
