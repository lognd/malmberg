"""FastAPI routes for the Server role."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.logging import get_logger
from malmberg_core.models import HidePolicy, MediaPage, Tag
from malmberg_core.networking import get_mac_address
from malmberg_server.api.web import DASHBOARD_PAGE_HTML
from malmberg_server.app.config import ServerConfig
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import make_thumbnail
from malmberg_server.ingest.playlists import PlaylistStore
from malmberg_server.ingest.store import MediaStore
from malmberg_server.ingest.upload import handle_upload
from malmberg_server.version import VersionInfo, collect_version_info

_log = get_logger(__name__)

_CONTROL_ROUTES = {
    "next": ("POST", "/slideshow/next"),
    "prev": ("POST", "/slideshow/prev"),
    "pause": ("POST", "/slideshow/pause"),
    "status": ("GET", "/status"),
    "play-all": ("POST", "/slideshow/all"),
    "show": ("POST", ""),
    "playlist": ("POST", ""),
}


class PlaylistCreate(BaseModel):
    """Request body for POST /playlists."""

    name: str


class PlaylistItemAdd(BaseModel):
    """Request body for POST /playlists/{name}/items."""

    item_id: str


class BulkDeleteRequest(BaseModel):
    """Request body for POST /media/bulk-delete."""

    ids: list[str]
    permanent: bool = False


class BulkPlaylistAddRequest(BaseModel):
    """Request body for POST /playlists/{name}/items/bulk."""

    ids: list[str]


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
    _playlists = PlaylistStore()

    def _media_root() -> Path:
        return cfg.fs_root / "media"

    def _upload_root() -> Path:
        return cfg.fs_root / "uploads"

    def _trash_root() -> Path:
        return cfg.fs_root / ".trash"

    def _index_path() -> Path:
        return cfg.fs_root / "logs" / "media-index.jsonl"

    def _playlists_path() -> Path:
        return cfg.fs_root / "logs" / "playlists.json"

    _playlists.load_from_disk(_playlists_path())

    def _save_playlists() -> None:
        save = _playlists.save_to_disk(_playlists_path())
        if save.is_err:
            _log.error("Failed to persist playlists")

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
        q: Optional[str] = Query(default=None),
    ) -> MediaPage:
        result = _store.list(
            page=page,
            page_size=page_size,
            skip_hidden=True,
            sort=sort,
            media_root=_media_root(),
            q=q,
        )
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        return result

    @app.get("/stats")
    async def media_stats() -> dict:
        """Report library-wide counts, date range, and per-year distribution."""
        return _store.stats()

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

    @app.get("/media/{item_id}/info")
    async def media_info(item_id: str) -> dict:
        """Return the full MediaItem JSON for *item_id* (details for the UI)."""
        item = _store.get(item_id, media_root=_media_root())
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        return item.model_dump(mode="json")

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

    @app.get("/upload")
    async def upload_page() -> RedirectResponse:
        """Redirect to the single dashboard page, which now hosts upload."""
        return RedirectResponse(url="/dashboard", status_code=307)

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
    async def delete_media(
        item_id: str, permanent: bool = Query(default=False)
    ) -> dict[str, str]:
        """Soft-delete (trash, recoverable) by default; hard-delete if
        *permanent* is true (unlinks the file, not recoverable)."""
        if permanent:
            result = _store.delete_permanent(item_id, _media_root())
        else:
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

    @app.post("/media/bulk-delete")
    async def bulk_delete_media(req: BulkDeleteRequest) -> dict:
        """Soft- or hard-delete multiple items in one call.

        Returns {"deleted": [ids...], "failed": [ids...]}; a failure on one
        item does not abort the rest.
        """
        deleted: list[str] = []
        failed: list[str] = []
        for item_id in req.ids:
            if req.permanent:
                result = _store.delete_permanent(item_id, _media_root())
            else:
                result = _store.delete(item_id, _trash_root(), _media_root())
            if result.is_err:
                failed.append(item_id)
                continue
            deleted.append(item_id)
            for thumb in (cfg.fs_root / ".thumbs").glob(f"{item_id}_*.jpg"):
                thumb.unlink(missing_ok=True)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after bulk delete")
        return {"deleted": deleted, "failed": failed}

    async def _forward_to_display(
        name: str, *, path_override: Optional[str] = None, json_body: object = None
    ) -> dict:
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
        if path_override is not None:
            path = path_override
        url = cfg.display_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.request(method, url, json=json_body)
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

    @app.post("/control/play-all")
    async def control_play_all() -> dict:
        """Proxy: revert the paired display to showing the whole library."""
        return await _forward_to_display("play-all")

    @app.post("/control/show/{item_id}")
    async def control_show(item_id: str) -> dict:
        """Proxy: display *item_id* now on the paired display."""
        return await _forward_to_display(
            "show", path_override=f"/slideshow/show/{item_id}"
        )

    @app.post("/control/playlist/{name}")
    async def control_playlist(name: str) -> dict:
        """Proxy: play the programmed slideshow *name* on the paired display."""
        item_ids = _playlists.get(name)
        if item_ids is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return await _forward_to_display(
            "playlist",
            path_override="/slideshow/playlist",
            json_body={"item_ids": item_ids},
        )

    # ------------------------------------------------------------------
    # Programmed slideshows (playlists)
    # ------------------------------------------------------------------

    @app.get("/playlists")
    async def list_playlists() -> list[dict]:
        """List programmed slideshows as [{"name", "count"}, ...]."""
        return _playlists.list()

    @app.post("/playlists")
    async def create_playlist(body: PlaylistCreate) -> dict:
        """Create a new empty programmed slideshow named *body.name*."""
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        result = _playlists.create(name)
        if result.is_err:
            raise HTTPException(status_code=409, detail="Playlist already exists")
        _save_playlists()
        return {"name": name, "count": 0}

    @app.delete("/playlists/{name}")
    async def delete_playlist(name: str) -> dict:
        """Delete the programmed slideshow named *name*."""
        result = _playlists.delete(name)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Playlist not found")
        _save_playlists()
        return {"status": "deleted", "name": name}

    @app.post("/playlists/{name}/items")
    async def add_playlist_item(name: str, body: PlaylistItemAdd) -> dict:
        """Append an item id to the programmed slideshow *name*."""
        result = _playlists.add_item(name, body.item_id)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Playlist not found")
        _save_playlists()
        return {"name": name, "count": len(result.danger_ok)}

    @app.post("/playlists/{name}/items/bulk")
    async def add_playlist_items_bulk(
        name: str, body: BulkPlaylistAddRequest
    ) -> dict:
        """Append multiple item ids to the programmed slideshow *name*."""
        items = _playlists.get(name)
        if items is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        for item_id in body.ids:
            _playlists.add_item(name, item_id)
        _save_playlists()
        return {"name": name, "count": len(_playlists.get(name) or [])}

    @app.delete("/playlists/{name}/items/{item_id}")
    async def remove_playlist_item(name: str, item_id: str) -> dict:
        """Remove an item id from the programmed slideshow *name*."""
        result = _playlists.remove_item(name, item_id)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Playlist not found")
        _save_playlists()
        return {"name": name, "count": len(result.danger_ok)}

    return app
