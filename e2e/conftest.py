"""e2e fixtures: one shared dir + one real wadi-joern container per session."""

import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e_support import JOERN_IMAGE

from wadi_joern_client import JoernClient


@pytest.fixture(scope="session")
def shared_dir() -> Iterator[Path]:
    """Host dir mounted at the SAME path inside the Joern container (§13 topology)."""
    path = Path(tempfile.mkdtemp(prefix="wadi-e2e-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def joern_url(shared_dir: Path) -> Iterator[str]:
    container = f"wadi-e2e-joern-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1:0:8080",
            "--volume",
            f"{shared_dir}:{shared_dir}",
            JOERN_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        port_line = subprocess.run(
            ["docker", "port", container, "8080/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
        url = f"http://127.0.0.1:{port_line.rsplit(':', 1)[1].strip()}"
        client = JoernClient(url, request_timeout=60)
        deadline = time.monotonic() + 180
        while not client.is_ready():
            if time.monotonic() > deadline:
                raise RuntimeError("wadi-joern container never became ready")
            time.sleep(2)
        client.close()
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
