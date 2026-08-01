"""Pytest fixtures: one throwaway Mongo container per session, one DB per test.

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

from wadi_storage.mongo import MongoDocument, WadiDatabase, create_client

MONGO_IMAGE = "mongo:8.0"

__all__ = ["MONGO_IMAGE", "database", "mongo_uri"]


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
