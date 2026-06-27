"""Producers that yield Displayable items from a local directory.

PictureDisplay and VideoDisplay are imported inside the generator body so that
this module can be imported in test environments where pygame/mpv are not
installed. The hardware packages are only required when the generator actually
runs (i.e. at display startup time, after provisioning).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Generator, Iterable, Literal

if TYPE_CHECKING:
    from malmberg_display.display.proto import Displayable

_IMAGE_EXTS = frozenset(
    {".png", ".jpg", ".jpeg", ".heic", ".webp", ".heif", ".avif", ".tiff"}
)
_VIDEO_EXTS = frozenset(
    {".mp4", ".mkv", ".mov", ".m4v", ".qt", ".avi", ".wmv", ".webm"}
)


def classify_file(file: Path) -> Literal["vid", "img", "na"]:
    """Return the media kind for *file* based on its extension."""
    ext = file.suffix.lower()
    if ext in _IMAGE_EXTS:
        return "img"
    if ext in _VIDEO_EXTS:
        return "vid"
    return "na"


def _from_paths(paths: Iterable[Path]) -> Generator[Displayable, None, None]:
    from malmberg_display.display.picture import PictureDisplay
    from malmberg_display.display.video import VideoDisplay

    for path in paths:
        if not path.is_file():
            continue
        kind = classify_file(path)
        if kind == "img":
            yield PictureDisplay(path)
        elif kind == "vid":
            yield VideoDisplay(path)


def load_flat_from_directory(directory: Path) -> Generator[Displayable, None, None]:
    """Yield one Displayable per media file in *directory* (non-recursive)."""
    yield from _from_paths(directory.iterdir())


def load_recr_from_directory(directory: Path) -> Generator[Displayable, None, None]:
    """Yield one Displayable per media file found recursively under *directory*."""
    yield from _from_paths(directory.rglob("*"))
