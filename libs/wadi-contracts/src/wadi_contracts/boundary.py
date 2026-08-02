"""ServiceBoundary — the discovered unit of analysis (§4, §7)."""

from pydantic import Field

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import ServiceKind
from wadi_contracts.source import SourceAnchor


class GatewayRoute(WadiModel):
    """One gateway routing rule extracted from config (§5.4.1 phone-book input).

    Only populated on services that ARE gateways (Spring Cloud Gateway routes
    in application.yml). The stitcher re-resolves ``target_uri`` through the
    phone book after applying the prefix rewrite.
    """

    route_id: str | None = Field(default=None, description="Config route id, when present")
    path_prefix: str = Field(min_length=1, description="Matched prefix, e.g. '/api/v1/orders/**'")
    target_uri: str = Field(
        min_length=1,
        description="Forward target, e.g. 'lb://ts-order-service' or 'http://orders:8080'",
    )
    strip_prefix: int = Field(default=0, ge=0, description="StripPrefix filter segment count")
    anchor: SourceAnchor | None = Field(
        default=None, description="Where in config this route is declared (evidence)"
    )


class NetworkIdentity(WadiModel):
    """How this service is addressed at runtime, as far as statics can see.

    Raw config facts extracted by the worker at extraction time (P2/P6 split:
    the worker extracts, the stitcher resolves). All fields best-effort — an
    absent fact is honest, never guessed (P10).
    """

    hostnames: list[str] = Field(default_factory=list[str])
    ports: list[int] = Field(default_factory=list[int])
    env: dict[str, str] = Field(
        default_factory=dict[str, str],
        description=(
            "Network-relevant config keys (flattened application.yml allowlist + compose env)"
        ),
    )
    application_name: str | None = Field(
        default=None, description="spring.application.name (or equivalent declared identity)"
    )
    discovery_names: list[str] = Field(
        default_factory=list[str],
        description="Names this service registers under in service discovery (Eureka/Consul)",
    )
    server_port: int | None = Field(
        default=None, ge=1, le=65535, description="Configured listen port (server.port)"
    )
    gateway_routes: list[GatewayRoute] = Field(
        default_factory=list[GatewayRoute],
        description="Routing rules when this service is a gateway; empty otherwise",
    )


class ServiceBoundary(ArtifactEnvelope):
    """One discovered service within a snapshot.

    The envelope's ``service_id`` is this service's own stable id
    (content-derived from repo + build root, §7).
    """

    name: str = Field(min_length=1, description="Display name (e.g. compose/module name)")
    repo: str = Field(min_length=1, description="Normalized repo source this service lives in")
    build_root: str = Field(
        min_length=1, description="Path of the build root relative to the repo root ('.' = root)"
    )
    languages: list[str] = Field(min_length=1, description="e.g. ['java']")
    build_system: str = Field(min_length=1, description="e.g. 'maven', 'gradle'")
    network: NetworkIdentity = Field(default_factory=NetworkIdentity)
    kind: ServiceKind = ServiceKind.SERVICE
