"""Tests for malmberg_display.slideshow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator

import pytest

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext
from malmberg_display.slideshow.producers.directory import classify_file
from malmberg_display.slideshow.producers.infinite import load_infinite
from malmberg_display.slideshow.slideshow import Slideshow


class _Stub(Displayable):
    def __init__(self, name: str) -> None:
        self.name = name
        self.loaded = False
        self.displayed = False

    async def load(self, ctx: LoadContext) -> None:
        self.loaded = True

    async def display(self, ctx: DisplayContext) -> None:
        self.displayed = True


def _stub_producer(names: list[str]) -> Generator[Displayable, None, None]:
    for n in names:
        yield _Stub(n)


def _make_slideshow(names: list[str]) -> Slideshow:
    return Slideshow(
        producer=_stub_producer(names),
        load_ctx=LoadContext(),
        display_ctx=DisplayContext(),
        max_preload=2,
    )


# -- classify_file -----------------------------------------------------------


def test_classify_image() -> None:
    for ext in (".jpg", ".jpeg", ".png", ".heic", ".webp"):
        assert classify_file(Path(f"photo{ext}")) == "img"


def test_classify_video() -> None:
    for ext in (".mp4", ".mkv", ".mov"):
        assert classify_file(Path(f"clip{ext}")) == "vid"


def test_classify_unknown() -> None:
    assert classify_file(Path("file.txt")) == "na"
    assert classify_file(Path("file")) == "na"


# -- load_infinite -----------------------------------------------------------


def test_load_infinite_loops() -> None:
    items = [_Stub("a"), _Stub("b")]
    gen = load_infinite(lambda: iter(items), shuffle=False)
    result = [next(gen) for _ in range(6)]
    assert [r.name for r in result] == ["a", "b", "a", "b", "a", "b"]


def test_load_infinite_empty_factory_stops() -> None:
    gen = load_infinite(lambda: iter([]))
    with pytest.raises(StopIteration):
        next(gen)


async def test_async_load_infinite_retries_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty first cycle must not end the stream; it retries and recovers."""
    from malmberg_display.slideshow.producers import infinite as inf

    monkeypatch.setattr(inf, "_EMPTY_RETRY_S", 0.0)
    calls = {"n": 0}

    async def factory():  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] >= 2:  # empty on the first cycle, items thereafter
            for name in ("a", "b"):
                yield _Stub(name)

    gen = inf.async_load_infinite(factory, shuffle=False)
    first = await gen.__anext__()
    assert first.name == "a"  # type: ignore[attr-defined]
    assert calls["n"] >= 2  # it retried after the empty cycle
    await gen.aclose()


# -- Slideshow ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_produce_and_display() -> None:
    show = _make_slideshow(["x", "y"])
    task = asyncio.create_task(show.produce_target())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert show.queue_depth > 0


@pytest.mark.asyncio
async def test_pause_resume() -> None:
    show = _make_slideshow(["a"])
    assert not show.is_paused
    show.pause()
    assert show.is_paused
    show.resume()
    assert not show.is_paused


@pytest.mark.asyncio
async def test_set_producer_swaps() -> None:
    show = _make_slideshow(["a"])
    new_items = [_Stub("z")]
    show.set_producer(iter(new_items))
    task = asyncio.create_task(show.produce_target())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert show.queue_depth == 1


@pytest.mark.asyncio
async def test_display_adds_to_history() -> None:
    show = _make_slideshow(["h1", "h2"])
    # Manually enqueue one item to test display_target.
    stub = _Stub("direct")
    await show._queue.put(stub)

    async def _stop_after_one() -> None:
        await show.display_target()

    # display_target is infinite; we cancel after one iteration.
    task = asyncio.create_task(_stop_after_one())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert show.current is stub
    assert stub in show.history
