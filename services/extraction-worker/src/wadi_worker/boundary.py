"""Service-boundary discovery (§4): build roots + network identities.

Phase 1 scope: Maven build roots (leaf ``pom.xml`` modules) and network
identity from a repo-root ``docker-compose.yml``. Discovery is heuristic by
design; the teachable override layer (`.wadi/services.yml`, Phase 3/4) sits
on top of exactly this output.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import yaml

from wadi_worker.appconfig import AppConfigFacts, parse_app_config

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"target", "build", "node_modules", ".git", ".idea", "src"}


@dataclass(frozen=True)
class DiscoveredService:
    name: str
    build_root: str  # relative to the repo root, '.' for the root itself
    build_system: str
    languages: list[str]
    hostnames: list[str] = field(default_factory=list[str])
    ports: list[int] = field(default_factory=list[int])
    config: AppConfigFacts = field(default_factory=AppConfigFacts)


def discover_services(repo_root: Path) -> list[DiscoveredService]:
    """Find analyzable services in one repo checkout."""
    maven_roots = _find_maven_leaf_modules(repo_root)
    compose_identities = _parse_compose_identities(repo_root)
    services: list[DiscoveredService] = []
    for pom_path in maven_roots:
        build_root = pom_path.parent.relative_to(repo_root).as_posix()
        if build_root == ".":
            build_root = "."
        name = _artifact_id(pom_path) or pom_path.parent.name or repo_root.name
        identity = compose_identities.get(build_root) or compose_identities.get(name)
        services.append(
            DiscoveredService(
                name=name,
                build_root=build_root,
                build_system="maven",
                languages=["java"],
                hostnames=identity.hostnames if identity else [],
                ports=identity.ports if identity else [],
                config=parse_app_config(pom_path.parent),
            )
        )
    services.sort(key=lambda s: s.build_root)
    return services


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


def _parse_compose_identities(repo_root: Path) -> dict[str, _ComposeIdentity]:
    """Map compose build-context dirs AND compose service names to identities.

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
    try:
        parsed: object = yaml.safe_load(compose_path.read_text())
    except yaml.YAMLError:
        logger.warning("unparseable compose file at %s — no network identities", compose_path)
        return identities
    if not isinstance(parsed, dict):
        return identities
    services = cast(dict[object, object], parsed).get("services")
    if not isinstance(services, dict):
        return identities

    for service_name, spec in cast(dict[object, object], services).items():
        if not isinstance(spec, dict) or not isinstance(service_name, str):
            continue
        typed_spec = cast(dict[str, object], spec)
        ports = _extract_container_ports(typed_spec)
        identity = _ComposeIdentity(hostnames=[service_name], ports=ports)
        identities[service_name] = identity
        build = typed_spec.get("build")
        context: object = (
            cast(dict[str, object], build).get("context") if isinstance(build, dict) else build
        )
        if isinstance(context, str):
            normalized = context.removeprefix("./").rstrip("/") or "."
            identities[normalized] = identity
    return identities


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
