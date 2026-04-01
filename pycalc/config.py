"""Configuration file loading for pycalc.

Lookup order (first found wins, CWD overrides user config):
  1. ./pycalc.toml
  2. $XDG_CONFIG_HOME/pycalc/pycalc.toml  (default: ~/.config/pycalc/pycalc.toml)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found]

CONFIG_FILENAME = "pycalc.toml"


@dataclass
class Config:
    editor: str = ""
    sandbox: bool = False
    width: int = 0
    format: str = ""
    libs: list[str] = field(default_factory=list)
    allowed_modules: list[str] = field(default_factory=list)
    config_path: str = ""


def user_config_dir() -> Path:
    """Return the user-level config directory (XDG_CONFIG_HOME/pycalc)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "pycalc"
    return Path.home() / ".config" / "pycalc"


def find_config() -> Path | None:
    """Find the first pycalc.toml in the lookup order."""
    cwd_config = Path.cwd() / CONFIG_FILENAME
    if cwd_config.is_file():
        return cwd_config

    user_config = user_config_dir() / CONFIG_FILENAME
    if user_config.is_file():
        return user_config

    return None


def _parse_config(data: dict[str, Any]) -> Config:
    """Parse a TOML dict into a Config, ignoring unknown keys."""
    cfg = Config()

    if "editor" in data and isinstance(data["editor"], str):
        cfg.editor = data["editor"]

    if "sandbox" in data and isinstance(data["sandbox"], bool):
        cfg.sandbox = data["sandbox"]

    if "width" in data:
        try:
            w = int(data["width"])
            if 4 <= w <= 40:
                cfg.width = w
        except (ValueError, TypeError):
            pass

    if "format" in data and isinstance(data["format"], str) and len(data["format"]) == 1:
        cfg.format = data["format"]

    if "libs" in data and isinstance(data["libs"], list):
        cfg.libs = [str(lib) for lib in data["libs"]]

    if "allowed_modules" in data and isinstance(data["allowed_modules"], list):
        cfg.allowed_modules = [str(m) for m in data["allowed_modules"]]

    return cfg


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from a TOML file.

    If path is None, uses the standard lookup order.
    Returns a default Config if no file is found or parsing fails.
    """
    if path is None:
        resolved = find_config()
    else:
        resolved = Path(path) if not isinstance(path, Path) else path
        if not resolved.is_file():
            return Config()

    if resolved is None:
        return Config()

    try:
        with open(resolved, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return Config()

    cfg = _parse_config(data)
    cfg.config_path = str(resolved)
    return cfg
