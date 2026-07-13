"""FastAPI routes for the Server role."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.logging import get_logger
from malmberg_core.models import HidePolicy, MediaItem, MediaPage, Tag
from malmberg_core.networking import get_mac_address
from malmberg_server.api.web import DASHBOARD_PAGE_HTML
from malmberg_server.app.config import ServerConfig
from malmberg_server.cloud.base import CloudError, CloudProvider
from malmberg_server.cloud.google_photos import GooglePhotosProvider
from malmberg_server.cloud.icloud import ICloudProvider
from malmberg_server.cloud.sync import (
    CloudStatus,
    CloudSyncAck,
    CloudSyncEngine,
    CloudSyncRequest,
    cloud_state_path,
    run_cloud_sync_worker,
)
from malmberg_server.cloud.verify_and_delete import (
    CloudDeleteRequest,
    DeletablePage,
    DeleteReport,
    delete_verified,
    dry_run_deletable,
)
from malmberg_server.faces.faces_index import FaceStore
from malmberg_server.faces.people import PersonStore
from malmberg_server.faces.worker import run_face_worker, sync_person_ids
from malmberg_server.ingest.errors import IngestError
from malmberg_server.ingest.media import (
    extract_exif,
    make_thumbnail,
    reverse_geocode,
    transform_image,
)
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
    "restart": ("POST", "/admin/restart"),
}


def _schedule_self_restart(module: str) -> None:
    """Re-exec the current interpreter running *module* shortly after this call.

    Deferred via ``loop.call_later`` so an in-flight HTTP response (e.g. the
    200 acknowledging the restart request) is flushed to the client before
    the process image is replaced. Re-exec (rather than os.kill/exit) is
    used deliberately so this works whether or not a supervisor like systemd
    is watching the process.
    """

    def _do_restart() -> None:
        _log.warning("Restart requested: re-executing %s", module)
        os.execv(sys.executable, [sys.executable, "-m", module])

    asyncio.get_event_loop().call_later(0.25, _do_restart)


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


class PersonNameRequest(BaseModel):
    """Request body for POST /people/{person_id}/name."""

    name: str


class FaceReassignRequest(BaseModel):
    """Request body for POST /faces/{face_id}/reassign.

    *person_id* None (or omitted) detaches the face onto a brand-new unnamed
    person ("not this person"); a value reassigns it to that existing person.
    """

    person_id: Optional[str] = None


class PersonMergeRequest(BaseModel):
    """Request body for POST /people/{person_id}/merge (merge *from_id* into it)."""

    from_id: str


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


class MediaTagRequest(BaseModel):
    """Request body for POST /media/{item_id}/tag: manual date/location.

    Every field is optional and independent. A field that is OMITTED from
    the request body is left unchanged; a field explicitly set to null
    CLEARS that manual override, reverting to the photo's own EXIF value
    (see MediaMetadata.effective_taken_at / effective_place). Omitted vs.
    explicit-null is distinguished via ``model_fields_set`` -- a plain
    Optional field cannot tell the two apart on its own.

    *date* is an ISO date (``YYYY-MM-DD``) or full ISO datetime string,
    stored as a UTC datetime. *place* is a free-text label. *lat*/*lon* are
    decimal degrees; when given without *place*, the coordinates are
    reverse-geocoded (best-effort, offline) into a place label.
    """

    date: Optional[str] = None
    place: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class MediaTagBulkRequest(MediaTagRequest):
    """Request body for POST /media/tag-bulk: apply the same manual
    date/location to every id in *ids* in one call."""

    ids: list[str]


class MediaTransformRequest(BaseModel):
    """Request body for POST /media/{item_id}/transform.

    *rotate* is degrees clockwise: 0, 90, 180, 270, or -90 (== 270). *flip*
    is "h" (horizontal), "v" (vertical), or omitted/None for no flip.
    """

    rotate: Literal[0, 90, 180, 270, -90] = 0
    flip: Optional[Literal["h", "v"]] = None


_INGEST_ERRORS = {
    IngestError.FileTooLarge: (413, "File exceeds maximum upload size"),
    IngestError.DuplicateFile: (409, "A file with this content already exists"),
    IngestError.ExifError: (422, "Could not process file metadata"),
    IngestError.IOError: (500, "I/O error during upload"),
    IngestError.StorageError: (500, "Media store error"),
    IngestError.NotFound: (404, "Media item not found"),
    IngestError.UnsupportedMedia: (400, "This operation is not supported for videos"),
}


def _raise_ingest(err: IngestError) -> None:
    status, detail = _INGEST_ERRORS.get(err, (500, str(err)))
    raise HTTPException(status_code=status, detail=detail)


def _parse_manual_date(raw: str) -> datetime:
    """Parse *raw* (``YYYY-MM-DD`` or full ISO datetime) into a UTC datetime.

    Raises HTTPException(400) on an unparseable string. A date-only string
    is taken as midnight UTC; a naive datetime is assumed UTC; an aware
    datetime is converted to UTC -- matching how EXIF-derived taken_at is
    always stored (see malmberg_server.ingest.media.extract_exif).
    """
    try:
        if len(raw) == 10:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {raw!r}") from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _manual_meta_updates(meta, body: MediaTagRequest, fields_set: set) -> dict:
    """Build a ``meta`` field-update dict from a manual-tag request.

    Only fields present in *fields_set* (i.e. actually sent by the client)
    are touched, so a partial request (date only, or place only) leaves the
    other manual overrides untouched. Coordinates given without an explicit
    *place* are reverse-geocoded into ``manual_place``; an explicit *place*
    always wins over any derived label. Clearing (a field explicitly sent
    as null) reverts that override to the EXIF value via
    MediaMetadata.effective_* -- see the model docstrings.
    """
    updates: dict = {}
    if "date" in fields_set:
        updates["manual_taken_at"] = (
            _parse_manual_date(body.date) if body.date is not None else None
        )
    if "lat" in fields_set or "lon" in fields_set:
        updates["manual_lat"] = body.lat
        updates["manual_lon"] = body.lon
        if body.lat is not None and body.lon is not None:
            derived = reverse_geocode(body.lat, body.lon)
            if derived is not None:
                updates["manual_place"] = derived
        else:
            updates.setdefault("manual_place", None)
    if "place" in fields_set:
        updates["manual_place"] = body.place
    return updates


def build_app(
    cfg: ServerConfig,
    store: Optional[MediaStore] = None,
    people: Optional[PersonStore] = None,
    faces: Optional[FaceStore] = None,
) -> FastAPI:
    """Build and return the FastAPI application wired to *cfg* and *store*.

    If *store* is None a new empty MediaStore is created.  Pass an existing
    store (e.g. pre-loaded from disk) when resuming across restarts. *people*
    and *faces* may likewise be pre-seeded (used by tests to exercise the
    /people and /faces endpoints without running the background worker).
    """
    app = FastAPI(title="Malmberg Server", version=__version__)
    _start = datetime.now(timezone.utc)
    _store = store if store is not None else MediaStore()
    _playlists = PlaylistStore()
    _people = people if people is not None else PersonStore()
    _faces = faces if faces is not None else FaceStore()
    # Named displays for multi-display control (a lone display_url counts as one).
    _displays: dict[str, str] = (
        dict(cfg.displays)
        if cfg.displays
        else ({"display": cfg.display_url} if cfg.display_url else {})
    )
    _selected = {"name": next(iter(_displays), None)}

    def _media_root() -> Path:
        return cfg.fs_root / "media"

    def _upload_root() -> Path:
        return cfg.fs_root / "uploads"

    def _item_file_root(item: MediaItem) -> Path:
        """Return the root a trashed-or-live item's file currently lives under."""
        return _trash_root() if item.trashed_at is not None else _media_root()

    def _trash_root() -> Path:
        return cfg.fs_root / ".trash"

    def _index_path() -> Path:
        return cfg.fs_root / "logs" / "media-index.jsonl"

    def _playlists_path() -> Path:
        return cfg.fs_root / "logs" / "playlists.json"

    def _people_path() -> Path:
        return cfg.fs_root / "logs" / "people.jsonl"

    def _faces_path() -> Path:
        return cfg.fs_root / "logs" / "faces.jsonl"

    _playlists.load_from_disk(_playlists_path())
    _people.load_from_disk(_people_path())
    _faces.load_from_disk(_faces_path())

    def _save_playlists() -> None:
        save = _playlists.save_to_disk(_playlists_path())
        if save.is_err:
            _log.error("Failed to persist playlists")

    def _save_faces_state() -> None:
        """Persist people + faces + media index together after a face mutation."""
        if _people.save_to_disk(_people_path()).is_err:
            _log.error("Failed to persist people index")
        if _faces.save_to_disk(_faces_path()).is_err:
            _log.error("Failed to persist faces index")
        if _store.save_to_disk(_index_path()).is_err:
            _log.error("Failed to persist media index after face mutation")

    def _build_providers() -> list[CloudProvider]:
        """Construct the cloud providers whose enable flag is set in config.

        Providers self-degrade (is_configured() False) when their optional
        dependency or credentials are absent, so construction never raises.
        """
        providers: list[CloudProvider] = []
        if cfg.cloud_icloud_enabled:
            providers.append(
                ICloudProvider(
                    cfg.cloud_icloud_username,
                    cfg.cloud_icloud_session_path(),
                )
            )
        if cfg.cloud_google_photos_enabled:
            providers.append(
                GooglePhotosProvider(
                    cfg.cloud_google_client_secrets_path(),
                    cfg.cloud_google_token_path(),
                )
            )
        return providers

    _cloud_engine = CloudSyncEngine(
        cfg,
        _store,
        _build_providers(),
        media_root=_media_root(),
        upload_root=cfg.fs_root / ".upload" / "cloud",
        state_path=cloud_state_path(cfg.fs_root),
        index_path=_index_path(),
    )
    _cloud_engine.load_state()

    @app.on_event("startup")
    async def _start_face_worker() -> None:
        """Kick off the background face-detection walker (see faces.worker).

        Runs off the request path: uploads return immediately and this task
        fills in the per-face index and person groups asynchronously, batch by
        batch, forever.
        """
        asyncio.create_task(
            run_face_worker(
                _store,
                _people,
                _faces,
                _media_root(),
                _index_path(),
                _people_path(),
                _faces_path(),
            )
        )

    @app.on_event("startup")
    async def _start_cloud_sync_worker() -> None:
        """Kick off the periodic cloud pull-sync (see cloud.sync).

        Pull-only: this task never deletes remote items; deletion happens
        exclusively through the explicit POST /cloud/delete path.
        """
        if _cloud_engine.providers:
            asyncio.create_task(
                run_cloud_sync_worker(_cloud_engine, float(cfg.cloud_sync_interval_s))
            )

    _CLOUD_ERRORS = {
        CloudError.NotConfigured: 503,
        CloudError.Unsupported: 400,
        CloudError.AuthError: 502,
        CloudError.NetworkError: 502,
        CloudError.RateLimited: 429,
        CloudError.NotFound: 404,
        CloudError.StateError: 500,
        CloudError.AuditError: 500,
    }

    @app.get("/cloud/status")
    async def cloud_status() -> CloudStatus:
        """Per-provider sync/verify/delete counters and last-sync info."""
        return _cloud_engine.status()

    @app.post("/cloud/sync")
    async def cloud_sync(req: CloudSyncRequest) -> CloudSyncAck:
        """Schedule an immediate sync (all providers, or one) as a background task."""
        if req.provider is not None:
            provider = _cloud_engine.provider_by_name(req.provider)
            if provider is None:
                return CloudSyncAck(status="unknown_provider", providers=[])
            targets = [provider]
        else:
            targets = list(_cloud_engine.providers)
        if not targets:
            return CloudSyncAck(status="no_providers", providers=[])

        async def _run() -> None:
            for p in targets:
                await _cloud_engine.sync_provider(p)

        asyncio.create_task(_run())
        return CloudSyncAck(status="started", providers=[p.name for p in targets])

    @app.get("/cloud/deletable")
    async def cloud_deletable(provider: str = Query(...)) -> DeletablePage:
        """Dry-run list of remote items verified safe to delete right now."""
        prov = _cloud_engine.provider_by_name(provider)
        if prov is None:
            raise HTTPException(status_code=404, detail="Unknown cloud provider")
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, dry_run_deletable, _cloud_engine, prov
        )
        return DeletablePage(provider=provider, items=entries, total=len(entries))

    @app.post("/cloud/delete")
    async def cloud_delete(req: CloudDeleteRequest) -> DeleteReport:
        """Verified deletion from the cloud; refuses without explicit confirm."""
        if not req.confirm:
            raise HTTPException(
                status_code=400,
                detail="confirm must be true to delete from the cloud",
            )
        prov = _cloud_engine.provider_by_name(req.provider)
        if prov is None:
            raise HTTPException(status_code=404, detail="Unknown cloud provider")
        cap = req.cap if req.cap is not None else cfg.cloud_delete_cap
        result = await delete_verified(_cloud_engine, prov, confirm=True, cap=cap)
        if result.is_err:
            status = _CLOUD_ERRORS.get(result.danger_err, 500)
            raise HTTPException(status_code=status, detail=str(result.danger_err))
        return result.danger_ok

    @app.get("/")
    async def root() -> Tag:
        return Tag(
            name="Malmberg File Server",
            id="server",
            version=__version__,
            mac=get_mac_address(),
        )

    @app.post("/admin/restart")
    async def admin_restart() -> dict[str, str]:
        """Acknowledge, then re-exec this process (see _schedule_self_restart)."""
        _log.warning("Server restart requested via /admin/restart")
        _schedule_self_restart("malmberg_server")
        return {"status": "restarting"}

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
        q_time: Optional[str] = Query(default=None),
        q_place: Optional[str] = Query(default=None),
        q_person: Optional[str] = Query(default=None),
    ) -> MediaPage:
        result = _store.list(
            page=page,
            page_size=page_size,
            skip_hidden=True,
            sort=sort,
            media_root=_media_root(),
            q=q,
            q_time=q_time,
            q_place=q_place,
            q_person=q_person,
            people=_people,
        )
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        return result

    @app.get("/stats")
    async def media_stats() -> dict:
        """Report library-wide counts, date range, and per-year/place/person
        distribution."""
        return _store.stats(people=_people)

    @app.get("/places")
    async def list_places(
        q: str = Query(default=""),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> list[str]:
        """Autocomplete: distinct place labels containing *q*, most-common first."""
        return _store.places(q=q, limit=limit)

    @app.get("/people")
    async def list_people(
        min_count: int = Query(default=3, ge=0, le=1000),
    ) -> list[dict]:
        """List detected people: id, name (None if unnamed), photo count,
        sample thumbnail id.

        *min_count* (default 3) hides small/uncertain clusters from the main
        list -- those groups are kept on disk and keep accruing new matching
        faces, they are just not surfaced for naming until confident. Named
        people are always included. Pass min_count=1 to fetch the small ones.
        """
        return _people.list(
            counts_by_person=_store.counts_by_person(), min_count=min_count
        )

    @app.get("/people/{person_id}/photos")
    async def person_photos(person_id: str) -> list[dict]:
        """Every face flagged for *person_id*, for the review + green-box UI.

        Returns [{item_id, face_id, bbox, img_w, img_h}, ...] -- bbox is in
        source pixels and img_w/img_h are the photo's pixel dimensions so the
        dashboard can scale a green rectangle onto the rendered image.
        """
        if _people.get(person_id) is None:
            raise HTTPException(status_code=404, detail="Person not found")
        out = []
        for face in _faces.faces_for_person(person_id):
            item = _store.get(face["item_id"])
            # A trashed photo keeps its face entries (they are needed if it is
            # restored), but it must not show up in review -- deleting a photo
            # from the review grid has to make it leave the grid. The person's
            # displayed count already excludes trashed items
            # (MediaStore.counts_by_person), so this also keeps the two in step.
            if item is None or item.trashed_at is not None:
                continue
            out.append(
                {
                    "item_id": face["item_id"],
                    "face_id": face["face_id"],
                    "bbox": face["bbox"],
                    "img_w": item.meta.width,
                    "img_h": item.meta.height,
                }
            )
        return out

    @app.delete("/people/{person_id}")
    async def delete_person(person_id: str) -> dict:
        """Delete a person group and its faces; the photos are kept.

        For a junk cluster (a stranger, a false positive) the user wants gone
        from the People grid. The face embeddings go with it -- see
        PersonStore.delete for why, and for the version-bump caveat.
        """
        result = _people.delete(person_id, _faces)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Person not found")
        sync_person_ids(_store, _faces)
        _save_faces_state()
        return {"status": "deleted", "person_id": person_id, "faces": result.danger_ok}

    @app.post("/people/{person_id}/merge")
    async def merge_people(person_id: str, body: PersonMergeRequest) -> dict:
        """Merge person *body.from_id* into *person_id* (fix an over-split)."""
        result = _people.merge(person_id, body.from_id, _faces)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Person not found")
        sync_person_ids(_store, _faces)
        _save_faces_state()
        return result.danger_ok.model_dump(mode="json")

    @app.post("/people/recluster")
    async def recluster_people() -> dict:
        """Rebuild all person groups from the per-face index (order-independent).

        Runs the connected-components recluster in a thread executor so the
        event loop is never blocked, preserving user-assigned names. Idempotent.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _people.recluster, _faces)
        sync_person_ids(_store, _faces)
        _save_faces_state()
        return {"status": "reclustered", "people": len(_people), "faces": len(_faces)}

    @app.post("/faces/{face_id}/reassign")
    async def reassign_face(face_id: str, body: FaceReassignRequest) -> dict:
        """Override a single face's person: reassign to another, or detach.

        *body.person_id* None detaches the face onto a new unnamed person
        ("not this person"); a value reassigns it to that existing person.
        Both affected persons' centroids/counts are recomputed and empty
        unnamed persons pruned.
        """
        entry = _faces.get(face_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Face not found")
        old_pid = entry.person_id
        if body.person_id is None:
            new_pid = _people.create_person()
        else:
            if _people.get(body.person_id) is None:
                raise HTTPException(status_code=404, detail="Target person not found")
            new_pid = body.person_id
        _faces.set_person(face_id, new_pid)
        _people.recompute_person(old_pid, _faces)
        _people.recompute_person(new_pid, _faces)
        _people.prune_empty()
        sync_person_ids(_store, _faces)
        _save_faces_state()
        return {"status": "reassigned", "face_id": face_id, "person_id": new_pid}

    @app.post("/people/{person_id}/name")
    async def name_person(person_id: str, body: PersonNameRequest) -> dict:
        """Assign or change the display name of a detected person."""
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        result = _people.rename_with_dedup(person_id, name, _faces)
        if result.is_err:
            raise HTTPException(status_code=404, detail="Person not found")
        sync_person_ids(_store, _faces)
        _save_faces_state()
        save = _people.save_to_disk(_people_path())
        if save.is_err:
            _log.error("Failed to persist people index after rename")
        return result.danger_ok.model_dump(mode="json")

    @app.get("/people/suggest")
    async def suggest_people(
        q: str = Query(default=""),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> list[str]:
        """Autocomplete: distinct named-person names containing *q*,
        most-common first."""
        return _people.suggest(q=q, limit=limit)

    @app.get("/media/trash")
    async def list_trash(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
    ) -> MediaPage:
        """List trashed (soft-deleted) items for the recycle bin view.

        Registered ahead of GET /media/{item_id} so the literal "trash"
        path segment is not swallowed as an item id.
        """
        return _store.list_trash(page=page, page_size=page_size)

    @app.get("/media/{item_id}")
    async def get_media(item_id: str) -> FileResponse:
        item = _store.get(item_id, media_root=_media_root())
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        if _store.pop_dirty():
            save = _store.save_to_disk(_index_path())
            if save.is_err:
                _log.error("Failed to persist media index after metadata refresh")
        path = _item_file_root(item) / item.server_path
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
            src = _item_file_root(item) / item.server_path
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

    @app.post("/media/{item_id}/tag")
    async def tag_media(item_id: str, body: MediaTagRequest) -> dict:
        """Set/clear manual date and location overrides for a single item.

        See MediaTagRequest for the omitted-vs-null semantics. Persists the
        index immediately, same as the other mutating routes.
        """
        item = _store.get(item_id, media_root=_media_root())
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        meta_updates = _manual_meta_updates(item.meta, body, body.model_fields_set)
        new_meta = item.meta.model_copy(update=meta_updates)
        result = _store.patch(item_id, {"meta": new_meta})
        if result.is_err:
            _raise_ingest(result.danger_err)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after tag")
        _log.info("Tagged %s: %s", item_id, meta_updates)
        return result.danger_ok.model_dump(mode="json")

    @app.post("/media/tag-bulk")
    async def tag_media_bulk(body: MediaTagBulkRequest) -> dict:
        """Apply the same manual date/location to every id in *body.ids*.

        Returns {"tagged": [ids...], "failed": [ids...]}; a failure on one
        item does not abort the rest.
        """
        fields_set = body.model_fields_set - {"ids"}
        tagged: list[str] = []
        failed: list[str] = []
        for item_id in body.ids:
            item = _store.get(item_id, media_root=_media_root())
            if item is None:
                failed.append(item_id)
                continue
            meta_updates = _manual_meta_updates(item.meta, body, fields_set)
            new_meta = item.meta.model_copy(update=meta_updates)
            result = _store.patch(item_id, {"meta": new_meta})
            if result.is_err:
                failed.append(item_id)
                continue
            tagged.append(item_id)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after bulk tag")
        _log.info("Bulk tagged %d item(s), %d failed", len(tagged), len(failed))
        return {"tagged": tagged, "failed": failed}

    @app.post("/media/{item_id}/transform")
    async def transform_media(item_id: str, body: MediaTransformRequest) -> dict:
        """Permanently rotate/flip an image, baking the change into the file.

        Rewriting the bytes ripples through four caches/records, all handled
        here: (1) meta.sha256/width/height are recomputed from the rewritten
        file and the index persisted; (2) every cached thumbnail for this
        item is dropped so it regenerates from the new pixels; (3) the
        display's ServerProducer keys its download cache off meta.sha256, so
        once the new sha256 is served the Pi re-downloads instead of showing
        the stale cached orientation forever; (4) any cloud-sync record
        tracking this item is marked unverified, since the local copy is no
        longer byte-identical to the cloud original -- this is deliberate,
        it is what stops the guarded cloud-cleanup from deleting the cloud
        copy out from under an edited local one.
        """
        item = _store.get(item_id, media_root=_media_root())
        if item is None:
            raise HTTPException(status_code=404, detail="Media item not found")
        if item.kind == "video":
            _raise_ingest(IngestError.UnsupportedMedia)
        if item.trashed_at is not None:
            raise HTTPException(
                status_code=400, detail="Cannot transform a trashed item"
            )
        path = _media_root() / item.server_path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File not found on disk")

        result = transform_image(path, rotate=body.rotate, flip=body.flip)
        if result.is_err:
            _raise_ingest(result.danger_err)

        meta_result = extract_exif(path)
        if meta_result.is_err:
            _raise_ingest(meta_result.danger_err)
        new_meta = meta_result.danger_ok.model_copy(
            update={
                "ingest_at": item.meta.ingest_at,
                "manual_taken_at": item.meta.manual_taken_at,
                "manual_lat": item.meta.manual_lat,
                "manual_lon": item.meta.manual_lon,
                "manual_place": item.meta.manual_place,
            }
        )
        patched = _store.patch(item_id, {"meta": new_meta})
        if patched.is_err:
            _raise_ingest(patched.danger_err)

        for thumb in (cfg.fs_root / ".thumbs").glob(f"{item_id}_*.jpg"):
            thumb.unlink(missing_ok=True)

        unverify = _cloud_engine.unverify_local_item(item_id)
        if unverify.is_err:
            _log.error("Failed to persist cloud state after unverifying %s", item_id)

        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after transform")

        _log.info(
            "Transformed %s (%s): rotate=%s flip=%s -> sha256=%s %dx%d",
            item_id,
            item.filename,
            body.rotate,
            body.flip,
            new_meta.sha256,
            new_meta.width,
            new_meta.height,
        )
        return patched.danger_ok.model_dump(mode="json")

    @app.delete("/media/{item_id}")
    async def delete_media(
        item_id: str, permanent: bool = Query(default=False)
    ) -> dict[str, str]:
        """Soft-delete (trash, recoverable) by default; hard-delete if
        *permanent* is true (unlinks the file, not recoverable)."""
        if permanent:
            result = _store.delete_permanent(item_id, _media_root(), _trash_root())
        else:
            result = _store.delete(item_id, _trash_root(), _media_root())
        if result.is_err:
            _raise_ingest(result.danger_err)
        if permanent:
            # Drop any cached thumbnails for this item so .thumbs never
            # accumulates orphans; trashed-but-recoverable items keep their
            # thumbnail so the recycle bin can still render one.
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
                result = _store.delete_permanent(item_id, _media_root(), _trash_root())
            else:
                result = _store.delete(item_id, _trash_root(), _media_root())
            if result.is_err:
                failed.append(item_id)
                continue
            deleted.append(item_id)
            if req.permanent:
                for thumb in (cfg.fs_root / ".thumbs").glob(f"{item_id}_*.jpg"):
                    thumb.unlink(missing_ok=True)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after bulk delete")
        return {"deleted": deleted, "failed": failed}

    @app.post("/media/{item_id}/restore")
    async def restore_media(item_id: str) -> dict:
        """Restore a trashed item: move its file back and clear the trash flag."""
        result = _store.restore(item_id, _trash_root(), _media_root())
        if result.is_err:
            _raise_ingest(result.danger_err)
        save = _store.save_to_disk(_index_path())
        if save.is_err:
            _log.error("Failed to persist media index after restore")
        return result.danger_ok.model_dump(mode="json")

    async def _forward_to_display(
        name: str, *, path_override: Optional[str] = None, json_body: object = None
    ) -> dict:
        """Forward a control action to the paired display's control API.

        Raises HTTPException(503) if no display is configured, or 502 if the
        selected display could not be reached.
        """
        target = _selected["name"]
        if target is None or target not in _displays:
            raise HTTPException(
                status_code=503,
                detail="No display configured; set MALMBERG_DISPLAY_URL(S)",
            )
        method, path = _CONTROL_ROUTES[name]
        if path_override is not None:
            path = path_override
        url = _displays[target].rstrip("/") + path
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
        """Selected display's status, plus the roster of all known displays."""
        roster = {
            "displays": [{"name": n} for n in _displays],
            "selected": _selected["name"],
        }
        if _selected["name"] is None:
            raise HTTPException(
                status_code=503,
                detail="No display configured; set MALMBERG_DISPLAY_URL(S)",
            )
        try:
            status = await _forward_to_display("status")
        except HTTPException as exc:
            if exc.status_code == 502:  # configured but unreachable
                return {**roster, "online": False, "current_item_id": None}
            raise
        return {**status, **roster}

    @app.post("/control/select/{name}")
    async def control_select(name: str) -> dict:
        """Choose which display the /control/* actions target."""
        if name not in _displays:
            raise HTTPException(status_code=404, detail="Unknown display")
        _selected["name"] = name
        return {"selected": name}

    @app.post("/control/play-all")
    async def control_play_all() -> dict:
        """Proxy: revert the paired display to showing the whole library."""
        return await _forward_to_display("play-all")

    @app.post("/control/restart")
    async def control_restart() -> dict:
        """Proxy: restart the selected paired display's process."""
        return await _forward_to_display("restart")

    @app.post("/control/show/{item_id}")
    async def control_show(item_id: str) -> dict:
        """Proxy: display *item_id* now on the paired display."""
        return await _forward_to_display(
            "show", path_override=f"/slideshow/show/{item_id}"
        )

    @app.post("/control/playlist/{name}")
    async def control_playlist(name: str, loop: bool = Query(default=False)) -> dict:
        """Proxy: play the programmed slideshow *name* on the paired display.

        *loop* false (default) plays it once and returns to the whole library;
        true repeats it until "play all" is pressed.
        """
        item_ids = _playlists.get(name)
        if item_ids is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return await _forward_to_display(
            "playlist",
            path_override="/slideshow/playlist",
            json_body={"item_ids": item_ids, "loop": loop},
        )

    @app.post("/control/play-query")
    async def control_play_query(
        q: Optional[str] = Query(default=None),
        q_time: Optional[str] = Query(default=None),
        q_place: Optional[str] = Query(default=None),
        q_person: Optional[str] = Query(default=None),
        loop: bool = Query(default=False),
    ) -> dict:
        """Play only the photos matching a search (e.g. a year) on the display.

        Accepts either the single free-text *q* (OR across filename / year /
        month / place / person) or the structured *q_time* / *q_place* /
        *q_person* filters, which combine by AND (all provided must match).
        At least one non-empty filter is required. *loop* false (default)
        plays the match once and returns to the whole library; true repeats
        it until "play all" is pressed.
        """
        if not any((v or "").strip() for v in (q, q_time, q_place, q_person)):
            raise HTTPException(status_code=400, detail="a filter is required")
        page = _store.list(
            page=1,
            page_size=500,
            skip_hidden=True,
            sort="recent",
            q=q,
            q_time=q_time,
            q_place=q_place,
            q_person=q_person,
            people=_people,
        )
        ids = [it.id for it in page.items]
        if not ids:
            raise HTTPException(status_code=404, detail="No photos match that filter")
        return await _forward_to_display(
            "playlist",
            path_override="/slideshow/playlist",
            json_body={"item_ids": ids, "loop": loop},
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
    async def add_playlist_items_bulk(name: str, body: BulkPlaylistAddRequest) -> dict:
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
