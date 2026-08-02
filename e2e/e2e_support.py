"""Shared helpers for the whole-stack e2e tests (real Joern container)."""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# The image tag tracks the VERSION file, same as the compose pins (§13) and
# the tag CI builds for these tests.
JOERN_IMAGE = f"ghcr.io/wadi-sh/joern:{(REPO_ROOT / 'VERSION').read_text().strip()}"


def docker_image_present() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", JOERN_IMAGE], capture_output=True, check=False
    )
    return probe.returncode == 0


requires_joern_image = pytest.mark.skipif(
    not docker_image_present(),
    reason=f"{JOERN_IMAGE} not built — run: docker build -t {JOERN_IMAGE} joern-platform/",
)


def git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "E2E",
            "GIT_AUTHOR_EMAIL": "e2e@wadi.test",
            "GIT_COMMITTER_NAME": "E2E",
            "GIT_COMMITTER_EMAIL": "e2e@wadi.test",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
        },
    )


def make_fixture_repo(fixture: Path, shared_dir: Path) -> Path:
    """A fixture copied into the shared dir as a real git repo."""
    repo = shared_dir / f"{fixture.name}-{uuid.uuid4().hex[:8]}"
    shutil.copytree(fixture, repo, ignore=shutil.ignore_patterns("expected", "target"))
    git("init", "--initial-branch=main", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-m", f"{fixture.name} fixture", cwd=repo)
    return repo
