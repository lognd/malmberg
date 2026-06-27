"""Tests for malmberg_server.backup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from malmberg_server.backup.audit import AuditEntry, AuditLog
from malmberg_server.backup.errors import BackupError
from malmberg_server.backup.retention import compute_deletions

# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------


def test_retention_within_window() -> None:
    snaps = ["s1", "s2", "s3"]
    assert compute_deletions(snaps, n_keep=5) == []


def test_retention_keeps_newest() -> None:
    snaps = [f"snap-{i:03d}" for i in range(20)]
    deletions = compute_deletions(snaps, n_keep=5)
    newest = set(snaps[-5:])
    assert not (set(deletions) & newest), "Must not delete any of the n_keep newest"


def test_retention_deletes_some_old() -> None:
    # With 100 old snapshots and n_keep=5, probabilistic halving should delete most.
    snaps = [f"old-{i:04d}" for i in range(100)]
    deletions = compute_deletions(snaps, n_keep=5)
    assert len(deletions) > 50, (
        "Expected most old snapshots to be scheduled for deletion"
    )


def test_retention_deterministic() -> None:
    snaps = [f"snap-{i}" for i in range(30)]
    assert compute_deletions(snaps, 5) == compute_deletions(snaps, 5)


def test_retention_invalid_n_keep() -> None:
    with pytest.raises(ValueError):
        compute_deletions(["s1"], n_keep=0)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


def test_audit_log_append_and_read(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    entry = AuditEntry.make(
        "snapshot", dataset="pool/data", snapshot_name="pool/data@t1"
    )
    result = log.append(entry)
    assert result.is_ok

    read_result = log.read_all()
    assert read_result.is_ok
    entries = read_result.danger_ok
    assert len(entries) == 1
    assert entries[0].action == "snapshot"
    assert entries[0].dataset == "pool/data"


def test_audit_log_empty(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "nonexistent.jsonl")
    result = log.read_all()
    assert result.is_ok
    assert result.danger_ok == []


def test_audit_log_multiple_entries(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append(AuditEntry.make("delete", snapshot_name=f"snap-{i}"))
    result = log.read_all()
    assert result.is_ok
    assert len(result.danger_ok) == 3


# ---------------------------------------------------------------------------
# ZFS wrappers (subprocess mocked)
# ---------------------------------------------------------------------------


def _mock_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_zfs_snapshot_ok() -> None:
    from malmberg_server.backup.zfs import snapshot

    with patch("malmberg_server.backup.zfs._run", return_value=_mock_proc(0)):
        result = snapshot("pool/data")
    assert result.is_ok
    name = result.danger_ok
    assert name.startswith("pool/data@malmberg-")


def test_zfs_snapshot_fail() -> None:
    from malmberg_server.backup.zfs import snapshot

    with patch(
        "malmberg_server.backup.zfs._run", return_value=_mock_proc(1, stderr="err")
    ):
        result = snapshot("pool/data")
    assert result.is_err
    assert result.danger_err is BackupError.CommandFailed


def test_zfs_list_snapshots_ok() -> None:
    from malmberg_server.backup.zfs import list_snapshots

    stdout = "pool/data@snap1\npool/data@snap2\npool/data/child@snap3\n"
    with patch(
        "malmberg_server.backup.zfs._run", return_value=_mock_proc(0, stdout=stdout)
    ):
        result = list_snapshots("pool/data")
    assert result.is_ok
    snaps = result.danger_ok
    assert snaps == ["pool/data@snap1", "pool/data@snap2"]


def test_zfs_list_snapshots_fail() -> None:
    from malmberg_server.backup.zfs import list_snapshots

    with patch(
        "malmberg_server.backup.zfs._run",
        return_value=_mock_proc(1, stderr="no dataset"),
    ):
        result = list_snapshots("pool/data")
    assert result.is_err
    assert result.danger_err is BackupError.CommandFailed


def test_zfs_delete_snapshot_ok() -> None:
    from malmberg_server.backup.zfs import delete_snapshot

    def mock_run(*args):
        if "list" in args:
            return _mock_proc(0, stdout="pool/data@snap1\n")
        return _mock_proc(0)

    with patch("malmberg_server.backup.zfs._run", side_effect=mock_run):
        result = delete_snapshot("pool/data@snap1")
    assert result.is_ok


def test_zfs_delete_snapshot_not_found() -> None:
    from malmberg_server.backup.zfs import delete_snapshot

    with patch(
        "malmberg_server.backup.zfs._run", return_value=_mock_proc(0, stdout="")
    ):
        result = delete_snapshot("pool/data@missing")
    assert result.is_err
    assert result.danger_err is BackupError.NotFound
