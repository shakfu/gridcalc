"""Grid text/value search -- pure helpers used by the search prompt."""

from __future__ import annotations

import math

from ..engine import EMPTY, FORMULA, NUM, Grid


def _search_grid(g: Grid, pattern: str) -> list[tuple[int, int]]:
    """Find all cells whose text or display value matches pattern (case-insensitive)."""
    pat = pattern.lower()
    matches: list[tuple[int, int]] = []
    for (c, r), cl in sorted(g._cells.items(), key=lambda x: (x[0][1], x[0][0])):
        if cl.type == EMPTY:
            continue
        text = cl.text.lower()
        if pat in text:
            matches.append((c, r))
            continue
        if cl.type in (NUM, FORMULA) and not math.isnan(cl.val):
            if abs(cl.val) < 1e15 and cl.val == int(cl.val):
                valstr = str(int(cl.val))
            else:
                valstr = f"{cl.val:g}"
            if pat in valstr:
                matches.append((c, r))
    return matches


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
    """Jump to the next (or previous) search match."""
    if not matches:
        return
    cur = (g.cc, g.cr)
    if forward:
        for c, r in matches:
            if (r, c) > (cur[1], cur[0]):
                g.cc, g.cr = c, r
                return
        g.cc, g.cr = matches[0]
    else:
        for c, r in reversed(matches):
            if (r, c) < (cur[1], cur[0]):
                g.cc, g.cr = c, r
                return
        g.cc, g.cr = matches[-1]
