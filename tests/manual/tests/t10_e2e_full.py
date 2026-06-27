"""t10_e2e_full -- full system end-to-end: server + display app, real slideshow.

This test starts both the server and the display in separate threads, uploads
a real image to the server, waits for the display to fetch and show it via the
slideshow, then checks that the display API reports a current item.

It requires a working display (pygame) and uses a loopback HTTP connection
between the server and display.

In --no-interactive mode it runs headlessly (no pygame window) and just
validates the API/data flow without rendering.
"""

from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
import time
from pathlib import Path

import httpx
from harness import TestContext

TITLE = "Full system E2E: server + display + slideshow"
DEPENDS: list[str] = ["t09_server_live", "t03_hal_detection"]
INTERACTIVE = False  # We gate pygame on has_display ourselves

_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAAAA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAA"
    "AAD/2gAMAwEAAhEDEQA/AJIAP//Z"
)

_SRV_PORT = 18445
_DSP_PORT = 18446


def _start_server(fs_root: Path) -> None:
    import uvicorn

    from malmberg_server.api.routes import build_app
    from malmberg_server.app.config import ServerConfig

    cfg = ServerConfig(port=_SRV_PORT, fs_root=fs_root)
    app = build_app(cfg)
    uvi_cfg = uvicorn.Config(app, host="127.0.0.1", port=_SRV_PORT, log_config=None)
    server = uvicorn.Server(uvi_cfg)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True).start()


def _wait_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=0.5)
            return
        except (httpx.ConnectError, httpx.ReadError):
            time.sleep(0.1)
    raise AssertionError(f"Service at {url} did not start in {timeout}s")


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t10_e2e_full")

    try:
        import pygame as _pygame_check  # noqa: F401

        has_pygame = True
    except ImportError:
        has_pygame = False

    headless = not has_pygame
    if headless:
        log.warning(
            "Running in headless mode (no display/pygame) -- "
            "data flow will be validated but no pixels rendered."
        )

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        fs_root = tmp / "server_data"
        cache_dir = tmp / "display_cache"
        fs_root.mkdir()
        cache_dir.mkdir()

        # Start server
        log.info("Starting server on port %d...", _SRV_PORT)
        _start_server(fs_root)
        _wait_http(f"http://127.0.0.1:{_SRV_PORT}/")
        log.info("Server up.")

        # Upload an image
        img_bytes = base64.b64decode(_JPEG_B64)
        with httpx.Client(base_url=f"http://127.0.0.1:{_SRV_PORT}", timeout=10.0) as c:
            r = c.post(
                "/media/upload",
                files={"file": ("shot.jpg", img_bytes, "image/jpeg")},
            )
            assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text}"
            item_id = r.json()["id"]
            log.info("Uploaded item id=%s", item_id)

        # Start display app pointing at server
        from malmberg_display.app.app import DisplayApp
        from malmberg_display.app.config import DisplayConfig

        dcfg = DisplayConfig(
            port=_DSP_PORT,
            server_url=f"http://127.0.0.1:{_SRV_PORT}",
            cache_dir=cache_dir,
            dwell_s=1.0,
            fade_duration_s=0.0,
            width=320,
            height=240,
        )

        display_error: list[Exception] = []

        def _display_thread() -> None:
            try:
                DisplayApp(dcfg)()
            except Exception as exc:
                display_error.append(exc)

        log.info("Starting display app on port %d...", _DSP_PORT)
        dt = threading.Thread(target=_display_thread, daemon=True)
        dt.start()

        # Wait for display API to come up
        try:
            _wait_http(f"http://127.0.0.1:{_DSP_PORT}/", timeout=15.0)
        except AssertionError:
            if display_error:
                raise AssertionError(
                    f"Display app crashed: {display_error[0]}"
                ) from display_error[0]
            raise

        log.info("Display app up.")

        # Give slideshow time to fetch and show at least one item
        log.info("Waiting up to 20s for slideshow to process first item...")
        deadline = time.monotonic() + 20.0
        current_id: str | None = None
        with httpx.Client(base_url=f"http://127.0.0.1:{_DSP_PORT}", timeout=5.0) as dc:
            while time.monotonic() < deadline:
                try:
                    r = dc.get("/status")
                    if r.status_code == 200:
                        body = r.json()
                        current = body.get("current")
                        if current is not None:
                            current_id = current
                            log.info("Display current item: %s", current_id)
                            break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)

        if display_error:
            raise AssertionError(
                f"Display app crashed: {display_error[0]}"
            ) from display_error[0]

        assert current_id is not None, (
            "Display never reported a current item within 20s. "
            "Check that ServerProducer can reach the server and that "
            "items are being fetched and queued."
        )

        # Verify the cache file was written
        cached = list(cache_dir.rglob("shot.jpg"))
        assert cached, f"Expected cached file under {cache_dir}, found none"
        log.info("Cached file: %s (%d bytes)", cached[0], cached[0].stat().st_size)

        if ctx.no_interactive or headless:
            log.info("Headless E2E complete -- data flow validated.")
        else:
            ctx.confirm(
                "The display window should be showing the test image. "
                "Check the screen, then press Enter."
            )
            ans = ctx.prompt("Did the display show the uploaded image?")
            assert ans == "y", "User did not confirm image was displayed"

    log.info("Full E2E test OK.")
