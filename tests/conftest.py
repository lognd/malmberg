"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx


@asynccontextmanager
async def asgi_client(
    app: object, base_url: str = "http://test"
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx.AsyncClient that talks to an ASGI app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        yield client
