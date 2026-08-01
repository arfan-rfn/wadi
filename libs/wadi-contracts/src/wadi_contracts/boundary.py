"""ServiceBoundary — the discovered unit of analysis (§4, §7)."""

from pydantic import Field

from wadi_contracts.base import ArtifactEnvelope, WadiModel
from wadi_contracts.enums import ServiceKind


class NetworkIdentity(WadiModel):
    """How this service is addressed at runtime, as far as statics can see."""

    hostnames: list[str] = Field(default_factory=list[str])
    ports: list[int] = Field(default_factory=list[int])
    env: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="Network-relevant environment (e.g. compose service env) — values, not secrets",
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
