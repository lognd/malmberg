"""Tests for malmberg_display.api.routes: dashboard hosting + library proxy."""

from __future__ import annotations

import sys
from typing import Generator

import httpx
import pytest
from fastapi.testclient import TestClient

from malmberg_display.api import routes as routes_module
from malmberg_display.api.routes import build_app
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext
from malmberg_display.slideshow.slideshow import Slideshow


class _Stub(Displayable):
    async def load(self, ctx: LoadContext) -> None:
        return None

    async def display(self, ctx: DisplayContext) -> None:
        return None


def _empty_producer() -> Generator[Displayable, None, None]:
    return
    yield  # pragma: no cover -- makes this a generator function


def _make_slideshow() -> Slideshow:
    return Slideshow(
        producer=_empty_producer(),
        load_ctx=LoadContext(),
        display_ctx=DisplayContext(),
        max_preload=2,
    )


def _client(server_url: object = None, http_client: object = None) -> TestClient:
    app = build_app(
        _make_slideshow(),
        server_url=server_url,
        http_client=http_client,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# /dashboard
# ---------------------------------------------------------------------------


def test_dashboard_page_served_by_display() -> None:
    r = _client().get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'MALMBERG_ROLE = "display"' in r.text
    assert 'id="grid"' in r.text


# ---------------------------------------------------------------------------
# Library proxy: unpaired (no server_url/http_client) -> 503
# ---------------------------------------------------------------------------


def test_proxy_media_503_when_unpaired() -> None:
    c = _client()
    assert c.get("/media").status_code == 503
    assert c.get("/stats").status_code == 503
    assert c.get("/media/abc/info").status_code == 503
    assert c.delete("/media/abc").status_code == 503


# ---------------------------------------------------------------------------
# Library proxy: paired, forwards to the paired server
# ---------------------------------------------------------------------------


def _mock_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_proxy_list_media_forwards_to_server() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"items": [], "total": 0})

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.get("/media", params={"page": 2})
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}
    assert seen["url"].startswith("http://server.local:8444/media")
    assert "page=2" in seen["url"]


def test_proxy_media_thumb_streams_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/media/xyz/thumb"
        return httpx.Response(
            200, content=b"\xff\xd8\xff", headers={"content-type": "image/jpeg"}
        )

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.get("/media/xyz/thumb")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff"
    assert r.headers["content-type"] == "image/jpeg"


def test_proxy_media_file_streams_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/media/xyz"
        return httpx.Response(200, content=b"filebytes")

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.get("/media/xyz")
    assert r.status_code == 200
    assert r.content == b"filebytes"


def test_proxy_delete_and_restore_and_trash() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/media/trash":
            return httpx.Response(200, json={"items": [], "total": 0})
        if request.url.path.endswith("/restore"):
            return httpx.Response(200, json={"id": "xyz", "trashed_at": None})
        return httpx.Response(200, json={"status": "trashed", "id": "xyz"})

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)

    assert c.delete("/media/xyz").status_code == 200
    assert c.get("/media/trash").status_code == 200
    assert c.post("/media/xyz/restore").status_code == 200
    assert ("DELETE", "/media/xyz") in calls
    assert ("GET", "/media/trash") in calls
    assert ("POST", "/media/xyz/restore") in calls


def test_proxy_bulk_delete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/media/bulk-delete"
        return httpx.Response(200, json={"deleted": ["a"], "failed": []})

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.post("/media/bulk-delete", json={"ids": ["a"]})
    assert r.status_code == 200
    assert r.json() == {"deleted": ["a"], "failed": []}


def test_proxy_502_when_server_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.get("/media")
    assert r.status_code == 502


def test_proxy_restart_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/admin/restart"
        return httpx.Response(200, json={"status": "restarting"})

    client = _mock_transport(handler)
    c = _client(server_url="http://server.local:8444", http_client=client)
    r = c.post("/control/restart-server")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"


# ---------------------------------------------------------------------------
# Self-restart
# ---------------------------------------------------------------------------


def test_admin_restart_triggers_execv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        routes_module.os, "execv", lambda path, argv: calls.append(argv)
    )

    class _ImmediateLoop:
        def call_later(self, delay: float, fn) -> None:
            fn()

    monkeypatch.setattr(
        routes_module.asyncio, "get_event_loop", lambda: _ImmediateLoop()
    )

    r = _client().post("/admin/restart")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
    assert calls == [[sys.executable, "-m", "malmberg_display"]]
