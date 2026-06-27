"""System tests: config merge pipeline (CLI args + env vars + TOML + defaults)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from malmberg_display.app.config import DisplayConfig
from malmberg_server.app.config import ServerConfig


def _args(**kwargs) -> argparse.Namespace:
    defaults = {
        "host": None,
        "port": None,
        "config": None,
        "media_dir": None,
        "server_url": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _server_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "host": None,
        "port": None,
        "config": None,
        "fs_root": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# ServerConfig merge
# ---------------------------------------------------------------------------


def test_server_defaults() -> None:
    cfg = ServerConfig.from_external(_server_args(), {})
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8444
    assert cfg.hide_policy == "delete"
    assert cfg.max_upload_mb == 500


def test_server_toml_overrides_defaults() -> None:
    cfg = ServerConfig.from_external(
        _server_args(), {"host": "127.0.0.1", "port": 9000, "max_upload_mb": 100}
    )
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9000
    assert cfg.max_upload_mb == 100


def test_server_cli_overrides_toml(tmp_path: Path) -> None:
    args = _server_args(host="10.0.0.1", port=7777)
    cfg = ServerConfig.from_external(args, {"host": "127.0.0.1", "port": 9000})
    assert cfg.host == "10.0.0.1"
    assert cfg.port == 7777


def test_server_env_overrides_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_HOST", "172.16.0.1")
    monkeypatch.setenv("MALMBERG_PORT", "6543")
    cfg = ServerConfig.from_external(
        _server_args(), {"host": "127.0.0.1", "port": 9000}
    )
    assert cfg.host == "172.16.0.1"
    assert cfg.port == 6543


def test_server_cli_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_HOST", "10.0.0.1")
    args = _server_args(host="192.168.1.1")
    cfg = ServerConfig.from_external(args, {})
    assert cfg.host == "192.168.1.1"


def test_server_hide_policy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_HIDE_POLICY", "keep")
    cfg = ServerConfig.from_external(_server_args(), {})
    assert cfg.hide_policy == "keep"


def test_server_validator_rejects_zero_upload_mb() -> None:
    with pytest.raises(Exception):
        ServerConfig(max_upload_mb=0)


def test_server_fs_root_cli(tmp_path: Path) -> None:
    args = _server_args(fs_root=str(tmp_path))
    cfg = ServerConfig.from_external(args, {})
    assert cfg.fs_root == tmp_path


# ---------------------------------------------------------------------------
# DisplayConfig merge
# ---------------------------------------------------------------------------


def test_display_defaults() -> None:
    cfg = DisplayConfig.from_external(_args(), {})
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8443
    assert cfg.dwell_s == 10.0
    assert cfg.web_overlays is False
    assert cfg.server_url is None
    assert cfg.discovery_port == 9456


def test_display_toml_overrides() -> None:
    cfg = DisplayConfig.from_external(
        _args(), {"dwell_s": 5.0, "width": 3840, "height": 2160}
    )
    assert cfg.dwell_s == 5.0
    assert cfg.width == 3840


def test_display_cli_overrides_toml() -> None:
    args = _args(host="10.0.0.2", port=5555)
    cfg = DisplayConfig.from_external(args, {"host": "127.0.0.1", "port": 9000})
    assert cfg.host == "10.0.0.2"
    assert cfg.port == 5555


def test_display_server_url_cli() -> None:
    args = _args(server_url="http://192.168.1.50:8444")
    cfg = DisplayConfig.from_external(args, {})
    assert cfg.server_url == "http://192.168.1.50:8444"


def test_display_server_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_SERVER_URL", "http://10.0.0.5:8444")
    cfg = DisplayConfig.from_external(_args(), {})
    assert cfg.server_url == "http://10.0.0.5:8444"


def test_display_env_web_overlays(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "true", "yes", "True", "YES"):
        monkeypatch.setenv("MALMBERG_WEB_OVERLAYS", val)
        cfg = DisplayConfig.from_external(_args(), {})
        assert cfg.web_overlays is True


def test_display_env_dwell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALMBERG_DWELL_S", "7.5")
    cfg = DisplayConfig.from_external(_args(), {})
    assert cfg.dwell_s == 7.5


def test_display_validator_rejects_zero_dwell() -> None:
    with pytest.raises(Exception):
        DisplayConfig(dwell_s=0)


def test_display_media_dir_cli(tmp_path: Path) -> None:
    args = _args(media_dir=str(tmp_path))
    cfg = DisplayConfig.from_external(args, {})
    assert cfg.media_dir == tmp_path


def test_display_all_layers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify CLI > env > TOML > defaults priority across all layers."""
    monkeypatch.setenv("MALMBERG_HOST", "10.0.0.1")  # env
    args = _args(port=7000)  # CLI (wins over toml+env for port)
    toml = {"host": "127.0.0.1", "dwell_s": 3.0}  # toml

    cfg = DisplayConfig.from_external(args, toml)
    assert cfg.host == "10.0.0.1"  # env beats toml
    assert cfg.port == 7000  # CLI
    assert cfg.dwell_s == 3.0  # toml (no env/CLI for this)
