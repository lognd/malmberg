"""Integration tests: UDP broadcast + listen round-trip on loopback."""

from __future__ import annotations

import asyncio
import sys

import pytest

from malmberg_core.networking import broadcast_udp, listen_udp, parse_broadcast

_UDP_PORT = 19456  # non-standard port to avoid conflicts

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="UDP broadcast to loopback is unreliable on Windows",
)


async def test_broadcast_and_listen() -> None:
    received: list[dict] = []
    stop = asyncio.Event()

    async def _handler(data: bytes, addr: tuple[str, int]) -> None:
        parsed = parse_broadcast(data)
        if parsed and not stop.is_set():
            received.append(parsed)
            stop.set()

    payload = {"role": "server", "mac": "AA:BB:CC:DD:EE:FF", "port": 8444}

    async with asyncio.timeout(5.0):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(listen_udp(_UDP_PORT, _handler, stop_event=stop))
            tg.create_task(
                broadcast_udp(payload, _UDP_PORT, interval_s=0.15, stop_event=stop)
            )
            await stop.wait()

    assert len(received) >= 1
    assert received[0]["role"] == "server"
    assert received[0]["port"] == 8444
    assert received[0]["mac"] == "AA:BB:CC:DD:EE:FF"


async def test_listen_stops_on_event() -> None:
    """listen_udp exits promptly when stop_event is set."""
    stop = asyncio.Event()

    async def _noop(data: bytes, addr: tuple[str, int]) -> None:
        pass

    stop.set()
    # Should return immediately (stop already set before call)
    async with asyncio.timeout(2.0):
        await listen_udp(_UDP_PORT + 1, _noop, stop_event=stop)


async def test_broadcast_stops_on_event() -> None:
    """broadcast_udp exits promptly when stop_event is set."""
    stop = asyncio.Event()
    payload = {"role": "display", "mac": "00:11:22:33:44:55", "port": 8443}

    stop.set()
    async with asyncio.timeout(2.0):
        await broadcast_udp(payload, _UDP_PORT + 2, interval_s=1.0, stop_event=stop)


async def test_parse_broadcast_variants() -> None:
    """parse_broadcast handles edge cases correctly."""
    assert parse_broadcast(b"") is None
    assert parse_broadcast(b"not json") is None
    assert parse_broadcast(b"{}") == {}
    valid = b'{"role": "display", "mac": "AA:BB:CC:DD:EE:FF", "port": 8443}'
    result = parse_broadcast(valid)
    assert result is not None
    assert result["role"] == "display"
