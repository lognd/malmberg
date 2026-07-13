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
async def test_load_sets_frame_none_on_bad_file(tmp_path: Path) -> None:
    """load() on an undecodable file leaves the frame None instead of raising."""
    src = tmp_path / "garbage.jpg"
    src.write_bytes(b"not an image at all")

    display = PictureDisplay(src)
    await display.load(LoadContext())
    assert display._frame is None


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


@pytest.mark.asyncio
async def test_load_precomposes_frame_at_screen_size(tmp_path: Path) -> None:
    """load() leaves a ready-to-blit, screen-sized frame so display() is just a swap."""
    from PIL import Image

    src = tmp_path / "photo.jpg"
    Image.new("RGB", (640, 480), (10, 120, 200)).save(src, "JPEG")

    display = PictureDisplay(src)
    await display.load(LoadContext(screen_width=800, screen_height=600))

    assert display._frame is not None
    assert display._frame.get_size() == (800, 600)


@pytest.mark.asyncio
async def test_display_releases_frame(tmp_path: Path) -> None:
    """The composed frame is dropped once shown: history must not pin surfaces.

    Retaining it per item is what exhausted the Pi's memory (32 history entries
    x a full-screen surface each).
    """
    from PIL import Image

    from malmberg_display.display.proto import DisplayContext

    src = tmp_path / "photo.jpg"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(src, "JPEG")

    display = PictureDisplay(src)
    await display.load(LoadContext(screen_width=1, screen_height=1))
    assert display._frame is not None

    ctx = DisplayContext(
        screen=pygame.display.get_surface(),
        width=1,
        height=1,
        fade_duration_s=0,
        dwell_s=0,
    )
    await display.display(ctx)
    assert display._frame is None


# ---------------------------------------------------------------------------
# Caption location precedence
# ---------------------------------------------------------------------------


def test_caption_prefers_server_place_over_geocoder() -> None:
    """A server-supplied place wins; no local geocoder call is made."""
    from malmberg_display.display.overlay import ImageCaption

    def boom(lat: float, lon: float) -> str:
        raise AssertionError("geocoder must not be called when place is known")

    cap = ImageCaption.from_metadata(
        None, 27.97, -82.53, None, place="Tampa, Florida, US", geocoder=boom
    )
    assert cap.location_label == "Tampa, Florida, US"


def test_caption_falls_back_to_coordinates_without_place() -> None:
    """With no server place and no working geocoder, show decimal coordinates."""
    from malmberg_display.display.overlay import ImageCaption

    cap = ImageCaption.from_metadata(None, 27.97, -82.53, None)
    assert cap.location_label == "27.97 N  82.53 W"

    # An empty/whitespace place from the server is treated as absent.
    cap2 = ImageCaption.from_metadata(None, 27.97, -82.53, None, place="  ")
    assert cap2.location_label == "27.97 N  82.53 W"


def test_caption_place_without_coordinates() -> None:
    """A manually-tagged place with no GPS fix still captions the photo."""
    from malmberg_display.display.overlay import ImageCaption

    cap = ImageCaption.from_metadata(None, None, None, None, place="Grandma's house")
    assert cap.location_label == "Grandma's house"
