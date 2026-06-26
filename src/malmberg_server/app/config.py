import argparse
from typing import Any

from pydantic import BaseModel

from malmberg_core.compat import Self


class ServerConfig(BaseModel):
    @staticmethod
    def args_to_dict(args: argparse.Namespace) -> dict[str, Any]: ...

    @classmethod
    def from_external(cls, args: argparse.Namespace, toml: dict[str, Any]) -> Self:
        return cls(**cls.args_to_dict(args), **toml)
