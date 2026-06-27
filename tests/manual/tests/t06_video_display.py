"""t06_video_display -- play a short video clip via VideoDisplay + mpv."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from harness import TestContext, TestSkip

TITLE = "VideoDisplay play via mpv"
DEPENDS: list[str] = ["t03_hal_detection"]
INTERACTIVE = True


def _make_test_video(dest: Path) -> None:
    """Generate a 3-second solid-colour MP4 via ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise TestSkip("ffmpeg not found -- cannot generate test video")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=3",
            "-c:v",
            "libx264",
            "-t",
            "3",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"ffmpeg failed:\n{result.stderr}")


def run(ctx: TestContext) -> None:
    log = ctx.setup_logger("t06_video_display")

    try:
        import mpv  # noqa: F401
    except ImportError:
        raise TestSkip("mpv Python binding not installed")

    # Display availability is detected at runtime by mpv, not a profile flag.

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        video_path = tmp / "test.mp4"
        log.info("Generating test video via ffmpeg...")
        _make_test_video(video_path)
        log.info("Test video: %s (%d bytes)", video_path, video_path.stat().st_size)

        from malmberg_display.display.proto import DisplayContext, LoadContext
        from malmberg_display.display.video import VideoDisplay

        load_ctx = LoadContext(cache_dir=tmp)
        display_ctx = DisplayContext(
            width=800, height=480, fade_duration_s=0.0, dwell_s=3.5
        )

        async def _inner() -> None:
            d = VideoDisplay(video_path)
            log.info("Loading video...")
            await d.load(load_ctx)
            log.info("Playing for ~3.5s...")
            await d.display(display_ctx)

        asyncio.run(_inner())
        log.info("VideoDisplay play completed without error.")

    if not ctx.no_interactive:
        ans = ctx.prompt("Did a solid-blue video play (~3 seconds)?")
        assert ans == "y", "User did not confirm video played"

    log.info("VideoDisplay test OK.")
