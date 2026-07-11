"""Tests for malmberg_display.display.picture: decode hardening (HEIC, truncated)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pygame = pytest.importorskip("pygame")

# Headless SDL: no real display attached in CI/dev containers.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from malmberg_display.display.picture import PictureDisplay  # noqa: E402
from malmberg_display.display.proto import LoadContext  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _pygame_display():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


def test_decode_heic(tmp_path: Path) -> None:
    """A synthesized HEIC file decodes to a real pygame surface."""
    try:
        import pillow_heif
        from PIL import Image
    except ImportError:
        pytest.skip("pillow-heif not installed")

    src = tmp_path / "photo.heic"
    heif = pillow_heif.from_pillow(Image.new("RGB", (20, 16), (5, 100, 200)))
    heif.save(src, quality=80)

    display = PictureDisplay(src)
    fg, bg = display._decode()
    assert fg is not None
    assert bg is not None
    assert fg.get_size() == (20, 16)


def test_decode_truncated_image(tmp_path: Path) -> None:
    """A partially-written JPEG still decodes (LOAD_TRUNCATED_IMAGES)."""
    from PIL import Image

    full = tmp_path / "full.jpg"
    Image.new("RGB", (100, 100), (1, 2, 3)).save(full, quality=90)
    data = full.read_bytes()

    # Cut only the tail (pixel scan data), leaving headers intact -- this is
    # the realistic "interrupted upload" shape LOAD_TRUNCATED_IMAGES targets;
    # cutting mid-header instead raises before pixel decode even starts.
    truncated = tmp_path / "truncated.jpg"
    truncated.write_bytes(data[: int(len(data) * 0.9)])

    display = PictureDisplay(truncated)
    decoded = display._decode()
    assert decoded is not None


def test_decode_undecodable_returns_none(tmp_path: Path) -> None:
    """Garbage bytes fail decode cleanly -- None, not a raised exception."""
    src = tmp_path / "garbage.jpg"
    src.write_bytes(b"not an image at all")

    display = PictureDisplay(src)
    assert display._decode() is None


@pytest.mark.asyncio
async def test_load_sets_surface_none_on_bad_file(tmp_path: Path) -> None:
    """load() on an undecodable file leaves the surface None instead of raising."""
    src = tmp_path / "garbage.jpg"
    src.write_bytes(b"not an image at all")

    display = PictureDisplay(src)
    await display.load(LoadContext())
    assert display._surface is None
    assert display._bg is None


@pytest.mark.asyncio
async def test_display_skips_gracefully_on_bad_file(tmp_path: Path) -> None:
    """display() on an undecodable file returns without raising or blitting."""
    from malmberg_display.display.proto import DisplayContext

    src = tmp_path / "garbage.jpg"
    src.write_bytes(b"not an image at all")

    display = PictureDisplay(src)
    ctx = DisplayContext(screen=pygame.display.get_surface(), width=1, height=1)
    # Should return cleanly, not raise.
    await display.display(ctx)
