"""Collect build/runtime version information for the ``/version`` endpoint.

Everything here is best-effort telemetry: a missing tool (no git checkout, ZFS
absent) yields ``None`` for that field rather than an error, so the endpoint
always returns a complete, serialisable object.
"""

from __future__ import annotations

import platform
import subprocess
from importlib import metadata
from pathlib import Path

from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.hal.detect import get_hardware_profile
from malmberg_core.logging import get_logger

_log = get_logger(__name__)

# Dependency distributions worth surfacing next to our own version.
_TRACKED_PACKAGES = ("fastapi", "uvicorn", "pydantic", "pillow")


class VersionInfo(BaseModel):
    """Response body for GET /version."""

    malmberg_version: str
    git_commit: str | None
    git_commit_short: str | None
    git_branch: str | None
    git_dirty: bool | None
    python_version: str
    platform: str
    hardware_profile: str
    openzfs_version: str | None
    packages: dict[str, str]


def collect_version_info() -> VersionInfo:
    """Gather version details from the package, git checkout, and OS."""
    repo = _repo_dir()
    commit = _git(repo, "rev-parse", "HEAD")
    return VersionInfo(
        malmberg_version=__version__,
        git_commit=commit,
        git_commit_short=commit[:12] if commit else None,
        git_branch=_git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        git_dirty=_git_dirty(repo),
        python_version=platform.python_version(),
        platform=platform.platform(),
        hardware_profile=get_hardware_profile().name,
        openzfs_version=_openzfs_version(),
        packages=_package_versions(),
    )


# ---------------------------------------------------------------------------
# Helpers (all best-effort; return None on failure)
# ---------------------------------------------------------------------------


def _repo_dir() -> Path | None:
    """Return the git checkout containing this package, if any."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _git(repo: Path | None, *args: str) -> str | None:
    """Run a read-only git command in *repo*; return stripped stdout or None."""
    if repo is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_dirty(repo: Path | None) -> bool | None:
    """Return True if the checkout has uncommitted changes, None if unknown.

    Runs git directly rather than via ``_git`` because empty output here is a
    meaningful result (a clean tree), not a failure.
    """
    if repo is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() != ""


def _openzfs_version() -> str | None:
    """Return the loaded OpenZFS kernel-module version, if present."""
    sysfs = Path("/sys/module/zfs/version")
    try:
        if sysfs.is_file():
            return sysfs.read_text().strip()
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["zfs", "version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _package_versions() -> dict[str, str]:
    """Return installed versions of the tracked dependency distributions."""
    versions: dict[str, str] = {}
    for name in _TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions
