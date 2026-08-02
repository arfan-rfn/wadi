"""Canonical WADI_* settings (§13).

Naming rule: ``WADI_<RESOURCE>_<PROPERTY>`` — never an unqualified
``WADI_URL``/``WADI_TOKEN``. Defaults describe the local compose stack
(service names on the compose network, the 9234 "WADI keypad" port block);
every one is an env-var override away from Atlas/Aura/a team server.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WadiSettings(BaseSettings):
    """Process-wide settings, loaded once from env (+ optional ``.env``)."""

    model_config = SettingsConfigDict(
        env_prefix="WADI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unrelated WADI_* vars (e.g. CLI-only) must not break services
        frozen=True,
    )

    # --- Backing stores (attached resources, URI-identified) ---
    mongo_uri: str = Field(
        default="mongodb://mongo:27017",
        description="MongoDB connection string; swap for Atlas (mongodb+srv://…) via env",
    )
    mongo_database: str = Field(default="wadi")
    neo4j_uri: str = Field(
        default="neo4j://neo4j:7687",
        description="Neo4j bolt URI; swap for Aura (neo4j+s://…) via env",
    )
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: SecretStr = Field(default=SecretStr("wadi-local"))
    neo4j_database: str = Field(
        default="neo4j", description="Neo4j database name (Community ships exactly one)"
    )
    graph_write_batch_size: int = Field(
        default=1000, ge=1, description="Rows per UNWIND chunk when the stitcher rebuilds Tier 2"
    )

    # --- Joern ---
    joern_url: str = Field(
        default="http://wadi-joern:8080",
        description="CPGQL server endpoint; the worker only ever dials this, never manages it",
    )
    joern_username: str | None = Field(default=None)
    joern_password: SecretStr | None = Field(default=None)

    # --- Shared filesystem (worker + wadi-joern share this view, §13 topology) ---
    workspace_dir: Path = Field(
        default=Path("/workspace"),
        description="Materialized checkouts + bulk-export exchange directory",
    )
    cpg_cache_dir: Path = Field(
        default=Path("/cpg-cache"),
        description="Tier-0 CPG cache keyed (service, language, content-hash); evictable",
    )
    repo_cache_dir: Path = Field(
        default=Path("/repo-cache"),
        description="Bare-clone cache; rebuildable from origin",
    )

    # --- API surface (client side: how the CLI/tools reach a deployment) ---
    api_url: str = Field(default="http://127.0.0.1:9234")
    api_token: SecretStr | None = Field(
        default=None, description="Bearer token for remote deployments (§14)"
    )

    # --- Ports (the WADI keypad block, §13) ---
    api_port: int = Field(default=9234, ge=1, le=65535)
    ui_port: int = Field(default=9235, ge=1, le=65535)
    mcp_port: int = Field(default=9236, ge=1, le=65535)

    # --- Worker behavior ---
    job_lease_seconds: int = Field(
        default=600,
        ge=30,
        description="Job claim lease; an expired lease requeues the job (§7)",
    )
    job_heartbeat_seconds: int = Field(default=60, ge=5)
    job_poll_seconds: float = Field(default=2.0, gt=0)
    fetch_dependencies: bool = Field(
        default=False,
        description="Run target build tooling for dependency resolution — arbitrary code "
        "execution on behalf of the analyzed repo; off by default (§12)",
    )


@lru_cache(maxsize=1)
def get_settings() -> WadiSettings:
    """The process-wide settings instance (cached; env is read once)."""
    return WadiSettings()
