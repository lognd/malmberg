"""Regression tests: recovering from single-photo mode on the real display API.

Drives the display FastAPI app (build_app) wired to a real Slideshow, with
make_producer backed by a real ServerProducer + async_load_infinite (the real
production path), against a fake httpx transport serving a small /media
listing.  Reproduces the "stuck on one photo forever" bug reported by the
user: entering single mode via /slideshow/show/{id} and then trying to
recover via /slideshow/show/{other} or /slideshow/all.
"""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from typing import Optional

# Headless SDL: no real display attached in CI/dev containers. Decoding a
# PictureDisplay's image via Pillow/pygame.image.fromstring() does not
# require a display mode to be set, but pygame still needs a video driver
# name it can resolve without an X server.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import httpx
import pytest

from malmberg_display.api.routes import build_app
from malmberg_display.display.proto import DisplayContext, LoadContext
from malmberg_display.slideshow.producers.infinite import async_load_infinite
from malmberg_display.slideshow.producers.server import ServerProducer
from malmberg_display.slideshow.slideshow import ProducerType, Slideshow
from tests.conftest import asgi_client

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)

_MEDIA = {
    "a": {"id": "a", "filename": "a.png"},
    "b": {"id": "b", "filename": "b.png"},
    "c": {"id": "c", "filename": "c.png"},
}


def _fake_transport() -> httpx.MockTransport:
    """A minimal fake malmberg-server: /media listing, /media/{id}, and /media/{id}/info."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/media":
            return httpx.Response(
                200,
                json={"items": list(_MEDIA.values()), "has_next": False},
            )
        if request.url.path.endswith("/info"):
            item_id = request.url.path.split("/")[-2]
            if item_id in _MEDIA:
                return httpx.Response(200, json=_MEDIA[item_id])
            return httpx.Response(404)
        item_id = request.url.path.rsplit("/", 1)[-1]
        if item_id in _MEDIA:
            return httpx.Response(200, content=_TINY_PNG)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def _run_case(cache_dir: Path) -> None:
    client = httpx.AsyncClient(transport=_fake_transport())
    server_url = "http://fake-server"

    def make_server_producer(
        item_ids: Optional[list[str]] = None,
    ) -> Optional[ProducerType]:
        return async_load_infinite(
            lambda: ServerProducer(
                server_url, cache_dir, client, item_ids=item_ids
            ).items()
        )

    initial = make_server_producer(None)
    assert initial is not None
    slideshow = Slideshow(
        producer=initial,
        load_ctx=LoadContext(cache_dir=cache_dir),
        display_ctx=DisplayContext(),
    )

    app = build_app(slideshow, make_producer=make_server_producer)

    produce_task = asyncio.create_task(slideshow.produce_target())
    display_task = asyncio.create_task(slideshow.display_target())

    async def wait_for_current_id(
        c: httpx.AsyncClient, expected_in: set[str], timeout: float = 5.0
    ) -> str:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            r = await c.get("/status")
            cur = r.json()["current_item_id"]
            if cur in expected_in:
                return cur
            await asyncio.sleep(0.05)
        raise AssertionError(
            f"current_item_id never reached {expected_in} within {timeout}s"
        )

    try:
        async with asgi_client(app) as c:
            # Wait for the initial 'all' producer to show something.
            await wait_for_current_id(c, {"a", "b", "c"})

            # Enter single mode on item 'a'.
            r = await c.post("/slideshow/show/a")
            assert r.status_code == 200
            got = await wait_for_current_id(c, {"a"})
            assert got == "a"

            # Recovery path 1: show a different single photo.
            r = await c.post("/slideshow/show/b")
            assert r.status_code == 200
            got = await wait_for_current_id(c, {"b"}, timeout=5.0)
            assert got == "b", "stuck on 'a': show/{other} did not switch item"

            # Recovery path 2: play whole library again.
            r = await c.post("/slideshow/all")
            assert r.status_code == 200
            status = await c.get("/status")
            assert status.json()["mode"] == "all"
            # Should eventually cycle through more than just 'b'.
            seen: set[str] = set()
            deadline = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < deadline and len(seen) < 2:
                s = await c.get("/status")
                cur = s.json()["current_item_id"]
                if cur:
                    seen.add(cur)
                await asyncio.sleep(0.05)
            assert len(seen) >= 2, f"stuck after /slideshow/all, only saw {seen}"
    finally:
        produce_task.cancel()
        display_task.cancel()
        await client.aclose()


@pytest.mark.asyncio
async def test_single_mode_recovery_real_server_producer(tmp_path: Path) -> None:
    """Real ServerProducer + async_load_infinite must recover from single mode."""
    await _run_case(tmp_path)
