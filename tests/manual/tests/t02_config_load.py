"""t02_config_load -- verify server and display configs load from defaults."""

from __future__ import annotations

from harness import TestContext, TestSkip

TITLE = "Config loading (defaults)"
DEPENDS: list[str] = ["t01_prereqs"]
INTERACTIVE = False


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t02_config_load")

    from malmberg_server.app.config import ServerConfig
    from malmberg_display.app.config import DisplayConfig

    scfg = ServerConfig()
    log.info("ServerConfig defaults: port=%d fs_root=%s", scfg.port, scfg.fs_root)
    assert scfg.port > 0, "ServerConfig.port must be positive"
    assert scfg.fs_root is not None, "ServerConfig.fs_root must not be None"

    dcfg = DisplayConfig()
    log.info(
        "DisplayConfig defaults: port=%d width=%d height=%d dwell=%s",
        dcfg.port,
        dcfg.width,
        dcfg.height,
        dcfg.dwell_s,
    )
    assert dcfg.port > 0
    assert dcfg.width > 0 and dcfg.height > 0

    log.info("Config load OK.")
