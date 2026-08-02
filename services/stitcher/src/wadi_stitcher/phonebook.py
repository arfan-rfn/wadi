"""Config resolution — the stitcher's "phone book" (§5.4.1).

Built from every analyzed service's :class:`~wadi_contracts.NetworkIdentity`
in the snapshot (the worker extracts raw config facts at extraction time; the
stitcher resolves them — the P2/P6 split of §5.2's "config analyzer").

Resolution precedence (recorded decision, §5.4):

1. **Compose hostname** — compose is the deployment's actual routing
   authority; if the URL host names a compose service, that *is* the target.
2. **Application/discovery name** — declared identity (`spring.application.name`,
   discovery registrations); matches `lb://name` targets, Feign names, and
   discovery-style hostnames. Below compose because a compose name resolves on
   the real network while a discovery name needs a registry in play.
3. **Gateway route** — when the resolved service is a gateway, the longest
   matching route prefix rewrites the path and the target re-resolves through
   rules 1-2 (depth-capped; a cycle abandons resolution). Indirection is
   config-proven but adds a link → resolution tier caps at HIGH.
4. **Port-only heuristic** — host is local/opaque but exactly one service owns
   the port. Never load-bearing: HEURISTIC tier only.

Conflicts are never silently picked from (P10): every claimant becomes a
candidate (the matcher emits one edge per candidate at degraded confidence)
and the conflict is recorded for the coverage report.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from enum import StrEnum

from wadi_contracts import ServiceBoundary

_MAX_GATEWAY_DEPTH = 4

_TARGET_URI = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?P<host>[^/:]+)(?::(?P<port>\d+))?")


class ResolutionKind(StrEnum):
    COMPOSE_HOSTNAME = "compose-hostname"
    APPLICATION_NAME = "application-name"
    GATEWAY_ROUTE = "gateway-route"
    PORT_HEURISTIC = "port-heuristic"


@dataclass(frozen=True)
class ResolvedTarget:
    """One candidate resolution of a host.

    ``service_id=None`` means config knows the name but no analyzed service
    carries it — the matcher turns that into a placeholder.
    """

    service_id: str | None
    logical_name: str
    rewritten_path: str | None = None


@dataclass(frozen=True)
class HostResolution:
    candidates: tuple[ResolvedTarget, ...]
    kind: ResolutionKind
    evidence: str
    ambiguous: bool = False
    port_mismatch: bool = False
    via_gateway: bool = False


@dataclass
class _Namespaces:
    compose: dict[str, list[ServiceBoundary]] = field(
        default_factory=dict[str, list[ServiceBoundary]]
    )
    names: dict[str, list[ServiceBoundary]] = field(
        default_factory=dict[str, list[ServiceBoundary]]
    )
    ports: dict[int, list[ServiceBoundary]] = field(
        default_factory=dict[int, list[ServiceBoundary]]
    )


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _known_ports(boundary: ServiceBoundary) -> set[int]:
    ports = set(boundary.network.ports)
    if boundary.network.server_port is not None:
        ports.add(boundary.network.server_port)
    return ports


class PhoneBook:
    """Immutable after :meth:`build`; resolution is pure and deterministic."""

    def __init__(self, namespaces: _Namespaces, conflicts: tuple[str, ...]) -> None:
        self._ns = namespaces
        self._conflicts = conflicts

    @property
    def conflicts(self) -> tuple[str, ...]:
        """Deterministic, human-readable conflict list for the coverage report."""
        return self._conflicts

    @classmethod
    def build(cls, boundaries: list[ServiceBoundary]) -> "PhoneBook":
        ns = _Namespaces()
        ordered = sorted(boundaries, key=lambda b: b.service_id)
        for boundary in ordered:
            for hostname in boundary.network.hostnames:
                ns.compose.setdefault(hostname.strip().lower(), []).append(boundary)
            declared_names: list[str] = []
            if boundary.network.application_name:
                declared_names.append(boundary.network.application_name)
            declared_names.extend(boundary.network.discovery_names)
            for name in dict.fromkeys(n.strip().lower() for n in declared_names if n.strip()):
                ns.names.setdefault(name, []).append(boundary)
            for port in _known_ports(boundary):
                ns.ports.setdefault(port, []).append(boundary)

        conflicts: list[str] = []
        for namespace_label, mapping in (("compose hostname", ns.compose), ("name", ns.names)):
            for key, claimants in sorted(mapping.items()):
                if len(claimants) > 1:
                    names = ", ".join(sorted(c.name for c in claimants))
                    conflicts.append(
                        f"{namespace_label} {key!r} is claimed by multiple services: {names}"
                    )
        for key in sorted(set(ns.compose) & set(ns.names)):
            compose_ids = {b.service_id for b in ns.compose[key]}
            name_ids = {b.service_id for b in ns.names[key]}
            if compose_ids != name_ids:
                conflicts.append(
                    f"identity {key!r} maps to different services as a compose hostname "
                    f"than as an application/discovery name (compose wins by precedence)"
                )
        return cls(ns, tuple(conflicts))

    def resolve(self, host: str, port: int | None, path: str) -> HostResolution | None:
        """Resolve a URL authority to candidate services. None = unknown host."""
        return self._resolve(host, port, path, depth=0)

    def _resolve(self, host: str, port: int | None, path: str, depth: int) -> HostResolution | None:
        key = host.strip().lower()

        direct = self._direct_lookup(key)
        if direct is not None:
            claimants, kind = direct
            gateway = self._single_gateway(claimants)
            if gateway is not None and depth < _MAX_GATEWAY_DEPTH:
                routed = self._via_gateway(gateway, path, depth)
                if routed is not None:
                    return routed
            port_mismatch = self._port_mismatch(claimants, port)
            return HostResolution(
                candidates=tuple(
                    ResolvedTarget(service_id=b.service_id, logical_name=key) for b in claimants
                ),
                kind=kind,
                evidence=f"host {key!r} = {kind.value} of "
                + ", ".join(sorted(b.name for b in claimants)),
                ambiguous=len(claimants) > 1,
                port_mismatch=port_mismatch,
            )

        if port is not None and (key in ("localhost", "127.0.0.1", "0.0.0.0") or _is_ip(key)):
            owners = self._ns.ports.get(port, [])
            if len(owners) == 1:
                owner = owners[0]
                return HostResolution(
                    candidates=(ResolvedTarget(service_id=owner.service_id, logical_name=key),),
                    kind=ResolutionKind.PORT_HEURISTIC,
                    evidence=f"port {port} is owned only by service {owner.name!r}",
                )
        return None

    def _direct_lookup(self, key: str) -> tuple[list[ServiceBoundary], ResolutionKind] | None:
        compose = self._ns.compose.get(key)
        if compose:
            return compose, ResolutionKind.COMPOSE_HOSTNAME
        names = self._ns.names.get(key)
        if names:
            return names, ResolutionKind.APPLICATION_NAME
        return None

    @staticmethod
    def _single_gateway(claimants: list[ServiceBoundary]) -> ServiceBoundary | None:
        if len(claimants) == 1 and (
            claimants[0].network.gateway_routes or claimants[0].network.gateway_discovery_locator
        ):
            return claimants[0]
        return None

    def _via_gateway(
        self, gateway: ServiceBoundary, path: str, depth: int
    ) -> HostResolution | None:
        route = _longest_route_match(gateway, path)
        if route is None:
            return self._via_discovery_locator(gateway, path)
        prefix, target_uri, strip_prefix = route
        rewritten = _strip_segments(path, strip_prefix)
        parsed = _TARGET_URI.match(target_uri.strip())
        if parsed is None:
            return HostResolution(
                candidates=(
                    ResolvedTarget(
                        service_id=None,
                        logical_name=target_uri.strip().lower(),
                        rewritten_path=rewritten,
                    ),
                ),
                kind=ResolutionKind.GATEWAY_ROUTE,
                evidence=(
                    f"gateway {gateway.name!r} route {prefix!r} forwards to "
                    f"unparseable target {target_uri!r}"
                ),
                via_gateway=True,
            )
        target_host = parsed.group("host")
        target_port = int(parsed.group("port")) if parsed.group("port") else None
        inner = self._resolve(target_host, target_port, rewritten, depth + 1)
        evidence = f"gateway {gateway.name!r} route {prefix!r} -> {target_uri!r}" + (
            f" (strip {strip_prefix})" if strip_prefix else ""
        )
        if inner is None:
            # Config names the target, but nothing analyzed answers to it.
            return HostResolution(
                candidates=(
                    ResolvedTarget(
                        service_id=None,
                        logical_name=target_host.strip().lower(),
                        rewritten_path=rewritten,
                    ),
                ),
                kind=ResolutionKind.GATEWAY_ROUTE,
                evidence=evidence + " — target not among analyzed services",
                via_gateway=True,
            )
        return HostResolution(
            candidates=tuple(
                ResolvedTarget(
                    service_id=c.service_id,
                    logical_name=c.logical_name,
                    rewritten_path=rewritten,
                )
                for c in inner.candidates
            ),
            kind=ResolutionKind.GATEWAY_ROUTE,
            evidence=evidence + "; " + inner.evidence,
            ambiguous=inner.ambiguous,
            port_mismatch=inner.port_mismatch,
            via_gateway=True,
        )

    def _via_discovery_locator(self, gateway: ServiceBoundary, path: str) -> HostResolution | None:
        """Spring Cloud Gateway discovery locator: '/{service-name}/**' forwards
        to that service by discovery name, stripping the first segment. The
        locator effectively declares the first segment as a target name, so an
        unknown name honestly becomes a config-known placeholder."""
        if not gateway.network.gateway_discovery_locator:
            return None
        segments = [s for s in path.split("/") if s]
        if len(segments) < 2:
            return None
        target_name = segments[0].strip().lower()
        rewritten = "/" + "/".join(segments[1:])
        evidence = (
            f"gateway {gateway.name!r} discovery locator: first segment "
            f"{target_name!r} is the target's discovery name"
        )
        claimants = self._ns.names.get(target_name)
        if not claimants:
            return HostResolution(
                candidates=(
                    ResolvedTarget(
                        service_id=None, logical_name=target_name, rewritten_path=rewritten
                    ),
                ),
                kind=ResolutionKind.GATEWAY_ROUTE,
                evidence=evidence + " — target not among analyzed services",
                via_gateway=True,
            )
        return HostResolution(
            candidates=tuple(
                ResolvedTarget(
                    service_id=b.service_id, logical_name=target_name, rewritten_path=rewritten
                )
                for b in claimants
            ),
            kind=ResolutionKind.GATEWAY_ROUTE,
            evidence=evidence,
            ambiguous=len(claimants) > 1,
            via_gateway=True,
        )

    def _port_mismatch(self, claimants: list[ServiceBoundary], port: int | None) -> bool:
        """Both sides know ports and they disagree → degrade, don't reject
        (port remaps are routine in container networks)."""
        if port is None:
            return False
        return all(_known_ports(b) and port not in _known_ports(b) for b in claimants)


def _longest_route_match(gateway: ServiceBoundary, path: str) -> tuple[str, str, int] | None:
    best: tuple[str, str, int] | None = None
    best_len = -1
    for route in gateway.network.gateway_routes:
        prefix = route.path_prefix.rstrip("*").rstrip("/")
        if not prefix:
            prefix_segments: list[str] = []
        else:
            prefix_segments = [s for s in prefix.split("/") if s]
        path_segments = [s for s in path.split("/") if s]
        if path_segments[: len(prefix_segments)] == prefix_segments and (
            len(prefix_segments) > best_len
        ):
            best = (route.path_prefix, route.target_uri, route.strip_prefix)
            best_len = len(prefix_segments)
    return best


def _strip_segments(path: str, count: int) -> str:
    if count <= 0:
        return path
    segments = [s for s in path.split("/") if s]
    return "/" + "/".join(segments[count:])
