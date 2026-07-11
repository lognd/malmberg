"""Regression test: UDP discovery pairing must persist server_url onto DisplayConfig.

Before the fix, DisplayApp._pairing_task hot-swapped the Slideshow producer
directly on discovery but never updated self._cfg.server_url. Since
make_server_producer (wired into the display API as make_producer) reads
self._cfg.server_url on every call, a display that paired via UDP discovery
(rather than an explicit server_url in config) would 409 forever on
/slideshow/show, /slideshow/playlist, and /slideshow/all -- there was no way
to show a different photo or return to the full library after using "show
single photo", because the control routes could never build a new producer.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from malmberg_display.app.app import DisplayApp
from malmberg_display.app.config import DisplayConfig
from malmberg_display.display.proto import DisplayContext, LoadContext
from malmberg_display.slideshow.slideshow import Slideshow


class _NullDisplayable:
    async def load(self, ctx: LoadContext) -> None:
        pass

    async def display(self, ctx: DisplayContext) -> None:
        pass


@pytest.mark.asyncio
async def test_pairing_task_persists_server_url(tmp_path: Path) -> None:
    cfg = DisplayConfig(
        cache_dir=tmp_path,
        media_dir=None,
        server_url=None,  # discovery mode
        discovery_port=0,  # placeholder; replaced below with a free port
    )
    # Grab a free UDP port for the test.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    cfg.discovery_port = port

    app = DisplayApp(cfg)
    app._http_client = None  # not used by the handler path under test

    slideshow = Slideshow(
        producer=iter([_NullDisplayable()]),
        load_ctx=LoadContext(cache_dir=tmp_path),
        display_ctx=DisplayContext(),
    )

    # Give the app a client (pairing task asserts it is not None), but avoid
    # opening real network connections since the discovered producer is not
    # exercised by this test.
    import httpx

    async with httpx.AsyncClient() as client:
        app._http_client = client
        assert cfg.server_url is None

        pairing = asyncio.create_task(app._pairing_task(slideshow, tmp_path))
        await asyncio.sleep(0.2)  # let listen_udp bind the socket

        payload = json.dumps({"role": "server", "port": 8444}).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(payload, ("127.0.0.1", port))
        sock.close()

        deadline = asyncio.get_event_loop().time() + 5.0
        while cfg.server_url is None and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)

        pairing.cancel()
        try:
            await pairing
        except asyncio.CancelledError:
            pass

    assert cfg.server_url is not None, (
        "pairing task discovered a server but never persisted server_url onto "
        "DisplayConfig -- make_server_producer would 409 forever after this"
    )
    assert cfg.server_url.startswith("http://127.0.0.1:8444")
