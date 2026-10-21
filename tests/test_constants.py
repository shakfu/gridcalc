"""Typed logical and error constants (`TRUE`, `#N/A`), as Excel keeps them."""

import zipfile

import pytest

from gridcalc.engine import LABEL, NUM, Grid, Mode, is_constant
from gridcalc.formula.errors import ExcelError

openpyxl = pytest.importorskip("openpyxl")


def _grid(mode: Mode = Mode.EXCEL) -> Grid:
    g = Grid()
    g.mode = mode
    g._apply_mode_libs()
    return g


@pytest.mark.parametrize(
    ("typed", "text", "val", "err"),
    [
        ("TRUE", "TRUE", True, None),
        ("false", "FALSE", False, None),
        ("#N/A", "#N/A", None, ExcelError.NA),
        ("#div/0!", "#DIV/0!", None, ExcelError.DIV0),
    ],
)
@pytest.mark.parametrize("mode", [Mode.EXCEL, Mode.HYBRID])
def test_a_typed_constant_is_a_logical_or_an_error(typed, text, val, err, mode) -> None:
    g = _grid(mode)
    g.setcell(0, 0, typed)
    cl = g.cells[0][0]
    assert cl.type == NUM and cl.text == text and is_constant(cl)
    assert cl.err is err
    if val is not None:
        assert cl.val is val


def test_constants_read_as_excel_reads_them() -> None:
    g = _grid()
    g.setcell(0, 0, "TRUE")
    g.setcell(0, 1, "5")
    g.setcell(0, 2, "#N/A")
    for r, f in enumerate(
        ["=ISLOGICAL(A1)", "=COUNT(A1:A2)", "=SUM(A1:A2)", "=A1+1", "=ISNA(A3)", "=ISFORMULA(A1)"]
    ):
        g.setcell(1, r, f)
    g.recalc()
    assert [g.cells[1][r].val for r in range(6)] == [True, 1, 5, 2, True, False]


def test_python_mode_and_the_label_marker_keep_text() -> None:
    p = _grid(Mode.PYTHON)
    p.setcell(0, 0, "TRUE")
    assert p.cells[0][0].type == LABEL
    g = _grid()
    g.setcell(0, 0, '"TRUE')
    assert g.cells[0][0].type == LABEL


def test_constants_round_trip_through_json(tmp_path) -> None:
    g = _grid()
    g.setcell(0, 0, "TRUE")
    g.setcell(0, 1, "#N/A")
    g._put_label(0, 2, '"FALSE')  # text that would read back as a logical
    f = tmp_path / "c.json"
    assert g.jsonsave(str(f)) == 0
    h = Grid()
    assert h.jsonload(str(f)) == 0
    assert h.cells[0][0].val is True and h.cells[0][1].err is ExcelError.NA
    assert h.cells[0][2].type == LABEL


def test_constants_round_trip_through_xlsx(tmp_path) -> None:
    g = _grid()
    g.setcell(0, 0, "TRUE")
    g.setcell(0, 1, "#N/A")
    g.setcell(0, 2, "=A2")
    g.recalc()
    f = tmp_path / "c.xlsx"
    assert g.xlsxsave(str(f)) == 0
    with zipfile.ZipFile(f) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert '<c r="A2" t="e"><v>#N/A</v></c>' in xml
    ws = openpyxl.load_workbook(f).active
    assert ws["A1"].value is True and ws["A2"].value == "#N/A" and ws["A2"].data_type == "e"
    h = Grid()
    assert h.xlsxload(str(f)) == 0
    assert h.cells[0][0].val is True and h.cells[0][1].err is ExcelError.NA
    assert is_constant(h.cells[0][1]) and h.cells[0][2].err is ExcelError.NA


def test_xlsx_text_that_reads_as_a_constant_stays_text(tmp_path) -> None:
    wb = openpyxl.Workbook()
    wb.active["A1"] = "TRUE"  # a string cell
    f = tmp_path / "t.xlsx"
    wb.save(f)
    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert g.cells[0][0].type == LABEL and g.cells[0][0].text == '"TRUE'


def test_goal_seek_refuses_a_constant_variable() -> None:
    from gridcalc.goalseek import GoalSeekError, seek

    g = _grid()
    g.setcell(0, 0, "TRUE")
    g.setcell(1, 0, "=A1*2")
    g.recalc()
    with pytest.raises(GoalSeekError):
        seek(g, formula_cell=(1, 0), target=4.0, var_cell=(0, 0))
