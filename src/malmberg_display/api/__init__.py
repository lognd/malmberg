"""FastAPI application factory for the malmberg_display role."""

from __future__ import annotations

from malmberg_display.api.routes import DisplayHistoryEntry, DisplayStatus, build_app

__all__ = [
    "build_app",
    "DisplayHistoryEntry",
    "DisplayStatus",
]
