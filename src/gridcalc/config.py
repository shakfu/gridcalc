"""Configuration file loading for gridcalc.

Lookup order (first found wins, CWD overrides user config):
  1. ./gridcalc.toml
  2. $XDG_CONFIG_HOME/gridcalc/gridcalc.toml  (default: ~/.config/gridcalc/gridcalc.toml)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found]

CONFIG_FILENAME = "gridcalc.toml"

_KNOWN_KEYS = frozenset({"editor", "sandbox", "width", "format", "libs", "allowed_modules"})


@dataclass
class Config:
    editor: str = ""
    sandbox: bool = True
    width: int = 0
    format: str = ""
    libs: list[str] = field(default_factory=list)
    allowed_modules: list[str] = field(default_factory=list)
    config_path: str = ""
    warnings: list[str] = field(default_factory=list)


def user_config_dir() -> Path:
    """Return the user-level config directory (XDG_CONFIG_HOME/gridcalc)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "gridcalc"
    return Path.home() / ".config" / "gridcalc"


def find_config() -> Path | None:
    """Find the first gridcalc.toml in the lookup order."""
    cwd_config = Path.cwd() / CONFIG_FILENAME
    if cwd_config.is_file():
        return cwd_config

    user_config = user_config_dir() / CONFIG_FILENAME
    if user_config.is_file():
        return user_config

    return None


def _parse_config(data: dict[str, Any]) -> Config:
    """Parse a TOML dict into a Config.

    Out-of-range or wrong-type values fall back to defaults; each fallback
    appends a human-readable note to ``cfg.warnings``. Unknown top-level
    keys are likewise warned about (typo guard).
    """
    cfg = Config()

    if "editor" in data:
        if isinstance(data["editor"], str):
            cfg.editor = data["editor"]
        else:
            cfg.warnings.append(f"editor: expected string, got {type(data['editor']).__name__}")

    if "sandbox" in data:
        if isinstance(data["sandbox"], bool):
            cfg.sandbox = data["sandbox"]
        else:
            cfg.warnings.append(f"sandbox: expected bool, got {type(data['sandbox']).__name__}")

    if "width" in data:
        try:
            w = int(data["width"])
            if 4 <= w <= 40:
                cfg.width = w
            else:
                cfg.warnings.append(f"width: {w} out of range [4, 40]; using default")
        except (ValueError, TypeError):
            cfg.warnings.append(f"width: not an integer ({data['width']!r}); using default")

    if "format" in data:
        v = data["format"]
        if isinstance(v, str) and len(v) == 1:
            cfg.format = v
        else:
            cfg.warnings.append(f"format: expected single-character string, got {v!r}")

    if "libs" in data:
        if isinstance(data["libs"], list):
            cfg.libs = [str(lib) for lib in data["libs"]]
        else:
            cfg.warnings.append(f"libs: expected list, got {type(data['libs']).__name__}")

    if "allowed_modules" in data:
        if isinstance(data["allowed_modules"], list):
            cfg.allowed_modules = [str(m) for m in data["allowed_modules"]]
        else:
            cfg.warnings.append(
                f"allowed_modules: expected list, got {type(data['allowed_modules']).__name__}"
            )

    unknown = sorted(set(data.keys()) - _KNOWN_KEYS)
    for k in unknown:
        cfg.warnings.append(f"unknown key '{k}'")

    return cfg


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from a TOML file.

    If path is None, uses the standard lookup order. On a parse error or
    missing file, returns a default Config (with the parse error reported
    via ``cfg.warnings`` and printed to stderr by the caller, if desired).
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
    except OSError as exc:
        cfg = Config()
        cfg.config_path = str(resolved)
        cfg.warnings.append(f"could not read {resolved}: {exc}")
        return cfg
    except tomllib.TOMLDecodeError as exc:
        cfg = Config()
        cfg.config_path = str(resolved)
        cfg.warnings.append(f"TOML parse error in {resolved}: {exc}")
        return cfg

    cfg = _parse_config(data)
    cfg.config_path = str(resolved)
    return cfg


def emit_warnings(cfg: Config) -> None:
    """Print any config warnings to stderr. Call once after load_config."""
    for w in cfg.warnings:
        print(f"gridcalc: config warning: {w}", file=sys.stderr)
