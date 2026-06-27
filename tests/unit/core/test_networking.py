"""Tests for malmberg_core.networking."""

from __future__ import annotations

from malmberg_core.networking import get_mac_address, parse_broadcast


def test_get_mac_address_format() -> None:
    mac = get_mac_address()
    parts = mac.split(":")
    assert len(parts) == 6
    for part in parts:
        assert len(part) == 2
        int(part, 16)  # must be valid hex


def test_parse_broadcast_valid() -> None:
    data = b'{"role": "display", "mac": "AA:BB:CC:DD:EE:FF", "port": 8443}'
    result = parse_broadcast(data)
    assert result is not None
    assert result["role"] == "display"
    assert result["port"] == 8443


def test_parse_broadcast_invalid() -> None:
    assert parse_broadcast(b"not json") is None
    assert parse_broadcast(b"") is None
    assert parse_broadcast(b"{bad}") is None
