"""DisplayApp: top-level application entrypoint for the display role."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Optional

import httpx
import uvicorn
from typani.unreachable import Unreachable

from malmberg_core.compat import TaskGroup
from malmberg_core.hal import get_hardware_profile
from malmberg_core.logging import get_logger
from malmberg_core.networking import listen_udp, parse_broadcast
from malmberg_display.app.config import DisplayConfig
from malmberg_display.display.overlay import (
    OverlayConfig,
    OverlayRenderer,
    make_geocoder,
)
from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext
from malmberg_display.display.toast import Toast
from malmberg_display.display.video import make_player
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

        overlay_cfg = OverlayConfig(
            show_clock=self._cfg.show_clock,
            show_caption=self._cfg.show_caption,
            show_camera=self._cfg.show_camera,
            clock_position=self._cfg.clock_position,
            font_size_primary=self._cfg.overlay_font_size,
            font_size_secondary=max(16, self._cfg.overlay_font_size - 12),
            font_size_clock=self._cfg.overlay_font_size + 12,
            scrim_alpha=self._cfg.overlay_scrim_alpha,
        )
        overlay_renderer = OverlayRenderer(overlay_cfg)
        geocoder = make_geocoder()

        screen = self._init_screen()
        # Open the screen first: load() pre-composes each frame at the real
        # screen size, so it has to know that size before any item is loaded.
        width = screen.get_width() if screen is not None else self._cfg.width
        height = screen.get_height() if screen is not None else self._cfg.height
        load_ctx = LoadContext(
            cache_dir=cache_dir,
            geocoder=geocoder,
            screen_width=width,
            screen_height=height,
        )
        # One mpv player for the whole run, drawing INTO our pygame window.
        # A per-clip mpv window (the old behaviour) flashed the desktop every
        # time it was created and destroyed, and stuttered.
        mpv_player = make_player(self._window_id(screen), self._profile.hw_video_decode)
        display_ctx = DisplayContext(
            screen=screen,
            width=width,
            height=height,
            fade_duration_s=self._cfg.fade_duration_s,
            dwell_s=self._cfg.dwell_s,
            show_clock=self._cfg.show_clock,
            show_caption=self._cfg.show_caption,
            overlay_renderer=overlay_renderer,
            mpv_player=mpv_player,
            hw_video_decode=self._profile.hw_video_decode,
            video_max_s=self._cfg.video_max_s,
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

            toast = Toast()

            def make_server_producer(
                item_ids: Optional[list[str]] = None,
                loop: bool = True,
            ) -> Optional[ProducerType]:
                """Build a server producer for all items, or a specific id list.

                Returns None when the display is not in server mode (nothing to
                target for show/playlist actions). When *loop* is False the
                producer yields the ids once in order and then ends (a one-pass
                playlist); otherwise it repeats forever, shuffling each cycle.
                """
                url = self._cfg.server_url
                if url is None:
                    return None

                def factory() -> AsyncIterator[Displayable]:
                    return ServerProducer(
                        url,
                        cache_dir,
                        client,
                        item_ids=item_ids,
                        max_items=self._cfg.cache_max_items,
                        max_bytes=self._cfg.cache_max_bytes,
                    ).items()

                if loop:
                    return async_load_infinite(factory)
                return factory()

            uvi_cfg = uvicorn.Config(
                build_app(
                    slideshow,
                    toast=toast,
                    make_producer=make_server_producer,
                    server_url=self._cfg.server_url,
                    http_client=client,
                    display_ctx=display_ctx,
                ),
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
                if display_ctx.screen is not None:
                    tg.create_task(self._pump_events(), name="events")
                    tg.create_task(
                        self._status_task(slideshow, display_ctx), name="status"
                    )
                    tg.create_task(self._toast_task(display_ctx, toast), name="toast")
                if discovery_mode:
                    tg.create_task(
                        self._pairing_task(slideshow, cache_dir),
                        name="discovery",
                    )

    def _window_id(self, screen: Optional[Any]) -> Optional[int]:
        """Return the X11 window id of the pygame window, for embedding mpv."""
        if screen is None:
            return None
        import pygame  # noqa: PLC0415 -- hardware-optional import deferred

        try:
            wid = pygame.display.get_wm_info().get("window")
        except Exception as exc:
            _log.warning("Could not get window id for mpv embedding: %s", exc)
            return None
        return int(wid) if wid else None

    def _init_screen(self) -> Optional[Any]:
        """Open the fullscreen pygame window and return its Surface.

        Returns None if no display can be opened (e.g. headless / no X server),
        so the API and producers still run and the process does not crash.
        """
        import os

        import pygame  # noqa: PLC0415 -- hardware-optional import deferred to runtime

        # No audio device on a photo frame; keep SDL from failing on mixer init.
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        try:
            pygame.display.init()
            pygame.font.init()
            # (0, 0) selects the current desktop resolution for true fullscreen.
            screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        except pygame.error as exc:
            _log.error(
                "Could not open display window (running without a screen): %s", exc
            )
            return None
        w, h = screen.get_size()
        _log.info("Display window initialized: %dx%d fullscreen", w, h)
        return screen

    async def _pump_events(self) -> None:
        """Service the pygame event queue so the window stays responsive."""
        import pygame  # noqa: PLC0415 -- hardware-optional import deferred to runtime

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    _log.info("Display window received QUIT.")
                    return
            await asyncio.sleep(0.05)

    async def _toast_task(self, display_ctx: Any, toast: Toast) -> None:
        """Paint the active toast over the current frame, and clear it on expiry.

        Repaints ~10x/s while a toast is active so it appears immediately after a
        control tap, then repaints the base frame once to erase it. Only touches
        the screen when a message is (or just was) active, so it does not fight
        the slideshow during normal playback.
        """
        import pygame  # noqa: PLC0415 -- hardware-optional import deferred to runtime

        screen = display_ctx.screen
        renderer = display_ctx.overlay_renderer
        if screen is None or renderer is None:
            return
        was_active = False
        while True:
            active = toast.active
            base = display_ctx.base_frame
            # Never draw while the picture renderer owns the screen (fast-forward
            # would otherwise tear); wait for the current frame to settle.
            if display_ctx.rendering:
                await asyncio.sleep(0.05)
                continue
            if active and base is not None:
                screen.blit(base, (0, 0))
                renderer.render_toast(
                    screen, display_ctx.width, display_ctx.height, toast.message
                )
                pygame.display.flip()
            elif was_active and not active and base is not None:
                screen.blit(base, (0, 0))
                pygame.display.flip()
            was_active = active
            await asyncio.sleep(0.1 if active else 0.25)

    async def _status_task(self, slideshow: Slideshow, display_ctx: Any) -> None:
        """Paint an animated status message until the first photo appears.

        Avoids an ambiguous black screen while the display is still connecting
        to the server or waiting for the first item to download.
        """
        import pygame  # noqa: PLC0415 -- hardware-optional import deferred to runtime

        screen = display_ctx.screen
        if screen is None:
            return
        font = pygame.font.SysFont(None, 52)
        cx, cy = display_ctx.width // 2, display_ctx.height // 2
        dots = 0
        while slideshow.current is None:
            dots = (dots % 3) + 1
            screen.fill((12, 13, 16))
            text = font.render(
                "Connecting to your photos" + "." * dots, True, (228, 228, 234)
            )
            screen.blit(text, text.get_rect(center=(cx, cy)))
            pygame.display.flip()
            await asyncio.sleep(0.6)

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
            max_items = self._cfg.cache_max_items
            max_bytes = self._cfg.cache_max_bytes
            return async_load_infinite(
                lambda: ServerProducer(
                    server_url,
                    cache_dir,
                    client,
                    max_items=max_items,
                    max_bytes=max_bytes,
                ).items()
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
            # Persist the discovered URL so make_server_producer (used by the
            # /slideshow/show, /slideshow/playlist, and /slideshow/all API
            # routes) can build server producers after pairing.  Without this,
            # a display that paired via discovery (rather than an explicit
            # server_url) 409s on every dashboard control action forever,
            # since make_server_producer reads self._cfg.server_url and it was
            # never set here.
            self._cfg.server_url = server_url
            cap_items = self._cfg.cache_max_items
            cap_bytes = self._cfg.cache_max_bytes
            slideshow.set_producer(
                async_load_infinite(
                    lambda: ServerProducer(
                        server_url,
                        cache_dir,
                        client,
                        max_items=cap_items,
                        max_bytes=cap_bytes,
                    ).items()
                )
            )
            stop.set()

        _log.info(
            "Listening for server broadcasts on UDP port %d", self._cfg.discovery_port
        )
        await listen_udp(self._cfg.discovery_port, _handler, stop_event=stop)
