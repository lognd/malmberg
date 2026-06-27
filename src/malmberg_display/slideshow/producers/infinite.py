"""InfiniteProducer: wrap any generator and loop it forever, shuffling each cycle."""

from __future__ import annotations

import random
from typing import AsyncGenerator, Callable, Generator

from malmberg_display.display.proto import Displayable


def load_infinite(
    factory: Callable[[], Generator[Displayable, None, None]],
    *,
    shuffle: bool = True,
) -> Generator[Displayable, None, None]:
    """Yield from *factory()* in an infinite loop, optionally shuffling each cycle.

    *factory* is called at the start of each cycle to rebuild the item list.
    This lets the producer pick up new files added to a directory between cycles.
    Use this for sync producers (local directory, cache scan).
    """
    while True:
        items = list(factory())
        if not items:
            return
        if shuffle:
            random.shuffle(items)
        yield from items


async def async_load_infinite(
    factory: Callable[[], AsyncGenerator[Displayable, None]],
    *,
    shuffle: bool = True,
) -> AsyncGenerator[Displayable, None]:
    """Async variant of load_infinite for producers that return async generators.

    *factory* is called at the start of each cycle to collect all items.
    Use this for ServerProducer which fetches over HTTP.
    """
    while True:
        items: list[Displayable] = []
        async for item in factory():
            items.append(item)
        if not items:
            return
        if shuffle:
            random.shuffle(items)
        for item in items:
            yield item
