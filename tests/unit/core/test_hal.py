"""Tests for malmberg_core.hal."""

from __future__ import annotations

from malmberg_core.hal.detect import (
    _load_from_toml,
    get_hardware_profile,
    write_hardware_toml,
)
from malmberg_core.hal.errors import HalError
from malmberg_core.hal.profile import HardwareProfile


def test_fallback_profile_is_valid() -> None:
    p = HardwareProfile.fallback()
    assert p.name == "generic-x86"
    assert not p.hw_video_decode
    assert not p.gpio_available
    assert p.status_panel_bus == "none"
    assert p.max_preload_queue > 0
    assert p.playwright_supported


def test_load_from_toml_missing_file(tmp_path) -> None:
    result = _load_from_toml(tmp_path / "nope.toml")
    assert result.is_err
    assert result.danger_err is HalError.FileNotFound


def test_load_from_toml_bad_content(tmp_path) -> None:
    bad = tmp_path / "hardware.toml"
    bad.write_text("not valid toml ][")
    result = _load_from_toml(bad)
    assert result.is_err
    assert result.danger_err is HalError.ParseError


def test_load_from_toml_valid(tmp_path) -> None:
    p = HardwareProfile(
        name="pi-4",
        hw_video_decode=True,
        gpio_available=True,
        status_panel_bus="i2c",
        max_preload_queue=4,
        playwright_supported=True,
    )
    path = tmp_path / "hardware.toml"
    write_hardware_toml(p, path)
    result = _load_from_toml(path)
    assert result.is_ok
    loaded = result.danger_ok
    assert loaded.name == "pi-4"
    assert loaded.hw_video_decode
    assert loaded.status_panel_bus == "i2c"


def test_get_hardware_profile_uses_toml(tmp_path) -> None:
    p = HardwareProfile.fallback()
    path = tmp_path / "hardware.toml"
    write_hardware_toml(p, path)
    loaded = get_hardware_profile(config_path=path)
    assert loaded.name == p.name


def test_get_hardware_profile_falls_back(tmp_path) -> None:
    """No file -> auto-detection -> fallback; should never raise."""
    profile = get_hardware_profile(config_path=tmp_path / "missing.toml")
    assert isinstance(profile, HardwareProfile)


def test_write_hardware_toml_roundtrip(tmp_path) -> None:
    original = HardwareProfile(
        name="test-board",
        hw_video_decode=False,
        gpio_available=True,
        status_panel_bus="spi",
        max_preload_queue=2,
        playwright_supported=False,
    )
    path = tmp_path / "sub" / "hardware.toml"
    write_hardware_toml(original, path)
    result = _load_from_toml(path)
    assert result.is_ok
    rt = result.danger_ok
    assert rt == original
