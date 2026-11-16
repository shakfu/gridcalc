"""Trim references (`A:.A`, `A.:A`, `A.:.A`): TRIMRANGE written as a separator.

Values probed against Excel 16.114. Excel stores them in a file as
`_xlfn._TRO_TRAILING(A:A)`, `_TRO_LEADING` and `_TRO_ALL`.
"""

from __future__ import annotations

import zipfile

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError

openpyxl = pytest.importorskip("openpyxl")


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, 0, "1"), (0, 1, "2"), (0, 2, "3"), (25, 0, "5")])
    return g


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=ROWS(A:.A)", 3.0),
        ("=ROWS(A.:A)", 1048576.0),
        ("=ROWS(TRIMRANGE(A:A,1))", 1048576.0),  # leading only keeps the tail
        ("=ROWS(A2.:A20)", 19.0),
        ("=ROWS(A2:.A20)", 2.0),
        ("=COLUMNS(A1.:Z1)", 26.0),
        ("=ROWS(B5.:.B9)", ExcelError.REF),  # nothing left
    ],
)
def test_a_trim_reference_drops_blank_edges(formula, value) -> None:
    g = _grid()
    g.setcell(9, 9, formula)
    cl = g.cell(9, 9)
    assert (cl.err if cl.err is not None else cl.val) == value


def test_excel_file_form_loads_as_the_separator_and_saves_back(tmp_path) -> None:
    src = tmp_path / "in.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for r, v in enumerate([1, 2, 3], start=2):
        ws.cell(r, 1, v)
    ws["C1"] = "=ROWS(_xlfn._TRO_TRAILING(A:A))"
    ws["C2"] = "=ROWS(_xlfn._TRO_LEADING(A:A))"
    ws["C3"] = "=SUM(_xlfn._TRO_ALL(Sheet!A1:B20))"
    wb.save(src)
    g = Grid()
    g.xlsxload(str(src))
    assert [g.cell(2, r).text for r in range(3)] == [
        "=ROWS(A:.A)",
        "=ROWS(A.:A)",
        "=SUM(Sheet!A1.:.B20)",
    ]
    assert [g.cell(2, r).val for r in range(3)] == [4.0, 1048575.0, 6.0]
    out = tmp_path / "out.xlsx"
    g.xlsxsave(str(out))
    with zipfile.ZipFile(out) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert "ROWS(_xlfn._TRO_TRAILING(A:A))" in xml
    assert "ROWS(_xlfn._TRO_LEADING(A:A))" in xml
    assert "SUM(_xlfn._TRO_ALL(Sheet!A1:B20))" in xml


def test_inserting_rows_and_columns_moves_both_ends() -> None:
    g = _grid()
    g.setcells_bulk([(5, 5, "=SUM(A1:.A9)"), (5, 6, "=ROWS(A.:.A)"), (5, 7, "=ROWS(1:.3)")])
    g.insertrow(0)
    g.insertcol(0)
    assert [g.cell(6, r).text for r in (6, 7, 8)] == [
        "=SUM(B2:.B10)",
        "=ROWS(B.:.B)",
        "=ROWS(2:.4)",
    ]
    assert [g.cell(6, r).val for r in (6, 7, 8)] == [6.0, 3.0, 3.0]


def test_a_trim_call_over_another_reference_keeps_its_prefix() -> None:
    from gridcalc.engine import _add_xl_prefixes, _strip_xl_prefixes

    text = _strip_xl_prefixes("=ROWS(_xlfn._TRO_TRAILING((A1:A9)))")
    assert text == "=ROWS(_TRO_TRAILING((A1:A9)))"
    assert _add_xl_prefixes(text) == "=ROWS(_xlfn._TRO_TRAILING((A1:A9)))"
