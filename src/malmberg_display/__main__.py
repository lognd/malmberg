import argparse
import os
from pathlib import Path

from malmberg_core.compat import toml
from malmberg_display.app import DisplayApp, DisplayConfig

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    toml_path = Path(os.environ.get("TOML_CONFIG") or "config.toml")
    toml_cfg = toml.load(toml_path.open("rb"))

    app_cfg = DisplayConfig.from_external(parser.parse_args(), toml_cfg)

    app = DisplayApp(app_cfg)
    app()
