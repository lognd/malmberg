"""Tag model returned by the root endpoint of every role."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Tag(BaseModel):
    """Identity envelope returned by GET / on any Malmberg node."""

    name: str
    id: Literal["display", "server"]
    version: str
    mac: str
