"""Curses-facing search wrappers over the frontend-neutral `gridcalc.search`.

The matching itself moved down to `gridcalc/search.py` so the web frontend can
reuse it without importing `tui` (the same promotion `display.py` / `undo.py`
got). What stays here is the part that is about *this* view: moving the grid
cursor, and rendering the `[3/12]` position indicator into the status line.
"""

from __future__ import annotations

from ..engine import Grid
from ..search import find_matches, next_match

# Retained under its historical private name: `tui/__init__.py` re-exports it
# and a fair number of tests import it from there.
_search_grid = find_matches


def search_indicator(g: Grid, matches: list[tuple[int, int]]) -> str:
    """Return a string like '[3/12]' showing current match position, or '' if no matches."""
    if not matches:
        return ""
    cur = (g.cc, g.cr)
    if cur in matches:
        idx = matches.index(cur) + 1
        return f"[{idx}/{len(matches)}]"
    return f"[?/{len(matches)}]"


def search_next(g: Grid, matches: list[tuple[int, int]], forward: bool = True) -> None:
    """Jump the cursor to the next (or previous) search match."""
    target = next_match(matches, (g.cc, g.cr), forward)
    if target is not None:
        g.cc, g.cr = target
