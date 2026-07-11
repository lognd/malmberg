"""CloudSyncEngine: pull remote photos into local storage and track them.

Holds the per-remote-item state index (remote_id -> CloudSyncRecord) persisted
as one JSON document at fs_root/logs/cloud-state.json. Downloads go through
ingest_bytes (ingest/upload.py) so cloud items obey the exact same dedup, EXIF,
and YYYY/MM/DD layout rules as user uploads. Provider calls are blocking and
are run in an executor; run_cloud_sync_worker mirrors faces/worker.py's
forever-loop background-task pattern.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.app.config import ServerConfig
from malmberg_server.cloud.base import CloudError, CloudProvider, RemotePhoto
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.store import MediaStore
from malmberg_server.ingest.upload import ingest_bytes

_log = get_logger(__name__)

_POLL_MIN_INTERVAL_S = 60.0
"""Floor on the auto-sync sleep, guarding against a misconfigured interval."""


def cloud_state_path(fs_root: Path) -> Path:
    """Return fs_root/logs/cloud-state.json -- the one home for this path rule."""
    return fs_root / "logs" / "cloud-state.json"


def state_key(provider: str, remote_id: str) -> str:
    """Return '<provider>:<remote_id>', the CloudSyncState.records key."""
    return f"{provider}:{remote_id}"


class CloudSyncRecord(BaseModel):
    """Tracking state for one remote item across sync, verify, and delete."""

    provider: str
    remote_id: str
    local_item_id: Optional[str] = None
    """MediaItem.id of the local copy; None until ingested."""
    sha256: Optional[str] = None
    """Digest of the downloaded bytes; the verification anchor."""
    verified: bool = False
    """Cached result of the last verify pass -- display only. delete_verified
    NEVER trusts this; it re-verifies from disk."""
    synced_at: Optional[datetime] = None
    deleted_from_cloud_at: Optional[datetime] = None


class ProviderSyncMeta(BaseModel):
    """Last-run bookkeeping for one provider, for /cloud/status."""

    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None


class CloudSyncState(BaseModel):
    """Whole-file persisted sync state (atomic tmp+replace on save)."""

    records: dict[str, CloudSyncRecord] = Field(default_factory=dict)
    """Keyed by state_key(provider, remote_id)."""
    provider_meta: dict[str, ProviderSyncMeta] = Field(default_factory=dict)


class SyncResult(BaseModel):
    """Outcome report of one sync_provider run."""

    provider: str
    discovered: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    """Already tracked, or dedup-matched an existing local item."""
    verified: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_s: float = 0.0


class ProviderStatus(BaseModel):
    """Per-provider block of the /cloud/status response."""

    name: str
    enabled: bool
    configured: bool
    tracked: int
    verified: int
    deleted_from_cloud: int
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None


class CloudStatus(BaseModel):
    """Response model for GET /cloud/status."""

    providers: list[ProviderStatus]


class CloudSyncRequest(BaseModel):
    """Request body for POST /cloud/sync."""

    provider: Optional[str] = None
    """Provider name to sync, or None for all registered providers."""


class CloudSyncAck(BaseModel):
    """Response for POST /cloud/sync -- the sync runs as a background task."""

    status: Literal["started", "no_providers", "unknown_provider"]
    providers: list[str] = Field(default_factory=list)


class CloudSyncEngine:
    """Coordinates providers, the media store, and the persisted sync state.

    Single-writer: only the cloud sync worker task and /cloud/* handlers touch
    this engine, all on the server's one event loop; blocking provider and
    hashing work happens in executors. Persists the media index (index_path)
    and the sync state (state_path) after every sweep that changed something.
    """

    def __init__(
        self,
        config: ServerConfig,
        store: MediaStore,
        providers: list[CloudProvider],
        *,
        media_root: Path,
        upload_root: Path,
        state_path: Path,
        index_path: Path,
    ) -> None:
        """Wire dependencies; performs no I/O (call load_state after)."""
        self._config = config
        self._store = store
        self._providers = providers
        self._media_root = media_root
        self._upload_root = upload_root
        self._state_path = state_path
        self._index_path = index_path
        self._state = CloudSyncState()

    @property
    def providers(self) -> list[CloudProvider]:
        """Return the registered providers (enabled + constructible)."""
        return self._providers

    @property
    def config(self) -> ServerConfig:
        """Return the ServerConfig driving delete caps and enable flags."""
        return self._config

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def load_state(self) -> Result[int, CloudError]:
        """Load state_path into memory; Ok(n records). Missing file -> Ok(0)."""
        if not self._state_path.is_file():
            return Ok(0)
        try:
            self._state = CloudSyncState.model_validate_json(
                self._state_path.read_text()
            )
            _log.info(
                "Loaded %d cloud sync records from %s",
                len(self._state.records),
                self._state_path,
            )
            return Ok(len(self._state.records))
        except Exception as exc:
            _log.error("Failed to load cloud state from %s: %s", self._state_path, exc)
            return Err(CloudError.StateError)

    def save_state(self) -> Result[None, CloudError]:
        """Atomically write the state document to state_path (tmp + replace)."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(self._state.model_dump_json())
            tmp.replace(self._state_path)
            return Ok(None)
        except Exception as exc:
            _log.error("Failed to save cloud state to %s: %s", self._state_path, exc)
            return Err(CloudError.StateError)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    async def sync_provider(self, provider: CloudProvider) -> SyncResult:
        """One pull pass: list remote, download+ingest new items, verify, persist.

        Per-item failures are recorded in the result's errors list and never
        abort the pass. Err(NotConfigured) from the provider yields an empty
        result with one error string. Blocking provider calls and hashing run
        in an executor.
        """
        started = time.monotonic()
        result = SyncResult(provider=provider.name)
        loop = asyncio.get_running_loop()

        if not provider.is_configured():
            result.errors.append("provider not configured")
            self._set_meta(provider.name, error="not configured")
            result.duration_s = time.monotonic() - started
            return result

        listed = await loop.run_in_executor(None, provider.list_remote)
        if listed.is_err:
            msg = str(listed.danger_err)
            _log.warning(
                "Cloud sync: list_remote failed for %s: %s", provider.name, msg
            )
            result.errors.append(f"list_remote: {msg}")
            self._set_meta(provider.name, error=msg)
            result.duration_s = time.monotonic() - started
            return result

        remote = listed.danger_ok
        result.discovered = len(remote)
        changed = False
        for photo in remote:
            key = state_key(provider.name, photo.remote_id)
            existing = self._state.records.get(key)
            if existing is not None and existing.local_item_id is not None:
                result.skipped_existing += 1
                if existing.verified:
                    result.verified += 1
                continue
            try:
                outcome = await loop.run_in_executor(
                    None, self._download_and_ingest, provider, photo
                )
            except Exception as exc:  # defensive: helper is Result-typed
                _log.warning(
                    "Cloud sync: unexpected failure on %s/%s",
                    provider.name,
                    photo.remote_id,
                    exc_info=True,
                )
                result.failed += 1
                result.errors.append(f"{photo.remote_id}: {exc}")
                continue
            if outcome.is_err:
                result.failed += 1
                result.errors.append(f"{photo.remote_id}: {outcome.danger_err}")
                continue
            record = outcome.danger_ok
            self._state.records[key] = record
            changed = True
            if record.local_item_id is not None and existing is None:
                result.downloaded += 1
            if record.verified:
                result.verified += 1

        self._set_meta(
            provider.name,
            error=None,
            synced_at=datetime.now(timezone.utc),
        )
        if changed:
            self._persist_after_sweep()
        else:
            self.save_state()
        result.duration_s = time.monotonic() - started
        _log.info(
            "Cloud sync %s: discovered=%d downloaded=%d skipped=%d "
            "verified=%d failed=%d",
            provider.name,
            result.discovered,
            result.downloaded,
            result.skipped_existing,
            result.verified,
            result.failed,
        )
        return result

    async def sync_all(self) -> list[SyncResult]:
        """Run sync_provider for every registered provider, sequentially."""
        results: list[SyncResult] = []
        for provider in self._providers:
            results.append(await self.sync_provider(provider))
        return results

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def status(self) -> CloudStatus:
        """Summarize per-provider tracked/verified/deleted counts and last run."""
        enabled = self._enabled_names()
        blocks: list[ProviderStatus] = []
        for provider in self._providers:
            recs = self.records_for(provider.name)
            meta = self._state.provider_meta.get(provider.name, ProviderSyncMeta())
            blocks.append(
                ProviderStatus(
                    name=provider.name,
                    enabled=provider.name in enabled,
                    configured=provider.is_configured(),
                    tracked=len(recs),
                    verified=sum(1 for r in recs if r.verified),
                    deleted_from_cloud=sum(
                        1 for r in recs if r.deleted_from_cloud_at is not None
                    ),
                    last_sync_at=meta.last_sync_at,
                    last_error=meta.last_error,
                )
            )
        return CloudStatus(providers=blocks)

    def provider_by_name(self, name: str) -> Optional[CloudProvider]:
        """Return the registered provider with *name*, or None."""
        for provider in self._providers:
            if provider.name == name:
                return provider
        return None

    def records_for(self, provider_name: str) -> list[CloudSyncRecord]:
        """Return every tracked record belonging to *provider_name*."""
        return [r for r in self._state.records.values() if r.provider == provider_name]

    def get_record(
        self, provider_name: str, remote_id: str
    ) -> Optional[CloudSyncRecord]:
        """Return one tracked record, or None if unknown."""
        return self._state.records.get(state_key(provider_name, remote_id))

    # ------------------------------------------------------------------
    # Mutations used by verify_and_delete
    # ------------------------------------------------------------------

    def mark_deleted(
        self, provider_name: str, remote_id: str
    ) -> Result[None, CloudError]:
        """Stamp deleted_from_cloud_at on a record and save state immediately."""
        key = state_key(provider_name, remote_id)
        record = self._state.records.get(key)
        if record is None:
            return Err(CloudError.NotFound)
        record.deleted_from_cloud_at = datetime.now(timezone.utc)
        self._state.records[key] = record
        return self.save_state()

    def verify_record(self, record: CloudSyncRecord) -> bool:
        """Re-hash the local file from disk NOW and compare to record.sha256.

        The single verification rule: the local item must exist in the store,
        be un-trashed, its file present under media_root, and its streamed
        SHA-256 equal record.sha256. Blocking (reads the whole file); callers
        on the event loop must use an executor.
        """
        if record.sha256 is None or record.local_item_id is None:
            return False
        item = self._store.get(record.local_item_id)
        if item is None or item.trashed_at is not None:
            return False
        path = self._media_root / item.server_path
        if not path.is_file():
            return False
        try:
            sha = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            return sha.hexdigest() == record.sha256
        except OSError as exc:
            _log.warning("verify_record: cannot read %s: %s", path, exc)
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _download_and_ingest(
        self, provider: CloudProvider, photo: RemotePhoto
    ) -> Result[CloudSyncRecord, CloudError]:
        """Download one item and push it through ingest_bytes; build its record.

        IngestError.DuplicateFile is treated as an already-local item: the
        record is marked verified against the existing store copy, not failed.
        Runs blocking; called from an executor by sync_provider.
        """
        blob = provider.download(photo.remote_id)
        if blob.is_err:
            return Err(blob.danger_err)
        data = blob.danger_ok
        digest = hashlib.sha256(data).hexdigest()
        now = datetime.now(timezone.utc)

        ingested = ingest_bytes(
            data,
            photo.filename,
            self._store,
            self._media_root,
            self._upload_root,
            self._config.max_upload_mb * 1024 * 1024,
        )
        if ingested.is_ok:
            item = ingested.danger_ok
            record = CloudSyncRecord(
                provider=provider.name,
                remote_id=photo.remote_id,
                local_item_id=item.id,
                sha256=digest,
                verified=(item.meta.sha256 == digest),
                synced_at=now,
            )
            return Ok(record)

        err = ingested.danger_err
        if err == IngestError.DuplicateFile:
            local_id = self._store_id_for_digest(digest)
            record = CloudSyncRecord(
                provider=provider.name,
                remote_id=photo.remote_id,
                local_item_id=local_id,
                sha256=digest,
                verified=local_id is not None,
                synced_at=now,
            )
            return Ok(record)

        _log.warning(
            "Cloud sync: ingest of %s/%s failed: %s",
            provider.name,
            photo.remote_id,
            err,
        )
        return Err(CloudError.NetworkError)

    def _store_id_for_digest(self, digest: str) -> Optional[str]:
        """Return the local MediaItem id whose sha256 equals *digest*, if any."""
        for item_id in self._store.all_ids():
            item = self._store.get(item_id)
            if item is not None and item.meta.sha256 == digest:
                return item_id
        return None

    def _set_meta(
        self,
        provider_name: str,
        *,
        error: Optional[str] = None,
        synced_at: Optional[datetime] = None,
    ) -> None:
        """Update a provider's last-run bookkeeping in place."""
        meta = self._state.provider_meta.get(provider_name, ProviderSyncMeta())
        if synced_at is not None:
            meta.last_sync_at = synced_at
        meta.last_error = error
        self._state.provider_meta[provider_name] = meta

    def _enabled_names(self) -> set[str]:
        """Return provider names enabled via ServerConfig flags."""
        names: set[str] = set()
        if self._config.cloud_icloud_enabled:
            names.add("icloud")
        if self._config.cloud_google_photos_enabled:
            names.add("google_photos")
        return names

    def _persist_after_sweep(self) -> None:
        """Best-effort save of media index and sync state, logging failures."""
        if self._store.save_to_disk(self._index_path).is_err:
            _log.error("Cloud sync: failed to persist media index")
        if self.save_state().is_err:
            _log.error("Cloud sync: failed to persist cloud state")


async def run_cloud_sync_worker(
    engine: CloudSyncEngine,
    interval_s: float,
) -> None:
    """Forever: sync_all, persist, sleep interval_s; mirrors run_face_worker.

    Each sweep is wrapped in try/except so one provider outage cannot kill the
    loop; asyncio.CancelledError is re-raised for clean server shutdown. This
    worker only ever PULLS -- deletion happens exclusively through the explicit
    POST /cloud/delete path in verify_and_delete.
    """
    sleep_s = max(interval_s, _POLL_MIN_INTERVAL_S)
    enabled = engine._enabled_names()
    _log.info(
        "Cloud sync worker started (interval %.0fs, providers=%s)",
        sleep_s,
        sorted(enabled),
    )
    while True:
        try:
            active = [
                p for p in engine.providers if p.name in enabled and p.is_configured()
            ]
            for p in engine.providers:
                if p.name not in enabled:
                    _log.info("Cloud sync: skipping %s (disabled)", p.name)
                elif not p.is_configured():
                    _log.info("Cloud sync: skipping %s (not configured)", p.name)
            for provider in active:
                await engine.sync_provider(provider)
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            _log.info("Cloud sync worker stopping")
            raise
        except Exception:
            _log.warning("Cloud sync worker sweep failed unexpectedly", exc_info=True)
            await asyncio.sleep(sleep_s)
