"""Legacy formulas: Excel's implicit intersection (`@`) for xlsx formulas
stored without the dynamic-array flag."""

from pathlib import Path

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError

openpyxl = pytest.importorskip("openpyxl")


def _legacy(formula: str, at: tuple[int, int] = (3, 2)):
    """``formula`` as a legacy formula at ``at`` (D3), over A1:A5 = 1..5 and B1:D1 = 10, 20, 30."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk(
        [(0, r, str(r + 1)) for r in range(5)] + [(1, 0, "10"), (2, 0, "20"), (3, 0, "30")]
    )
    g.setcell(*at, formula)
    g.cell(*at).legacy = True
    g.recalc()
    cl = g.cell(*at)
    return cl.err if cl.err is not None else cl.val


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=A1:A5", 3.0),  # the cell on the formula's row
        ("=A1:A5*2", 6.0),
        ("=SIN(A1:A5)-SIN(3)", 0.0),
        ("=B1:D1", 30.0),  # one row: the cell in the formula's column
        ("=A1:B5", ExcelError.VALUE),  # two-dimensional: no intersection
        ("=A4:A5", ExcelError.VALUE),  # the row is outside the range
        ("=SUM(A1:A5)", 15.0),  # a whole range argument is untouched
        ("=SUM(A1:A5*2)", 6.0),  # an expression inside SUM is intersected
        ("=SUMPRODUCT(A1:A5*2)", 30.0),  # SUMPRODUCT evaluates arrays
        ("=INDEX(A1:A5*10,5)", 50.0),
        ("=SUM({1,2,3}*2)", 12.0),  # array constants are never intersected
        ("=INDEX({1,2,3,4},,)", 1.0),  # an array result shows its first value
    ],
)
def test_legacy_formula(formula, value) -> None:
    assert _legacy(formula) == value


def test_a_dynamic_formula_spills_instead() -> None:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, r, str(r + 1)) for r in range(5)])
    g.setcell(3, 2, "=A1:A5*2")
    assert g.cell(3, 2).val == 2.0 and g.cell(3, 6).val == 10.0


def test_xlsx_round_trip_keeps_which_formulas_are_legacy(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in range(1, 6):
        ws.cell(r, 1, r)
    ws["C3"] = "=A1:A5*2"  # openpyxl writes a plain formula: legacy, as in Excel
    src = tmp_path / "legacy.xlsx"
    wb.save(str(src))
    g = Grid()
    assert g.xlsxload(str(src)) == 0
    assert g.cell(2, 2).legacy and g.cell(2, 2).val == 6.0
    g.setcell(2, 4, "=A1:A5*2")  # typed in gridcalc: dynamic
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    g2 = Grid()
    assert g2.xlsxload(str(out)) == 0
    assert g2.cell(2, 2).legacy and g2.cell(2, 2).val == 6.0
    assert not g2.cell(2, 4).legacy and g2.cell(2, 8).val == 10.0
    f = tmp_path / "out.json"
    assert g2.jsonsave(str(f)) == 0
    g3 = Grid()
    assert g3.jsonload(str(f)) == 0
    assert g3.cell(2, 2).legacy and g3.cell(2, 2).val == 6.0


def test_editing_a_legacy_formula_makes_it_dynamic() -> None:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, r, str(r + 1)) for r in range(5)])
    g.setcell(3, 2, "=A1:A5")
    g.cell(3, 2).legacy = True
    g.setcell(3, 2, "=A1:A5")
    assert not g.cell(3, 2).legacy and g.cell(3, 2).val == 1.0
