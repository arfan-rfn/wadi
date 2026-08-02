"""The extraction pipeline (§5.2): the worker-side orchestration of one job.

Phase 1 flow (one extract job per snapshot, §5.3 note): materialize every
repo at its pinned SHA → discover service boundaries → per service: build
the CPG via Joern, run the in-graph pipeline (DI pass + packs + bulk export),
read the export from the shared volume, assemble artifacts, write them.

The Joern interaction is behind :class:`JoernExtractor` so the pipeline is
fully testable with a fake extractor; the real one drives the CPGQL control
channel (§5.1).
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Protocol

from wadi_config import WadiSettings
from wadi_contracts import (
    ExtractionJob,
    GatewayRoute,
    NetworkIdentity,
    ServiceBoundary,
    normalize_repo_source,
    service_id,
)
from wadi_joern_client import JoernClient, ServiceExport
from wadi_repo import RepoCache
from wadi_storage import ArtifactRepository, SnapshotRepository, SystemRepository
from wadi_worker.assembler import Assembler
from wadi_worker.boundary import discover_services

logger = logging.getLogger(__name__)


class JoernExtractor(Protocol):
    """Builds a CPG for one build root and returns the bulk export."""

    def extract(self, source_path: Path, export_dir: Path, project_name: str) -> ServiceExport: ...


class CpgqlJoernExtractor:
    """The real extractor: control via CPGQL, bulk data via the shared volume (§5.1)."""

    def __init__(self, client: JoernClient) -> None:
        self._client = client

    def extract(self, source_path: Path, export_dir: Path, project_name: str) -> ServiceExport:
        export_dir.mkdir(parents=True, exist_ok=True)
        self._client.import_code(str(source_path), project_name)
        try:
            summary = self._client.run_wadi_pipeline(str(export_dir))
            logger.info("wadi pipeline for %s: %s", project_name, summary.strip())
        finally:
            # CPGs are disposable (P5); free the server's memory regardless of outcome.
            try:
                self._client.delete_project(project_name)
            except Exception:
                logger.warning("could not delete Joern project %s", project_name)
        export_file = export_dir / "export.json"
        if not export_file.exists():
            raise RuntimeError(
                f"Joern pipeline reported success but wrote no export at {export_file}"
            )
        return ServiceExport.model_validate(json.loads(export_file.read_text()))


class ExtractionPipeline:
    def __init__(
        self,
        *,
        settings: WadiSettings,
        systems: SystemRepository,
        snapshots: SnapshotRepository,
        artifacts: ArtifactRepository,
        repo_cache: RepoCache,
        extractor: JoernExtractor,
    ) -> None:
        self._settings = settings
        self._systems = systems
        self._snapshots = snapshots
        self._artifacts = artifacts
        self._repo_cache = repo_cache
        self._extractor = extractor

    async def run(self, job: ExtractionJob) -> None:
        snapshot = await self._snapshots.get(job.snapshot_id)
        if snapshot is None:
            raise RuntimeError(f"snapshot {job.snapshot_id} not found")
        system = await self._systems.get(snapshot.system_id)
        if system is None:
            raise RuntimeError(f"system {snapshot.system_id} not found")

        workspace = self._settings.workspace_dir / snapshot.id
        endpoint_count = 0
        service_count = 0

        for repo in system.repos:
            normalized = normalize_repo_source(repo.source)
            sha = snapshot.commits.get(normalized)
            if sha is None:
                raise RuntimeError(f"snapshot has no pinned commit for repo {normalized!r}")
            checkout = workspace / _path_slug(normalized)
            await asyncio.to_thread(self._repo_cache.ensure_mirror, repo.source)
            await asyncio.to_thread(self._repo_cache.materialize, repo.source, sha, checkout)

            discovered = await asyncio.to_thread(discover_services, checkout)
            if not discovered:
                logger.warning("no analyzable services found in %s", normalized)
            for service in discovered:
                service_count += 1
                svc_id = service_id(repo.source, service.build_root)
                boundary = ServiceBoundary(
                    snapshot_id=snapshot.id,
                    service_id=svc_id,
                    name=service.name,
                    repo=normalized,
                    build_root=service.build_root,
                    languages=service.languages,
                    build_system=service.build_system,
                    network=NetworkIdentity(
                        hostnames=service.hostnames,
                        ports=service.ports,
                        env=service.config.env,
                        application_name=service.config.application_name,
                        server_port=service.config.server_port,
                        gateway_routes=[
                            GatewayRoute(
                                route_id=route.route_id,
                                path_prefix=route.path_prefix,
                                target_uri=route.target_uri,
                                strip_prefix=route.strip_prefix,
                            )
                            for route in service.config.gateway_routes
                        ],
                        gateway_discovery_locator=service.config.gateway_discovery_locator,
                        config_notes=service.config.notes,
                    ),
                )
                await self._artifacts.write_service_boundaries([boundary])

                build_root_path = (
                    checkout if service.build_root == "." else checkout / service.build_root
                )
                export_dir = workspace / "exports" / svc_id
                export = await asyncio.to_thread(
                    self._extractor.extract,
                    build_root_path,
                    export_dir,
                    f"{snapshot.id}-{svc_id}",
                )
                assembled = Assembler(
                    snapshot_id=snapshot.id,
                    service_id=svc_id,
                    config_env=service.config.env,
                ).assemble(export)
                await self._artifacts.write_endpoints(assembled.endpoints)
                for icfg in assembled.icfgs:
                    await self._artifacts.write_icfg(icfg)
                await self._artifacts.write_remote_calls(assembled.remote_calls)
                await self._artifacts.write_mq_interactions(assembled.mq_interactions)
                await self._artifacts.write_data_models(assembled.data_models)
                endpoint_count += len(assembled.endpoints)

        logger.info(
            "snapshot %s: extracted %d endpoints across %d services",
            snapshot.id,
            endpoint_count,
            service_count,
        )


def _path_slug(normalized_source: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", normalized_source).strip("-")[-80:]
