"""Values from an analyzed project's config are not published (§5.2.18, issue #28).

The repo below carries one sentinel per place a config value can enter the
worker: application YAML, a profile properties file, gateway and Zuul routes,
compose ``environment:``, an ``env_file`` and the repo ``.env``. Every sentinel
is distinct, so a failure names the place that leaked.

The records are searched as TEXT. A check that walked named fields would pass
on a leak through a field nobody thought to name, which is the only kind of
leak left once the named fields are fixed.
"""

import json
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel
from worker_support import petstore_like_export

from wadi_config import WadiSettings
from wadi_contracts import (
    AuthEvidenceKind,
    Endpoint,
    ExtractionJob,
    JobType,
    RepoSource,
    Snapshot,
    System,
    normalize_repo_source,
)
from wadi_joern_client import ServiceExport
from wadi_repo import RepoCache
from wadi_storage import (
    ArtifactRepository,
    SnapshotRepository,
    SystemRepository,
    WadiDatabase,
)
from wadi_worker.boundary import discover_services
from wadi_worker.pipeline import ExtractionPipeline, service_boundary

# One sentinel per place. None of these is a real credential.
SECURITY_PASSWORD = "wadi-sentinel-security-user-password"
CLIENT_SECRET = "wadi-sentinel-security-client-secret"
ISSUER = "wadi-sentinel-security-issuer"
JDBC_PASSWORD = "wadi-sentinel-jdbc-password"
USER_NAME = "wadi-sentinel-userinfo-name"
USER_PASSWORD = "wadi-sentinel-userinfo-password"
QUERY_TOKEN = "wadi-sentinel-query-token"
SLASH_PASSWORD = "wadi-sentinel-malformed-password"
GATEWAY_HEADER = "wadi-sentinel-gateway-header"
ROUTE_PASSWORD = "wadi-sentinel-gateway-route-password"
HOST_PASSWORD = "wadi-sentinel-host-password"
ZUUL_PASSWORD = "wadi-sentinel-zuul-password"
COMPOSE_PASSWORD = "wadi-sentinel-compose-userinfo"
COMPOSE_JDBC = "wadi-sentinel-compose-jdbc"
COMPOSE_SECURITY = "wadi-sentinel-compose-security"
COMPOSE_TOKEN = "wadi-sentinel-compose-query-token"
ENV_FILE_PASSWORD = "wadi-sentinel-envfile-password"
DOTENV_PASSWORD = "wadi-sentinel-dotenv-password"

#: place -> the value seeded there, so a failure names where the leak entered.
SENTINELS = {
    "application.yml spring.security.user.password": SECURITY_PASSWORD,
    "application.yml spring.security client-secret": CLIENT_SECRET,
    "application.yml spring.security issuer-uri": ISSUER,
    "application.yml datasource JDBC URL password": JDBC_PASSWORD,
    "application.yml URL user-info name": USER_NAME,
    "application.yml URL user-info password": USER_PASSWORD,
    "application.yml URL query token": QUERY_TOKEN,
    "application.yml URL with a slash in its password": SLASH_PASSWORD,
    "application.yml gateway default-filters header": GATEWAY_HEADER,
    "application.yml gateway route uri password": ROUTE_PASSWORD,
    "profile properties host with user-info": HOST_PASSWORD,
    "profile properties zuul route url password": ZUUL_PASSWORD,
    "compose environment URL user-info": COMPOSE_PASSWORD,
    "compose environment JDBC URL password": COMPOSE_JDBC,
    "compose environment SPRING_SECURITY_* value": COMPOSE_SECURITY,
    "compose environment URL query token": COMPOSE_TOKEN,
    "compose env_file URL user-info": ENV_FILE_PASSWORD,
    "repo .env pass-through URL user-info": DOTENV_PASSWORD,
}

_APPLICATION_YML = f"""
spring:
  application:
    name: shop
  datasource:
    url: jdbc:postgresql://db:5432/shop?user=shop&password={JDBC_PASSWORD}
  security:
    user:
      password: {SECURITY_PASSWORD}
    oauth2:
      client:
        registration:
          shop:
            client-secret: {CLIENT_SECRET}
      resourceserver:
        jwt:
          issuer-uri: https://idp.example.test/realms/{ISSUER}
  cloud:
    gateway:
      default-filters:
        - AddRequestHeader=X-Api-Key, {GATEWAY_HEADER}
      routes:
        - id: legacy
          uri: http://gateway-user:{ROUTE_PASSWORD}@legacy:8000
          predicates:
            - Path=/legacy/**
server:
  port: 8080
billing:
  url: https://{USER_NAME}:{USER_PASSWORD}@billing:9000/api
audit:
  uri: http://audit:7000/log?access_token={QUERY_TOKEN}
reports:
  url: https://reports-user:pa/{SLASH_PASSWORD}@reports:8443/x
"""

_PROFILE_PROPERTIES = f"""
partner.host=partner-user:{HOST_PASSWORD}@partner.example.test
zuul.routes.old.path=/old/**
zuul.routes.old.url=http://zuul-user:{ZUUL_PASSWORD}@old:8000
"""

_COMPOSE = f"""
services:
  shop:
    build: .
    env_file: shop.env
    environment:
      - DATABASE_URL=postgres://shop:{COMPOSE_PASSWORD}@db:5432/shop
      - SPRING_DATASOURCE_URL=jdbc:mysql://db/shop?password={COMPOSE_JDBC}
      - SPRING_SECURITY_OAUTH2_CLIENT_PROVIDER_IDP_ISSUER_URI=https://idp.example.test/{COMPOSE_SECURITY}
      - WEBHOOK=https://hooks.example.test/notify?token={COMPOSE_TOKEN}
      - INVENTORY_URL
"""

_ENV_FILE = f"REPORTS_URL=https://reports:{ENV_FILE_PASSWORD}@reports:8443\n"
_DOTENV = f"INVENTORY_URL=http://inventory:{DOTENV_PASSWORD}@inventory:8081\n"


def _seed_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "pom.xml").write_text(
        '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<modelVersion>4.0.0</modelVersion><artifactId>shop</artifactId></project>"
    )
    java = repo / "src" / "main" / "java"
    java.mkdir(parents=True)
    (java / "App.java").write_text("class App {}\n")
    resources = repo / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text(_APPLICATION_YML)
    (resources / "application-prod.properties").write_text(_PROFILE_PROPERTIES)
    (repo / "docker-compose.yml").write_text(_COMPOSE)
    (repo / "shop.env").write_text(_ENV_FILE)
    (repo / ".env").write_text(_DOTENV)


def _leaked(text: str) -> list[str]:
    """The places whose sentinel appears anywhere in ``text``."""
    return sorted(place for place, value in SENTINELS.items() if value in text)


@pytest.fixture
def seeded_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shop"
    _seed_repo(repo)
    return repo


class TestBoundaryRecord:
    """The published boundary, built without a database."""

    def test_the_seed_is_read(self, seeded_repo: Path) -> None:
        # Guards the search below against passing because nothing was parsed:
        # every seeded file has to have reached the worker's own facts.
        [service] = discover_services(seeded_repo)
        assert service.config.application_name == "shop"
        assert "config-profile-merged:application-prod.properties" in service.config.notes
        assert {"DATABASE_URL", "REPORTS_URL", "INVENTORY_URL"} <= set(service.config.env)

    def test_no_seeded_value_reaches_the_boundary_record(self, seeded_repo: Path) -> None:
        [service] = discover_services(seeded_repo)
        boundary = service_boundary("snap_secrets", "local/shop", "svc_" + "a" * 16, service)
        assert _leaked(boundary.model_dump_json()) == []

    def test_what_the_stitcher_routes_by_survives_without_credentials(
        self, seeded_repo: Path
    ) -> None:
        [service] = discover_services(seeded_repo)
        network = service_boundary("snap_secrets", "local/shop", "svc_" + "a" * 16, service).network
        assert network.env == {
            "DATABASE_URL": "postgres://db:5432/shop",
            "INVENTORY_URL": "http://inventory:8081",
            "REPORTS_URL": "https://reports:8443",
            "WEBHOOK": "https://hooks.example.test/notify?token=",
            "audit.uri": "http://audit:7000/log?access_token=",
            "billing.url": "https://billing:9000/api",
            "partner.host": "partner.example.test",
            "server.port": "8080",
            "spring.application.name": "shop",
            "zuul.routes.old.url": "http://old:8000",
        }
        # Withheld whole, and counted: the credentials of `reports.url` could
        # not be told apart from its host, so no part of it is published.
        assert "config-value-withheld:reports.url" in network.config_notes
        assert sorted((r.path_prefix, r.target_uri) for r in network.gateway_routes) == [
            ("/legacy/**", "http://legacy:8000"),
            ("/old/**", "http://old:8000"),
        ]
        assert network.application_name == "shop"
        assert network.server_port == 8080


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@e.c",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@e.c",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
        },
    )


class _FakeExtractor:
    """Stands in for Joern. Config never reaches Joern, so the canned export
    is the right double: what is under test is what the worker adds to it."""

    def extract(self, source_path: Path, export_dir: Path, project_name: str) -> ServiceExport:
        return petstore_like_export()


@dataclass(frozen=True)
class _Analysis:
    """One seeded repo, committed and pinned, ready for a pipeline run."""

    settings: WadiSettings
    cache: RepoCache
    system: System
    snapshot: Snapshot
    job: ExtractionJob


def _analysis_of(repo: Path, tmp_path: Path) -> _Analysis:
    _git("init", "--initial-branch=main", cwd=repo)
    # `.env` is seeded on purpose, so add it past any ignore rule.
    _git("add", "--force", ".", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    # Validated from a dict, so no environment variable or `.env` of the
    # machine running the test is read into the settings.
    settings = WadiSettings.model_validate(
        {
            "workspace_dir": tmp_path / "workspace",
            "cpg_cache_dir": tmp_path / "cpg-cache",
            "repo_cache_dir": tmp_path / "repo-cache",
        }
    )
    cache = RepoCache(settings.repo_cache_dir)
    cache.ensure_mirror(str(repo))
    system = System(id=f"sys_{uuid.uuid4().hex}", name="shop", repos=[RepoSource(source=str(repo))])
    snapshot = Snapshot(
        id=f"snap_{uuid.uuid4().hex}",
        system_id=system.id,
        commits={normalize_repo_source(str(repo)): cache.resolve_ref(str(repo), None)},
    )
    job = ExtractionJob(id=f"job_{uuid.uuid4().hex}", type=JobType.EXTRACT, snapshot_id=snapshot.id)
    return _Analysis(settings, cache, system, snapshot, job)


#: The three `spring.security.*` settings the seed declares. The key says
#: which setting exists; its value stays in the repo.
_SECURITY_KEYS = [
    "spring.security.oauth2.client.registration.shop.client-secret",
    "spring.security.oauth2.resourceserver.jwt.issuer-uri",
    "spring.security.user.password",
]


def _config_evidence(endpoint: Endpoint) -> list[str]:
    assert endpoint.auth is not None
    return [item.detail for item in endpoint.auth.evidence if item.kind is AuthEvidenceKind.CONFIG]


class _Holding[T]:
    """A repository that returns the one record it was given."""

    def __init__(self, record: T) -> None:
        self._record = record

    async def get(self, record_id: str) -> T | None:
        return self._record


class _RecordingArtifacts:
    """Keeps every artifact the pipeline writes, in place of Mongo."""

    def __init__(self) -> None:
        self.written: list[BaseModel] = []

    async def write_service_boundaries(self, boundaries: Sequence[BaseModel]) -> None:
        self.written.extend(boundaries)

    async def write_endpoints(self, endpoints: Sequence[BaseModel]) -> None:
        self.written.extend(endpoints)

    async def write_icfg(self, icfg: BaseModel) -> None:
        self.written.append(icfg)

    async def write_remote_calls(self, calls: Sequence[BaseModel]) -> None:
        self.written.extend(calls)

    async def write_mq_interactions(self, interactions: Sequence[BaseModel]) -> None:
        self.written.extend(interactions)

    async def write_data_models(self, models: Sequence[BaseModel]) -> None:
        self.written.extend(models)


class TestWrittenRecords:
    """The whole worker run, with the writes kept in memory.

    This is the pipeline's own wiring, so it also covers what the boundary
    alone cannot: the auth evidence the assembler puts on every endpoint.
    """

    async def test_no_seeded_value_reaches_a_record_the_pipeline_writes(
        self, seeded_repo: Path, tmp_path: Path
    ) -> None:
        analysis = _analysis_of(seeded_repo, tmp_path)
        artifacts = _RecordingArtifacts()
        await ExtractionPipeline(
            settings=analysis.settings,
            systems=cast(SystemRepository, _Holding(analysis.system)),
            snapshots=cast(SnapshotRepository, _Holding(analysis.snapshot)),
            artifacts=cast(ArtifactRepository, artifacts),
            repo_cache=analysis.cache,
            extractor=_FakeExtractor(),
        ).run(analysis.job)

        # The run wrote what the search is about to read.
        assert {type(record).__name__ for record in artifacts.written} >= {
            "ServiceBoundary",
            "Endpoint",
            "Icfg",
            "RemoteCall",
        }
        # `model_dump_json()` is how the export route serializes each record
        # (orchestrator `export.py`), so this is the bundle's worker half.
        written = "\n".join(record.model_dump_json() for record in artifacts.written)
        assert _leaked(written) == []

        [endpoint] = [record for record in artifacts.written if isinstance(record, Endpoint)]
        assert _config_evidence(endpoint) == _SECURITY_KEYS


async def _stored_text(database: WadiDatabase) -> str:
    """Every document in every collection, as text."""
    lines: list[str] = []
    for name in sorted(await database.db.list_collection_names()):
        async for document in database.collection(name).find({}):
            lines.append(f"{name}: {json.dumps(document, default=str, sort_keys=True)}")
    return "\n".join(lines)


@pytest.mark.integration
class TestStoredRecords:
    """The whole worker run against real Mongo, read back raw."""

    async def test_no_seeded_value_reaches_a_stored_record(
        self, database: WadiDatabase, seeded_repo: Path, tmp_path: Path
    ) -> None:
        analysis = _analysis_of(seeded_repo, tmp_path)
        await SystemRepository(database).insert(analysis.system)
        await SnapshotRepository(database).insert(analysis.snapshot)
        artifacts = ArtifactRepository(database)
        await ExtractionPipeline(
            settings=analysis.settings,
            systems=SystemRepository(database),
            snapshots=SnapshotRepository(database),
            artifacts=artifacts,
            repo_cache=analysis.cache,
            extractor=_FakeExtractor(),
        ).run(analysis.job)

        # The run stored what the search is about to read: a boundary carrying
        # config, and an endpoint whose auth evidence came from config.
        snapshot_id = analysis.snapshot.id
        [boundary] = await artifacts.list_service_boundaries(snapshot_id)
        assert "billing.url" in boundary.network.env
        [endpoint] = await artifacts.list_endpoints(snapshot_id, boundary.service_id)
        assert endpoint.auth is not None

        stored = await _stored_text(database)
        assert "service_boundaries: " in stored
        assert "endpoints: " in stored
        assert _leaked(stored) == []

        assert boundary.network.env["billing.url"] == "https://billing:9000/api"
        assert _config_evidence(endpoint) == _SECURITY_KEYS
