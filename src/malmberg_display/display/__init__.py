"""Display rendering primitives for malmberg_display.

Protocol types (Displayable, LoadContext, DisplayContext) are safe to import
at any time. Concrete renderers (PictureDisplay, VideoDisplay, WebDisplay)
require pygame/mpv/playwright and must be imported directly from their modules
to avoid pulling in hardware dependencies at package import time.
"""

from __future__ import annotations

from malmberg_display.display.proto import Displayable, DisplayContext, LoadContext

__all__ = [
    "Displayable",
    "DisplayContext",
    "LoadContext",
]
