"""Workbook loading shared by frontends -- engine + sandbox only, no view.

A frontend (the web view today, `gridcalc.web`) needs to open a workbook and
show a first-run demo. That logic is frontend-neutral, so it lives here below
the view boundary rather than inside a view. Keeping it here also means a
second frontend could reuse it unchanged. `tests/test_architecture.py` guards
this module curses-free, the same as the rest of the core.
"""

from __future__ import annotations

from pathlib import Path

from .engine import Grid, Mode
from .sandbox import LoadPolicy


def load_workbook(path: str | Path) -> Grid:
    """Load a ``.json``, ``.xlsx``, or ``.csv`` workbook (format by extension).

    JSON files load *formulas only* -- any embedded code block is not executed
    -- because a frontend should never run untrusted code merely to open a
    file. Cells that depend on a code block therefore show their error state,
    the safe and honest outcome. ``.xlsx`` and ``.csv`` carry no code path.
    The workbook is recalculated before return.
    """
    p = str(path)
    low = p.lower()
    g = Grid()
    if low.endswith(".xlsx"):
        if g.xlsxload(p) < 0:
            raise OSError(f"could not load workbook: {p}")
    elif low.endswith(".csv"):
        if g.csvload(p) < 0:
            raise OSError(f"could not load workbook: {p}")
    else:
        if g.jsonload(p, policy=LoadPolicy.formulas_only()) < 0:
            raise OSError(f"could not load workbook: {p}")
    g.filename = p
    g.recalc()
    return g


def demo_grid() -> Grid:
    """A small self-contained workbook shown when no file is given."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcell(0, 0, "gridcalc demo")
    headers = ["Item", "Qty", "Price", "Total"]
    for c, label in enumerate(headers):
        g.setcell(c, 2, label)
    rows = [("Widget", 10, 2.5), ("Gadget", 4, 9.0), ("Gizmo", 7, 3.25)]
    for i, (name, qty, price) in enumerate(rows):
        r = 3 + i
        g.setcell(0, r, name)
        g.setcell(1, r, str(qty))
        g.setcell(2, r, str(price))
        g.setcell(3, r, f"=B{r + 1}*C{r + 1}")
    g.setcell(0, 6, "Total")
    g.setcell(3, 6, "=SUM(D4:D6)")
    g.recalc()
    g.filename = ""
    return g
