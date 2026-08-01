"""System / Snapshot — the registration and run-freezing models (§4, §7)."""

from pydantic import Field, field_validator

from wadi_contracts.base import WadiModel
from wadi_contracts.enums import SnapshotStatus
from wadi_contracts.timeutil import UtcDatetime, utc_now
from wadi_contracts.version import SCHEMA_VERSION


class RepoSource(WadiModel):
    """One repository of a system: a git URL or a local path (first-class, §7)."""

    source: str = Field(min_length=1, description="git URL (https/ssh/scp) or local path")
    branch: str | None = Field(
        default=None, description="Branch to track; None = the remote default branch"
    )
    cred_ref: str | None = Field(
        default=None, description="Opaque reference to stored credentials (never the secret)"
    )

    @property
    def is_local(self) -> bool:
        """Local-path sources have no scheme and no scp-style host prefix."""
        src = self.source
        return "://" not in src and not (":" in src.split("/", 1)[0] and "@" in src)


class System(WadiModel):
    """A registered analysis target — the only place repo topology exists (P3)."""

    schema_version: str = SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^sys_[0-9a-f]{16,32}$")
    name: str = Field(min_length=1, max_length=200)
    repos: list[RepoSource] = Field(min_length=1)
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @field_validator("repos")
    @classmethod
    def _no_duplicate_sources(cls, repos: list[RepoSource]) -> list[RepoSource]:
        seen: set[str] = set()
        for repo in repos:
            if repo.source in seen:
                raise ValueError(f"duplicate repo source: {repo.source!r}")
            seen.add(repo.source)
        return repos


class Snapshot(WadiModel):
    """One analysis run's frozen commit-set (§4). Immutable once created."""

    schema_version: str = SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^snap_[0-9a-f]{16,32}$")
    system_id: str = Field(min_length=1)
    commits: dict[str, str] = Field(
        min_length=1,
        description="Normalized repo source -> resolved commit SHA at kickoff",
    )
    status: SnapshotStatus = SnapshotStatus.PENDING
    created_at: UtcDatetime = Field(default_factory=utc_now)
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    error: str | None = None

    @field_validator("commits")
    @classmethod
    def _shas_look_like_shas(cls, commits: dict[str, str]) -> dict[str, str]:
        for repo, sha in commits.items():
            if not (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)):
                raise ValueError(f"commit for {repo!r} is not a full lowercase hex SHA: {sha!r}")
        return commits
