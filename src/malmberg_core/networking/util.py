"""Low-level networking utilities: MAC address and UDP broadcast."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Coroutine


def get_mac_address() -> str:
    """Return this machine's primary MAC address as 'AA:BB:CC:DD:EE:FF'."""
    raw = uuid.UUID(int=uuid.getnode()).hex[-12:]
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2)).upper()


async def broadcast_udp(
    payload: dict[str, Any],
    port: int,
    *,
    interval_s: float = 5.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Broadcast *payload* as JSON to the LAN every *interval_s* seconds.

    Runs until *stop_event* is set (or forever if None). Used by the Display
    to announce itself during peer discovery.
    """
    data = json.dumps(payload).encode()
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        local_addr=("0.0.0.0", 0),
        allow_broadcast=True,
    )
    try:
        while stop_event is None or not stop_event.is_set():
            transport.sendto(data, ("<broadcast>", port))
            await asyncio.sleep(interval_s)
    finally:
        transport.close()


async def listen_udp(
    port: int,
    handler: Callable[[bytes, tuple[str, int]], Coroutine[Any, Any, None]],
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Listen for UDP datagrams on *port* and call *handler* for each one.

    *handler* receives the raw bytes and the sender address tuple. Runs until
    *stop_event* is set or the task is cancelled.
    """

    class _Protocol(asyncio.DatagramProtocol):
        def __init__(self) -> None:
            self._loop = asyncio.get_event_loop()

        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            self._loop.create_task(handler(data, addr))

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        _Protocol,
        local_addr=("0.0.0.0", port),
        allow_broadcast=True,
    )
    try:
        while stop_event is None or not stop_event.is_set():
            await asyncio.sleep(1.0)
    finally:
        transport.close()


def parse_broadcast(data: bytes) -> dict[str, Any] | None:
    """Decode a UDP broadcast payload; return None on any parse error."""
    try:
        return json.loads(data.decode())
    except Exception:
        return None
