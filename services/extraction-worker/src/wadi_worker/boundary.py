"""Service-boundary discovery (§4): build roots + network identities.

Phase 1 scope: Maven build roots (leaf ``pom.xml`` modules) and network
identity from a repo-root ``docker-compose.yml``. Discovery is heuristic by
design; the teachable override layer (`.wadi/services.yml`, Phase 3/4) sits
on top of exactly this output.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import yaml

from wadi_contracts.enums import ClientLibrary
from wadi_worker.appconfig import AppConfigFacts, parse_app_config

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"target", "build", "node_modules", ".git", ".idea", "src", "old-docs"}

# Annotations that mark a module as a runnable service (§5.2.6 classification).
# Word-boundary matched: @ControllerAdvice / @RestControllerAdvice are library
# code (yas common-library ships a global exception handler) and must NOT trip
# the @Controller / @RestController markers by substring.
_SERVICE_MARKER_PATTERN = re.compile(
    r"@(?:SpringBootApplication|RestController|Controller)(?![A-Za-z0-9_])"
)

# Client-library census (§5.4.2): import-line markers -> KNOWN_CLIENT_LIBRARIES
# labels. Deterministic text scan; presence facts only (an import is not a
# call, P10). The stitcher flags labels outside MODELLED_CLIENT_LIBRARIES.
_CLIENT_IMPORT_MARKERS: dict[ClientLibrary, tuple[str, ...]] = {
    ClientLibrary.RESTTEMPLATE: ("org.springframework.web.client.RestTemplate",),
    ClientLibrary.RESTCLIENT: ("org.springframework.web.client.RestClient",),
    ClientLibrary.WEBCLIENT: ("org.springframework.web.reactive.function.client.WebClient",),
    ClientLibrary.FEIGN: ("org.springframework.cloud.openfeign", "feign."),
    ClientLibrary.HTTP_INTERFACE: ("org.springframework.web.service.annotation",),
    ClientLibrary.JDK_HTTPCLIENT: ("java.net.http.HttpClient",),
    ClientLibrary.OKHTTP: ("okhttp3.",),
    ClientLibrary.RETROFIT: ("retrofit2.",),
    ClientLibrary.APACHE_HTTPCLIENT: ("org.apache.http.client", "org.apache.hc.client5"),
    ClientLibrary.UNIREST: ("kong.unirest", "com.mashape.unirest"),
}
_IMPORT_LINE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.MULTILINE)


@dataclass(frozen=True)
class DiscoveredService:
    name: str
    build_root: str  # relative to the repo root, '.' for the root itself
    build_system: str
    languages: list[str]
    hostnames: list[str] = field(default_factory=list[str])
    ports: list[int] = field(default_factory=list[int])
    config: AppConfigFacts = field(default_factory=AppConfigFacts)
    kind: str = "service"  # 'service' | 'library' (§5.2.6)
    library_roots: list[str] = field(default_factory=list[str])
    """Build roots of transitive in-repo library deps to stage into the parse."""
    client_libraries: list[ClientLibrary] = field(default_factory=list[ClientLibrary])
    """§5.4.2 census: HTTP client libraries detected by import scan."""


def discover_services(repo_root: Path) -> list[DiscoveredService]:
    """Find analyzable services + in-repo library modules in one repo checkout.

    §5.2.6: every Maven leaf module is classified — *service* (Spring Boot
    main / controller markers or a compose identity), *library* (depended on
    by another in-repo module, no service markers), or skipped when it has no
    Java sources at all (frontend/pom-only modules). Libraries are never
    analyzed as services; their build roots land on each dependent service's
    ``library_roots`` (transitively) so the worker can stage a source union.
    """
    maven_roots = _find_maven_leaf_modules(repo_root)
    compose_identities = _parse_compose_identities(repo_root)

    modules: list[tuple[Path, str, str]] = []  # (pom, build_root, artifact)
    for pom_path in maven_roots:
        if not _has_java_sources(pom_path.parent):
            logger.info("module %s has no Java sources — skipped", pom_path.parent)
            continue
        build_root = pom_path.parent.relative_to(repo_root).as_posix() or "."
        artifact = _artifact_id(pom_path) or pom_path.parent.name or repo_root.name
        modules.append((pom_path, build_root, artifact))

    root_by_artifact = {artifact: build_root for _, build_root, artifact in modules}
    deps_by_root: dict[str, set[str]] = {}
    depended_on: set[str] = set()
    for pom_path, build_root, _ in modules:
        in_repo = {
            dep for dep in _declared_dependency_artifacts(pom_path) if dep in root_by_artifact
        }
        deps_by_root[build_root] = in_repo
        depended_on.update(in_repo)

    services: list[DiscoveredService] = []
    library_artifacts: set[str] = set()
    for pom_path, build_root, artifact in modules:
        identity = compose_identities.get(build_root) or compose_identities.get(artifact)
        is_library = (
            artifact in depended_on
            and identity is None
            and not _has_service_markers(pom_path.parent)
        )
        if is_library:
            library_artifacts.add(artifact)
        config = parse_app_config(
            pom_path.parent,
            active_profiles=identity.profiles if identity and identity.profiles else None,
        )
        if identity and identity.env:
            # Compose env overrides application files (Spring precedence, T3);
            # keys stay in their raw env-var spelling — the stitcher's relaxed-
            # binding lookup bridges to ${dotted.keys}.
            config = replace(config, env={**config.env, **identity.env})
        services.append(
            DiscoveredService(
                name=artifact,
                build_root=build_root,
                build_system="maven",
                languages=["java"],
                hostnames=identity.hostnames if identity else [],
                ports=identity.ports if identity else [],
                config=config,
                kind="library" if is_library else "service",
                client_libraries=_client_library_census(pom_path.parent),
            )
        )

    services = [
        replace(
            service,
            library_roots=_transitive_library_roots(
                service.build_root, deps_by_root, root_by_artifact, library_artifacts
            ),
        )
        if service.kind == "service"
        else service
        for service in services
    ]
    services.sort(key=lambda s: s.build_root)
    return _disambiguate_names(services)


def _has_java_sources(module_dir: Path) -> bool:
    main = module_dir / "src" / "main" / "java"
    return main.is_dir() and any(main.rglob("*.java"))


def _client_library_census(module_dir: Path) -> list[ClientLibrary]:
    """§5.4.2: which known HTTP client libraries this module's production
    sources import. Deterministic, sorted; presence only.
    """
    main = module_dir / "src" / "main" / "java"
    if not main.is_dir():
        return []
    found: set[ClientLibrary] = set()
    for source in main.rglob("*.java"):
        try:
            text = source.read_text(errors="replace")
        except OSError:
            continue
        for imported in _IMPORT_LINE.findall(text):
            for label, prefixes in _CLIENT_IMPORT_MARKERS.items():
                if label not in found and any(imported.startswith(p) for p in prefixes):
                    found.add(label)
        if len(found) == len(_CLIENT_IMPORT_MARKERS):
            break
    return sorted(found)


def _has_service_markers(module_dir: Path) -> bool:
    main = module_dir / "src" / "main" / "java"
    if not main.is_dir():
        return False
    for source in main.rglob("*.java"):
        try:
            text = source.read_text(errors="replace")
        except OSError:
            continue
        if _SERVICE_MARKER_PATTERN.search(text):
            return True
    return False


def _declared_dependency_artifacts(pom_path: Path) -> set[str]:
    """artifactIds in <dependencies> — pure XML, nothing executed (§5.2.6)."""
    try:
        root = ElementTree.parse(pom_path).getroot()
    except ElementTree.ParseError:
        return set()
    namespace = _pom_namespace(root)
    artifacts: set[str] = set()
    for dependency in root.iter(f"{namespace}dependency"):
        element = dependency.find(f"{namespace}artifactId")
        if element is not None and element.text:
            artifacts.add(element.text.strip())
    return artifacts


def _transitive_library_roots(
    build_root: str,
    deps_by_root: dict[str, set[str]],
    root_by_artifact: dict[str, str],
    library_artifacts: set[str],
) -> list[str]:
    """BFS over in-repo deps, collecting library build roots (lib→lib chains
    included). A dependency on another *service* module is not staged —
    merging two services' sources would blur their identities.
    """
    roots: list[str] = []
    queue = list(deps_by_root.get(build_root, ()))
    seen: set[str] = set()
    while queue:
        artifact = queue.pop(0)
        if artifact in seen:
            continue
        seen.add(artifact)
        if artifact not in library_artifacts:
            logger.info(
                "module %s depends on service module %s — not staged (§5.2.6)",
                build_root,
                artifact,
            )
            continue
        lib_root = root_by_artifact[artifact]
        roots.append(lib_root)
        queue.extend(deps_by_root.get(lib_root, ()))
    return sorted(roots)


def _disambiguate_names(services: list[DiscoveredService]) -> list[DiscoveredService]:
    """Colliding display names fall back to the module directory name.

    TrainTicket's two gateways both declare ``<artifactId>gateway</artifactId>``
    — surfacing both as "gateway" is a human-facing collision even though ids
    and build roots stay distinct. The directory name (build-root basename) is
    unique per module in practice; the full build-root path is the last resort.
    Deterministic: derived purely from discovered facts.
    """
    name_counts = Counter(service.name for service in services)
    colliding = {name for name, count in name_counts.items() if count > 1}
    if not colliding:
        return services
    basenames = [Path(service.build_root).name or service.name for service in services]
    basenames_unique = len(set(basenames)) == len(basenames)

    def fallback(service: DiscoveredService, basename: str) -> str:
        return basename if basenames_unique else service.build_root

    return [
        replace(service, name=fallback(service, basename)) if service.name in colliding else service
        for service, basename in zip(services, basenames, strict=True)
    ]


def _find_maven_leaf_modules(repo_root: Path) -> list[Path]:
    """Every pom.xml that is not an aggregator (<modules>) — those are services."""
    poms: list[Path] = []
    for pom in sorted(repo_root.rglob("pom.xml")):
        relative_parts = pom.relative_to(repo_root).parts[:-1]
        if any(part in _SKIP_DIRS or part.startswith(".") for part in relative_parts):
            continue
        if _is_aggregator(pom):
            continue
        poms.append(pom)
    return poms


def _is_aggregator(pom_path: Path) -> bool:
    try:
        root = ElementTree.parse(pom_path).getroot()
    except ElementTree.ParseError:
        logger.warning("unparseable pom.xml at %s — skipping", pom_path)
        return True
    namespace = _pom_namespace(root)
    return root.find(f"{namespace}modules") is not None


def _artifact_id(pom_path: Path) -> str | None:
    try:
        root = ElementTree.parse(pom_path).getroot()
    except ElementTree.ParseError:
        return None
    namespace = _pom_namespace(root)
    element = root.find(f"{namespace}artifactId")
    return element.text.strip() if element is not None and element.text else None


def _pom_namespace(root: ElementTree.Element) -> str:
    match = re.match(r"^(\{[^}]+\})", root.tag)
    return match.group(1) if match else ""


@dataclass(frozen=True)
class _ComposeIdentity:
    hostnames: list[str]
    ports: list[int]
    env: dict[str, str] = field(default_factory=dict[str, str])
    profiles: list[str] = field(default_factory=list[str])


# Compose env keys worth carrying onto the boundary (T3, §5.4.2): URL-shaped
# values (the yas ${yas.services.*} closure), *_URL/*_URI/*_HOST/*_PORT names,
# and the Spring identity/profile keys — never the whole environment (secrets
# and infra noise stay out).
_ENV_VALUE_SHAPES = ("http://", "https://", "lb://")
_ENV_NAME_SUFFIXES = ("_URL", "_URI", "_HOST", "_PORT")
_ENV_EXACT_NAMES = {"SERVER_PORT", "SPRING_APPLICATION_NAME", "SERVER_SERVLET_CONTEXT_PATH"}


def _carry_env_entry(name: str, value: str) -> bool:
    return (
        value.startswith(_ENV_VALUE_SHAPES)
        or name.upper().endswith(_ENV_NAME_SUFFIXES)
        or name.upper() in _ENV_EXACT_NAMES
    )


def _parse_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; compose loads `.env` for interpolation AND as the
    default source for bare `environment:` pass-through entries (T3)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_compose_identities(repo_root: Path) -> dict[str, _ComposeIdentity]:
    """Map compose build-context dirs AND compose service names to identities.

    T3 (§5.4.2): the deployment env surface rides along — `environment:` (map
    and list forms; bare names resolve from the repo `.env`, compose's own
    semantics), `env_file:` files, network `aliases:`, `hostname:`,
    `container_name:`, and the standard override file merged service-wise.

    Best-effort (P10): a malformed compose file degrades to no identities,
    never to a failed boundary scan.
    """
    identities: dict[str, _ComposeIdentity] = {}
    for candidate in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        compose_path = repo_root / candidate
        if compose_path.exists():
            break
    else:
        return identities
    services = _compose_services(compose_path)
    if services is None:
        return identities
    # The standard override file merges service-wise (compose semantics).
    for override_name in (
        "docker-compose.override.yml",
        "docker-compose.override.yaml",
        "compose.override.yml",
        "compose.override.yaml",
    ):
        override_path = repo_root / override_name
        if override_path.exists():
            extra = _compose_services(override_path)
            if extra:
                for name, spec in extra.items():
                    if (
                        name in services
                        and isinstance(services[name], dict)
                        and isinstance(spec, dict)
                    ):
                        merged = dict(cast(dict[str, object], services[name]))
                        merged.update(cast(dict[str, object], spec))
                        services[name] = merged
                    else:
                        services[name] = spec
            break
    dotenv = _parse_dotenv(repo_root / ".env")

    for service_name, spec in services.items():
        if not isinstance(spec, dict):
            continue
        typed_spec = cast(dict[str, object], spec)
        ports = _extract_container_ports(typed_spec)
        env, profiles = _extract_environment(typed_spec, dotenv, compose_path.parent)
        hostnames = [service_name]
        for extra_host_key in ("hostname", "container_name"):
            extra_host = typed_spec.get(extra_host_key)
            if isinstance(extra_host, str) and extra_host.strip() and extra_host not in hostnames:
                hostnames.append(extra_host.strip())
        hostnames.extend(_network_aliases(typed_spec, hostnames))
        identity = _ComposeIdentity(hostnames=hostnames, ports=ports, env=env, profiles=profiles)
        identities[service_name] = identity
        build = typed_spec.get("build")
        context: object = (
            cast(dict[str, object], build).get("context") if isinstance(build, dict) else build
        )
        if isinstance(context, str):
            normalized = context.removeprefix("./").rstrip("/") or "."
            identities[normalized] = identity
    return identities


def _compose_services(compose_path: Path) -> dict[str, object] | None:
    try:
        parsed: object = yaml.safe_load(compose_path.read_text())
    except yaml.YAMLError:
        logger.warning("unparseable compose file at %s — no network identities", compose_path)
        return None
    if not isinstance(parsed, dict):
        return None
    services = cast(dict[object, object], parsed).get("services")
    if not isinstance(services, dict):
        return None
    return {str(k): v for k, v in cast(dict[object, object], services).items()}


def _extract_environment(
    spec: dict[str, object], dotenv: dict[str, str], compose_dir: Path
) -> tuple[dict[str, str], list[str]]:
    """The service's carried env (allowlisted) + its active Spring profiles."""
    collected: dict[str, str] = {}
    for env_file in _env_file_paths(spec, compose_dir):
        collected.update(_parse_dotenv(env_file))
    raw = spec.get("environment")
    if isinstance(raw, dict):
        for key, value in cast(dict[object, object], raw).items():
            collected[str(key)] = str(value) if value is not None else dotenv.get(str(key), "")
    elif isinstance(raw, list):
        for entry in cast(list[object], raw):
            text = str(entry)
            if "=" in text:
                key, value = text.split("=", 1)
                collected[key.strip()] = value.strip()
            else:
                # Bare pass-through: compose resolves it from the caller env,
                # which `.env` populates for local runs (the yas idiom).
                name = text.strip()
                if name in dotenv:
                    collected[name] = dotenv[name]
    profiles: list[str] = []
    raw_profiles = collected.get("SPRING_PROFILES_ACTIVE", "")
    if raw_profiles:
        profiles = [p.strip() for p in raw_profiles.split(",") if p.strip()]
    carried = {
        name: value for name, value in sorted(collected.items()) if _carry_env_entry(name, value)
    }
    return carried, profiles


def _env_file_paths(spec: dict[str, object], compose_dir: Path) -> list[Path]:
    raw = spec.get("env_file")
    entries: list[object]
    if isinstance(raw, str):
        entries = [raw]
    elif isinstance(raw, list):
        entries = cast(list[object], raw)
    else:
        return []
    return [compose_dir / str(entry) for entry in entries]


def _network_aliases(spec: dict[str, object], known: list[str]) -> list[str]:
    aliases: list[str] = []
    networks = spec.get("networks")
    if isinstance(networks, dict):
        for network_spec in cast(dict[object, object], networks).values():
            if isinstance(network_spec, dict):
                raw_aliases = cast(dict[str, object], network_spec).get("aliases")
                if isinstance(raw_aliases, list):
                    aliases.extend(
                        str(a)
                        for a in cast(list[object], raw_aliases)
                        if str(a) not in known and str(a) not in aliases
                    )
    return aliases


def _extract_container_ports(spec: dict[str, object]) -> list[int]:
    ports: list[int] = []
    raw_ports = spec.get("ports")
    if isinstance(raw_ports, list):
        for entry in cast(list[object], raw_ports):
            container_port = _container_port(entry)
            if container_port is not None:
                ports.append(container_port)
    raw_expose = spec.get("expose")
    if isinstance(raw_expose, list):
        for entry in cast(list[object], raw_expose):
            try:
                ports.append(int(str(entry)))
            except ValueError:
                continue
    return sorted(set(ports))


def _container_port(entry: object) -> int | None:
    """The container-side port from '8080', '9000:8080', or '127.0.0.1:9000:8080'."""
    if isinstance(entry, int):
        return entry
    if isinstance(entry, str):
        container_side = entry.rsplit(":", 1)[-1].split("/", 1)[0]
        try:
            return int(container_side)
        except ValueError:
            return None
    if isinstance(entry, dict):  # long syntax
        target = cast(dict[str, object], entry).get("target")
        if isinstance(target, int):
            return target
    return None
