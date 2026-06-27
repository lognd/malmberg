"""Load or detect a HardwareProfile.

Priority:
  1. hardware.toml in the config directory (written by provisioning script)
  2. Auto-detection via /proc/cpuinfo and dmidecode
  3. Generic x86 fallback profile

Application code should call `get_hardware_profile()` once at startup and
store the result; detection reads files and may invoke subprocesses.
"""

from __future__ import annotations

from pathlib import Path

from typani.result import Err, Ok, Result  # Result needed for return annotation

from malmberg_core.compat import toml
from malmberg_core.hal.errors import HalError
from malmberg_core.hal.profile import HardwareProfile

_DEFAULT_CONFIG_PATH = Path("/etc/malmberg/hardware.toml")

# Known Raspberry Pi board identifiers found in /proc/cpuinfo "Model" line.
_PI_ZERO_2W = "Raspberry Pi Zero 2"
_PI_4 = "Raspberry Pi 4"
_PI_5 = "Raspberry Pi 5"


def get_hardware_profile(
    config_path: Path | None = None,
) -> HardwareProfile:
    """Return the HardwareProfile for the current machine.

    Reads `hardware.toml` from *config_path* (or the default location). If the
    file does not exist, falls back to auto-detection, then to the generic x86
    profile. Never raises; always returns a usable profile.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    result = _load_from_toml(path)
    if result.is_ok:
        return result.danger_ok
    detected = _detect_profile()
    if detected.is_ok:
        return detected.danger_ok
    return HardwareProfile.fallback()


def _load_from_toml(path: Path) -> Result[HardwareProfile, HalError]:
    """Parse hardware.toml and validate it into a HardwareProfile."""
    if not path.is_file():
        return Err(HalError.FileNotFound)
    try:
        with open(path, "rb") as f:
            data = toml.load(f)
        return Ok(HardwareProfile.model_validate(data))
    except Exception:
        return Err(HalError.ParseError)


def _detect_profile() -> Result[HardwareProfile, HalError]:
    """Auto-detect board type by reading /proc/cpuinfo."""
    try:
        model = _read_pi_model()
    except OSError:
        return Err(HalError.DetectionFailed)

    if model is None:
        return Err(HalError.DetectionFailed)

    if _PI_ZERO_2W in model:
        return Ok(
            HardwareProfile(
                name="pi-zero-2w",
                hw_video_decode=False,
                gpio_available=True,
                status_panel_bus="i2c",
                max_preload_queue=2,
                playwright_supported=False,
            )
        )
    if _PI_4 in model:
        return Ok(
            HardwareProfile(
                name="pi-4",
                hw_video_decode=True,
                gpio_available=True,
                status_panel_bus="i2c",
                max_preload_queue=4,
                playwright_supported=True,
            )
        )
    if _PI_5 in model:
        return Ok(
            HardwareProfile(
                name="pi-5",
                hw_video_decode=True,
                gpio_available=True,
                status_panel_bus="i2c",
                max_preload_queue=8,
                playwright_supported=True,
            )
        )
    return Err(HalError.DetectionFailed)


def _read_pi_model() -> str | None:
    """Return the 'Model' string from /proc/cpuinfo, or None if absent."""
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Model"):
            _, _, value = line.partition(":")
            return value.strip()
    return None


def write_hardware_toml(profile: HardwareProfile, path: Path) -> None:
    """Serialize *profile* to *path* in TOML format (used by provisioning)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'name = "{profile.name}"',
        f"hw_video_decode = {str(profile.hw_video_decode).lower()}",
        f"gpio_available = {str(profile.gpio_available).lower()}",
        f'status_panel_bus = "{profile.status_panel_bus}"',
        f"max_preload_queue = {profile.max_preload_queue}",
        f"playwright_supported = {str(profile.playwright_supported).lower()}",
    ]
    path.write_text("\n".join(lines) + "\n")
