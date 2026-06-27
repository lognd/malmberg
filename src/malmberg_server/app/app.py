"""ServerApp: top-level application entrypoint for the server role."""

from __future__ import annotations

import asyncio

import uvicorn
from typani.unreachable import Unreachable

from malmberg_core.hal import get_hardware_profile
from malmberg_core.logging import get_logger
from malmberg_server.app.config import ServerConfig

_log = get_logger(__name__)


class ServerApp:
    """Owns the full lifecycle of the server role.

    Startup order:
    1. Detect hardware profile.
    2. Ensure fs_root directory structure exists.
    3. Start uvicorn serving the FastAPI app.
    """

    def __init__(self, cfg: ServerConfig) -> None:
        self._cfg = cfg
        self._profile = get_hardware_profile()
        _log.info("Hardware profile: %s", self._profile.name)

    def __call__(self) -> Unreachable:
        asyncio.run(self._run())
        return Unreachable()

    async def _run(self) -> None:
        self._ensure_dirs()

        from malmberg_server.api.routes import build_app  # local to break cycle

        uvi_cfg = uvicorn.Config(
            build_app(self._cfg),
            host=self._cfg.host,
            port=self._cfg.port,
            ssl_keyfile=None,
            ssl_certfile=None,
            log_config=None,
        )
        server = uvicorn.Server(uvi_cfg)
        await server.serve()

    def _ensure_dirs(self) -> None:
        """Create the media filesystem layout if it doesn't exist."""
        root = self._cfg.fs_root
        for subdir in ("media", "uploads", "cloud", ".trash", "logs"):
            (root / subdir).mkdir(parents=True, exist_ok=True)
        _log.info("Storage root ready: %s", root)
