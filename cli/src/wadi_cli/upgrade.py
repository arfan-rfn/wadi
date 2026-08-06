"""Self-upgrade support (§15 "Versioning & upgrade").

One version spans the whole release set: CLI `x.y.z` embeds a compose file
whose images are tagged `x.y.z` (§13). Upgrading is therefore *upgrade the
package* — which brings the new pinned tags with it — and then let `wadi up`
pull them. This module owns the two things that requires: discovering the
latest published version, and discovering the command that upgrades the
package through whichever channel installed it.

The channel is detected rather than configured: a user who installed via
Homebrew must not be handed a `uv tool upgrade` line that would silently
create a second, shadowing installation.
"""

import shutil
import subprocess

PACKAGE_NAME = "wadi-sh"
"""The PyPI distribution (§13 naming) — note the command is plain `wadi`."""

HOMEBREW_FORMULA = "wadi-sh/tap/wadi"

PYPI_RELEASE_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


class UpgradeError(RuntimeError):
    """The upgrade could not be planned or carried out."""


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a release version into a comparable tuple.

    Only the numeric release segment is compared. Anything trailing (`1.2.0rc1`,
    `+local`) sorts with its release, which is the right call here: the CLI is
    published as plain semver, and a pre-release should never be reported as an
    upgrade over the final of the same number.
    """
    parts: list[int] = []
    for segment in value.strip().split("."):
        digits = ""
        for char in segment:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        raise UpgradeError(f"unparseable version {value!r}")
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """True when `candidate` is a strictly later release than `current`."""
    return parse_version(candidate) > parse_version(current)


def latest_released_version(*, timeout: float = 10.0) -> str:
    """The newest `wadi-sh` version on PyPI — the canonical channel (§13)."""
    import httpx

    try:
        response = httpx.get(PYPI_RELEASE_URL, timeout=timeout)
        response.raise_for_status()
        version = response.json()["info"]["version"]
    except httpx.HTTPError as exc:
        raise UpgradeError(f"could not reach PyPI to check for updates: {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise UpgradeError("PyPI returned an unreadable release document") from exc
    if not isinstance(version, str):
        raise UpgradeError("PyPI returned an unreadable release document")
    return version


def installed_via(probe: list[str], needle: str) -> bool:
    """True when `probe`'s package listing contains `needle` as a whole name.

    Whole-token, not substring: Homebrew is probed for the bare name `wadi`,
    and a substring test matches unrelated formulae that merely end in it
    (`font-noto-sans-khudawadi` is a real one), which would route the user to
    a `brew upgrade` of a tap they never installed from.
    """
    try:
        result = subprocess.run(probe, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and needle in result.stdout.split()


def upgrade_command() -> list[str] | None:
    """The command that upgrades this installation, or None if undetectable.

    Probed in the order the channels are documented (§13): uv is the lead
    install path, pipx the documented alternative, Homebrew the macOS
    convenience wrapper. None means "tell the user what to run" — guessing
    would risk installing a second copy alongside the real one.
    """
    if shutil.which("uv") and installed_via(["uv", "tool", "list"], PACKAGE_NAME):
        # `--reinstall-package` implies `--refresh-package`, which is the point:
        # uv resolves from a CACHED package index, and the moment someone runs
        # `wadi upgrade` is exactly when that cache is most likely stale — a
        # release minutes old. Without it uv reads its cached index, sees the
        # version already installed, prints "Nothing to upgrade" and exits 0
        # while PyPI (which this CLI queries directly) has the new one.
        # Measured: cached resolve gave 0.6.0 while --refresh gave 0.7.0 for the
        # same PyPI state. Scoped to this package rather than `--refresh` so an
        # upgrade never invalidates the whole cache.
        return ["uv", "tool", "upgrade", PACKAGE_NAME, "--reinstall-package", PACKAGE_NAME]
    if shutil.which("pipx") and installed_via(["pipx", "list", "--short"], PACKAGE_NAME):
        return ["pipx", "upgrade", PACKAGE_NAME]
    if shutil.which("brew") and installed_via(["brew", "list", "--formula"], "wadi"):
        return ["brew", "upgrade", HOMEBREW_FORMULA]
    return None


def run_upgrade(command: list[str]) -> None:
    """Run the channel's upgrade command, surfacing its output to the user.

    A zero exit says the installer did not FAIL. It does not say it upgraded
    anything — `uv tool upgrade` prints "Nothing to upgrade" and exits 0 when
    its cached index shows nothing newer. Callers must verify with
    :func:`installed_version` rather than trusting this returning.
    """
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise UpgradeError(f"'{' '.join(command)}' could not be run: {exc}") from exc
    if result.returncode != 0:
        raise UpgradeError(f"'{' '.join(command)}' exited with {result.returncode}")


def installed_version(*, timeout: float = 15.0) -> str | None:
    """The version the `wadi` on PATH reports NOW, or None if it cannot be read.

    This process cannot answer the question itself: `CLI_VERSION` was baked in
    at import, so after a successful upgrade the running CLI still reports the
    OLD number while a new one sits on disk. Asking the executable is also the
    only channel-agnostic check — parsing installer output would need a
    different rule for uv, pipx and Homebrew, and would break whenever any of
    them reworded a line.

    None means "could not determine", never "unchanged": a caller must treat it
    as unverified rather than as failure, because the upgrade may well have
    worked (§P10 — an unknown is not a negative).
    """
    executable = shutil.which("wadi")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # `wadi --version` prints "wadi X.Y.Z"; take the last whitespace-separated
    # token so a reworded prefix does not break the read.
    tokens = result.stdout.strip().split()
    if not tokens:
        return None
    candidate = tokens[-1].lstrip("v")
    try:
        parse_version(candidate)
    except UpgradeError:
        return None
    return candidate
