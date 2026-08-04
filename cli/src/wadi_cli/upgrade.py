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
        return ["uv", "tool", "upgrade", PACKAGE_NAME]
    if shutil.which("pipx") and installed_via(["pipx", "list", "--short"], PACKAGE_NAME):
        return ["pipx", "upgrade", PACKAGE_NAME]
    if shutil.which("brew") and installed_via(["brew", "list", "--formula"], "wadi"):
        return ["brew", "upgrade", HOMEBREW_FORMULA]
    return None


def run_upgrade(command: list[str]) -> None:
    """Run the channel's upgrade command, surfacing its output to the user."""
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise UpgradeError(f"'{' '.join(command)}' could not be run: {exc}") from exc
    if result.returncode != 0:
        raise UpgradeError(f"'{' '.join(command)}' exited with {result.returncode}")
