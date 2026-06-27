"""ZFS subprocess wrappers -- all operations return Result, never raise."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.backup.errors import BackupError

_log = get_logger(__name__)


def _run(*args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
    )


def snapshot(dataset: str) -> Result[str, BackupError]:
    """Create a ZFS snapshot named ``<dataset>@malmberg-<utc-timestamp>``.

    Returns Ok(snapshot_name) on success.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{dataset}@malmberg-{ts}"
    proc = _run("zfs", "snapshot", name)
    if proc.returncode != 0:
        _log.error("zfs snapshot %s failed: %s", name, proc.stderr.strip())
        return Err(BackupError.CommandFailed)
    _log.info("Created snapshot %s", name)
    return Ok(name)


def list_snapshots(dataset: str) -> Result[list[str], BackupError]:
    """Return all snapshot names for *dataset*, oldest first."""
    proc = _run("zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-r", dataset)
    if proc.returncode != 0:
        _log.error("zfs list snapshots for %s failed: %s", dataset, proc.stderr.strip())
        return Err(BackupError.CommandFailed)
    names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    # Filter to snapshots that belong to this dataset specifically (not children).
    prefix = f"{dataset}@"
    own = [n for n in names if n.startswith(prefix)]
    return Ok(own)


def delete_snapshot(name: str) -> Result[None, BackupError]:
    """Destroy the snapshot *name*.

    Returns Err(NotFound) if the snapshot does not exist.
    """
    # Check existence first so we can return a typed error.
    check = _run("zfs", "list", "-H", "-t", "snapshot", "-o", "name", name)
    if check.returncode != 0 or not check.stdout.strip():
        return Err(BackupError.NotFound)
    proc = _run("zfs", "destroy", name)
    if proc.returncode != 0:
        _log.error("zfs destroy %s failed: %s", name, proc.stderr.strip())
        return Err(BackupError.CommandFailed)
    _log.info("Deleted snapshot %s", name)
    return Ok(None)
