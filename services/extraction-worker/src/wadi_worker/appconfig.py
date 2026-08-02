"""Application-config fact extraction (§5.2 step 5 / §5.4.1 phone-book feed).

The worker parses each service's ``application.{yml,yaml,properties}`` at
extraction time into raw, network-relevant facts on the boundary artifact —
the stitcher consumes artifacts only (P2/P6 split; recorded in §5.4). Base
profile only (recorded limitation: profile-specific overrides are not
merged). Best-effort by design (P10): a malformed file degrades to no facts,
never to a failed extraction.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

logger = logging.getLogger(__name__)

# Keys worth carrying into NetworkIdentity.env: what URL templates resolve
# against (`${key}` → *.url/*.uri), identity/port facts, and security config
# (auth-evidence source three, §5.2 step 5).
_EXACT_KEYS = {
    "spring.application.name",
    "server.port",
    "server.servlet.context-path",
}
_SUFFIXES = (".url", ".uri")
_PREFIXES = ("spring.security.", "spring.cloud.gateway.")

_PATH_PREDICATE = re.compile(r"^Path=(?P<patterns>.+)$")
_STRIP_FILTER = re.compile(r"^StripPrefix=(?P<count>\d+)$")


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


_EMPTY = AppConfigFacts()


def parse_app_config(build_root: Path) -> AppConfigFacts:
    """Facts from the service's base application config, or empty facts."""
    resources = build_root / "src" / "main" / "resources"
    for candidate in ("application.yml", "application.yaml", "application.properties"):
        config_path = resources / candidate
        if config_path.exists():
            if candidate.endswith(".properties"):
                return _from_flat(_parse_properties(config_path))
            return _from_yaml(config_path)
    return _EMPTY


def _from_yaml(config_path: Path) -> AppConfigFacts:
    try:
        parsed: object = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError:
        logger.warning("unparseable %s — no config facts extracted", config_path)
        return _EMPTY
    if not isinstance(parsed, dict):
        return _EMPTY
    flat: dict[str, str] = {}
    routes = _flatten(cast(dict[object, object], parsed), prefix="", into=flat)
    return _from_flat(flat, routes)


def _flatten(
    node: dict[object, object], prefix: str, into: dict[str, str]
) -> list[AppGatewayRoute]:
    """Flatten to dotted keys; gateway route lists get structured parsing."""
    routes: list[AppGatewayRoute] = []
    for raw_key, value in node.items():
        key = f"{prefix}{raw_key}".strip()
        if key == "spring.cloud.gateway.routes" and isinstance(value, list):
            routes.extend(_parse_gateway_routes(cast(list[object], value)))
            continue
        if isinstance(value, dict):
            routes.extend(_flatten(cast(dict[object, object], value), f"{key}.", into))
        elif isinstance(value, list):
            into[key] = ",".join(str(item) for item in cast(list[object], value))
        elif value is not None:
            into[key] = str(value)
    return routes


def _parse_gateway_routes(entries: list[object]) -> list[AppGatewayRoute]:
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
                matched = _STRIP_FILTER.match(str(filter_entry).strip())
                if matched:
                    strip_prefix = int(matched.group("count"))
        raw_predicates = spec.get("predicates")
        patterns: list[str] = []
        if isinstance(raw_predicates, list):
            for predicate in cast(list[object], raw_predicates):
                matched = _PATH_PREDICATE.match(str(predicate).strip())
                if matched:
                    patterns.extend(
                        p.strip() for p in matched.group("patterns").split(",") if p.strip()
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
        key, separator, value = stripped.partition("=")
        if separator:
            flat[key.strip()] = value.strip()
    return flat


def _from_flat(flat: dict[str, str], routes: list[AppGatewayRoute] | None = None) -> AppConfigFacts:
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
    return AppConfigFacts(
        env=env,
        application_name=flat.get("spring.application.name") or None,
        server_port=server_port,
        gateway_routes=routes or [],
    )
