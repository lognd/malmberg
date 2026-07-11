"""Tests for malmberg_server.cloud: sync, verification, guarded deletion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import pytest
from typani.result import Err, Ok, Result

from malmberg_server.app.config import ServerConfig
from malmberg_server.cloud.base import CloudError, CloudProvider, RemotePhoto
from malmberg_server.cloud.sync import (
    CloudSyncEngine,
    CloudSyncState,
    cloud_state_path,
    state_key,
)
from malmberg_server.cloud.verify_and_delete import (
    audit_log_path,
    delete_verified,
    dry_run_deletable,
)
from malmberg_server.ingest.store import MediaStore

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class FakeProvider(CloudProvider):
    """In-memory CloudProvider serving known bytes; records delete calls."""

    def __init__(
        self,
        name: str,
        photos: dict[str, bytes],
        *,
        configured: bool = True,
        can_delete: bool = True,
    ) -> None:
        self._name = name
        self._photos = photos
        self._configured = configured
        self._can_delete = can_delete
        self.deleted: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def is_configured(self) -> bool:
        return self._configured

    def list_remote(self) -> Result[list[RemotePhoto], CloudError]:
        return Ok(
            [RemotePhoto(remote_id=rid, filename=f"{rid}.jpg") for rid in self._photos]
        )

    def download(self, remote_id: str) -> Result[bytes, CloudError]:
        data = self._photos.get(remote_id)
        if data is None:
            return Err(CloudError.NotFound)
        return Ok(data)

    def delete(self, remote_id: str) -> Result[None, CloudError]:
        if not self._can_delete:
            return Err(CloudError.Unsupported)
        self.deleted.append(remote_id)
        return Ok(None)


def _engine(
    tmp_path: Path, provider: CloudProvider, store: Optional[MediaStore] = None
) -> CloudSyncEngine:
    """Build a CloudSyncEngine rooted at tmp_path with one provider."""
    fs_root = tmp_path
    cfg = ServerConfig(fs_root=fs_root, cloud_delete_cap=3)
    store = store if store is not None else MediaStore()
    return CloudSyncEngine(
        cfg,
        store,
        [provider],
        media_root=fs_root / "media",
        upload_root=fs_root / ".upload" / "cloud",
        state_path=cloud_state_path(fs_root),
        index_path=fs_root / "logs" / "media-index.jsonl",
    )


# ---------------------------------------------------------------------------
# Sync + idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_ingests_and_is_idempotent(tmp_path: Path) -> None:
    """First sync ingests new photos; a second sync adds nothing new."""
    provider = FakeProvider("fake", {"a": b"photo-a-bytes", "b": b"photo-b-bytes"})
    engine = _engine(tmp_path, provider)

    r1 = await engine.sync_provider(provider)
    assert r1.discovered == 2
    assert r1.downloaded == 2
    assert r1.verified == 2
    assert len(engine._store) == 2

    r2 = await engine.sync_provider(provider)
    assert r2.downloaded == 0
    assert r2.skipped_existing == 2
    assert len(engine._store) == 2


@pytest.mark.asyncio
async def test_verification_only_on_sha_match(tmp_path: Path) -> None:
    """A record is verified only when the local file's sha256 matches."""
    provider = FakeProvider("fake", {"a": b"content-a"})
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)

    record = engine.get_record("fake", "a")
    assert record is not None
    assert record.verified is True
    assert engine.verify_record(record) is True

    # Corrupt the stored digest so the on-disk file no longer matches.
    record.sha256 = hashlib.sha256(b"different").hexdigest()
    assert engine.verify_record(record) is False


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_lists_only_verified_and_deletes_nothing(
    tmp_path: Path,
) -> None:
    """dry_run_deletable lists verified items and never calls provider.delete."""
    provider = FakeProvider("fake", {"a": b"aa", "b": b"bb"})
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)

    entries = dry_run_deletable(engine, provider)
    assert len(entries) == 2
    assert provider.deleted == []
    # State unchanged: nothing stamped deleted.
    assert all(r.deleted_from_cloud_at is None for r in engine.records_for("fake"))


# ---------------------------------------------------------------------------
# Guarded delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_refuses_without_confirm(tmp_path: Path) -> None:
    """confirm=False is a dry run: deletes nothing, touches no provider."""
    provider = FakeProvider("fake", {"a": b"aa"})
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)

    result = await delete_verified(engine, provider, confirm=False)
    assert result.is_ok
    report = result.danger_ok
    assert report.dry_run is True
    assert report.deleted == 0
    assert provider.deleted == []


@pytest.mark.asyncio
async def test_delete_skips_unverified(tmp_path: Path) -> None:
    """An item whose local copy no longer matches is never deleted."""
    provider = FakeProvider("fake", {"a": b"aa"})
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)

    # Break verification by trashing the local file on disk.
    record = engine.get_record("fake", "a")
    assert record is not None
    item = engine._store.get(record.local_item_id)
    (engine._media_root / item.server_path).unlink()

    result = await delete_verified(engine, provider, confirm=True)
    assert result.is_ok
    report = result.danger_ok
    # An item that fails verification is excluded from candidates entirely
    # (exclusion is the safe direction); it is never deleted.
    assert report.candidates == 0
    assert report.deleted == 0
    assert provider.deleted == []


@pytest.mark.asyncio
async def test_delete_respects_cap_and_writes_audit(tmp_path: Path) -> None:
    """Cap bounds deletions per run; one audit line is written per deletion."""
    photos = {f"p{i}": f"bytes-{i}".encode() for i in range(6)}
    provider = FakeProvider("fake", photos)
    engine = _engine(tmp_path, provider)  # cfg cloud_delete_cap = 3
    await engine.sync_provider(provider)

    assert len(dry_run_deletable(engine, provider)) == 6

    result = await delete_verified(engine, provider, confirm=True, cap=100)
    assert result.is_ok
    report = result.danger_ok
    assert report.deleted == 3  # capped by config
    assert report.capped is True
    assert len(provider.deleted) == 3

    log = audit_log_path(engine.config.fs_root)
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    deleted_lines = [ln for ln in lines if json.loads(ln)["action"] == "deleted"]
    assert len(deleted_lines) == 3
    intent_lines = [ln for ln in lines if json.loads(ln)["action"] == "intent"]
    assert len(intent_lines) == 3


@pytest.mark.asyncio
async def test_delete_unsupported_provider_never_fakes_success(
    tmp_path: Path,
) -> None:
    """A provider that cannot delete surfaces failure, not a fake success."""
    provider = FakeProvider("fake", {"a": b"aa"}, can_delete=False)
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)

    result = await delete_verified(engine, provider, confirm=True)
    assert result.is_ok
    report = result.danger_ok
    assert report.deleted == 0
    assert report.failed == 1
    record = engine.get_record("fake", "a")
    assert record.deleted_from_cloud_at is None


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_round_trips(tmp_path: Path) -> None:
    """Cloud state saves and reloads identically from cloud-state.json."""
    provider = FakeProvider("fake", {"a": b"aa", "b": b"bb"})
    engine = _engine(tmp_path, provider)
    await engine.sync_provider(provider)
    assert engine.save_state().is_ok

    fresh = _engine(tmp_path, provider, store=engine._store)
    loaded = fresh.load_state()
    assert loaded.is_ok
    assert loaded.danger_ok == 2
    assert fresh.get_record("fake", "a") is not None
    assert state_key("fake", "a") == "fake:a"


def test_status_reports_diagnostics(tmp_path: Path) -> None:
    """status() reports configured/tracked/verified/deleted per provider."""
    provider = FakeProvider("fake", {"a": b"aa"})
    engine = _engine(tmp_path, provider)
    status = engine.status()
    assert len(status.providers) == 1
    block = status.providers[0]
    assert block.name == "fake"
    assert block.configured is True
    assert block.tracked == 0


# ---------------------------------------------------------------------------
# Graceful degradation of optional deps
# ---------------------------------------------------------------------------


def test_icloud_degrades_without_pyicloud(tmp_path: Path, monkeypatch) -> None:
    """ICloudProvider.is_configured() is False and nothing raises w/o pyicloud."""
    import malmberg_server.cloud.icloud as icloud_mod

    monkeypatch.setattr(icloud_mod, "pyicloud", None)
    provider = icloud_mod.ICloudProvider("me@example.com", tmp_path / "sess")
    assert provider.is_configured() is False
    assert provider.list_remote().is_err
    assert provider.download("x").is_err
    assert provider.delete("x").is_err


def test_google_degrades_without_lib(tmp_path: Path, monkeypatch) -> None:
    """GooglePhotosProvider degrades gracefully when google auth is absent."""
    import malmberg_server.cloud.google_photos as gp_mod

    monkeypatch.setattr(gp_mod, "_GOOGLE_AVAILABLE", False)
    provider = gp_mod.GooglePhotosProvider(
        tmp_path / "secret.json", tmp_path / "token.json"
    )
    assert provider.is_configured() is False
    assert provider.list_remote().is_err
    # delete is always Unsupported regardless of availability.
    assert provider.delete("x").is_err
    assert provider.delete("x").danger_err is CloudError.Unsupported


def test_state_model_default() -> None:
    """An empty CloudSyncState is a valid, empty document."""
    st = CloudSyncState()
    assert st.records == {}
    assert st.provider_meta == {}


# ---------------------------------------------------------------------------
# Layering invariant: display never imports server cloud
# ---------------------------------------------------------------------------


def test_display_never_imports_server_cloud() -> None:
    """No malmberg_display source references malmberg_server.cloud."""
    import malmberg_display

    root = Path(malmberg_display.__file__).parent
    for py in root.rglob("*.py"):
        text = py.read_text()
        assert "malmberg_server.cloud" not in text, f"{py} references server cloud"
