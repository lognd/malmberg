from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from warnings import warn

from malmberg_core.compat import toml

try:
    __version__: str = version("malmberg")
except PackageNotFoundError:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    __version__ = "0.0.0"
    if pyproject_path.is_file():
        pyproject_data = toml.load(pyproject_path.open("rb"))
        __version__ = pyproject_data["project"]["version"]
    if __version__ == "0.0.0":
        warn("Could get package information nor pyproject.toml.")
