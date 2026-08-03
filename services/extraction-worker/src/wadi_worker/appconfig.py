"""Application-config fact extraction (§5.2 step 5 / §5.4.1 phone-book feed).

The worker parses each service's ``application.{yml,yaml,properties}`` at
extraction time into raw, network-relevant facts on the boundary artifact —
the stitcher consumes artifacts only (P2/P6 split; recorded in §5.4).

T3 (§5.4.2): profile-specific files (``application-<profile>.*``) and
multi-document YAML profile documents MERGE over the base — exactly the
active profiles when they are known (compose ``SPRING_PROFILES_ACTIVE``),
else every profile in deterministic order with an honest note. Discovery
registration names (Eureka/Consul) and Zuul routes are extracted; unmodelled
gateway shapes are perceived and noted, never silently dropped.

Best-effort by design (P10): a malformed file degrades to no facts, never to
a failed extraction.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

logger = logging.getLogger(__name__)

# Keys worth carrying into NetworkIdentity.env: what URL templates resolve
# against (`${key}` → *.url/*.uri and — T3 — *.host/*.port pairs), identity
# and port facts, and security config (auth-evidence source three, §5.2).
_EXACT_KEYS = {
    "spring.application.name",
    "server.port",
    "server.servlet.context-path",
}
_SUFFIXES = (".url", ".uri", ".host", ".port")
_PREFIXES = ("spring.security.", "spring.cloud.gateway.")

_PATH_PREDICATE = re.compile(r"^Path=(?P<patterns>.+)$")
_STRIP_FILTER = re.compile(r"^StripPrefix=(?P<count>\d+)$")

# Gateway shapes the parser can PERCEIVE but does not model (T3): each is
# noted per route so the gap is queryable (§5.4.2 — the difference between a
# gap and a blind spot is whether you can count it).
_UNMODELLED_FILTERS = ("RewritePath", "PrefixPath", "SetPath")
_UNMODELLED_PREDICATES = ("Host=", "Method=")

_DISCOVERY_NAME_KEYS = (
    "eureka.instance.appname",
    "spring.cloud.consul.discovery.service-name",
)


@dataclass(frozen=True)
class AppGatewayRoute:
    route_id: str | None
    path_prefix: str
    target_uri: str
    strip_prefix: int


@dataclass(frozen=True)
class AppConfigFacts:
    env: dict[str, str] = field(default_factory=dict[str, str])
    application_name: str | None = None
    server_port: int | None = None
    gateway_routes: list[AppGatewayRoute] = field(default_factory=list[AppGatewayRoute])
    gateway_discovery_locator: bool = False
    discovery_names: list[str] = field(default_factory=list[str])
    """Explicit discovery registration names (Eureka/Consul, T3)."""
    notes: list[str] = field(default_factory=list[str])
    """Machine-readable parsing-gap notes (§5.4.2): what this parser knowingly
    skipped — queryable, never just prose (P10)."""


_EMPTY = AppConfigFacts()


def parse_app_config(
    build_root: Path, active_profiles: Sequence[str] | None = None
) -> AppConfigFacts:
    """Facts from the service's application config, profiles merged (T3).

    ``active_profiles`` comes from deployment facts (compose
    ``SPRING_PROFILES_ACTIVE``) when known: exactly those profiles merge, in
    activation order. When unknown, EVERY profile file/document merges in
    deterministic (alphabetical/declaration) order with an honest note —
    over-approximation beats silently dropping declared config (§5.2).
    """
    resources = build_root / "src" / "main" / "resources"
    flat: dict[str, str] = {}
    routes: list[AppGatewayRoute] = []
    notes: list[str] = []

    base_found = False
    for candidate in ("application.yml", "application.yaml", "application.properties"):
        config_path = resources / candidate
        if config_path.exists():
            base_found = True
            if candidate.endswith(".properties"):
                _merge_flat(flat, _parse_properties(config_path))
            else:
                routes.extend(_merge_yaml_documents(config_path, flat, active_profiles, notes))
            break

    profile_files = (
        sorted(
            path
            for path in resources.glob("application-*")
            if path.suffix in (".yml", ".yaml", ".properties")
        )
        if resources.is_dir()
        else []
    )
    selected = _select_profile_files(profile_files, active_profiles)
    if active_profiles is None and selected:
        notes.append("config-profile-merged-all")
    for path in selected:
        notes.append(f"config-profile-merged:{path.name}")
        if path.suffix == ".properties":
            _merge_flat(flat, _parse_properties(path))
        else:
            routes.extend(_merge_yaml_documents(path, flat, None, notes, profile_docs_apply=True))

    if not base_found and not flat:
        return _EMPTY if not notes else AppConfigFacts(notes=notes)
    return _from_flat(flat, routes, notes)


def _select_profile_files(
    profile_files: list[Path], active_profiles: Sequence[str] | None
) -> list[Path]:
    if active_profiles is None:
        return profile_files
    ordered: list[Path] = []
    for profile in active_profiles:
        for path in profile_files:
            if path.stem == f"application-{profile}":
                ordered.append(path)
    return ordered


def _merge_yaml_documents(
    config_path: Path,
    flat: dict[str, str],
    active_profiles: Sequence[str] | None,
    notes: list[str],
    *,
    profile_docs_apply: bool = False,
) -> list[AppGatewayRoute]:
    """Merge a YAML file's documents (T3): the base document always applies;
    profile-activated documents (``spring.config.activate.on-profile`` /
    legacy ``spring.profiles``) apply per the active set — all of them, with a
    note, when the active set is unknown.
    """
    try:
        documents: list[object] = [
            document
            for document in yaml.safe_load_all(config_path.read_text())
            if document is not None
        ]
    except yaml.YAMLError:
        logger.warning("unparseable %s — no config facts extracted", config_path)
        return []
    routes: list[AppGatewayRoute] = []
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            continue
        doc_flat: dict[str, str] = {}
        doc_routes = _flatten(
            cast(dict[object, object], document), prefix="", into=doc_flat, notes=notes
        )
        marker = doc_flat.pop("spring.config.activate.on-profile", None) or (
            doc_flat.pop("spring.profiles", None) if index > 0 else None
        )
        if marker is not None and not profile_docs_apply:
            declared = [p.strip() for p in marker.split(",") if p.strip()]
            if active_profiles is not None:
                if not any(p in active_profiles for p in declared):
                    continue  # correctly inactive — not a gap
            else:
                notes.append(f"config-profile-doc-merged:{marker}")
        _merge_flat(flat, doc_flat)
        routes.extend(doc_routes)
    return routes


def _merge_flat(into: dict[str, str], new: dict[str, str]) -> None:
    into.update(new)  # later sources (profiles) override the base — Spring order


def _flatten(
    node: dict[object, object],
    prefix: str,
    into: dict[str, str],
    notes: list[str] | None = None,
) -> list[AppGatewayRoute]:
    """Flatten to dotted keys; gateway route lists get structured parsing."""
    routes: list[AppGatewayRoute] = []
    for raw_key, value in node.items():
        key = f"{prefix}{raw_key}".strip()
        if key == "spring.cloud.gateway.routes" and isinstance(value, list):
            routes.extend(_parse_gateway_routes(cast(list[object], value), notes))
            continue
        if isinstance(value, dict):
            routes.extend(_flatten(cast(dict[object, object], value), f"{key}.", into, notes))
        elif isinstance(value, list):
            into[key] = ",".join(str(item) for item in cast(list[object], value))
        elif value is not None:
            into[key] = str(value)
    return routes


def _parse_gateway_routes(
    entries: list[object], notes: list[str] | None = None
) -> list[AppGatewayRoute]:
    routes: list[AppGatewayRoute] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        spec = cast(dict[str, object], entry)
        uri = spec.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            continue
        route_id = spec.get("id")
        strip_prefix = 0
        raw_filters = spec.get("filters")
        if isinstance(raw_filters, list):
            for filter_entry in cast(list[object], raw_filters):
                strip = _strip_prefix_of(filter_entry)
                if strip is not None:
                    strip_prefix = strip
                elif notes is not None:
                    _note_unmodelled_route_shape(filter_entry, _UNMODELLED_FILTERS, "filter", notes)
        raw_predicates = spec.get("predicates")
        patterns: list[str] = []
        if isinstance(raw_predicates, list):
            for predicate in cast(list[object], raw_predicates):
                found = _path_patterns_of(predicate)
                patterns.extend(found)
                if not found and notes is not None:
                    _note_unmodelled_route_shape(
                        predicate,
                        tuple(p.rstrip("=") for p in _UNMODELLED_PREDICATES),
                        "predicate",
                        notes,
                    )
        for pattern in patterns:
            routes.append(
                AppGatewayRoute(
                    route_id=str(route_id) if route_id is not None else None,
                    path_prefix=pattern,
                    target_uri=uri.strip(),
                    strip_prefix=strip_prefix,
                )
            )
    return routes


def _strip_prefix_of(filter_entry: object) -> int | None:
    """StripPrefix in string form ('StripPrefix=1') or expanded map form
    ({name: StripPrefix, args: {parts: 1}}) — T3."""
    if isinstance(filter_entry, str):
        matched = _STRIP_FILTER.match(filter_entry.strip())
        return int(matched.group("count")) if matched else None
    if isinstance(filter_entry, dict):
        spec = cast(dict[str, object], filter_entry)
        if str(spec.get("name", "")).strip() == "StripPrefix":
            args = spec.get("args")
            if isinstance(args, dict):
                for value in cast(dict[str, object], args).values():
                    try:
                        return int(str(value))
                    except ValueError:
                        continue
    return None


def _path_patterns_of(predicate: object) -> list[str]:
    """Path predicates in string form ('Path=/a/**,/b/**') or expanded map
    form ({name: Path, args: {...}}) — T3."""
    if isinstance(predicate, str):
        matched = _PATH_PREDICATE.match(predicate.strip())
        if matched:
            return [p.strip() for p in matched.group("patterns").split(",") if p.strip()]
        return []
    if isinstance(predicate, dict):
        spec = cast(dict[str, object], predicate)
        if str(spec.get("name", "")).strip() == "Path":
            args = spec.get("args")
            if isinstance(args, dict):
                patterns: list[str] = []
                for value in cast(dict[str, object], args).values():
                    patterns.extend(p.strip() for p in str(value).split(",") if p.strip())
                return patterns
    return []


def _parse_properties(config_path: Path) -> dict[str, str]:
    flat: dict[str, str] = {}
    try:
        text = config_path.read_text()
    except OSError:
        logger.warning("unreadable %s — no config facts extracted", config_path)
        return flat
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
            flat[key.strip()] = value.strip()
    return flat


def _from_flat(
    flat: dict[str, str],
    routes: list[AppGatewayRoute] | None = None,
    notes: list[str] | None = None,
) -> AppConfigFacts:
    env = {
        key: value
        for key, value in sorted(flat.items())
        if key in _EXACT_KEYS or key.endswith(_SUFFIXES) or key.startswith(_PREFIXES)
    }
    server_port: int | None = None
    raw_port = flat.get("server.port")
    if raw_port is not None:
        try:
            server_port = int(raw_port)
        except ValueError:
            logger.warning("non-numeric server.port %r ignored", raw_port)
    locator = flat.get("spring.cloud.gateway.discovery.locator.enabled", "").lower() == "true"
    all_notes = list(notes or [])
    all_routes = list(routes or [])
    all_routes.extend(_zuul_routes(flat))
    all_notes.extend(_unmodelled_gateway_notes(flat))
    discovery_names = [
        flat[key].strip() for key in _DISCOVERY_NAME_KEYS if flat.get(key, "").strip()
    ]
    return AppConfigFacts(
        env=env,
        application_name=flat.get("spring.application.name"),
        server_port=server_port,
        gateway_routes=all_routes,
        gateway_discovery_locator=locator,
        discovery_names=discovery_names,
        notes=all_notes,
    )


def _zuul_routes(flat: dict[str, str]) -> list[AppGatewayRoute]:
    """Zuul route groups (T3): ``zuul.routes.<name>.{path,url,serviceId,
    stripPrefix}``. ``stripPrefix`` defaults TRUE (one matched segment) —
    Zuul's own default semantics."""
    groups: dict[str, dict[str, str]] = {}
    for key, value in flat.items():
        if not key.startswith("zuul.routes."):
            continue
        remainder = key.removeprefix("zuul.routes.")
        if "." in remainder:
            name, attribute = remainder.split(".", 1)
        else:
            name, attribute = remainder, "path"  # zuul.routes.users=/users/** shorthand
        groups.setdefault(name, {})[attribute] = value
    routes: list[AppGatewayRoute] = []
    for name, attributes in sorted(groups.items()):
        path = attributes.get("path", f"/{name}/**")
        target = attributes.get("url") or f"lb://{attributes.get('serviceId', name)}"
        strip = attributes.get("stripPrefix", "true").lower() != "false"
        routes.append(
            AppGatewayRoute(
                route_id=name,
                path_prefix=path,
                target_uri=target,
                strip_prefix=1 if strip else 0,
            )
        )
    return routes


def _note_unmodelled_route_shape(
    entry: object, names: tuple[str, ...], kind: str, notes: list[str]
) -> None:
    text = str(entry)
    for name in names:
        if name in text:
            note = f"gateway-{kind}-unmodelled:{name}"
            if note not in notes:
                notes.append(note)


def _unmodelled_gateway_notes(flat: dict[str, str]) -> list[str]:
    """Perceive-and-note (T3): gateway filters/predicates wadi sees but does
    not model become queryable notes instead of silent drops."""
    notes: list[str] = []
    for key, value in sorted(flat.items()):
        if not key.startswith("spring.cloud.gateway."):
            continue
        for unmodelled in _UNMODELLED_FILTERS:
            if unmodelled in value and f"gateway-filter-unmodelled:{unmodelled}" not in notes:
                notes.append(f"gateway-filter-unmodelled:{unmodelled}")
        for unmodelled in _UNMODELLED_PREDICATES:
            if unmodelled in value:
                note = f"gateway-predicate-unmodelled:{unmodelled.rstrip('=')}"
                if note not in notes:
                    notes.append(note)
    return notes
