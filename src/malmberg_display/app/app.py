"""DisplayApp: top-level application entrypoint for the display role."""

from __future__ import annotations

import asyncio

import uvicorn
from typani.unreachable import Unreachable

from malmberg_core.hal import get_hardware_profile
from malmberg_core.logging import get_logger
from malmberg_display.app.config import DisplayConfig
from malmberg_display.display.proto import DisplayContext, LoadContext
from malmberg_display.slideshow.producers.directory import load_flat_from_directory
from malmberg_display.slideshow.producers.infinite import load_infinite
from malmberg_display.slideshow.slideshow import Slideshow

_log = get_logger(__name__)


class DisplayApp:
    """Owns the full lifecycle of the display role.

    Startup order:
    1. Detect hardware profile.
    2. Build LoadContext / DisplayContext from config and profile.
    3. Build initial producer (local directory or wait for server pairing).
    4. Start Slideshow produce/display tasks.
    5. Start uvicorn serving the FastAPI app.
    All tasks run in a single asyncio event loop.
    """

    def __init__(self, cfg: DisplayConfig) -> None:
        self._cfg = cfg
        self._profile = get_hardware_profile()
        _log.info("Hardware profile: %s", self._profile.name)

    def __call__(self) -> Unreachable:
        asyncio.run(self._run())
        return Unreachable()

    async def _run(self) -> None:
        load_ctx = LoadContext(cache_dir=self._cfg.cache_dir.expanduser())
        display_ctx = DisplayContext(
            width=self._cfg.width,
            height=self._cfg.height,
            fade_duration_s=self._cfg.fade_duration_s,
            dwell_s=self._cfg.dwell_s,
        )

        producer = self._build_producer()
        slideshow = Slideshow(
            producer=producer,
            load_ctx=load_ctx,
            display_ctx=display_ctx,
            max_preload=self._profile.max_preload_queue,
        )

        from malmberg_display.api.routes import build_app  # local to break cycle

        uvi_cfg = uvicorn.Config(
            build_app(slideshow),
            host=self._cfg.host,
            port=self._cfg.port,
            ssl_keyfile=None,
            ssl_certfile=None,
            log_config=None,
        )
        server = uvicorn.Server(uvi_cfg)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(slideshow.produce_target(), name="produce")
            tg.create_task(slideshow.display_target(), name="display")
            tg.create_task(server.serve(), name="api")

    def _build_producer(self):  # type: ignore[return]
        if self._cfg.media_dir is not None:
            directory = self._cfg.media_dir.expanduser()
            return load_infinite(lambda: load_flat_from_directory(directory))
        _log.warning(
            "No media_dir configured; slideshow will be empty until a server pairs."
        )
        return iter([])
