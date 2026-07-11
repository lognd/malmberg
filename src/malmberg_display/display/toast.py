"""Transient on-screen status message ("toast") shown after a control action.

Shared between the display's HTTP control API (which calls :meth:`Toast.show`
when someone taps Next/Previous/Pause on the dashboard) and the render loop,
which paints the active message in the corner of the screen for a moment so the
operator gets immediate visual confirmation that the click registered.
"""

from __future__ import annotations

import time

_DEFAULT_DURATION_S = 2.5


class Toast:
    """A single most-recent status message with an expiry time."""

    def __init__(self) -> None:
        self._message = ""
        self._expires_at = 0.0

    def show(self, message: str, duration_s: float = _DEFAULT_DURATION_S) -> None:
        """Display *message* for *duration_s* seconds from now."""
        self._message = message
        self._expires_at = time.monotonic() + duration_s

    @property
    def active(self) -> bool:
        """True while the current message is still within its display window."""
        return time.monotonic() < self._expires_at

    @property
    def message(self) -> str:
        """The current message text (may be stale if not :attr:`active`)."""
        return self._message
