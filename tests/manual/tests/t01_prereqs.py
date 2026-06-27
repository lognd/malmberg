"""t01_prereqs -- verify all required system dependencies are importable / executable."""

from __future__ import annotations

import importlib
import shutil
import sys

from harness import TestContext

TITLE = "Prerequisites check"
DEPENDS: list[str] = []
INTERACTIVE = False


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t01_prereqs")

    failures: list[str] = []

    # Python version
    log.info("Python version: %s", sys.version)
    if sys.version_info < (3, 10):
        failures.append(f"Python 3.10+ required (got {sys.version_info})")

    # Core Python packages
    py_packages = [
        "fastapi",
        "uvicorn",
        "httpx",
        "pydantic",
        "PIL",  # Pillow
        "typani",
    ]
    for pkg in py_packages:
        try:
            importlib.import_module(pkg)
            log.info("  [ok] %s", pkg)
        except ImportError as exc:
            log.error("  [missing] %s: %s", pkg, exc)
            failures.append(f"Missing Python package: {pkg}")

    # Optional display packages -- warn but do not fail prereqs
    optional = ["pygame", "mpv", "playwright"]
    for pkg in optional:
        try:
            importlib.import_module(pkg)
            log.info("  [ok] %s (optional)", pkg)
        except ImportError:
            log.warning(
                "  [not installed] %s (optional -- some display tests will skip)", pkg
            )

    # System binaries
    bins = ["ffprobe", "ffmpeg"]
    for b in bins:
        path = shutil.which(b)
        if path:
            log.info("  [ok] %s -> %s", b, path)
        else:
            log.warning(
                "  [not found] %s (optional -- video metadata tests will skip)", b
            )

    # Network stack sanity -- can we open a UDP socket?
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.close()
        log.info("  [ok] UDP sockets available")
    except OSError as exc:
        failures.append(f"Cannot open UDP socket: {exc}")

    assert not failures, "\n".join(failures)
    log.info("All prerequisite checks passed.")
