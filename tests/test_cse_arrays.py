"""Legacy (Ctrl+Shift+Enter) array formulas: `t="array"` without the dynamic-array flag.

Excel fits the result to the range the formula was entered over, and never
spills past it. openpyxl writes `ArrayFormula` this way.
"""

import json
import zipfile

import pytest

openpyxl = pytest.importorskip("openpyxl")
from openpyxl.worksheet.formula import ArrayFormula  # noqa: E402

from gridcalc.engine import Grid  # noqa: E402
from gridcalc.formula.errors import ExcelError  # noqa: E402


def _load(tmp_path, ref: str, formula: str, data=((1, 2, 3),)) -> Grid:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r, row in enumerate(data, start=1):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    ws[ref.split(":")[0]] = ArrayFormula(ref, formula)
    path = tmp_path / "cse.xlsx"
    wb.save(path)
    g = Grid()
    assert g.xlsxload(str(path)) == 0
    return g


def _v(g: Grid, c: int, r: int):
    cl = g.cell(c, r)
    if cl is None:
        return None
    if cl.err is not None:
        return cl.err
    return cl.sval if cl.sval is not None else cl.val


def test_one_cell_shows_the_first_element_and_does_not_spill(tmp_path):
    g = _load(tmp_path, "E1", "=INDEX(A1:C1,,0)")
    assert _v(g, 4, 0) == 1
    assert _v(g, 5, 0) is None


def test_a_column_past_the_result_is_na(tmp_path):
    g = _load(tmp_path, "E1:E4", "=TRANSPOSE(A1:C1)*2")
    assert [_v(g, 4, r) for r in range(4)] == [2, 4, 6, ExcelError.NA]
    assert _v(g, 4, 4) is None


def test_a_row_repeats_down_and_a_value_fills_the_range(tmp_path):
    g = _load(tmp_path, "E1:G2", "=A1:C1*10")
    assert [[_v(g, 4 + c, r) for c in range(3)] for r in range(2)] == [[10, 20, 30]] * 2
    g = _load(tmp_path, "E1:E3", "=SUM(A1:C1)")
    assert [_v(g, 4, r) for r in range(3)] == [6, 6, 6]


def test_a_smaller_range_clips_the_result(tmp_path):
    g = _load(tmp_path, "E1:F1", "=A1:C1")
    assert [_v(g, 4, 0), _v(g, 5, 0), _v(g, 6, 0)] == [1, 2, None]


def test_xlsx_save_keeps_the_range_without_the_dynamic_flag(tmp_path):
    g = _load(tmp_path, "E1:E4", "=TRANSPOSE(A1:C1)*2")
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    with zipfile.ZipFile(out) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    cell = xml[xml.index('<c r="E1"') :].split("</c>")[0]
    assert 't="array" ref="E1:E4"' in cell and "cm=" not in cell
    g2 = Grid()
    assert g2.xlsxload(str(out)) == 0
    assert g2.cell(4, 0).cse == (4, 1)
    assert [_v(g2, 4, r) for r in range(4)] == [2, 4, 6, ExcelError.NA]


def test_json_round_trip_keeps_the_range(tmp_path):
    g = _load(tmp_path, "E1", "=INDEX(A1:C1,,0)")
    path = tmp_path / "b.json"
    assert g.jsonsave(str(path)) == 0
    g2 = Grid()
    assert g2.jsonload(str(path)) == 0
    assert g2.cell(4, 0).cse == (1, 1)
    assert _v(g2, 4, 0) == 1 and _v(g2, 5, 0) is None


@pytest.mark.parametrize("bad", [[0, 1], [1, 2**40], [1.5, 1], "1x1", [1]])
def test_json_ignores_an_invalid_range(tmp_path, bad):
    path = tmp_path / "b.json"
    g = _load(tmp_path, "E1", "=INDEX(A1:C1,,0)")
    assert g.jsonsave(str(path)) == 0
    doc = json.loads(path.read_text())
    doc["sheets"][0]["cells"][0][4]["cse"] = bad  # E1: rows of cells
    path.write_text(json.dumps(doc))
    g2 = Grid()
    assert g2.jsonload(str(path)) == 0
    assert g2.cell(4, 0).cse is None


def test_editing_the_formula_makes_it_dynamic(tmp_path):
    g = _load(tmp_path, "E1", "=INDEX(A1:C1,,0)")
    g.setcell(4, 0, "=INDEX(A1:C1,,0)")
    assert g.cell(4, 0).cse is None
    assert [_v(g, 4 + c, 0) for c in range(3)] == [1, 2, 3]


def test_a_sheet_sized_range_loads_and_gives_num(tmp_path):
    """A crafted `ref` names 1.7e10 cells; the load must not list them."""
    g = _load(tmp_path, "A1:XFD1048576", "=1", data=())
    assert g.cell(0, 0).err is ExcelError.NUM
