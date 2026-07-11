"""Verified-before-delete: the only code path allowed to delete cloud items.

Safety model (all four required, in order):
1. Re-verification at decision time -- every candidate is re-hashed from disk
   via engine.verify_record immediately before its remote delete; the cached
   'verified' flag in state is never trusted.
2. Explicit confirmation -- confirm=False runs the identical selection logic as
   a dry run and deletes nothing.
3. Hard cap -- at most min(cap, config.cloud_delete_cap) deletions per run.
4. Audit-before-action -- an 'intent' JSON line is appended to
   fs_root/logs/cloud-deletions.log BEFORE each provider.delete call, and an
   outcome line after; if the intent line cannot be written the run aborts
   (Err(AuditError)) without touching the provider.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.cloud.base import CloudError, CloudProvider
from malmberg_server.cloud.sync import CloudSyncEngine

_log = get_logger(__name__)


def audit_log_path(fs_root: Path) -> Path:
    """Return fs_root/logs/cloud-deletions.log -- the one home for this path rule."""
    return fs_root / "logs" / "cloud-deletions.log"


class DeletableEntry(BaseModel):
    """One remote item verified (just now) as safe to delete from the cloud."""

    provider: str
    remote_id: str
    filename: str
    local_item_id: str
    sha256: str
    synced_at: Optional[datetime] = None


class DeletablePage(BaseModel):
    """Response model for GET /cloud/deletable."""

    provider: str
    items: list[DeletableEntry]
    total: int


class CloudDeleteRequest(BaseModel):
    """Request body for POST /cloud/delete."""

    provider: str
    confirm: bool = False
    """False = dry run through the identical selection logic."""
    cap: Optional[int] = None
    """Per-run deletion cap; None uses config.cloud_delete_cap. The effective
    cap is min(cap, config.cloud_delete_cap) -- callers can lower, not raise."""


class DeleteReport(BaseModel):
    """Outcome of one delete_verified run (also the dry-run response)."""

    provider: str
    dry_run: bool
    candidates: int
    deleted: int = 0
    skipped_unverified: int = 0
    failed: int = 0
    capped: bool = False
    errors: list[str] = Field(default_factory=list)


class DeletionAuditRecord(BaseModel):
    """One JSON line in cloud-deletions.log; 'intent' precedes every attempt."""

    ts: datetime
    provider: str
    remote_id: str
    local_item_id: str
    sha256: str
    filename: str
    action: Literal["intent", "deleted", "failed"]
    detail: Optional[str] = None
    """Error variant name on 'failed'; None otherwise."""


def append_audit_line(
    log_path: Path,
    record: DeletionAuditRecord,
) -> Result[None, CloudError]:
    """Append one JSON line to the audit log (creating parents); flush to disk.

    Err(AuditError) on any I/O failure -- callers must abort deletion when this
    fails, never proceed unlogged.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(record.model_dump_json())
            f.write("\n")
            f.flush()
        return Ok(None)
    except OSError as exc:
        _log.error("Cannot write cloud deletion audit line to %s: %s", log_path, exc)
        return Err(CloudError.AuditError)


def dry_run_deletable(
    engine: CloudSyncEngine,
    provider: CloudProvider,
) -> list[DeletableEntry]:
    """Return provider records that pass engine.verify_record right now.

    Excludes records already stamped deleted_from_cloud_at. Blocking (hashes
    every candidate's file from disk); routes call it via an executor. Failing
    verification silently excludes an item -- this is a report, and exclusion
    is the safe direction.
    """
    entries: list[DeletableEntry] = []
    for record in engine.records_for(provider.name):
        if record.deleted_from_cloud_at is not None:
            continue
        if record.local_item_id is None or record.sha256 is None:
            continue
        if not engine.verify_record(record):
            continue
        filename = _filename_for(engine, record.local_item_id)
        entries.append(
            DeletableEntry(
                provider=record.provider,
                remote_id=record.remote_id,
                filename=filename,
                local_item_id=record.local_item_id,
                sha256=record.sha256,
                synced_at=record.synced_at,
            )
        )
    return entries


async def delete_verified(
    engine: CloudSyncEngine,
    provider: CloudProvider,
    *,
    confirm: bool,
    cap: int = 200,
) -> Result[DeleteReport, CloudError]:
    """Delete up to min(cap, config cap) re-verified items from the cloud.

    Err(NotConfigured) if the provider is unusable; Err(AuditError) aborts
    before any un-logged deletion. confirm=False returns a dry-run report.
    Per-item flow: re-verify from disk -> append 'intent' audit line ->
    provider.delete in executor -> append outcome line -> engine.mark_deleted.
    Providers that cannot delete (Google Photos) surface per-item
    Err(Unsupported) into the report's failed/errors -- never fake success.
    """
    if not provider.is_configured():
        return Err(CloudError.NotConfigured)

    loop = asyncio.get_running_loop()
    effective_cap = min(cap, engine.config.cloud_delete_cap)
    log_path = audit_log_path(engine.config.fs_root)

    candidates = await loop.run_in_executor(None, dry_run_deletable, engine, provider)
    report = DeleteReport(
        provider=provider.name,
        dry_run=not confirm,
        candidates=len(candidates),
    )

    if not confirm:
        return Ok(report)

    for entry in candidates:
        if report.deleted >= effective_cap:
            report.capped = True
            break

        record = engine.get_record(provider.name, entry.remote_id)
        if record is None or not engine.verify_record(record):
            # Re-verify at the moment of deletion; state may have shifted.
            report.skipped_unverified += 1
            continue

        intent = DeletionAuditRecord(
            ts=datetime.now(timezone.utc),
            provider=provider.name,
            remote_id=entry.remote_id,
            local_item_id=entry.local_item_id,
            sha256=entry.sha256,
            filename=entry.filename,
            action="intent",
        )
        logged = append_audit_line(log_path, intent)
        if logged.is_err:
            _log.error("Aborting cloud delete run: audit log unwritable")
            return Err(CloudError.AuditError)

        deleted = await loop.run_in_executor(None, provider.delete, entry.remote_id)
        if deleted.is_err:
            report.failed += 1
            report.errors.append(f"{entry.remote_id}: {deleted.danger_err}")
            append_audit_line(
                log_path,
                intent.model_copy(
                    update={
                        "ts": datetime.now(timezone.utc),
                        "action": "failed",
                        "detail": str(deleted.danger_err),
                    }
                ),
            )
            continue

        engine.mark_deleted(provider.name, entry.remote_id)
        report.deleted += 1
        append_audit_line(
            log_path,
            intent.model_copy(
                update={"ts": datetime.now(timezone.utc), "action": "deleted"}
            ),
        )

    _log.info(
        "Cloud delete %s: deleted=%d failed=%d skipped=%d capped=%s",
        provider.name,
        report.deleted,
        report.failed,
        report.skipped_unverified,
        report.capped,
    )
    return Ok(report)


def _filename_for(engine: CloudSyncEngine, local_item_id: str) -> str:
    """Best-effort filename lookup for an audit/report row."""
    item = engine._store.get(local_item_id)
    return item.filename if item is not None else local_item_id
