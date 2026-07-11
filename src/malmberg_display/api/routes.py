"""FastAPI routes for the Display role."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.models import Tag
from malmberg_core.networking import get_mac_address
from malmberg_display.display.toast import Toast
from malmberg_display.slideshow.slideshow import ProducerType, Slideshow


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


class DisplayHistoryEntry(BaseModel):
    item_repr: str


def build_app(
    slideshow: Slideshow,
    toast: Optional[Toast] = None,
    make_producer: Optional[
        Callable[..., Optional[ProducerType]]
    ] = None,
) -> FastAPI:
    """Build and return the FastAPI application wired to *slideshow*.

    *toast*, when provided, is updated on each control action so the display
    paints on-screen confirmation of dashboard button taps. *make_producer*,
    when provided, builds a server producer (optionally for a specific ordered
    list of item ids) so the display can show a single photo or a programmed
    slideshow on demand.
    """
    app = FastAPI(title="Malmberg Display", version=__version__)
    state = {"mode": "all"}

    def _notify(message: str) -> None:
        if toast is not None:
            toast.show(message)

    def _switch(producer: ProducerType, mode: str, message: str) -> None:
        """Swap the producer and preempt the current photo immediately."""
        slideshow.set_producer(producer)
        slideshow.flush()
        slideshow.resume()
        slideshow.skip()
        state["mode"] = mode
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

    @app.post("/slideshow/next")
    async def next_item() -> dict[str, str]:
        """Skip the current item immediately; the next one shows at once."""
        slideshow.resume()
        slideshow.skip()
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
        """Play a programmed slideshow: only these item ids, in order, looping."""
        factory = _require_producer()
        _switch(factory(body.item_ids), "playlist", "Playing slideshow")
        return {"status": "ok", "count": len(body.item_ids)}

    @app.post("/slideshow/all")
    async def play_all() -> dict[str, str]:
        """Revert to playing the whole library."""
        factory = _require_producer()
        _switch(factory(None), "all", "Playing all photos")
        return {"status": "ok"}

    @app.post("/slideshow/prev")
    async def prev_item() -> dict[str, str]:
        hist = slideshow.history
        if len(hist) < 2:
            _notify("No previous photo")
            raise HTTPException(status_code=404, detail="No previous item in history")
        _notify("Previous")
        return {"status": "ok", "prev": repr(hist[1])}

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

    return app
