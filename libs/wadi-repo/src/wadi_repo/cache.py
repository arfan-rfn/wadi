"""Bare-clone cache + snapshot materialization (§3, §4).

The cache holds one bare mirror per repo source, keyed by the normalized
source identity. Everything downstream is derived from mirrors:

- branch/tag/SHA resolution happens against the mirror (``resolve_ref``);
- workspaces are disposable clones of the mirror at a pinned SHA;
- path deltas between snapshots are a mirror-side ``git diff --name-only``;
- source-on-demand reads exact pinned-SHA file content via ``git show``.

The whole chain is rebuildable: delete the cache and it re-clones from
origin; delete a workspace and it re-materializes from the cache (§6).

All git invocations are argument lists (never shell) with terminal prompts
disabled, so a missing credential fails fast instead of hanging a worker.
"""

import hashlib
import re
import subprocess
from pathlib import Path

from wadi_contracts.ids import normalize_repo_source

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

_GIT_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",  # fail fast instead of prompting inside a worker
    "LC_ALL": "C",  # stable, parseable output
}


class GitError(RuntimeError):
    """A git invocation failed."""

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_list = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {self.stderr}")


class RefNotFoundError(GitError):
    """The requested branch/tag/SHA does not exist in the repository."""


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: float = 600) -> str:
    import os

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **_GIT_ENV_OVERRIDES},
        check=False,
    )
    if result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr)
    return result.stdout


class RepoCache:
    """Bare-mirror cache under one directory; safe to delete at any time."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def mirror_path(self, source: str) -> Path:
        """Deterministic mirror location for a repo source."""
        normalized = normalize_repo_source(source)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        # Human-debuggable prefix + collision-proof digest.
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-")[-60:]
        return self._cache_dir / f"{stem}-{digest}.git"

    def ensure_mirror(self, source: str) -> Path:
        """Clone the mirror on first use; fetch (prune) to refresh on later uses."""
        mirror = self.mirror_path(source)
        if mirror.exists():
            _run_git(["--git-dir", str(mirror), "fetch", "--prune", "origin"])
        else:
            _run_git(["clone", "--mirror", source, str(mirror)])
        return mirror

    def resolve_ref(self, source: str, ref: str | None) -> str:
        """Resolve a branch/tag/SHA (or None = default branch HEAD) to a full SHA.

        Assumes :meth:`ensure_mirror` ran for this source in this session.
        """
        mirror = self.mirror_path(source)
        candidates = (
            ["HEAD"]
            if ref is None
            else [
                # Unambiguous ref forms first; raw ref last covers full/abbrev SHAs.
                f"refs/heads/{ref}",
                f"refs/tags/{ref}",
                ref,
            ]
        )
        for candidate in candidates:
            try:
                sha = _run_git(
                    ["--git-dir", str(mirror), "rev-parse", "--verify", f"{candidate}^{{commit}}"]
                ).strip()
            except GitError:
                continue
            if _FULL_SHA.match(sha):
                return sha
        raise RefNotFoundError(
            ["rev-parse", ref or "HEAD"], 128, f"ref {ref!r} not found in {source}"
        )

    def materialize(self, source: str, sha: str, dest: Path) -> Path:
        """Produce a disposable working tree of ``source`` at exactly ``sha``.

        Local clone from the mirror (hardlinked objects — cheap), detached
        checkout at the pinned SHA. Idempotent: an existing correct checkout
        is reused; anything else is rebuilt.
        """
        if not _FULL_SHA.match(sha):
            raise ValueError(f"materialize requires a full 40-hex SHA, got {sha!r}")
        mirror = self.mirror_path(source)
        if dest.exists():
            try:
                current = _run_git(["rev-parse", "HEAD"], cwd=dest).strip()
                if current == sha:
                    return dest
            except GitError:
                pass  # not a usable checkout — rebuild below
            import shutil

            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", "--no-checkout", str(mirror), str(dest)])
        _run_git(["checkout", "--detach", sha], cwd=dest)
        return dest

    def changed_paths(self, source: str, sha_a: str, sha_b: str) -> list[str]:
        """Paths that differ between two commits.

        Rename detection is disabled so a rename reports BOTH sides — the
        build root that lost the file and the one that gained it must both be
        invalidated for incremental rebuilds (§4).
        """
        mirror = self.mirror_path(source)
        output = _run_git(
            ["--git-dir", str(mirror), "diff", "--name-only", "--no-renames", sha_a, sha_b]
        )
        return [line for line in output.splitlines() if line]

    def read_file(self, source: str, sha: str, path: str) -> str:
        """Exact pinned-SHA file content — the source-on-demand primitive (§5.3)."""
        mirror = self.mirror_path(source)
        return _run_git(["--git-dir", str(mirror), "show", f"{sha}:{path}"])
