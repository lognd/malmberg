"""Gzip for the dashboard's text payloads, and only those.

The dashboard is one large inline-everything HTML file, and every page turn pulls
a JSON blob of full MediaItems; over house Wi-Fi both are worth compressing. The
photo bytes are not: JPEG and MP4 are already compressed, so gzipping them buys
nothing, costs a full pass over a multi-megabyte file on the NAS's CPU (in the
request path, per photo), and would strip the Content-Length that video seeking
depends on.

Starlette's GZipMiddleware excludes only ``text/event-stream``, so it would
happily do exactly that. This narrows it to everything except the two routes that
serve file bytes.
"""

from __future__ import annotations

from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send

from malmberg_core.logging import get_logger

_log = get_logger(__name__)


def serves_file_bytes(path: str) -> bool:
    """True for the routes that stream a media file straight off disk.

    Those are ``GET /media/{id}`` (the original) and ``GET /media/{id}/thumb``.
    Every other ``/media`` route (the listing, ``/info``) is JSON and should be
    compressed like any other text.
    """
    if not path.startswith("/media/"):
        return False
    rest = path[len("/media/") :]
    return "/" not in rest or rest.endswith("/thumb")


class TextOnlyGZipMiddleware(GZipMiddleware):
    """GZipMiddleware that passes the media byte routes through untouched."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and serves_file_bytes(scope.get("path", "")):
            _log.debug("Skipping gzip for media byte route %s", scope.get("path"))
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
