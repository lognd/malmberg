"""Integration tests: display FastAPI app with a real (but minimal) Slideshow."""

from __future__ import annotations

from malmberg_core import __version__
from malmberg_display.api.routes import build_app
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext
from malmberg_display.slideshow.slideshow import Slideshow
from tests.conftest import asgi_client


class NullDisplayable(Displayable):
    """Displayable that does nothing; used to build a real Slideshow cheaply."""

    async def load(self, ctx: LoadContext) -> None:
        pass

    async def display(self, ctx: DisplayContext) -> None:
        pass


def _make_slideshow() -> Slideshow:
    return Slideshow(
        producer=iter([NullDisplayable()]),
        load_ctx=LoadContext(),
        display_ctx=DisplayContext(),
    )


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


async def test_root() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r = await c.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "display"
    assert data["version"] == __version__
    assert "mac" in data


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


async def test_status_initial() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r = await c.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert data["paused"] is False
    assert data["queue_depth"] == 0
    assert data["current_item"] is None
    assert data["history_count"] == 0
    assert data["online"] is True


# ---------------------------------------------------------------------------
# POST /slideshow/pause  (toggle)
# ---------------------------------------------------------------------------


async def test_pause_toggle() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r1 = await c.post("/slideshow/pause")
        assert r1.status_code == 200
        assert r1.json()["status"] == "paused"

        r2 = await c.post("/slideshow/pause")
        assert r2.status_code == 200
        assert r2.json()["status"] == "resumed"


# ---------------------------------------------------------------------------
# POST /slideshow/next
# ---------------------------------------------------------------------------


async def test_next_ok() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r = await c.post("/slideshow/next")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /slideshow/prev -- 404 when no history
# ---------------------------------------------------------------------------


async def test_prev_no_history() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r = await c.post("/slideshow/prev")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /history -- empty initially
# ---------------------------------------------------------------------------


async def test_history_empty() -> None:
    app = build_app(_make_slideshow())
    async with asgi_client(app) as c:
        r = await c.get("/history")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Pause persists across requests (state is shared via slideshow reference)
# ---------------------------------------------------------------------------


async def test_pause_state_shared() -> None:
    slideshow = _make_slideshow()
    app = build_app(slideshow)
    async with asgi_client(app) as c:
        await c.post("/slideshow/pause")
        status = await c.get("/status")
    assert status.json()["paused"] is True
    assert slideshow.is_paused is True

# ---------------------------------------------------------------------------
# Toast feedback on control actions
# ---------------------------------------------------------------------------


async def test_control_sets_toast() -> None:
    from malmberg_display.display.toast import Toast

    toast = Toast()
    app = build_app(_make_slideshow(), toast=toast)
    async with asgi_client(app) as c:
        r = await c.post("/slideshow/pause")
    assert r.status_code == 200
    assert toast.active
    assert toast.message == "Paused"


# ---------------------------------------------------------------------------
# Source-switching controls (show single / playlist / all)
# ---------------------------------------------------------------------------


def _fake_producer(item_ids=None):
    """Stand-in producer factory for control tests."""
    return iter([NullDisplayable()])


async def test_show_and_playlist_and_all_switch_mode() -> None:
    ss = _make_slideshow()
    app = build_app(ss, make_producer=_fake_producer)
    async with asgi_client(app) as c:
        r1 = await c.post("/slideshow/show/abc123")
        assert r1.status_code == 200 and r1.json()["item_id"] == "abc123"
        s1 = await c.get("/status")
        assert s1.json()["mode"] == "single"

        r2 = await c.post("/slideshow/playlist", json={"item_ids": ["a", "b", "c"]})
        assert r2.status_code == 200 and r2.json()["count"] == 3
        assert (await c.get("/status")).json()["mode"] == "playlist"

        r3 = await c.post("/slideshow/all")
        assert r3.status_code == 200
        assert (await c.get("/status")).json()["mode"] == "all"


async def test_show_requires_server_mode() -> None:
    app = build_app(_make_slideshow())  # no make_producer
    async with asgi_client(app) as c:
        r = await c.post("/slideshow/show/abc")
    assert r.status_code == 409
