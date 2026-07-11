"""Slideshow orchestrator: two asyncio tasks that produce and display items."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterator, Optional, Union, cast

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

ProducerType = Union[Iterator[Displayable], AsyncIterator[Displayable]]


class Slideshow:
    """Manages a produce/display pipeline for a stream of Displayable items.

    Two asyncio coroutines run concurrently:
    - ``produce_target``: calls next(producer) or __anext__(producer), awaits
      item.load(), enqueues.
    - ``display_target``: dequeues and awaits item.display().

    Both sync generators (local directory) and async generators (ServerProducer)
    are accepted; produce_target detects which protocol to use via __anext__.

    History (last 32 items shown) is maintained for backward navigation.
    The active producer can be swapped at runtime via ``set_producer``.
    """

    def __init__(
        self,
        producer: ProducerType,
        load_ctx: LoadContext,
        display_ctx: DisplayContext,
        *,
        max_preload: int = 4,
        history_len: int = 32,
    ) -> None:
        self._producer: ProducerType = producer
        self._load_ctx = load_ctx
        self._display_ctx = display_ctx
        # Queue items are tagged with the producer generation they came from, so
        # items pre-loaded from a superseded source are dropped on dequeue.
        self._queue: asyncio.Queue[tuple[int, Displayable]] = asyncio.Queue(
            maxsize=max_preload
        )
        self._generation = 0
        self._history: list[Displayable] = []
        self._history_len = history_len
        # Cursor into _history for Previous/back-navigation; -1 before anything
        # is shown, otherwise the index of the item currently displayed.
        self._cursor = -1
        self._paused = False
        self._current: Optional[Displayable] = None
        # One-shot item to display next, bypassing the queue (for Previous).
        self._override: Optional[Displayable] = None
        # Set to cut the current item's dwell short (Next / producer switch).
        self._skip: asyncio.Event = asyncio.Event()
        display_ctx.skip_event = self._skip

    def set_producer(self, producer: ProducerType) -> None:
        """Hot-swap the active producer; items from the old one are then dropped."""
        self._producer = producer
        self._generation += 1

    def skip(self) -> None:
        """Cut the current item's dwell short so the next item shows at once."""
        self._skip.set()

    def show_previous(self) -> bool:
        """Step back one item in history and display it. False if at the start."""
        if self._cursor <= 0:
            return False
        self._cursor -= 1
        self._override = self._history[self._cursor]
        self._skip.set()
        return True

    def flush(self) -> None:
        """Discard pre-loaded items so a producer swap takes effect immediately."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

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
        """Continuously pre-load the next item and enqueue it (with its generation)."""
        while True:
            gen = self._generation
            p = self._producer
            try:
                if hasattr(p, "__anext__"):
                    item = await cast(AsyncIterator[Displayable], p).__anext__()
                else:
                    item = next(cast(Iterator[Displayable], p))
            except (StopIteration, StopAsyncIteration):
                await asyncio.sleep(0.1)
                continue
            await item.load(self._load_ctx)
            await self._queue.put((gen, item))

    async def display_target(self) -> None:
        """Dequeue and display items; drop stale-source items; block on pause."""
        while True:
            if self._paused:
                await asyncio.sleep(0.1)
                continue
            if self._override is not None:
                # Back-navigation: show the item without re-recording history.
                item = self._override
                self._override = None
                self._current = item
            else:
                gen, item = await self._queue.get()
                if gen != self._generation:
                    continue  # item is from a producer that has been replaced
                self._current = item
                self._history.append(item)
                if len(self._history) > self._history_len:
                    self._history.pop(0)
                self._cursor = len(self._history) - 1
            self._skip.clear()  # fresh skip window for this item's dwell
            await item.display(self._display_ctx)
