"""DisplayApp: top-level application entrypoint for the display role."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
import uvicorn
from typani.unreachable import Unreachable

from malmberg_core.compat import TaskGroup
from malmberg_core.hal import get_hardware_profile
from malmberg_core.logging import get_logger
from malmberg_core.networking import listen_udp, parse_broadcast
from malmberg_display.app.config import DisplayConfig
from malmberg_display.display.proto import DisplayContext, LoadContext
from malmberg_display.slideshow.producers.cache import CacheProducer
from malmberg_display.slideshow.producers.directory import load_flat_from_directory
from malmberg_display.slideshow.producers.infinite import (
    async_load_infinite,
    load_infinite,
)
from malmberg_display.slideshow.producers.server import ServerProducer
from malmberg_display.slideshow.slideshow import ProducerType, Slideshow

_log = get_logger(__name__)


class DisplayApp:
    """Owns the full lifecycle of the display role.

    Startup order:
    1. Detect hardware profile.
    2. Build LoadContext / DisplayContext from config and profile.
    3. Build initial producer (local directory, explicit server URL, or offline cache).
    4. Start Slideshow produce/display tasks.
    5. Start uvicorn serving the FastAPI app.
    6. If in discovery mode, run UDP listen task until a server is found.
    All tasks run in a single asyncio event loop.
    """

    def __init__(self, cfg: DisplayConfig) -> None:
        self._cfg = cfg
        self._profile = get_hardware_profile()
        self._http_client: Optional[httpx.AsyncClient] = None
        _log.info("Hardware profile: %s", self._profile.name)

    def __call__(self) -> Unreachable:
        asyncio.run(self._run())
        return Unreachable()

    async def _run(self) -> None:
        cache_dir = self._cfg.cache_dir.expanduser()
        load_ctx = LoadContext(cache_dir=cache_dir)
        display_ctx = DisplayContext(
            width=self._cfg.width,
            height=self._cfg.height,
            fade_duration_s=self._cfg.fade_duration_s,
            dwell_s=self._cfg.dwell_s,
        )

        async with httpx.AsyncClient() as client:
            self._http_client = client
            producer = self._build_producer(cache_dir)
            slideshow = Slideshow(
                producer=producer,
                load_ctx=load_ctx,
                display_ctx=display_ctx,
                max_preload=self._profile.max_preload_queue,
                history_len=self._cfg.history_len,
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

            discovery_mode = (
                self._cfg.media_dir is None and self._cfg.server_url is None
            )

            async with TaskGroup() as tg:
                tg.create_task(slideshow.produce_target(), name="produce")
                tg.create_task(slideshow.display_target(), name="display")
                tg.create_task(server.serve(), name="api")
                if discovery_mode:
                    tg.create_task(
                        self._pairing_task(slideshow, cache_dir),
                        name="discovery",
                    )

    def _build_producer(self, cache_dir: Any) -> ProducerType:
        """Select the initial media producer based on configuration."""
        if self._cfg.media_dir is not None:
            directory = self._cfg.media_dir.expanduser()
            _log.info("Using local directory producer: %s", directory)
            return load_infinite(lambda: load_flat_from_directory(directory))

        if self._cfg.server_url is not None:
            server_url = self._cfg.server_url
            assert self._http_client is not None
            client = self._http_client
            _log.info("Using server producer: %s", server_url)
            return async_load_infinite(
                lambda: ServerProducer(server_url, cache_dir, client).items()
            )

        _log.warning(
            "No media_dir or server_url configured; starting in offline cache mode."
        )
        return load_infinite(lambda: CacheProducer(cache_dir).items())

    async def _pairing_task(self, slideshow: Slideshow, cache_dir: Any) -> None:
        """Listen for a server UDP broadcast and hot-swap the producer when found."""
        stop = asyncio.Event()
        assert self._http_client is not None
        client = self._http_client

        async def _handler(data: bytes, addr: tuple[str, int]) -> None:
            payload = parse_broadcast(data)
            if payload is None or payload.get("role") != "server":
                return
            host = addr[0]
            port = payload.get("port", 8444)
            server_url = f"http://{host}:{port}"
            _log.info("Discovered server at %s via UDP", server_url)
            slideshow.set_producer(
                async_load_infinite(
                    lambda: ServerProducer(server_url, cache_dir, client).items()
                )
            )
            stop.set()

        _log.info(
            "Listening for server broadcasts on UDP port %d", self._cfg.discovery_port
        )
        await listen_udp(self._cfg.discovery_port, _handler, stop_event=stop)
