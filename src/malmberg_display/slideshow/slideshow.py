"""Slideshow orchestrator: two asyncio tasks that produce and display items."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Generator, Iterator, Optional

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext


class Slideshow:
    """Manages a produce/display pipeline for a stream of Displayable items.

    Two asyncio coroutines run concurrently:
    - ``produce_target``: calls next(producer), awaits item.load(), enqueues.
    - ``display_target``: dequeues and awaits item.display().

    History (last 32 items shown) is maintained for backward navigation.
    The active producer can be swapped at runtime via ``set_producer``.
    """

    def __init__(
        self,
        producer: Generator[Displayable, None, None],
        load_ctx: LoadContext,
        display_ctx: DisplayContext,
        *,
        max_preload: int = 4,
    ) -> None:
        self._producer: Iterator[Displayable] = producer
        self._load_ctx = load_ctx
        self._display_ctx = display_ctx
        self._queue: asyncio.Queue[Displayable] = asyncio.Queue(maxsize=max_preload)
        self._history: deque[Displayable] = deque(maxlen=32)
        self._paused = False
        self._current: Optional[Displayable] = None

    def set_producer(self, producer: Iterator[Displayable]) -> None:
        """Hot-swap the active producer; takes effect on the next produce cycle."""
        self._producer = producer

    def pause(self) -> None:
        """Pause the slideshow; display_target will stop dequeuing."""
        self._paused = True

    def resume(self) -> None:
        """Resume the slideshow."""
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current(self) -> Optional[Displayable]:
        """The item currently being displayed, or None before the first item."""
        return self._current

    @property
    def history(self) -> list[Displayable]:
        """Snapshot of the display history, newest first."""
        return list(reversed(self._history))

    @property
    def queue_depth(self) -> int:
        """Number of pre-loaded items waiting in the queue."""
        return self._queue.qsize()

    async def produce_target(self) -> None:
        """Continuously pre-load the next item and enqueue it."""
        while True:
            try:
                item = next(self._producer)
            except StopIteration:
                await asyncio.sleep(0.1)
                continue
            await item.load(self._load_ctx)
            await self._queue.put(item)

    async def display_target(self) -> None:
        """Dequeue and display items; block on pause."""
        while True:
            if self._paused:
                await asyncio.sleep(0.1)
                continue
            item = await self._queue.get()
            self._current = item
            self._history.append(item)
            await item.display(self._display_ctx)
