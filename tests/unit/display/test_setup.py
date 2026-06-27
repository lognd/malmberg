"""Unit tests for malmberg_display.setup."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from malmberg_core.hal.profile import HardwareProfile
from malmberg_display.setup import (
    _step_enable,
    _step_hardware,
    _step_mpv_conf,
    _step_no_blanking,
    _step_playwright,
    _step_unit,
    run,
)

_FALLBACK = HardwareProfile.fallback()
_PI4 = HardwareProfile(
    name="pi-4",
    hw_video_decode=True,
    gpio_available=True,
    status_panel_bus="i2c",
    max_preload_queue=4,
    playwright_supported=True,
)
_PI_ZERO = HardwareProfile(
    name="pi-zero-2w",
    hw_video_decode=False,
    gpio_available=True,
    status_panel_bus="i2c",
    max_preload_queue=2,
    playwright_supported=False,
)


def _mock_proc(rc: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = rc
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# _step_hardware
# ---------------------------------------------------------------------------


def test_step_hardware_detected() -> None:
    with (
        patch("malmberg_display.setup._detect_profile") as mock_detect,
        patch("malmberg_display.setup.write_hardware_toml") as mock_write,
    ):
        from typani.result import Ok

        mock_detect.return_value = Ok(_PI4)
        warnings: list[str] = []
        result = _step_hardware(dry=True, warnings=warnings)

    assert result.name == "pi-4"
    assert warnings == []
    mock_write.assert_not_called()


def test_step_hardware_fallback_warns() -> None:
    with (
        patch("malmberg_display.setup._detect_profile") as mock_detect,
        patch("malmberg_display.setup.write_hardware_toml"),
    ):
        from typani.result import Err

        from malmberg_core.hal.errors import HalError

        mock_detect.return_value = Err(HalError.DetectionFailed)
        warnings: list[str] = []
        result = _step_hardware(dry=False, warnings=warnings)

    assert result.name == "generic-x86"
    assert any("auto-detection failed" in w for w in warnings)


# ---------------------------------------------------------------------------
# _step_no_blanking
# ---------------------------------------------------------------------------


def test_step_no_blanking_already_present(tmp_path: Path) -> None:
    conf = tmp_path / "10-malmberg-no-blanking.conf"
    conf.write_text("existing")
    warnings: list[str] = []
    with patch("malmberg_display.setup._XORG_BLANKING_CONF", conf):
        _step_no_blanking(dry=False, warnings=warnings)
    assert conf.read_text() == "existing"


def test_step_no_blanking_writes_conf(tmp_path: Path) -> None:
    conf = tmp_path / "10-malmberg-no-blanking.conf"
    warnings: list[str] = []
    with (
        patch("malmberg_display.setup._XORG_BLANKING_CONF", conf),
        patch("malmberg_display.setup._XORG_CONF_DIR", tmp_path),
        patch("malmberg_display.setup.Path") as _mock_path,
    ):
        # Ensure Pi boot config paths don't exist so we skip that branch.
        _step_no_blanking(dry=False, warnings=warnings)
    assert conf.is_file()
    assert "BlankTime" in conf.read_text()


def test_step_no_blanking_dry_run_noop(tmp_path: Path) -> None:
    conf = tmp_path / "10-malmberg-no-blanking.conf"
    warnings: list[str] = []
    with (
        patch("malmberg_display.setup._XORG_BLANKING_CONF", conf),
        patch("malmberg_display.setup._XORG_CONF_DIR", tmp_path),
    ):
        _step_no_blanking(dry=True, warnings=warnings)
    assert not conf.exists()


# ---------------------------------------------------------------------------
# _step_mpv_conf
# ---------------------------------------------------------------------------


def test_step_mpv_conf_hw_decode(tmp_path: Path) -> None:
    with patch("malmberg_display.setup._user_home", return_value=tmp_path):
        path = _step_mpv_conf(_PI4, "pi", dry=False)
    content = path.read_text()
    assert "hwdec=auto" in content


def test_step_mpv_conf_no_hw_decode(tmp_path: Path) -> None:
    with patch("malmberg_display.setup._user_home", return_value=tmp_path):
        path = _step_mpv_conf(_PI_ZERO, "pi", dry=False)
    content = path.read_text()
    assert "hwdec=no" in content


def test_step_mpv_conf_dry_run(tmp_path: Path) -> None:
    with patch("malmberg_display.setup._user_home", return_value=tmp_path):
        path = _step_mpv_conf(_PI4, "pi", dry=True)
    assert not path.exists()


# ---------------------------------------------------------------------------
# _step_playwright
# ---------------------------------------------------------------------------


def test_step_playwright_skipped_on_unsupported() -> None:
    msg = _step_playwright(_PI_ZERO, dry=False, warnings=[])
    assert "not supported" in msg


def test_step_playwright_already_installed() -> None:
    with patch(
        "malmberg_display.setup.subprocess.run",
        return_value=_mock_proc(0),
    ):
        msg = _step_playwright(_FALLBACK, dry=False, warnings=[])
    assert "already installed" in msg


def test_step_playwright_non_interactive_warns() -> None:
    warnings: list[str] = []
    with (
        patch(
            "malmberg_display.setup.subprocess.run",
            return_value=_mock_proc(1),
        ),
        patch("malmberg_display.setup.sys.stdin.isatty", return_value=False),
    ):
        msg = _step_playwright(_FALLBACK, dry=False, warnings=warnings)
    assert "non-interactive" in msg
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# _step_unit
# ---------------------------------------------------------------------------


def test_step_unit_writes_file(tmp_path: Path) -> None:
    unit_path = tmp_path / "malmberg-display.service"
    with (
        patch("malmberg_display.setup._SYSTEMD_UNIT", unit_path),
        patch("malmberg_display.setup._user_home", return_value=tmp_path),
        patch("malmberg_display.setup.subprocess.run"),
    ):
        _step_unit("pi", dry=False)
    assert unit_path.is_file()
    content = unit_path.read_text()
    assert "malmberg_display" in content
    assert "DISPLAY=:0" in content


def test_step_unit_dry_run_noop(tmp_path: Path) -> None:
    unit_path = tmp_path / "malmberg-display.service"
    with (
        patch("malmberg_display.setup._SYSTEMD_UNIT", unit_path),
        patch("malmberg_display.setup._user_home", return_value=tmp_path),
    ):
        _step_unit("pi", dry=True)
    assert not unit_path.exists()


# ---------------------------------------------------------------------------
# _step_enable
# ---------------------------------------------------------------------------


def test_step_enable_ok() -> None:
    warnings: list[str] = []
    with patch(
        "malmberg_display.setup.subprocess.run",
        return_value=_mock_proc(0),
    ):
        _step_enable(dry=False, warnings=warnings)
    assert warnings == []


def test_step_enable_failure_warns() -> None:
    warnings: list[str] = []
    with patch(
        "malmberg_display.setup.subprocess.run",
        return_value=_mock_proc(1, stderr="failed"),
    ):
        _step_enable(dry=False, warnings=warnings)
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------


def test_run_requires_root() -> None:
    args = argparse.Namespace(dry_run=False, no_enable=False, user="pi")
    with (
        patch("malmberg_display.setup.os.getuid", return_value=1000),
        pytest.raises(SystemExit) as exc_info,
    ):
        run(args)
    assert exc_info.value.code == 2


def test_run_dry_run_completes(tmp_path: Path, capsys) -> None:
    args = argparse.Namespace(dry_run=True, no_enable=True, user="pi")
    with (
        patch("malmberg_display.setup.os.getuid", return_value=0),
        patch("malmberg_display.setup._detect_profile") as mock_detect,
        patch("malmberg_display.setup.write_hardware_toml"),
        patch("malmberg_display.setup._HARDWARE_TOML", tmp_path / "hw.toml"),
        patch("malmberg_display.setup._XORG_BLANKING_CONF", tmp_path / "blanking.conf"),
        patch("malmberg_display.setup._XORG_CONF_DIR", tmp_path),
        patch("malmberg_display.setup._user_home", return_value=tmp_path),
        patch("malmberg_display.setup._SYSTEMD_UNIT", tmp_path / "unit.service"),
        patch("malmberg_display.setup.subprocess.run", return_value=_mock_proc(0)),
    ):
        from typani.result import Ok

        mock_detect.return_value = Ok(_FALLBACK)
        run(args)

    out = capsys.readouterr().out
    assert "Provisioning Complete" in out
    assert "Next steps" in out
