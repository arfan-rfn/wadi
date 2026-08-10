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
            # Bounded, because unbounded is not "no limit" — it is "size the
            # JVM heap against the WHOLE Docker VM". Run beside a live wadi
            # stack, whose own analyzer reserves 10g of a 15.6g VM, the two
            # overcommit and Docker kills containers: locally that shows up as
            # the stack's non-database services disappearing mid-run, and as
            # intermittent e2e errors that pass on a re-run. CI never saw it —
            # a fresh runner has no competing stack.
            #
            # 4g against a measured peak of 807 MiB on these fixtures: five
            # times headroom, and small enough that both can coexist.
            "--memory",
            "4g",
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
