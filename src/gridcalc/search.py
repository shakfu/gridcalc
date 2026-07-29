"""Grid text/value search -- engine-adjacent, shared by frontends, no view deps.

Finding cells that match a pattern needs the engine and nothing else, so it
lives below the view boundary alongside `display.py` / `loader.py` / `undo.py`.
`tui/search.py` keeps the curses-facing wrappers (which move the grid cursor
and render a position indicator); the web `Api` calls straight into here.
`tests/test_architecture.py` keeps this module curses-free.

A match is a `(col, row)` key. Results come back in reading order -- row, then
column -- which is the order both frontends step through them in.
"""

from __future__ import annotations

import math

from .engine import EMPTY, FORMULA, NUM, Grid


def display_number(value: float) -> str:
    """Render a cell's numeric value the way a search compares it.

    Whole numbers lose the trailing `.0` so searching `42` finds a cell
    holding `42.0`; everything else uses `%g`. Deliberately not the display
    formatter -- a search matches the underlying number, not whatever number
    format the cell happens to be wearing.
    """
    if abs(value) < 1e15 and value == int(value):
        return str(int(value))
    return f"{value:g}"


def find_matches(g: Grid, pattern: str) -> list[tuple[int, int]]:
    """Cells whose source text or numeric value contains `pattern`.

    Case-insensitive, substring, and over *both* the text the user typed and
    the value a formula produced -- so `=SUM(A1:A9)` is found by searching
    either `SUM` or its result. An empty pattern matches nothing rather than
    everything, since "find nothing" is the useful answer for an empty box.
    """
    pat = pattern.lower()
    if not pat:
        return []
    matches: list[tuple[int, int]] = []
    for (c, r), cl in sorted(g._cells.items(), key=lambda x: (x[0][1], x[0][0])):
        if cl.type == EMPTY:
            continue
        if pat in cl.text.lower():
            matches.append((c, r))
            continue
        if cl.type in (NUM, FORMULA) and not math.isnan(cl.val) and pat in display_number(cl.val):
            matches.append((c, r))
    return matches


def next_match(
    matches: list[tuple[int, int]], cur: tuple[int, int], forward: bool = True
) -> tuple[int, int] | None:
    """The match after (or before) `cur`, wrapping at the ends.

    Pure: it reports where to go rather than moving anything, so both a cursor
    and a client-side selection can be driven from it. `cur` need not itself be
    a match -- searching from an arbitrary position is the normal case.
    """
    if not matches:
        return None
    cc, cr = cur
    if forward:
        for c, r in matches:
            if (r, c) > (cr, cc):
                return (c, r)
        return matches[0]
    for c, r in reversed(matches):
        if (r, c) < (cr, cc):
            return (c, r)
    return matches[-1]
