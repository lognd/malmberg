"""FastAPI application factory for the malmberg_server role."""

from __future__ import annotations

from malmberg_server.api.routes import MediaPatch, ServerStatus, build_app

__all__ = [
    "build_app",
    "MediaPatch",
    "ServerStatus",
]
