"""Unit tests for malmberg_server.setup."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from malmberg_core.hal.profile import HardwareProfile
from malmberg_server.setup import (
    _step_dirs,
    _step_enable,
    _step_hardware,
    _step_pin,
    _step_tls,
    _step_unit,
    _step_user,
    _step_zfs,
    run,
)

_FALLBACK = HardwareProfile.fallback()


# ---------------------------------------------------------------------------
# _step_hardware
# ---------------------------------------------------------------------------


def test_step_hardware_detected(tmp_path: Path) -> None:
    profile = HardwareProfile(
        name="pi-4",
        hw_video_decode=True,
        gpio_available=True,
        status_panel_bus="i2c",
        max_preload_queue=4,
        playwright_supported=True,
    )
    with (
        patch("malmberg_server.setup._detect_profile") as mock_detect,
        patch("malmberg_server.setup.write_hardware_toml") as mock_write,
    ):
        from typani.result import Ok

        mock_detect.return_value = Ok(profile)
        warnings: list[str] = []
        result = _step_hardware(dry=True, warnings=warnings)

    assert result.name == "pi-4"
    assert warnings == []
    mock_write.assert_not_called()  # dry=True


def test_step_hardware_fallback_warns(tmp_path: Path) -> None:
    with (
        patch("malmberg_server.setup._detect_profile") as mock_detect,
        patch("malmberg_server.setup.write_hardware_toml"),
    ):
        from typani.result import Err

        from malmberg_core.hal.errors import HalError

        mock_detect.return_value = Err(HalError.DetectionFailed)
        warnings: list[str] = []
        result = _step_hardware(dry=False, warnings=warnings)

    assert result.name == "generic-x86"
    assert len(warnings) == 1
    assert "auto-detection failed" in warnings[0]


def test_step_hardware_writes_toml(tmp_path: Path) -> None:
    with (
        patch("malmberg_server.setup._detect_profile") as mock_detect,
        patch("malmberg_server.setup.write_hardware_toml") as mock_write,
    ):
        from typani.result import Ok

        mock_detect.return_value = Ok(_FALLBACK)
        _step_hardware(dry=False, warnings=[])

    mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# _step_user
# ---------------------------------------------------------------------------


def test_step_user_already_exists() -> None:
    with (
        patch("malmberg_server.setup.pwd.getpwnam", return_value=MagicMock()),
        patch("malmberg_server.setup.subprocess.run") as mock_run,
    ):
        _step_user(dry=False)
    mock_run.assert_not_called()


def test_step_user_creates_when_missing() -> None:
    with (
        patch("malmberg_server.setup.pwd.getpwnam", side_effect=KeyError),
        patch("malmberg_server.setup.subprocess.run") as mock_run,
    ):
        _step_user(dry=False)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "useradd" in cmd
    assert "--system" in cmd


def test_step_user_dry_run_skips_create() -> None:
    with (
        patch("malmberg_server.setup.pwd.getpwnam", side_effect=KeyError),
        patch("malmberg_server.setup.subprocess.run") as mock_run,
    ):
        _step_user(dry=True)
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _step_dirs
# ---------------------------------------------------------------------------


def test_step_dirs_creates_layout(tmp_path: Path) -> None:
    fs = tmp_path / "fs"
    with (
        patch("malmberg_server.setup.pwd.getpwnam", side_effect=KeyError),
        patch("malmberg_server.setup.grp.getgrnam", side_effect=KeyError),
        patch("malmberg_server.setup.os.chown"),
    ):
        _step_dirs(fs, dry=False)
    assert (fs / "media").is_dir()
    assert (fs / "uploads").is_dir()
    assert (fs / ".trash").is_dir()
    assert (fs / "logs").is_dir()


def test_step_dirs_dry_run_noop(tmp_path: Path) -> None:
    fs = tmp_path / "fs"
    _step_dirs(fs, dry=True)
    assert not fs.exists()


# ---------------------------------------------------------------------------
# _step_zfs
# ---------------------------------------------------------------------------


def _mock_proc(rc: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = rc
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_step_zfs_no_zfs_warns() -> None:
    warnings: list[str] = []
    with patch(
        "malmberg_server.setup.subprocess.run",
        return_value=_mock_proc(1),
    ):
        msg = _step_zfs(Path("/fs"), dry=False, warnings=warnings)
    assert "unavailable" in msg
    assert len(warnings) == 1


def test_step_zfs_dataset_exists() -> None:
    warnings: list[str] = []

    def fake_run(cmd, **kw):
        if "which" in cmd:
            return _mock_proc(0)
        if "list" in cmd:
            return _mock_proc(0, stdout="tank/malmberg\n")
        return _mock_proc(0)

    with patch("malmberg_server.setup.subprocess.run", side_effect=fake_run):
        msg = _step_zfs(Path("/fs"), dry=False, warnings=warnings)
    assert "already exists" in msg
    assert warnings == []


def test_step_zfs_creates_dataset() -> None:
    warnings: list[str] = []
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "which" in cmd:
            return _mock_proc(0)
        if "list" in cmd:
            return _mock_proc(1)  # dataset not found
        return _mock_proc(0)

    with patch("malmberg_server.setup.subprocess.run", side_effect=fake_run):
        msg = _step_zfs(Path("/fs"), dry=False, warnings=warnings)
    assert "created" in msg
    assert any("create" in " ".join(c) for c in calls)


# ---------------------------------------------------------------------------
# _step_tls
# ---------------------------------------------------------------------------


def test_step_tls_already_present(tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.touch()
    key.touch()
    warnings: list[str] = []
    with (
        patch("malmberg_server.setup._TLS_DIR", tmp_path),
        patch("malmberg_server.setup.subprocess.run") as mock_run,
    ):
        _step_tls(dry=False, warnings=warnings)
    mock_run.assert_not_called()


def test_step_tls_no_openssl_warns() -> None:
    warnings: list[str] = []
    with (
        patch("malmberg_server.setup._TLS_DIR", Path("/nonexistent/tls")),
        patch(
            "malmberg_server.setup.subprocess.run",
            return_value=_mock_proc(1),
        ),
    ):
        _step_tls(dry=False, warnings=warnings)
    assert len(warnings) == 1
    assert "openssl" in warnings[0]


def test_step_tls_dry_run_skips() -> None:
    warnings: list[str] = []
    with (
        patch("malmberg_server.setup._TLS_DIR", Path("/nonexistent/tls")),
        patch(
            "malmberg_server.setup.subprocess.run",
            return_value=_mock_proc(0),
        ) as mock_run,
    ):
        _step_tls(dry=True, warnings=warnings)
    # The cert generation command (openssl req ...) must not run in dry-run.
    assert not any(len(c[0]) > 0 and "req" in c[0][0] for c in mock_run.call_args_list)


# ---------------------------------------------------------------------------
# _step_unit
# ---------------------------------------------------------------------------


def test_step_unit_writes_file(tmp_path: Path) -> None:
    unit_path = tmp_path / "malmberg-server.service"
    with (
        patch("malmberg_server.setup._SYSTEMD_UNIT", unit_path),
        patch("malmberg_server.setup.subprocess.run"),
    ):
        _step_unit(Path("/fs"), dry=False)
    assert unit_path.is_file()
    content = unit_path.read_text()
    assert "malmberg_server" in content
    assert "ExecStart=" in content


def test_step_unit_dry_run_noop(tmp_path: Path) -> None:
    unit_path = tmp_path / "malmberg-server.service"
    with patch("malmberg_server.setup._SYSTEMD_UNIT", unit_path):
        _step_unit(Path("/fs"), dry=True)
    assert not unit_path.exists()


# ---------------------------------------------------------------------------
# _step_enable
# ---------------------------------------------------------------------------


def test_step_enable_ok() -> None:
    warnings: list[str] = []
    with patch(
        "malmberg_server.setup.subprocess.run",
        return_value=_mock_proc(0),
    ):
        _step_enable(dry=False, warnings=warnings)
    assert warnings == []


def test_step_enable_failure_warns() -> None:
    warnings: list[str] = []
    with patch(
        "malmberg_server.setup.subprocess.run",
        return_value=_mock_proc(1, stderr="unit not found"),
    ):
        _step_enable(dry=False, warnings=warnings)
    assert len(warnings) == 1
    assert "systemctl enable failed" in warnings[0]


def test_step_enable_dry_run_skips() -> None:
    with patch("malmberg_server.setup.subprocess.run") as mock_run:
        _step_enable(dry=True, warnings=[])
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _step_pin
# ---------------------------------------------------------------------------


def test_step_pin_generates_six_digits(tmp_path: Path) -> None:
    pin_path = tmp_path / "pin.txt"
    with patch("malmberg_server.setup._PIN_FILE", pin_path):
        pin = _step_pin(dry=False)
    assert len(pin) == 6
    assert pin.isdigit()
    assert pin_path.read_text().strip() == pin


def test_step_pin_reuses_existing(tmp_path: Path) -> None:
    pin_path = tmp_path / "pin.txt"
    pin_path.write_text("123456\n")
    with patch("malmberg_server.setup._PIN_FILE", pin_path):
        pin = _step_pin(dry=False)
    assert pin == "123456"


def test_step_pin_dry_run_generates_but_does_not_write(tmp_path: Path) -> None:
    pin_path = tmp_path / "pin.txt"
    with patch("malmberg_server.setup._PIN_FILE", pin_path):
        pin = _step_pin(dry=True)
    assert len(pin) == 6
    assert not pin_path.exists()


# ---------------------------------------------------------------------------
# run() integration (all steps mocked)
# ---------------------------------------------------------------------------


def test_run_requires_root() -> None:
    args = argparse.Namespace(dry_run=False, no_enable=False, fs_root="/fs")
    with (
        patch("malmberg_server.setup.os.getuid", return_value=1000),
        pytest.raises(SystemExit) as exc_info,
    ):
        run(args)
    assert exc_info.value.code == 2


def test_run_dry_run_completes(tmp_path: Path, capsys) -> None:
    args = argparse.Namespace(
        dry_run=True, no_enable=True, fs_root=str(tmp_path / "fs")
    )
    with (
        patch("malmberg_server.setup.os.getuid", return_value=0),
        patch("malmberg_server.setup._detect_profile") as mock_detect,
        patch("malmberg_server.setup.write_hardware_toml"),
        patch("malmberg_server.setup.pwd.getpwnam", side_effect=KeyError),
        patch("malmberg_server.setup.grp.getgrnam", side_effect=KeyError),
        patch("malmberg_server.setup.os.chown"),
        patch("malmberg_server.setup.validate_environment", return_value=[]),
        patch("malmberg_server.setup.subprocess.run", return_value=_mock_proc(1)),
        patch("malmberg_server.setup._TLS_DIR", tmp_path / "tls"),
        patch("malmberg_server.setup._SYSTEMD_UNIT", tmp_path / "unit.service"),
        patch("malmberg_server.setup._PIN_FILE", tmp_path / "pin.txt"),
        patch("malmberg_server.setup._CONFIG_DIR", tmp_path / "cfg"),
    ):
        from typani.result import Ok

        mock_detect.return_value = Ok(_FALLBACK)
        run(args)

    out = capsys.readouterr().out
    assert "Provisioning Complete" in out
    assert "PAIRING PIN" in out
