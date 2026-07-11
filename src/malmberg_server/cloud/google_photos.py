"""Google Photos provider -- READ-SCOPED AND APP-DATA-ONLY SINCE ~MARCH 2025.

IMPORTANT SCOPE RESTRICTION: as of the Google Photos Library API policy change
enforced around March 31, 2025, third-party apps can only list/download items
THAT THE APP ITSELF UPLOADED (photoslibrary.readonly and full-library access
were removed for external apps). This provider therefore CANNOT see the user's
full library, and the Library API has never exposed a delete operation at all
-- delete() ALWAYS returns Err(CloudError.Unsupported) and must never
fabricate success. Practical consequence: Google Photos sync is useful only
for app-uploaded content unless Google restores broader scopes; cleanup of the
real library must happen manually in the Google Photos UI.

Install with the cloud-googlephotos extra: uv sync --extra cloud-googlephotos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typani.result import Err, Ok, Result

from malmberg_core.logging import get_logger
from malmberg_server.cloud.base import CloudError, CloudProvider, RemotePhoto

try:  # extra-optional dependency: degrade, never crash
    import google.auth.transport.requests as _google_requests
    from google.oauth2.credentials import Credentials as _GoogleCredentials

    _GOOGLE_AVAILABLE = True
except ImportError:
    _google_requests = None
    _GoogleCredentials = None
    _GOOGLE_AVAILABLE = False

_log = get_logger(__name__)

_LIST_URL = "https://photoslibrary.googleapis.com/v1/mediaItems"
_ITEM_URL = "https://photoslibrary.googleapis.com/v1/mediaItems/{id}"


class GooglePhotosProvider(CloudProvider):
    """Pulls app-uploaded items from Google Photos via the Library API.

    is_configured() is False (and every method returns Err(NotConfigured))
    when the google auth extras are not installed or the token file is
    missing. The OAuth consent flow is established out-of-band
    (scripts/cloud_setup_google.py); this provider only refreshes an existing
    token.
    """

    def __init__(self, client_secrets_path: Path, token_path: Path) -> None:
        """Remember credential file locations; performs no network I/O."""
        self._client_secrets_path = client_secrets_path
        self._token_path = token_path

    @property
    def name(self) -> str:
        """Return 'google_photos'."""
        return "google_photos"

    def is_configured(self) -> bool:
        """True if google auth libs imported and the token file exists."""
        if not _GOOGLE_AVAILABLE:
            return False
        return self._token_path.is_file()

    def list_remote(self) -> Result[list[RemotePhoto], CloudError]:
        """List items visible to this app (app-uploaded only; see module doc)."""
        creds = self._credentials()
        if creds.is_err:
            return Err(creds.danger_err)
        session = _google_requests.AuthorizedSession(creds.danger_ok)
        photos: list[RemotePhoto] = []
        page_token = None
        try:
            while True:
                params = {"pageSize": 100}
                if page_token:
                    params["pageToken"] = page_token
                resp = session.get(_LIST_URL, params=params, timeout=30)
                if resp.status_code == 429:
                    return Err(CloudError.RateLimited)
                if resp.status_code in (401, 403):
                    return Err(CloudError.AuthError)
                if resp.status_code != 200:
                    return Err(CloudError.NetworkError)
                body = resp.json()
                for item in body.get("mediaItems", []):
                    photos.append(
                        RemotePhoto(
                            remote_id=item["id"],
                            filename=item.get("filename", item["id"]),
                        )
                    )
                page_token = body.get("nextPageToken")
                if not page_token:
                    break
            _log.info("Google Photos: listed %d app-visible items", len(photos))
            return Ok(photos)
        except Exception as exc:
            _log.warning("Google Photos list_remote failed: %s", exc)
            return Err(CloudError.NetworkError)

    def download(self, remote_id: str) -> Result[bytes, CloudError]:
        """Download one media item's bytes via its baseUrl ('=d' original)."""
        creds = self._credentials()
        if creds.is_err:
            return Err(creds.danger_err)
        session = _google_requests.AuthorizedSession(creds.danger_ok)
        try:
            meta = session.get(_ITEM_URL.format(id=remote_id), timeout=30)
            if meta.status_code == 404:
                return Err(CloudError.NotFound)
            if meta.status_code != 200:
                return Err(CloudError.NetworkError)
            base_url = meta.json().get("baseUrl")
            if not base_url:
                return Err(CloudError.NotFound)
            blob = session.get(base_url + "=d", timeout=60)
            if blob.status_code != 200:
                return Err(CloudError.NetworkError)
            return Ok(blob.content)
        except Exception as exc:
            _log.warning("Google Photos download of %s failed: %s", remote_id, exc)
            return Err(CloudError.NetworkError)

    def delete(self, remote_id: str) -> Result[None, CloudError]:
        """Always Err(Unsupported): the Library API has no delete (see module doc)."""
        _log.warning(
            "Google Photos delete requested for %s but the Library API cannot "
            "delete media items; refusing to fabricate success",
            remote_id,
        )
        return Err(CloudError.Unsupported)

    def _credentials(self) -> Result[Any, CloudError]:
        """Load and refresh OAuth credentials from token_path (lazy)."""
        if not self.is_configured():
            return Err(CloudError.NotConfigured)
        try:
            with open(self._token_path) as f:
                data = json.load(f)
            creds = _GoogleCredentials.from_authorized_user_info(data)
            if not creds.valid and creds.refresh_token:
                creds.refresh(_google_requests.Request())
                with open(self._token_path, "w") as f:
                    f.write(creds.to_json())
            if not creds.valid:
                return Err(CloudError.AuthError)
            return Ok(creds)
        except Exception as exc:
            _log.warning("Google Photos credential load failed: %s", exc)
            return Err(CloudError.AuthError)
