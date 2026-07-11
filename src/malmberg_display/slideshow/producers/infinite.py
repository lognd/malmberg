"""InfiniteProducer: wrap any generator and loop it forever, shuffling each cycle."""

from __future__ import annotations

import asyncio
import random
from typing import AsyncGenerator, Callable, Generator

from malmberg_display.display.proto import Displayable

# When an async cycle yields nothing (server has no media yet, or is briefly
# unreachable), wait this long before re-polling instead of terminating.  This
# keeps a freshly-provisioned display alive so it picks up photos as soon as
# they are added, with no restart.
_EMPTY_RETRY_S = 5.0


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

    Unlike the sync variant, an empty cycle does not terminate the generator: a
    server with no media yet (or a transient outage) is not a permanent
    end-of-stream.  It waits ``_EMPTY_RETRY_S`` and re-polls, so newly added
    photos appear without restarting the display.
    """
    while True:
        items: list[Displayable] = []
        async for item in factory():
            items.append(item)
        if not items:
            await asyncio.sleep(_EMPTY_RETRY_S)
            continue
        if shuffle:
            random.shuffle(items)
        for item in items:
            yield item
