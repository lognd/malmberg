"""Error set for hardware detection failures."""

from __future__ import annotations

from typani.error_set import ErrorSet


class HalError(ErrorSet):
    FileNotFound = "hardware.toml does not exist at the configured path"
    ParseError = "hardware.toml exists but could not be parsed or validated"
    DetectionFailed = "Auto-detection did not recognise the hardware"
