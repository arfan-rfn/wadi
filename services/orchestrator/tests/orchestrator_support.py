"""Local helpers for orchestrator tests (unique module name — pytest imports
test-adjacent modules into one namespace across the workspace)."""

import subprocess
from pathlib import Path

from wadi_config import WadiSettings


def run_git(*args: str, cwd: Path) -> str:
    """git in a hermetic environment — no user config, no ambient identity.

    Shared rather than conftest-private because two test modules build real
    repositories now: the fixture repo, and the staged-library source case.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
        },
    )
    return result.stdout


def make_settings(tmp_path: Path, **overrides: object) -> WadiSettings:
    return WadiSettings(
        _env_file=None,  # type: ignore[call-arg]
        repo_cache_dir=tmp_path / "repo-cache",
        workspace_dir=tmp_path / "workspace",
        cpg_cache_dir=tmp_path / "cpg-cache",
        **overrides,  # type: ignore[arg-type]
    )
