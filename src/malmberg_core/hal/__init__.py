"""Hardware Abstraction Layer for malmberg.

Application code imports only `get_hardware_profile` and branches on
profile fields -- never on raw platform strings or `sys.platform`.
"""

from __future__ import annotations

from malmberg_core.hal.detect import get_hardware_profile
from malmberg_core.hal.profile import HardwareProfile

__all__ = ["HardwareProfile", "get_hardware_profile"]
