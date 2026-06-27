"""t09_server_live -- start the server app, upload a file, verify it appears."""

from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
import time
from pathlib import Path

import httpx

from harness import TestContext, TestSkip

TITLE = "Server app: start, upload, list, fetch"
DEPENDS: list[str] = ["t02_config_load"]
INTERACTIVE = False

# Minimal 1x1 red JPEG (same as t05)
_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAAAA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAA"
    "AAD/2gAMAwEAAhEDEQA/AJIAP//Z"
)

_SERVER_PORT = 18444


def _start_server(fs_root: Path) -> threading.Thread:
    """Run the server in a background thread; returns after uvicorn is up."""
    import uvicorn
    from malmberg_server.app.config import ServerConfig
    from malmberg_server.api.routes import build_app

    cfg = ServerConfig(port=_SERVER_PORT, fs_root=fs_root)
    app = build_app(cfg)
    uvi_cfg = uvicorn.Config(app, host="127.0.0.1", port=_SERVER_PORT, log_config=None)
    server = uvicorn.Server(uvi_cfg)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    def _run() -> None:
        asyncio.run(server.serve())

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # Wait for the server to become ready
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{_SERVER_PORT}/", timeout=0.5)
            return t
        except httpx.ConnectError:
            time.sleep(0.1)
    raise AssertionError("Server did not start within 10 seconds")


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t09_server_live")

    with tempfile.TemporaryDirectory() as _tmp:
        fs_root = Path(_tmp) / "server_data"
        fs_root.mkdir()
        log.info("Starting server on port %d with fs_root=%s", _SERVER_PORT, fs_root)
        _start_server(fs_root)

        base = f"http://127.0.0.1:{_SERVER_PORT}"
        with httpx.Client(base_url=base, timeout=10.0) as client:
            # Root
            r = client.get("/")
            assert r.status_code == 200, f"Root returned {r.status_code}"
            log.info("Root: %s", r.json())

            # Upload
            img_bytes = base64.b64decode(_JPEG_B64)
            r = client.post(
                "/media/upload",
                files={"file": ("test.jpg", img_bytes, "image/jpeg")},
            )
            assert r.status_code == 200, f"Upload returned {r.status_code}: {r.text}"
            item = r.json()
            item_id = item["id"]
            log.info("Uploaded item id=%s filename=%s", item_id, item.get("filename"))

            # List
            r = client.get("/media")
            assert r.status_code == 200
            data = r.json()
            assert data["total"] == 1, f"Expected 1 item, got {data['total']}"
            log.info("List total=%d", data["total"])

            # Fetch file bytes
            r = client.get(f"/media/{item_id}")
            assert r.status_code == 200, f"Fetch returned {r.status_code}"
            assert len(r.content) == len(img_bytes), "File size mismatch"
            log.info("Fetched %d bytes OK.", len(r.content))

            # Delete
            r = client.delete(f"/media/{item_id}")
            assert r.status_code in (200, 204), f"Delete returned {r.status_code}"
            log.info("Deleted item OK.")

            # Confirm deleted
            r = client.get(f"/media/{item_id}")
            assert r.status_code == 404, f"Expected 404 after delete, got {r.status_code}"

    log.info("Server live test OK.")
