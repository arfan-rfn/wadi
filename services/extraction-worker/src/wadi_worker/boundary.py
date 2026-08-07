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

# What makes a module DEPLOYABLE (§5.2.14). Deliberately NOT the controller
# annotations: web presence is not deployability. A library shipping a
# `@RestController` is an ordinary Spring pattern — its routes are mounted by
# whatever application depends on it — and treating that as proof of a service
# vetoed the library classification for the one module that most needed it.
# Word-boundary matched so `@SpringBootApplicationX` cannot trip it.
_DEPLOYABLE_MARKER_PATTERN = re.compile(r"@SpringBootApplication(?![A-Za-z0-9_])")

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


@dataclass(frozen=True)
class _ModuleScan:
    """One Maven leaf module, read but not yet classified (§5.2.14).

    Classification moved out of the scan because it needs the whole system:
    whether a module is a library depends on what OTHER repos declare.
    """

    module_dir: Path
    build_root: str
    artifact: str
    deps: set[str]
    deployable: bool
    identity: "_ComposeIdentity | None"


def _scan_modules(repo_root: Path) -> list[_ModuleScan]:
    maven_roots = _find_maven_leaf_modules(repo_root)
    compose_identities = _parse_compose_identities(repo_root)
    scans: list[_ModuleScan] = []
    for pom_path in maven_roots:
        if not _has_java_sources(pom_path.parent):
            logger.info("module %s has no Java sources — skipped", pom_path.parent)
            continue
        build_root = pom_path.parent.relative_to(repo_root).as_posix() or "."
        artifact = _artifact_id(pom_path) or pom_path.parent.name or repo_root.name
        scans.append(
            _ModuleScan(
                module_dir=pom_path.parent,
                build_root=build_root,
                artifact=artifact,
                deps=_declared_dependency_artifacts(pom_path),
                deployable=_is_deployable(pom_path.parent),
                identity=compose_identities.get(build_root) or compose_identities.get(artifact),
            )
        )
    return scans


def _to_service(module: _ModuleScan, is_library: bool) -> DiscoveredService:
    identity = module.identity
    config = parse_app_config(
        module.module_dir,
        active_profiles=identity.profiles if identity and identity.profiles else None,
    )
    if identity and identity.env:
        # Compose env overrides application files (Spring precedence, T3);
        # keys stay in their raw env-var spelling — the stitcher's relaxed-
        # binding lookup bridges to ${dotted.keys}.
        config = replace(config, env={**config.env, **identity.env})
    return DiscoveredService(
        name=module.artifact,
        build_root=module.build_root,
        build_system="maven",
        languages=["java"],
        hostnames=identity.hostnames if identity else [],
        ports=identity.ports if identity else [],
        config=config,
        kind="library" if is_library else "service",
        client_libraries=_client_library_census(module.module_dir),
    )


def discover_system_services(checkouts: dict[str, Path]) -> dict[str, list[DiscoveredService]]:
    """Classify every module of a SYSTEM, keyed by repo (§5.2.14).

    Dependency resolution has to be system-wide because the artifact and the
    module that depends on it need not share a repo: a shared internal jar in
    its own repository is the ordinary shape, and resolving
    `<artifactId>base</artifactId>` against one checkout's module map can only
    ever miss it. Pooling first is the whole fix — ICPC's `base` is depended on
    from a sibling repo, so per-repo classification saw no edge at all and gave
    it its own service, its own CPG, and 335 response shapes it could not
    resolve for the app that actually deploys it.

    Returns the same shape `discover_services` returns, per repo, so callers
    that already loop over repos change only where the list comes from.
    """
    scans = {repo: _scan_modules(root) for repo, root in checkouts.items()}
    # One artifact map across the system. A duplicate artifactId in two repos
    # is ambiguous, and guessing which one a dependency meant would invent a
    # build graph — first repo in iteration order wins and the collision is
    # logged, so a wrong union is visible rather than silent (P10).
    owner: dict[str, tuple[str, str]] = {}
    for repo, modules in scans.items():
        for module in modules:
            if module.artifact in owner:
                logger.warning(
                    "artifact %s declared in two repos (%s, %s) — using the first",
                    module.artifact,
                    owner[module.artifact][0],
                    repo,
                )
                continue
            owner[module.artifact] = (repo, module.build_root)

    depended_on: set[str] = set()
    deps_by_module: dict[tuple[str, str], set[str]] = {}
    for repo, modules in scans.items():
        for module in modules:
            in_system = {dep for dep in module.deps if dep in owner}
            deps_by_module[(repo, module.build_root)] = in_system
            depended_on.update(in_system)

    library_artifacts = {
        module.artifact
        for modules in scans.values()
        for module in modules
        if module.artifact in depended_on and module.identity is None and not module.deployable
    }

    result: dict[str, list[DiscoveredService]] = {}
    for repo, modules in scans.items():
        services = [_to_service(module, module.artifact in library_artifacts) for module in modules]
        services = [
            replace(
                service,
                library_roots=_transitive_system_library_roots(
                    (repo, service.build_root), deps_by_module, owner, library_artifacts
                ),
            )
            if service.kind == "service"
            else service
            for service in services
        ]
        services.sort(key=lambda s: s.build_root)
        result[repo] = _disambiguate_names(services)
    return result


def _transitive_system_library_roots(
    start: tuple[str, str],
    deps_by_module: dict[tuple[str, str], set[str]],
    owner: dict[str, tuple[str, str]],
    library_artifacts: set[str],
) -> list[str]:
    """Library build roots this module needs staged, `repo::root`-qualified.

    The qualifier is what lets the stage reach another repo's checkout. A
    same-repo root keeps its bare spelling so existing single-repo behaviour —
    and every golden written against it — is byte-identical.
    """
    seen: set[tuple[str, str]] = set()
    roots: list[str] = []
    queue = list(deps_by_module.get(start, set()))
    while queue:
        artifact = queue.pop()
        if artifact not in library_artifacts or artifact not in owner:
            continue
        located = owner[artifact]
        if located in seen:
            continue
        seen.add(located)
        repo, root = located
        roots.append(root if repo == start[0] else f"{repo}::{root}")
        queue.extend(deps_by_module.get(located, set()))
    return sorted(roots)


def discover_services(repo_root: Path) -> list[DiscoveredService]:
    """Find analyzable services + library modules in ONE repo checkout.

    The single-repo case of :func:`discover_system_services`, kept as its own
    entry point because most callers (and every fixture) analyze one tree. It
    shares the classifier rather than reimplementing it, so the two cannot
    drift into disagreeing about what a service is — which is exactly how a
    library came to be modelled as a peer service (§5.2.14).
    """
    return discover_system_services({".": repo_root})["."]


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


def _is_deployable(module_dir: Path) -> bool:
    """Does this module RUN on its own? (§5.2.14)

    Web presence is not deployability. A library shipping a `@RestController`
    is an ordinary Spring pattern — the routes are mounted by whatever
    application depends on it — and treating the controller as proof of a
    service vetoed the library classification for the one module that most
    needed it. ICPC's `base` ships exactly one, `AspectFacesController`, and
    the consuming app's own `SecurityConfig` carries a rule for
    `/aspectfaces/**`: that route is served by *contest*, which is only
    sayable if contest is what deploys it.

    What marks a deployable is an entry point — `@SpringBootApplication` — or
    a compose identity, which the caller checks separately. `base` has 0 of
    the former; `backend` has 1.
    """
    # `war` packaging declares deployability on its own: a plain Spring MVC
    # application has no `@SpringBootApplication` and is still a thing you
    # deploy. Without this the rule would absorb every non-Boot web app into
    # whatever depends on it.
    pom = module_dir / "pom.xml"
    if pom.is_file():
        try:
            root = ElementTree.parse(pom).getroot()
        except ElementTree.ParseError:
            root = None
        if root is not None:
            packaging = root.find(f"{_pom_namespace(root)}packaging")
            if packaging is not None and (packaging.text or "").strip() == "war":
                return True

    main = module_dir / "src" / "main" / "java"
    if not main.is_dir():
        return False
    for source in main.rglob("*.java"):
        try:
            text = source.read_text(errors="replace")
        except OSError:
            continue
        if _DEPLOYABLE_MARKER_PATTERN.search(text):
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
