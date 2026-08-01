"""Local helpers for orchestrator tests (unique module name — pytest imports
test-adjacent modules into one namespace across the workspace)."""

from pathlib import Path

from wadi_config import WadiSettings


def make_settings(tmp_path: Path, **overrides: object) -> WadiSettings:
    return WadiSettings(
        _env_file=None,  # type: ignore[call-arg]
        repo_cache_dir=tmp_path / "repo-cache",
        workspace_dir=tmp_path / "workspace",
        cpg_cache_dir=tmp_path / "cpg-cache",
        **overrides,  # type: ignore[arg-type]
    )
