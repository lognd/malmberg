"""FastAPI routes for the Display role."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Callable, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.logging import get_logger
from malmberg_core.models import Tag
from malmberg_core.networking import get_mac_address
from malmberg_display.display.proto import DisplayContext
from malmberg_display.display.toast import Toast
from malmberg_display.slideshow.slideshow import ProducerType, Slideshow
from malmberg_server.api.web import render_dashboard_html

_log = get_logger(__name__)

# How long a manually shown single photo stays up before the display returns to
# the automatic whole-library slideshow on its own.
_AUTO_REVERT_SINGLE_S = 60.0


def _schedule_self_restart(module: str) -> None:
    """Re-exec the current interpreter running *module* shortly after this call.

    Deferred via ``loop.call_later`` so the in-flight HTTP response
    acknowledging the restart is flushed to the client before the process
    image is replaced. Re-exec (rather than os.kill/exit) is used
    deliberately so this works whether or not a supervisor like systemd is
    watching the process.
    """

    def _do_restart() -> None:
        _log.warning("Restart requested: re-executing %s", module)
        os.execv(sys.executable, [sys.executable, "-m", module])

    asyncio.get_event_loop().call_later(0.25, _do_restart)


class DisplayStatus(BaseModel):
    """Response body for GET /status."""

    paired_server: Optional[str]
    """IP address of the paired server, or None if not paired."""
    online: bool
    current_item: Optional[str]
    current_item_id: Optional[str]
    """Media id of the currently displayed item (for a dashboard thumbnail)."""
    queue_depth: int
    paused: bool
    history_count: int
    mode: str
    """Playback mode: 'all' | 'single' | 'playlist'."""


class PlaylistBody(BaseModel):
    """Request body for POST /slideshow/playlist."""

    item_ids: list[str]
    loop: bool = False
    """When False (default) the slideshow plays through once and then the
    display returns to the whole library; when True it repeats forever until
    the viewer presses "play all"."""


class DisplayHistoryEntry(BaseModel):
    item_repr: str


def build_app(
    slideshow: Slideshow,
    toast: Optional[Toast] = None,
    make_producer: Optional[Callable[..., Optional[ProducerType]]] = None,
    server_url: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    display_ctx: Optional[DisplayContext] = None,
) -> FastAPI:
    """Build and return the FastAPI application wired to *slideshow*.

    *toast*, when provided, is updated on each control action so the display
    paints on-screen confirmation of dashboard button taps. *make_producer*,
    when provided, builds a server producer (optionally for a specific ordered
    list of item ids) so the display can show a single photo or a programmed
    slideshow on demand.

    *server_url* and *http_client*, when both given, enable the display's own
    GET /dashboard page: a second accessor to the paired server's photo
    library, hosted on the display itself. Library/browse calls are proxied
    to the paired server (see ``_forward_media``); slideshow controls hit
    this app's own /slideshow/* routes directly.
    """
    app = FastAPI(title="Malmberg Display", version=__version__)
    state = {"mode": "all"}
    # Pending "single photo -> back to the full slideshow" timer, so a manually
    # shown photo does not stay up forever (a non-technical viewer never has to
    # find the "play all" button). Reset on every source switch.
    revert: dict[str, Optional[asyncio.Task]] = {"task": None}

    def _notify(message: str) -> None:
        if toast is not None:
            toast.show(message)

    def _cancel_revert() -> None:
        task = revert["task"]
        if task is not None and not task.done():
            task.cancel()
        revert["task"] = None

    def _revert_to_all() -> None:
        """Fall back to the whole-library slideshow (used by both revert timers)."""
        revert["task"] = None  # firing now; nothing left to cancel
        if make_producer is None:
            return
        producer = make_producer(None)
        if producer is None:
            return
        _switch(producer, "all", "Back to all photos")

    async def _auto_revert_after(delay: float) -> None:
        """After *delay*s still in single mode, fall back to the whole library."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if state["mode"] != "single":
            return
        _log.info("Auto-reverting from single photo to the full slideshow")
        _revert_to_all()

    async def _revert_after_playlist(count: int) -> None:
        """Once *count* fresh items have played, fall back to the whole library.

        Used for a non-looping programmed slideshow so it plays through exactly
        once and then the display returns to the full library on its own.
        """
        target = slideshow.displayed_count + count
        try:
            while slideshow.displayed_count < target:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return
        if state["mode"] != "playlist":
            return
        _log.info("Programmed slideshow finished a pass; reverting to full library")
        _revert_to_all()

    def _switch(producer: ProducerType, mode: str, message: str) -> None:
        """Swap the producer and preempt the current photo immediately."""
        slideshow.set_producer(producer)
        slideshow.flush()
        slideshow.resume()
        slideshow.skip()
        state["mode"] = mode
        # Video audio plays only when the user manually picks a single item to
        # show; the automatic slideshow (all / playlist) stays muted.
        if display_ctx is not None:
            display_ctx.mute_video = mode != "single"
        # A manually shown single photo auto-reverts to the full slideshow after
        # a minute; any other switch just clears the pending timer.
        _cancel_revert()
        if mode == "single" and make_producer is not None:
            revert["task"] = asyncio.create_task(
                _auto_revert_after(_AUTO_REVERT_SINGLE_S)
            )
        _notify(message)

    @app.get("/")
    async def root() -> Tag:
        return Tag(
            name="Malmberg Display",
            id="display",
            version=__version__,
            mac=get_mac_address(),
        )

    @app.get("/status")
    async def status() -> DisplayStatus:
        current = slideshow.current
        return DisplayStatus(
            paired_server=None,
            online=True,
            current_item=repr(current) if current else None,
            current_item_id=getattr(current, "item_id", None),
            queue_depth=slideshow.queue_depth,
            paused=slideshow.is_paused,
            history_count=len(slideshow.history),
            mode=state["mode"],
        )

    @app.post("/admin/restart")
    async def admin_restart() -> dict[str, str]:
        """Acknowledge, then re-exec this process (see _schedule_self_restart)."""
        _log.warning("Display restart requested via /admin/restart")
        _schedule_self_restart("malmberg_display")
        return {"status": "restarting"}

    @app.post("/slideshow/next")
    async def next_item() -> dict[str, str]:
        """Advance: forward through rewound history first, else a fresh item."""
        slideshow.resume()
        if not slideshow.show_next_in_history():
            slideshow.skip()  # already live: pull the next fresh item
        _notify("Next")
        return {"status": "ok"}

    def _require_producer() -> Callable[..., Optional[ProducerType]]:
        if make_producer is None:
            raise HTTPException(
                status_code=409,
                detail="Display is not in server mode; cannot switch source",
            )
        return make_producer

    @app.post("/slideshow/show/{item_id}")
    async def show_item(item_id: str) -> dict[str, str]:
        """Show a single photo now (a one-item slideshow), preempting the queue."""
        factory = _require_producer()
        _switch(factory([item_id]), "single", "Showing photo")
        return {"status": "ok", "item_id": item_id}

    @app.post("/slideshow/playlist")
    async def play_playlist(body: PlaylistBody) -> dict[str, object]:
        """Play a programmed slideshow of these item ids, in order.

        By default (``loop`` false) it plays through once and the display then
        returns to the whole library; ``loop`` true repeats it forever until the
        viewer presses "play all".
        """
        factory = _require_producer()
        if body.loop:
            message = 'Looping this slideshow. Press "Play whole library" to stop.'
        else:
            message = "Playing slideshow, then back to all photos"
        _switch(factory(body.item_ids, loop=body.loop), "playlist", message)
        if not body.loop and body.item_ids:
            revert["task"] = asyncio.create_task(
                _revert_after_playlist(len(body.item_ids))
            )
        return {"status": "ok", "count": len(body.item_ids)}

    @app.post("/slideshow/all")
    async def play_all() -> dict[str, str]:
        """Revert to playing the whole library."""
        factory = _require_producer()
        _switch(factory(None), "all", "Playing all photos")
        return {"status": "ok"}

    @app.post("/slideshow/prev")
    async def prev_item() -> dict[str, str]:
        if not slideshow.show_previous():
            if toast is not None:
                toast.show("No earlier photos -- start of history", duration_s=4.0)
            raise HTTPException(
                status_code=409, detail="Already at the earliest photo in history"
            )
        slideshow.resume()
        _notify("Previous")
        return {"status": "ok"}

    @app.post("/slideshow/pause")
    async def toggle_pause() -> dict[str, str]:
        if slideshow.is_paused:
            slideshow.resume()
            _notify("Resumed")
            return {"status": "resumed"}
        slideshow.pause()
        _notify("Paused")
        return {"status": "paused"}

    @app.get("/history")
    async def history() -> list[DisplayHistoryEntry]:
        return [DisplayHistoryEntry(item_repr=repr(i)) for i in slideshow.history]

    # ------------------------------------------------------------------
    # Library proxy: lets the display's own /dashboard browse, inspect, and
    # delete photos on the paired server without the display owning a
    # MediaStore of its own. Only wired up when both server_url and
    # http_client are supplied (i.e. the display is in server-paired mode).
    # ------------------------------------------------------------------

    def _require_server() -> tuple[str, httpx.AsyncClient]:
        if server_url is None or http_client is None:
            raise HTTPException(
                status_code=503,
                detail="Display is not paired with a server; library unavailable",
            )
        return server_url, http_client

    async def _proxy_json(
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: object = None,
    ) -> object:
        """Forward a JSON request to the paired server and return its body.

        Raises HTTPException(503) if unpaired, or 502 if the server could
        not be reached (mirrors the server's own _forward_to_display).
        """
        base, client = _require_server()
        url = base.rstrip("/") + path
        try:
            resp = await client.request(
                method, url, timeout=10.0, params=params, json=json
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            _log.error("Failed to reach paired server at %s: %s", url, exc)
            raise HTTPException(
                status_code=502, detail="Could not reach paired server"
            ) from exc

    async def _proxy_stream(path: str, params: Optional[dict] = None) -> Response:
        """Forward a GET to the paired server and stream the response bytes back."""
        base, client = _require_server()
        url = base.rstrip("/") + path
        try:
            req = client.build_request("GET", url, params=params, timeout=15.0)
            resp = await client.send(req, stream=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            _log.error("Failed to reach paired server at %s: %s", url, exc)
            raise HTTPException(
                status_code=502, detail="Could not reach paired server"
            ) from exc
        return StreamingResponse(
            resp.aiter_bytes(),
            media_type=resp.headers.get("content-type", "application/octet-stream"),
            background=resp.aclose,
        )

    @app.post("/control/restart-server")
    async def proxy_restart_server() -> object:
        """Proxy: ask the paired server to restart itself via its /admin/restart."""
        return await _proxy_json("POST", "/admin/restart")

    @app.get("/media")
    async def proxy_list_media(request: Request) -> object:
        """Proxy: list library pages from the paired server (browse grid)."""
        return await _proxy_json("GET", "/media", params=dict(request.query_params))

    @app.get("/media/trash")
    async def proxy_list_trash(request: Request) -> object:
        """Proxy: list trashed (soft-deleted) items from the paired server."""
        return await _proxy_json(
            "GET", "/media/trash", params=dict(request.query_params)
        )

    @app.get("/media/{item_id}/thumb")
    async def proxy_media_thumb(
        item_id: str, size: int = Query(default=400, ge=64, le=1024)
    ) -> Response:
        """Proxy: stream a thumbnail JPEG from the paired server."""
        return await _proxy_stream(f"/media/{item_id}/thumb", params={"size": size})

    @app.get("/media/{item_id}")
    async def proxy_media_file(item_id: str) -> Response:
        """Proxy: stream the full-resolution original from the paired server."""
        return await _proxy_stream(f"/media/{item_id}")

    @app.get("/media/{item_id}/info")
    async def proxy_media_info(item_id: str) -> object:
        """Proxy: fetch full MediaItem JSON (details modal) from the paired server."""
        return await _proxy_json("GET", f"/media/{item_id}/info")

    @app.get("/stats")
    async def proxy_stats() -> object:
        """Proxy: library-wide stats (counts, date range, by-year) from the server."""
        return await _proxy_json("GET", "/stats")

    @app.get("/places")
    async def proxy_places(request: Request) -> object:
        """Proxy: place-name autocomplete suggestions from the paired server."""
        return await _proxy_json("GET", "/places", params=dict(request.query_params))

    @app.get("/cloud/status")
    async def proxy_cloud_status() -> object:
        """Proxy (read-only): cloud-sync per-provider diagnostics from the server."""
        return await _proxy_json("GET", "/cloud/status")

    @app.get("/cloud/deletable")
    async def proxy_cloud_deletable(request: Request) -> object:
        """Proxy (read-only): dry-run list of cloud items verified safe to delete."""
        return await _proxy_json(
            "GET", "/cloud/deletable", params=dict(request.query_params)
        )

    @app.get("/people")
    async def proxy_people(request: Request) -> object:
        """Proxy: detected people (id, name, count, sample thumbnail)."""
        return await _proxy_json("GET", "/people", params=dict(request.query_params))

    @app.get("/people/suggest")
    async def proxy_suggest_people(request: Request) -> object:
        """Proxy: person-name autocomplete suggestions from the paired server."""
        return await _proxy_json(
            "GET", "/people/suggest", params=dict(request.query_params)
        )

    @app.get("/people/{person_id}/photos")
    async def proxy_person_photos(person_id: str) -> object:
        """Proxy: a person's faces (item_id, bbox, img dims) for the review UI."""
        return await _proxy_json("GET", f"/people/{person_id}/photos")

    @app.post("/people/{person_id}/name")
    async def proxy_name_person(person_id: str, request: Request) -> object:
        """Proxy: assign or change a detected person's display name."""
        body = await request.json()
        return await _proxy_json("POST", f"/people/{person_id}/name", json=body)

    @app.post("/people/{person_id}/merge")
    async def proxy_merge_people(person_id: str, request: Request) -> object:
        """Proxy: merge another person into *person_id*."""
        body = await request.json()
        return await _proxy_json("POST", f"/people/{person_id}/merge", json=body)

    @app.post("/people/recluster")
    async def proxy_recluster_people() -> object:
        """Proxy: rebuild all person groups from the per-face index."""
        return await _proxy_json("POST", "/people/recluster")

    @app.post("/faces/{face_id}/reassign")
    async def proxy_reassign_face(face_id: str, request: Request) -> object:
        """Proxy: reassign or detach a single face's person."""
        body = await request.json()
        return await _proxy_json("POST", f"/faces/{face_id}/reassign", json=body)

    @app.post("/media/{item_id}/transform")
    async def proxy_transform_media(item_id: str, request: Request) -> object:
        """Proxy: permanently rotate/flip an image on the paired server."""
        body = await request.json()
        return await _proxy_json("POST", f"/media/{item_id}/transform", json=body)

    @app.delete("/media/{item_id}")
    async def proxy_delete_media(
        item_id: str, permanent: bool = Query(default=False)
    ) -> object:
        """Proxy: soft- or hard-delete an item on the paired server."""
        return await _proxy_json(
            "DELETE", f"/media/{item_id}", params={"permanent": permanent}
        )

    @app.post("/media/{item_id}/restore")
    async def proxy_restore_media(item_id: str) -> object:
        """Proxy: restore a trashed item on the paired server."""
        return await _proxy_json("POST", f"/media/{item_id}/restore")

    @app.post("/media/bulk-delete")
    async def proxy_bulk_delete(request: Request) -> object:
        """Proxy: soft- or hard-delete multiple items in one call."""
        body = await request.json()
        return await _proxy_json("POST", "/media/bulk-delete", json=body)

    @app.get("/dashboard")
    async def dashboard_page() -> Response:
        """Serve the same dashboard UI as the server, adapted to run on-display.

        Library/browse calls above are proxied to the paired server; the
        page's slideshow controls (next/prev/pause/show/play-all) target this
        app's own /slideshow/* routes directly, since the display can act on
        them without a round trip.
        """
        return Response(
            content=render_dashboard_html(role="display"), media_type="text/html"
        )

    return app
