"""Boundary-analyzer unit tests (real files, no network)."""

from pathlib import Path

from wadi_worker.boundary import discover_services, discover_system_services

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
    packaging: str | None = None,
) -> None:
    """Write a pom; non-aggregators get a Java source (no-Java modules are
    skipped by discovery, §5.2.6). The default source carries a CONTROLLER,
    which since §5.2.14 marks web presence and not deployability — pass
    `@SpringBootApplication` (or `packaging="war"`) for a module that runs.
    """
    directory.mkdir(parents=True, exist_ok=True)
    extra = f"<packaging>{packaging}</packaging>" if packaging else ""
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

    def test_a_deployable_module_is_never_a_library(self, tmp_path: Path) -> None:
        # payment -> payment-paypal where the dep really does run on its own:
        # not staged, not absorbed. §5.2.14 narrowed the signal from "has a
        # controller" to "has an entry point", because a library shipping a
        # controller is an ordinary Spring pattern — but a module with a boot
        # main is a service no matter who depends on it, and that is what this
        # protects.
        write_pom(tmp_path, "parent", modules=["a", "b"])
        write_pom(tmp_path / "a", "a", dependencies=["b"])
        write_pom(
            tmp_path / "b",
            "b",
            java_source="@SpringBootApplication class App {}",
        )
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["b"].kind == "service"
        assert by_root["a"].library_roots == []

    def test_a_war_packaged_module_is_never_a_library(self, tmp_path: Path) -> None:
        # A plain Spring MVC app has no @SpringBootApplication and is still a
        # thing you deploy. Packaging declares that on its own.
        write_pom(tmp_path, "parent", modules=["a", "b"])
        write_pom(tmp_path / "a", "a", dependencies=["b"])
        write_pom(tmp_path / "b", "b", packaging="war")
        assert {s.build_root: s.kind for s in discover_services(tmp_path)}["b"] == "service"

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

    def test_a_library_may_ship_a_controller(self, tmp_path: Path) -> None:
        # §5.2.14, and the case that motivated it. ICPC's `base` ships exactly
        # one @RestController — a reusable web fragment — and the consuming
        # app's own SecurityConfig carries the rule for its route, which is
        # only sayable if the CONSUMER serves it. Treating the controller as
        # proof of a service gave that library its own CPG, cost the auth
        # vocabulary an annotation, and left 335 response shapes unresolved
        # for the app that actually deploys it.
        write_pom(tmp_path, "parent", modules=["svc", "shared"])
        write_pom(
            tmp_path / "svc",
            "svc",
            dependencies=["shared"],
            java_source="@SpringBootApplication class App {}",
        )
        write_pom(
            tmp_path / "shared",
            "shared",
            java_source='@Controller class Web { @GetMapping("/x") void x() {} }',
        )
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["shared"].kind == "library"
        # ...and its sources are staged into the app that deploys them.
        assert by_root["svc"].library_roots == ["shared"]


class TestCrossRepoLibraries:
    """§5.2.14: a shared internal jar in its OWN repository.

    The shape that produced the defect. Per-repo classification resolves
    `<artifactId>base</artifactId>` against one checkout's module map, which
    cannot contain a sibling repo's module — so the edge was never seen, the
    library got its own service and its own CPG, and the app that deploys it
    lost 77 guarded endpoints and 335 response shapes to types it could no
    longer see.
    """

    def test_a_library_in_a_sibling_repo_is_classified_as_one(self, tmp_path: Path) -> None:
        app, lib = tmp_path / "app", tmp_path / "lib"
        write_pom(
            app, "backend", dependencies=["base"], java_source="@SpringBootApplication class App {}"
        )
        write_pom(lib, "base", java_source="@RestController class Fragment {}")

        by_repo = discover_system_services({"app": app, "lib": lib})

        assert by_repo["lib"][0].kind == "library"
        assert by_repo["app"][0].kind == "service"
        # `repo::root` is what lets the stage reach the other checkout.
        assert by_repo["app"][0].library_roots == ["lib::."]

    def test_per_repo_discovery_alone_cannot_see_the_edge(self, tmp_path: Path) -> None:
        # The counterweight that names the mechanism: analyzed on its own, the
        # library repo has no dependency edge to observe and is a service. This
        # is not a bug in single-repo discovery — it is why classification has
        # to be system-wide.
        lib = tmp_path / "lib"
        write_pom(lib, "base", java_source="@RestController class Fragment {}")
        assert discover_services(lib)[0].kind == "service"

    def test_a_same_repo_library_keeps_its_bare_root(self, tmp_path: Path) -> None:
        # No qualifier when there is nothing to qualify: single-repo staging is
        # byte-identical to what it was before the change.
        write_pom(tmp_path, "parent", modules=["svc", "shared"])
        write_pom(
            tmp_path / "svc",
            "svc",
            dependencies=["shared"],
            java_source="@SpringBootApplication class App {}",
        )
        write_pom(tmp_path / "shared", "shared", java_source="class Util {}")
        by_root = {s.build_root: s for s in discover_services(tmp_path)}
        assert by_root["svc"].library_roots == ["shared"]


class TestClientLibraryCensus:
    """§5.4.2: presence facts from import scan — the yas RestClient lesson."""

    def test_census_detects_unmodelled_clients(self, tmp_path: Path) -> None:
        write_pom(
            tmp_path,
            "svc",
            java_source=(
                "import org.springframework.web.client.RestClient;\n"
                "import java.net.http.HttpClient;\n"
                "@RestController class App {}"
            ),
        )
        assert discover_services(tmp_path)[0].client_libraries == [
            "jdk-httpclient",
            "restclient",
        ]

    def test_census_detects_modelled_clients_too(self, tmp_path: Path) -> None:
        write_pom(
            tmp_path,
            "svc",
            java_source=(
                "import org.springframework.web.client.RestTemplate;\n@RestController class App {}"
            ),
        )
        assert discover_services(tmp_path)[0].client_libraries == ["resttemplate"]

    def test_no_clients_no_census(self, tmp_path: Path) -> None:
        write_pom(tmp_path, "svc")
        assert discover_services(tmp_path)[0].client_libraries == []


class TestComposeEnvSurface:
    """T3 (§5.4.2): the deployment env surface — environment/env_file/.env,
    aliases, hostname/container_name, override files."""

    def _repo(self, tmp_path: Path) -> Path:
        write_pom(tmp_path / "orders", "orders")
        return tmp_path

    def test_environment_list_bare_names_resolve_from_dotenv(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        (repo / ".env").write_text(
            "YAS_SERVICES_CUSTOMER=http://customer/customer\nSECRET_TOKEN=hunter2\n"
        )
        (repo / "docker-compose.yml").write_text(
            """
services:
  orders:
    build: ./orders
    environment:
    - YAS_SERVICES_CUSTOMER
    - SECRET_TOKEN
    - SPRING_PROFILES_ACTIVE=prod
"""
        )
        [service] = discover_services(repo)
        # The yas idiom: bare pass-through resolved from the repo .env; the
        # URL-shaped value carries, the secret does not (allowlist).
        assert service.config.env["YAS_SERVICES_CUSTOMER"] == "http://customer/customer"
        assert "SECRET_TOKEN" not in service.config.env

    def test_environment_map_env_file_aliases_and_override(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        (repo / "orders.env").write_text("BILLING_URL=http://billing:9000\n")
        (repo / "docker-compose.yml").write_text(
            """
services:
  orders:
    build: ./orders
    hostname: orders-host
    container_name: orders-container
    env_file: orders.env
    environment:
      INVENTORY_URL: http://inventory:8081
    networks:
      internal:
        aliases: [orders-alias]
"""
        )
        (repo / "docker-compose.override.yml").write_text(
            """
services:
  orders:
    environment:
      INVENTORY_URL: http://inventory:9999
"""
        )
        [service] = discover_services(repo)
        assert set(service.hostnames) >= {
            "orders",
            "orders-host",
            "orders-container",
            "orders-alias",
        }
        assert service.config.env["BILLING_URL"] == "http://billing:9000"
        # The override file wins service-wise (compose semantics).
        assert service.config.env["INVENTORY_URL"] == "http://inventory:9999"

    def test_spring_profiles_active_selects_profile_config(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        resources = repo / "orders" / "src" / "main" / "resources"
        resources.mkdir(parents=True, exist_ok=True)
        (resources / "application.yml").write_text("server:\n  port: 8080\n")
        (resources / "application-prod.yml").write_text("server:\n  port: 9090\n")
        (resources / "application-dev.yml").write_text("server:\n  port: 7070\n")
        (repo / "docker-compose.yml").write_text(
            """
services:
  orders:
    build: ./orders
    environment:
    - SPRING_PROFILES_ACTIVE=prod
"""
        )
        [service] = discover_services(repo)
        assert service.config.server_port == 9090
        assert "config-profile-merged:application-prod.yml" in service.config.notes
        assert "config-profile-merged-all" not in service.config.notes
