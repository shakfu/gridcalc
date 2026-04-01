"""Formula libs -- pluggable sets of builtins for the eval namespace.

Each lib is a submodule that exports a BUILTINS dict. Libs are composable:
enabling multiple libs merges their builtins (later libs override earlier
ones on conflict).

Available libs:
  - "xlsx": Excel-compatible function names (IF, AND, OR, VLOOKUP, etc.)
"""

from __future__ import annotations

from typing import Any

from .xlsx import BUILTINS as _XLSX_BUILTINS

LIBS: dict[str, dict[str, Any]] = {
    "xlsx": _XLSX_BUILTINS,
}


def get_lib_builtins(name: str) -> dict[str, Any]:
    """Return the builtins dict for a named lib, or empty dict if unknown."""
    return dict(LIBS.get(name, {}))
