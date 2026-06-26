from typani import Unreachable

from malmberg_server.app.config import ServerConfig


class ServerApp:
    def __init__(self, cfg: ServerConfig) -> None:
        self._cfg = cfg

    def __call__(self) -> Unreachable:
        while True:
            # TODO: setup asyncio targets.
            pass
        return Unreachable()
