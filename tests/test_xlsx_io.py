import math

import pytest

openpyxl = pytest.importorskip("openpyxl")

from gridcalc.engine import Grid, Mode  # noqa: E402


def test_xlsxsave_empty_grid_returns_minus_one(tmp_path):
    g = Grid()
    assert g.xlsxsave(str(tmp_path / "empty.xlsx")) == -1


def test_xlsxload_multisheet_preserves_sheets(tmp_path):
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Inputs"
    ws1.cell(row=1, column=1, value=10)
    ws1.cell(row=2, column=1, value=20)
    ws2 = wb.create_sheet("Outputs")
    ws2.cell(row=1, column=1, value=42)
    ws2.cell(row=2, column=1, value="hello")
    f = tmp_path / "multi.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert g.sheet_names() == ["Inputs", "Outputs"]
    # First xlsx sheet becomes active.
    assert g.active == 0
    assert g.cells[0][0].val == 10.0
    assert g.cells[0][1].val == 20.0
    g.set_active("Outputs")
    assert g.cells[0][0].val == 42.0
    assert g.cells[0][1].text == "hello"


def test_xlsxsave_multisheet_writes_all_sheets(tmp_path):
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.rename_sheet("Sheet1", "Inputs")
    g.setcell(0, 0, "10")
    g.add_sheet("Outputs")
    g.set_active("Outputs")
    g.setcell(0, 0, "20")
    f = tmp_path / "saved.xlsx"
    assert g.xlsxsave(str(f)) == 0

    wb = openpyxl.load_workbook(str(f))
    assert set(wb.sheetnames) == {"Inputs", "Outputs"}
    assert wb["Inputs"].cell(row=1, column=1).value == 10.0
    assert wb["Outputs"].cell(row=1, column=1).value == 20.0


def test_xlsx_multisheet_roundtrip_preserves_cross_sheet_formula_value(tmp_path):
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.rename_sheet("Sheet1", "Source")
    g.setcell(0, 0, "10")
    g.add_sheet("Derived")
    g.set_active("Derived")
    g.setcell(0, 0, "=Source!A1*5")
    assert g.cells[0][0].val == 50.0
    f = tmp_path / "rt.xlsx"
    assert g.xlsxsave(str(f)) == 0

    g2 = Grid()
    assert g2.xlsxload(str(f)) == 0
    assert set(g2.sheet_names()) == {"Source", "Derived"}
    g2.set_active("Source")
    assert g2.cells[0][0].val == 10.0
    g2.set_active("Derived")
    # xlsx round-trip stores evaluated values (not formulas), so the
    # loaded Derived!A1 is the saved 50.0 -- not a live formula.
    assert g2.cells[0][0].val == 50.0


def test_xlsxsave_basic(tmp_path):
    g = Grid()
    g.setcell(0, 0, "Header")
    g.setcell(1, 0, "10")
    g.setcell(2, 0, "=B1*2")
    f = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(f)) == 0
    wb = openpyxl.load_workbook(str(f), data_only=False)
    ws = wb.active
    assert ws.cell(row=1, column=1).value == "Header"
    assert ws.cell(row=1, column=2).value == 10.0
    # legacy mode evaluates =B1*2 = 20; we save the value
    assert ws.cell(row=1, column=3).value == 20.0


def test_xlsxload_values(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="City")
    ws.cell(row=1, column=2, value="Pop")
    ws.cell(row=2, column=1, value="NYC")
    ws.cell(row=2, column=2, value=8000000)
    f = tmp_path / "data.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert g.mode == Mode.EXCEL
    assert "xlsx" in g.libs
    assert g.cells[0][0].text == "City"
    assert g.cells[1][1].val == 8000000.0


def test_xlsxload_formulas(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value=10)
    ws.cell(row=1, column=2, value=20)
    ws.cell(row=1, column=3, value="=A1+B1")
    f = tmp_path / "f.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    # formula should be re-evaluated by gridcalc EXCEL evaluator
    assert g.cells[2][0].val == 30.0


def test_xlsxload_then_save_roundtrip(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value=5)
    ws.cell(row=1, column=2, value="=A1*3")
    src = tmp_path / "src.xlsx"
    wb.save(str(src))

    g = Grid()
    assert g.xlsxload(str(src)) == 0
    dst = tmp_path / "dst.xlsx"
    assert g.xlsxsave(str(dst)) == 0
    wb2 = openpyxl.load_workbook(str(dst), data_only=False)
    ws2 = wb2.active
    assert ws2.cell(row=1, column=1).value == 5.0
    # value, not formula, per phase 2 design
    assert ws2.cell(row=1, column=2).value == 15.0


def test_xlsxload_bool(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value=True)
    ws.cell(row=1, column=2, value=False)
    f = tmp_path / "b.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert g.cells[0][0].text == "TRUE"
    assert g.cells[1][0].text == "FALSE"


def test_xlsxload_unknown_function_yields_nan(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="=NONESUCH()")
    f = tmp_path / "u.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert math.isnan(g.cells[0][0].val)


def test_xlsxload_xlsx_lib_functions_work(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value=1)
    ws.cell(row=2, column=1, value=2)
    ws.cell(row=3, column=1, value=3)
    ws.cell(row=4, column=1, value="=AVERAGE(A1:A3)")
    f = tmp_path / "avg.xlsx"
    wb.save(str(f))

    g = Grid()
    assert g.xlsxload(str(f)) == 0
    assert g.cells[0][3].val == 2.0


def test_xlsxload_missing_file_returns_minus_one(tmp_path):
    g = Grid()
    assert g.xlsxload(str(tmp_path / "nope.xlsx")) == -1
