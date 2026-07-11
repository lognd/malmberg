"""FastAPI routes for the Display role."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from malmberg_core import __version__
from malmberg_core.models import Tag
from malmberg_core.networking import get_mac_address
from malmberg_display.display.toast import Toast
from malmberg_display.slideshow.slideshow import Slideshow


class DisplayStatus(BaseModel):
    """Response body for GET /status."""

    paired_server: Optional[str]
    """IP address of the paired server, or None if not paired."""
    online: bool
    current_item: Optional[str]
    queue_depth: int
    paused: bool
    history_count: int


class DisplayHistoryEntry(BaseModel):
    item_repr: str


def build_app(slideshow: Slideshow, toast: Optional[Toast] = None) -> FastAPI:
    """Build and return the FastAPI application wired to *slideshow*.

    *toast*, when provided, is updated on each control action so the display
    paints on-screen confirmation of dashboard button taps.
    """
    app = FastAPI(title="Malmberg Display", version=__version__)

    def _notify(message: str) -> None:
        if toast is not None:
            toast.show(message)

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
        return DisplayStatus(
            paired_server=None,
            online=True,
            current_item=repr(slideshow.current) if slideshow.current else None,
            queue_depth=slideshow.queue_depth,
            paused=slideshow.is_paused,
            history_count=len(slideshow.history),
        )

    @app.post("/slideshow/next")
    async def next_item() -> dict[str, str]:
        """Skip the current item; the produce task will supply the next one."""
        slideshow.resume()
        _notify("Next")
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
