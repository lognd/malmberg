"""InfiniteProducer: wrap any generator and loop it forever, shuffling each cycle."""

from __future__ import annotations

import random
from typing import Callable, Generator

from malmberg_display.display.proto import Displayable


def load_infinite(
    factory: Callable[[], Generator[Displayable, None, None]],
    *,
    shuffle: bool = True,
) -> Generator[Displayable, None, None]:
    """Yield from *factory()* in an infinite loop, optionally shuffling each cycle.

    *factory* is called at the start of each cycle to rebuild the item list.
    This lets the producer pick up new files added to a directory between cycles.
    """
    while True:
        items = list(factory())
        if not items:
            return
        if shuffle:
            random.shuffle(items)
        yield from items
