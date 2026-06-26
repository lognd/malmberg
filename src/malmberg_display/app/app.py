from typani import Unreachable

from malmberg_display.app.config import DisplayConfig


class DisplayApp:
    def __init__(self, cfg: DisplayConfig) -> None:
        self._cfg = cfg

    def __call__(self) -> Unreachable:
        while True:
            # TODO: setup asyncio targets.
            pass
        return Unreachable()
