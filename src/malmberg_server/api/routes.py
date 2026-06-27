"""FastAPI routes for the Server role."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.logging import get_logger
from malmberg_core.models import HidePolicy, MediaItem, MediaMetadata, MediaPage, Tag
from malmberg_core.networking import get_mac_address
from malmberg_server.app.config import ServerConfig

_log = get_logger(__name__)

_MEDIA_EXTS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".heic",
        ".webp",
        ".heif",
        ".avif",
        ".tiff",
        ".mp4",
        ".mkv",
        ".mov",
        ".m4v",
        ".avi",
        ".wmv",
        ".webm",
    }
)


class ServerStatus(BaseModel):
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


def build_app(cfg: ServerConfig) -> FastAPI:
    """Build and return the FastAPI application wired to *cfg*."""
    app = FastAPI(title="Malmberg Server", version=__version__)
    _start = datetime.now(timezone.utc)

    # In-memory media index for now; a persistent store is a future milestone.
    _media: dict[str, MediaItem] = {}

    def _media_root() -> Path:
        return cfg.fs_root / "media"

    def _upload_root() -> Path:
        return cfg.fs_root / "uploads"

    def _trash_root() -> Path:
        return cfg.fs_root / ".trash"

    @app.get("/")
    async def root() -> Tag:
        return Tag(
            name="Malmberg File Server",
            id="server",
            version=__version__,
            mac=get_mac_address(),
        )

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
    ) -> MediaPage:
        all_items = [it for it in _media.values() if not it.do_not_display]
        total = len(all_items)
        start = (page - 1) * page_size
        chunk = all_items[start : start + page_size]
        return MediaPage(
            items=chunk,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(start + page_size) < total,
        )

    @app.get("/media/{item_id}")
    async def get_media(item_id: str) -> FileResponse:
        item = _media.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        path = _media_root() / item.server_path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found on disk")
        return FileResponse(str(path))

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> MediaItem:
        if file.filename is None:
            raise HTTPException(status_code=400, detail="filename required")
        if (cfg.max_upload_mb * 1024 * 1024) < 0:
            pass  # validated by config

        upload_path = _upload_root() / (file.filename or "upload")
        sha = hashlib.sha256()

        with open(upload_path, "wb") as dest:
            while chunk := await file.read(65536):
                sha.update(chunk)
                dest.write(chunk)

        digest = sha.hexdigest()
        now = datetime.now(timezone.utc)
        rel_path = f"{now.year}/{now.month:02d}/{now.day:02d}/{file.filename}"
        final_path = _media_root() / rel_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.rename(final_path)

        kind = (
            "video"
            if Path(file.filename).suffix.lower()
            in {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".wmv", ".webm"}
            else "image"
        )
        item = MediaItem(
            kind=kind,
            filename=file.filename,
            server_path=rel_path,
            meta=MediaMetadata(sha256=digest),
        )
        _media[item.id] = item
        _log.info("Ingested %s -> %s", file.filename, rel_path)
        return item

    @app.patch("/media/{item_id}")
    async def patch_media(item_id: str, patch: MediaPatch) -> MediaItem:
        item = _media.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        updates = patch.model_dump(exclude_none=True)
        _media[item_id] = item.model_copy(update=updates)
        return _media[item_id]

    @app.delete("/media/{item_id}")
    async def delete_media(item_id: str) -> dict[str, str]:
        item = _media.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")

        path = _media_root() / item.server_path
        if item.hide_policy == "delete":
            if path.is_file():
                trash_path = _trash_root() / item.server_path
                trash_path.parent.mkdir(parents=True, exist_ok=True)
                path.rename(trash_path)
            del _media[item_id]
            _log.info("Trashed %s", item_id)
            return {"status": "trashed", "id": item_id}
        else:
            _media[item_id] = item.model_copy(update={"do_not_display": True})
            _log.info("Hidden (kept) %s", item_id)
            return {"status": "hidden", "id": item_id}

    return app
