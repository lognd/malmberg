"""UDP discovery payload models shared between server and display."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class DiscoveryPayload(BaseModel):
    """Payload broadcast over UDP during peer discovery."""

    role: Literal["display", "server"]
    mac: str
    port: int
    pin: Optional[str] = None
    """6-digit pairing PIN included by Display after user entry."""
