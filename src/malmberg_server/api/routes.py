"""FastAPI routes for the Server role."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.logging import get_logger
from malmberg_core.models import HidePolicy, MediaPage, Tag
from malmberg_core.networking import get_mac_address
from malmberg_server.api.web import DASHBOARD_PAGE_HTML, UPLOAD_PAGE_HTML
from malmberg_server.app.config import ServerConfig
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import make_thumbnail
from malmberg_server.ingest.store import MediaStore
from malmberg_server.ingest.upload import handle_upload
from malmberg_server.version import VersionInfo, collect_version_info

_log = get_logger(__name__)

_CONTROL_ROUTES = {
    "next": ("POST", "/slideshow/next"),
    "prev": ("POST", "/slideshow/prev"),
    "pause": ("POST", "/slideshow/pause"),
    "status": ("GET", "/status"),
}


class ServerStatus(BaseModel):
    """Response body for GET /status."""

    version: str
    uptime_s: float
    disk_used_bytes: int
    disk_total_bytes: int
    paired_displays: int
    mode: str


class MediaPatch(BaseModel):
    do_not_display: Optional[bool] = None
    hide_policy: Optional[HidePolicy] = None
    dwell_override_s: Optional[float] = None
    tags: Optional[list[str]] = None


_INGEST_ERRORS = {
    IngestError.FileTooLarge: (413, "File exceeds maximum upload size"),
    IngestError.DuplicateFile: (409, "A file with this content already exists"),
    IngestError.ExifError: (422, "Could not process file metadata"),
    IngestError.IOError: (500, "I/O error during upload"),
    IngestError.StorageError: (500, "Media store error"),
    IngestError.NotFound: (404, "Media item not found"),
}


def _raise_ingest(err: IngestError) -> None:
    status, detail = _INGEST_ERRORS.get(err, (500, str(err)))
    raise HTTPException(status_code=status, detail=detail)


def build_app(cfg: ServerConfig, store: Optional[MediaStore] = None) -> FastAPI:
    """Build and return the FastAPI application wired to *cfg* and *store*.

    If *store* is None a new empty MediaStore is created.  Pass an existing
    store (e.g. pre-loaded from disk) when resuming across restarts.
    """
    app = FastAPI(title="Malmberg Server", version=__version__)
    _start = datetime.now(timezone.utc)
    _store = store if store is not None else MediaStore()

    def _media_root() -> Path:
        return cfg.fs_root / "media"

    def _upload_root() -> Path:
        return cfg.fs_root / "uploads"

    def _trash_root() -> Path:
        return cfg.fs_root / ".trash"

    def _index_path() -> Path:
        return cfg.fs_root / "logs" / "media-index.jsonl"

    @app.get("/")
    async def root() -> Tag:
        return Tag(
            name="Malmberg File Server",
            id="server",
            version=__version__,
            mac=get_mac_address(),
        )

    @app.get("/version")
    async def version() -> VersionInfo:
        """Report package, git commit, Python, OpenZFS, and dependency versions."""
        return collect_version_info()

    @app.get("/status")
    async def status() -> ServerStatus:
        usage = shutil.disk_usage(cfg.fs_root)
        elapsed = (datetime.now(timezone.utc) - _start).total_seconds()
        return ServerStatus(
            version=__version__,
            uptime_s=elapsed,
            disk_used_bytes=usage.used,
            disk_total_bytes=usage.total,
            paired_displays=0,
            mode="running",
        )

    @app.get("/media")
    async def list_media(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        sort: Literal["id", "recent"] = Query(default="id"),
    ) -> MediaPage:
        result = _store.list(
            page=page,
            page_size=page_size,
            skip_hidden=True,
            sort=sort,
            media_root=_media_root(),
        )
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        return result

    @app.get("/media/{item_id}")
    async def get_media(item_id: str) -> FileResponse:
        item = _store.get(item_id, media_root=_media_root())
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        path = _media_root() / item.server_path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found on disk")
        return FileResponse(str(path))

    @app.get("/media/{item_id}/thumb")
    async def media_thumb(
        item_id: str,
        size: int = Query(default=400, ge=64, le=1024),
    ) -> FileResponse:
        """Serve a cached JPEG thumbnail for the item (generated on first request)."""
        item = _store.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        thumb_path = cfg.fs_root / ".thumbs" / f"{item_id}_{size}.jpg"
        if not thumb_path.is_file():
            src = _media_root() / item.server_path
            if not src.is_file():
                raise HTTPException(status_code=404, detail="File not found on disk")
            result = make_thumbnail(
                src, thumb_path, size, is_video=item.kind == "video"
            )
            if result.is_err:
                _raise_ingest(result.danger_err)
        return FileResponse(str(thumb_path), media_type="image/jpeg")

    @app.get("/upload", response_class=HTMLResponse)
    async def upload_page() -> str:
        """Serve the mobile-first bulk-upload page (drag-and-drop, many files)."""
        return UPLOAD_PAGE_HTML

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page() -> str:
        """Serve the control dashboard: recent photos grid plus slideshow controls."""
        return DASHBOARD_PAGE_HTML

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        if file.filename is None:
            raise HTTPException(status_code=400, detail="filename required")
        result = await handle_upload(
            file=file,
            store=_store,
            media_root=_media_root(),
            upload_root=_upload_root(),
            max_bytes=cfg.max_upload_mb * 1024 * 1024,
        )
        if result.is_err:
            _raise_ingest(result.danger_err)
        item = result.danger_ok
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after upload")
        return item.model_dump()

    @app.patch("/media/{item_id}")
    async def patch_media(item_id: str, patch: MediaPatch) -> dict:
        updates = patch.model_dump(exclude_none=True)
        result = _store.patch(item_id, updates)
        if result.is_err:
            _raise_ingest(result.danger_err)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after patch")
        return result.danger_ok.model_dump()

    @app.delete("/media/{item_id}")
    async def delete_media(item_id: str) -> dict[str, str]:
        result = _store.delete(item_id, _trash_root(), _media_root())
        if result.is_err:
            _raise_ingest(result.danger_err)
        # Drop any cached thumbnails for this item so .thumbs never accumulates
        # orphans as photos are replaced/removed.
        for thumb in (cfg.fs_root / ".thumbs").glob(f"{item_id}_*.jpg"):
            thumb.unlink(missing_ok=True)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after delete")
        return result.danger_ok

    async def _forward_to_display(name: str) -> dict:
        """Forward a control action to the paired display's control API.

        Raises HTTPException(503) if no display_url is configured, or 502 if
        the display could not be reached.
        """
        if not cfg.display_url:
            raise HTTPException(
                status_code=503,
                detail="No display configured; set MALMBERG_DISPLAY_URL",
            )
        method, path = _CONTROL_ROUTES[name]
        url = cfg.display_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.request(method, url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            _log.error("Failed to reach display at %s: %s", url, exc)
            raise HTTPException(
                status_code=502, detail="Could not reach paired display"
            ) from exc

    @app.post("/control/next")
    async def control_next() -> dict:
        """Proxy: skip to the next slideshow item on the paired display."""
        return await _forward_to_display("next")

    @app.post("/control/prev")
    async def control_prev() -> dict:
        """Proxy: jump to the previous slideshow item on the paired display."""
        return await _forward_to_display("prev")

    @app.post("/control/pause")
    async def control_pause() -> dict:
        """Proxy: toggle pause/resume on the paired display."""
        return await _forward_to_display("pause")

    @app.get("/control/status")
    async def control_status() -> dict:
        """Proxy: fetch the paired display's current slideshow status."""
        return await _forward_to_display("status")

    return app
