"""SHEET and SHEETS."""

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for name in ("Two", "Three"):
        g.add_sheet(name)
    g.set_active("Two")
    return g


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=SHEET()", 2),
        ("=SHEET(A1)", 2),
        ("=SHEET(Three!B2:C3)", 3),
        ('=SHEET("sheet1")', 1),
        ('=SHEET("Nope")', ExcelError.NA),
        ("=SHEET(OFFSET(Three!A1,1,1))", 3),
        ("=SHEET(Sheet1:Three!A1)", 1),
        ("=SHEETS()", 3),
        ("=SHEETS(Two:Three!A1)", 2),
        ("=SHEETS(A1:B2)", 1),
        ("=SHEETS(Nope!A1)", ExcelError.REF),
    ],
)
def test_sheet_functions(formula, value) -> None:
    g = _grid()
    g.setcell(0, 9, formula)
    cl = g.cells[0][9]
    assert (cl.err if isinstance(value, ExcelError) else cl.val) == value


def test_moving_a_sheet_updates_sheet() -> None:
    g = _grid()
    g.setcell(0, 0, "=SHEET()")
    g.move_sheet("Two", 0)
    g.recalc()
    assert g.cells[0][0].val == 1
