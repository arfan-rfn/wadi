"""RepoCache tests against real local git repositories (no network)."""

import subprocess
from pathlib import Path

import pytest

from wadi_repo import GitError, RefNotFoundError, RepoCache


def _git(*args: str, cwd: Path) -> str:
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


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A local 'origin' repo with two commits on main and a tag."""
    repo = tmp_path / "origin"
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=repo)
    (repo / "pom.xml").write_text("<project>v1</project>\n")
    (repo / "src").mkdir()
    (repo / "src" / "App.java").write_text("class App {}\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "first", cwd=repo)
    _git("tag", "v1.0.0", cwd=repo)
    (repo / "src" / "App.java").write_text("class App { int x; }\n")
    (repo / "src" / "New.java").write_text("class New {}\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "second", cwd=repo)
    return repo


@pytest.fixture
def cache(tmp_path: Path) -> RepoCache:
    return RepoCache(tmp_path / "cache")


def _sha(repo: Path, ref: str) -> str:
    return _git("rev-parse", ref, cwd=repo).strip()


class TestMirror:
    def test_first_use_clones(self, cache: RepoCache, origin: Path) -> None:
        mirror = cache.ensure_mirror(str(origin))
        assert mirror.exists()
        assert mirror.suffix == ".git"

    def test_refresh_picks_up_new_commits(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        (origin / "later.txt").write_text("later\n")
        _git("add", ".", cwd=origin)
        _git("commit", "-m", "third", cwd=origin)
        new_head = _sha(origin, "HEAD")

        cache.ensure_mirror(str(origin))  # refresh
        assert cache.resolve_ref(str(origin), "main") == new_head

    def test_distinct_sources_get_distinct_mirrors(
        self, cache: RepoCache, tmp_path: Path, origin: Path
    ) -> None:
        # Same basename, different parent — must not collide.
        other_parent = tmp_path / "elsewhere"
        other_parent.mkdir()
        other = other_parent / "origin"
        other.mkdir()
        _git("init", "--initial-branch=main", cwd=other)
        (other / "a.txt").write_text("a\n")
        _git("add", ".", cwd=other)
        _git("commit", "-m", "only", cwd=other)
        assert cache.mirror_path(str(origin)) != cache.mirror_path(str(other))


class TestResolveRef:
    def test_branch(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        assert cache.resolve_ref(str(origin), "main") == _sha(origin, "main")

    def test_tag(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        assert cache.resolve_ref(str(origin), "v1.0.0") == _sha(origin, "v1.0.0^{commit}")

    def test_none_resolves_default_branch(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        assert cache.resolve_ref(str(origin), None) == _sha(origin, "HEAD")

    def test_full_sha_passthrough(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        first = _sha(origin, "HEAD~1")
        assert cache.resolve_ref(str(origin), first) == first

    def test_abbreviated_sha(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        full = _sha(origin, "HEAD")
        assert cache.resolve_ref(str(origin), full[:10]) == full

    def test_missing_ref_raises(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        with pytest.raises(RefNotFoundError):
            cache.resolve_ref(str(origin), "does-not-exist")

    def test_branch_beats_ambiguous_raw_ref(self, cache: RepoCache, origin: Path) -> None:
        # A branch whose name could also parse as something else must resolve as branch.
        _git("branch", "v1.0.0-branch", "HEAD~1", cwd=origin)
        cache.ensure_mirror(str(origin))
        assert cache.resolve_ref(str(origin), "v1.0.0-branch") == _sha(origin, "HEAD~1")


class TestMaterialize:
    def test_checkout_at_pinned_sha(self, cache: RepoCache, origin: Path, tmp_path: Path) -> None:
        cache.ensure_mirror(str(origin))
        first = _sha(origin, "HEAD~1")
        workspace = cache.materialize(str(origin), first, tmp_path / "ws")
        assert (workspace / "src" / "App.java").read_text() == "class App {}\n"
        assert not (workspace / "src" / "New.java").exists()  # second commit's file

    def test_idempotent_reuse(self, cache: RepoCache, origin: Path, tmp_path: Path) -> None:
        cache.ensure_mirror(str(origin))
        head = _sha(origin, "HEAD")
        dest = tmp_path / "ws"
        cache.materialize(str(origin), head, dest)
        marker = dest / "marker.tmp"
        marker.write_text("scratch\n")
        cache.materialize(str(origin), head, dest)  # same SHA — reused, not rebuilt
        assert marker.exists()

    def test_rebuild_on_different_sha(self, cache: RepoCache, origin: Path, tmp_path: Path) -> None:
        cache.ensure_mirror(str(origin))
        dest = tmp_path / "ws"
        cache.materialize(str(origin), _sha(origin, "HEAD"), dest)
        cache.materialize(str(origin), _sha(origin, "HEAD~1"), dest)
        assert not (dest / "src" / "New.java").exists()

    def test_requires_full_sha(self, cache: RepoCache, origin: Path, tmp_path: Path) -> None:
        cache.ensure_mirror(str(origin))
        with pytest.raises(ValueError, match="full 40-hex SHA"):
            cache.materialize(str(origin), "main", tmp_path / "ws")


class TestChangedPaths:
    def test_modify_add(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        first, second = _sha(origin, "HEAD~1"), _sha(origin, "HEAD")
        changed = cache.changed_paths(str(origin), first, second)
        assert set(changed) == {"src/App.java", "src/New.java"}

    def test_delete_and_rename_both_sides_reported(self, cache: RepoCache, origin: Path) -> None:
        _git("mv", "src/App.java", "src/Renamed.java", cwd=origin)
        _git("rm", "pom.xml", cwd=origin)
        _git("commit", "-m", "restructure", cwd=origin)
        cache.ensure_mirror(str(origin))
        changed = cache.changed_paths(str(origin), _sha(origin, "HEAD~1"), _sha(origin, "HEAD"))
        assert {"src/App.java", "src/Renamed.java", "pom.xml"} <= set(changed)

    def test_identical_shas_no_changes(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        head = _sha(origin, "HEAD")
        assert cache.changed_paths(str(origin), head, head) == []


class TestReadFile:
    def test_reads_exact_pinned_content(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        first = _sha(origin, "HEAD~1")
        assert cache.read_file(str(origin), first, "src/App.java") == "class App {}\n"
        head = _sha(origin, "HEAD")
        assert cache.read_file(str(origin), head, "src/App.java") == "class App { int x; }\n"

    def test_missing_path_raises(self, cache: RepoCache, origin: Path) -> None:
        cache.ensure_mirror(str(origin))
        with pytest.raises(GitError):
            cache.read_file(str(origin), _sha(origin, "HEAD"), "nope/missing.java")
