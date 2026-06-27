"""Append-only audit log for backup operations (JSON-lines)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.backup.errors import BackupError

_log = get_logger(__name__)

Action = Literal["snapshot", "delete", "list", "error"]


class AuditEntry(BaseModel):
    """A single audit event recorded by the backup subsystem."""

    timestamp: str
    action: Action
    dataset: Optional[str] = None
    snapshot_name: Optional[str] = None
    detail: Optional[str] = None

    @classmethod
    def make(
        cls,
        action: Action,
        *,
        dataset: Optional[str] = None,
        snapshot_name: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> "AuditEntry":
        """Create an entry timestamped to the current UTC instant."""
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            dataset=dataset,
            snapshot_name=snapshot_name,
            detail=detail,
        )


class AuditLog:
    """Append-only JSON-lines audit log for backup operations.

    The log file is created (including parent dirs) on first write.
    Reads scan the whole file; for the expected scale (hundreds of entries
    per year) this is fast enough.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, entry: AuditEntry) -> Result[None, BackupError]:
        """Append *entry* to the log file."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a") as f:
                f.write(entry.model_dump_json())
                f.write("\n")
            return Ok(None)
        except OSError as exc:
            _log.error("Failed to write audit log %s: %s", self._path, exc)
            return Err(BackupError.IOError)

    def read_all(self) -> Result[list[AuditEntry], BackupError]:
        """Read and return all audit entries (oldest first)."""
        if not self._path.is_file():
            return Ok([])
        try:
            entries: list[AuditEntry] = []
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(AuditEntry.model_validate(json.loads(line)))
            return Ok(entries)
        except (OSError, ValueError) as exc:
            _log.error("Failed to read audit log %s: %s", self._path, exc)
            return Err(BackupError.IOError)
