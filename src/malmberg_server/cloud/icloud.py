"""iCloud Photos provider via pyicloud -- UNOFFICIAL, FRAGILE, BEST-EFFORT ONLY.

pyicloud reverse-engineers Apple's private web API: it is not sanctioned by
Apple, breaks without notice when Apple changes endpoints, and requires an
interactive 2FA/2SA handshake to establish a session (which then expires
periodically and must be re-established out-of-band -- see
docs/operations/cloud-sync.md). Treat every call as capable of failing at any
time; the sync engine and worker are built to tolerate that. Deletion moves
items to the iCloud "Recently Deleted" album (Apple retains them ~30 days), so
delete_verified's cloud-side effect is itself recoverable for a window.

Install with the cloud-icloud extra: uv sync --extra cloud-icloud.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.cloud.base import CloudError, CloudProvider, RemotePhoto

try:  # extra-optional dependency: degrade, never crash
    import pyicloud
except ImportError:
    pyicloud = None

_log = get_logger(__name__)

_PASSWORD_ENV = "MALMBERG_CLOUD_ICLOUD_PASSWORD"
"""Env var holding the app-specific password; never stored in config."""


class ICloudProvider(CloudProvider):
    """Pulls from the iCloud photo library through an existing pyicloud session.

    is_configured() is False (and every method returns Err(NotConfigured))
    when pyicloud is not installed, no username is set, or no cached session
    exists under session_dir -- this provider never initiates the interactive
    2FA flow itself.
    """

    def __init__(self, username: Optional[str], session_dir: Path) -> None:
        """Remember credentials location; performs no network I/O."""
        self._username = username
        self._session_dir = session_dir
        self._service: Optional[Any] = None

    @property
    def name(self) -> str:
        """Return 'icloud'."""
        return "icloud"

    def is_configured(self) -> bool:
        """True if pyicloud imported, username set, and a cached session exists."""
        if pyicloud is None:
            return False
        if not self._username:
            return False
        return self._session_dir.is_dir() and any(self._session_dir.iterdir())

    def list_remote(self) -> Result[list[RemotePhoto], CloudError]:
        """List the full photo library (blocking; may be slow on large libraries)."""
        svc = self._get_service()
        if svc.is_err:
            return Err(svc.danger_err)
        service = svc.danger_ok
        try:
            photos: list[RemotePhoto] = []
            for asset in service.photos.all:
                photos.append(
                    RemotePhoto(
                        remote_id=str(asset.id),
                        filename=asset.filename,
                        size_bytes=getattr(asset, "size", None),
                        created_at=getattr(asset, "created", None),
                    )
                )
            _log.info("iCloud: listed %d remote items", len(photos))
            return Ok(photos)
        except Exception as exc:  # pyicloud raises many undocumented errors
            _log.warning("iCloud list_remote failed: %s", exc)
            return Err(CloudError.NetworkError)

    def download(self, remote_id: str) -> Result[bytes, CloudError]:
        """Download one asset's original bytes."""
        asset = self._find_asset(remote_id)
        if asset.is_err:
            return Err(asset.danger_err)
        try:
            response = asset.danger_ok.download()
            return Ok(response.raw.read())
        except Exception as exc:
            _log.warning("iCloud download of %s failed: %s", remote_id, exc)
            return Err(CloudError.NetworkError)

    def delete(self, remote_id: str) -> Result[None, CloudError]:
        """Move one asset to iCloud's Recently Deleted (Apple keeps ~30 days)."""
        asset = self._find_asset(remote_id)
        if asset.is_err:
            return Err(asset.danger_err)
        try:
            asset.danger_ok.delete()
            _log.info("iCloud: deleted %s (moved to Recently Deleted)", remote_id)
            return Ok(None)
        except Exception as exc:
            _log.warning("iCloud delete of %s failed: %s", remote_id, exc)
            return Err(CloudError.NetworkError)

    def _get_service(self) -> Result[Any, CloudError]:
        """Return a live PyiCloudService, reusing the cached session (lazy)."""
        if not self.is_configured():
            return Err(CloudError.NotConfigured)
        if self._service is not None:
            return Ok(self._service)
        password = os.environ.get(_PASSWORD_ENV)
        try:
            service = pyicloud.PyiCloudService(
                self._username,
                password,
                cookie_directory=str(self._session_dir),
            )
            if service.requires_2fa or service.requires_2sa:
                _log.warning("iCloud session requires interactive 2FA; re-run setup")
                return Err(CloudError.AuthError)
            self._service = service
            return Ok(service)
        except Exception as exc:
            _log.warning("iCloud authentication failed: %s", exc)
            return Err(CloudError.AuthError)

    def _find_asset(self, remote_id: str) -> Result[Any, CloudError]:
        """Locate one asset by remote_id in the library (linear scan)."""
        svc = self._get_service()
        if svc.is_err:
            return Err(svc.danger_err)
        try:
            for asset in svc.danger_ok.photos.all:
                if str(asset.id) == remote_id:
                    return Ok(asset)
            return Err(CloudError.NotFound)
        except Exception as exc:
            _log.warning("iCloud lookup of %s failed: %s", remote_id, exc)
            return Err(CloudError.NetworkError)
