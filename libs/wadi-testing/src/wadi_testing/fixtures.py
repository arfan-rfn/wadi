"""Pytest fixtures: throwaway Mongo/Neo4j containers per session, wiped per test.

Usage in a package's ``tests/conftest.py``::

    from wadi_testing.fixtures import *  # noqa: F403

Tests are skipped when Docker is unavailable.
"""

import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest

from wadi_storage.graph import GraphRepository, GraphStore
from wadi_storage.mongo import MongoDocument, WadiDatabase, create_client

MONGO_IMAGE = "mongo:8.0"
NEO4J_IMAGE = "neo4j:5.26-community"  # matches infra/docker-compose.yml
_NEO4J_TEST_PASSWORD = "wadi-test"

__all__ = [
    "MONGO_IMAGE",
    "NEO4J_IMAGE",
    "database",
    "graph_repository",
    "mongo_uri",
    "neo4j_uri",
]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "info"], capture_output=True, check=False, timeout=30)
    return probe.returncode == 0


@pytest.fixture(scope="session")
def mongo_uri() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker is not available — skipping Mongo integration tests")
    container = f"wadi-test-mongo-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1:0:27017",
            MONGO_IMAGE,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    try:
        port_output = subprocess.run(
            ["docker", "port", container, "27017/tcp"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()[0]
        host_port = port_output.rsplit(":", 1)[1].strip()
        uri = f"mongodb://127.0.0.1:{host_port}"
        _wait_for_mongo(uri)
        yield uri
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def _wait_for_mongo(uri: str, timeout_seconds: float = 60.0) -> None:
    from pymongo import MongoClient

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client: MongoClient[MongoDocument] = MongoClient(uri, serverSelectionTimeoutMS=1000)
            client.admin.command("ping")
            client.close()
            return
        except Exception as exc:  # retry loop on any startup error
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Mongo container did not become ready: {last_error}")


@pytest.fixture
async def database(mongo_uri: str) -> AsyncIterator[WadiDatabase]:
    """A fresh, indexed database per test."""
    client = create_client(mongo_uri)
    db = WadiDatabase(client, f"wadi_test_{uuid.uuid4().hex[:12]}")
    await db.ensure_indexes()
    yield db
    await client.drop_database(db.db.name)
    await db.close()


@pytest.fixture(scope="session")
def neo4j_uri() -> Iterator[str]:
    """One throwaway Neo4j container per session (bolt URI)."""
    if not _docker_available():
        pytest.skip("Docker is not available — skipping Neo4j integration tests")
    container = f"wadi-test-neo4j-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1:0:7687",
            "--env",
            f"NEO4J_AUTH=neo4j/{_NEO4J_TEST_PASSWORD}",
            "--env",
            "NEO4J_server_memory_heap_max__size=512m",
            "--env",
            "NEO4J_server_memory_pagecache_size=128m",
            NEO4J_IMAGE,
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    try:
        port_output = subprocess.run(
            ["docker", "port", container, "7687/tcp"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()[0]
        host_port = port_output.rsplit(":", 1)[1].strip()
        uri = f"neo4j://127.0.0.1:{host_port}"
        _wait_for_neo4j(uri)
        yield uri
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def _wait_for_neo4j(uri: str, timeout_seconds: float = 120.0) -> None:
    from neo4j import GraphDatabase

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            driver = GraphDatabase.driver(uri, auth=("neo4j", _NEO4J_TEST_PASSWORD))  # pyright: ignore[reportUnknownMemberType]
            try:
                driver.verify_connectivity()  # pyright: ignore[reportUnknownMemberType]
                return
            finally:
                driver.close()
        except Exception as exc:  # retry loop on any startup error
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Neo4j container did not become ready: {last_error}")


@pytest.fixture
async def graph_repository(neo4j_uri: str) -> AsyncIterator[GraphRepository]:
    """A schema-ensured GraphRepository, graph wiped after each test.

    Community edition ships a single database, so per-test isolation is a
    full wipe rather than a per-test database.
    """
    async with GraphStore(neo4j_uri, "neo4j", _NEO4J_TEST_PASSWORD) as store:
        repository = GraphRepository(store)
        await repository.ensure_schema()
        yield repository
        await store.driver.execute_query(  # pyright: ignore[reportUnknownMemberType]
            "MATCH (n) DETACH DELETE n", database_="neo4j"
        )
