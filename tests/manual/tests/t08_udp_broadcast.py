"""t08_udp_broadcast -- send a server broadcast and verify it can be parsed."""

from __future__ import annotations

import asyncio
import sys

from harness import TestContext, TestSkip

TITLE = "UDP broadcast round-trip (loopback)"
DEPENDS: list[str] = ["t01_prereqs"]
INTERACTIVE = False


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t08_udp_broadcast")

    if sys.platform == "win32":
        raise TestSkip("UDP broadcast tests do not run on Windows")

    from malmberg_core.networking import broadcast_udp, listen_udp, parse_broadcast

    received: list[dict] = []
    stop = asyncio.Event()
    port = 19456
    test_payload = {"role": "server", "port": 8444, "version": "test"}

    async def _handler(data: bytes, addr: tuple) -> None:
        payload = parse_broadcast(data)
        if payload is not None and payload.get("role") == "server":
            received.append(payload)
            log.info("Received broadcast from %s: %s", addr, payload)
            stop.set()

    async def _test() -> None:
        listen_task = asyncio.create_task(
            listen_udp(port, _handler, stop_event=stop)
        )
        await asyncio.sleep(0.05)
        log.info("Sending broadcast on port %d...", port)
        broadcast_task = asyncio.create_task(
            broadcast_udp(test_payload, port=port, interval_s=0.1, stop_event=stop)
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            raise AssertionError("Timed out waiting for broadcast to be received")
        listen_task.cancel()
        broadcast_task.cancel()
        for t in (listen_task, broadcast_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    asyncio.run(_test())

    assert received, "No broadcast payload received"
    payload = received[0]
    assert payload.get("role") == "server", f"Expected role='server', got: {payload}"
    assert payload.get("port") == 8444, f"Expected port=8444, got: {payload}"
    log.info("UDP broadcast round-trip OK.")
