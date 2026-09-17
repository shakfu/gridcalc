"""Values survive save and reload: JSON, CSV, xlsx and pandas paths."""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gridcalc import loader
from gridcalc.engine import FORMULA, LABEL, NUM, Grid, Mode
from gridcalc.sandbox import LoadPolicy

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HYBRID = EXAMPLES / "example_hybrid.json"

PRECISE = ["1234567.891", "3.141592653589793", "12345678901234567", "0.1", "1e-300"]


def _excel() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


# --- JSON ---------------------------------------------------------------------


def test_json_keeps_every_digit_of_a_double(tmp_path: Path) -> None:
    g = _excel()
    g.setcells_bulk((0, r, t) for r, t in enumerate(PRECISE))
    f = tmp_path / "p.json"
    assert g.jsonsave(str(f)) == 0
    h = Grid()
    assert h.jsonload(str(f)) == 0
    assert [h.cells[0][r].val for r in range(len(PRECISE))] == [float(t) for t in PRECISE]


def test_json_infinity_round_trips_as_a_number_and_stays_valid_json(tmp_path: Path) -> None:
    g = _excel()
    g.setcell(0, 0, "1e400")
    g.setcell(0, 1, "-1e400")
    assert g.cells[0][0].val == math.inf
    f = tmp_path / "inf.json"
    assert g.jsonsave(str(f)) == 0

    def reject(token: str) -> None:
        raise AssertionError(f"invalid JSON constant {token}")

    json.loads(f.read_text(), parse_constant=reject)
    h = Grid()
    assert h.jsonload(str(f)) == 0
    assert (h.cells[0][0].type, h.cells[0][0].val) == (NUM, math.inf)
    assert (h.cells[0][1].type, h.cells[0][1].val) == (NUM, -math.inf)


def test_boolean_formula_results_round_trip_through_json(tmp_path: Path) -> None:
    g = _excel()
    g.setcell(0, 0, "=1>2")
    g.setcell(1, 0, "=A1+1")
    f = tmp_path / "b.json"
    assert g.jsonsave(str(f)) == 0
    h = Grid()
    assert h.jsonload(str(f)) == 0
    assert h.cells[0][0].val is False and h.cells[0][0].sval == "FALSE"
    assert h.cells[1][0].val == 1.0


@pytest.mark.parametrize("bad", [{"v": 1, "fmt": 5}, {"v": 1, "fmtstr": 7}, {"v": 1, "fmt": []}])
def test_a_malformed_cell_style_fails_the_load_and_changes_nothing(tmp_path: Path, bad) -> None:
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"version": 2, "sheets": [{"name": "S", "cells": [[bad]]}]}))
    g = _excel()
    g.setcell(0, 0, "keep")
    g.setcell(1, 0, "=LEN(A1)")
    g.code = ""
    before = (g.sheet_names(), g.mode, list(g.libs))
    assert g.jsonload(str(f)) == -1
    assert g.io_error
    assert (g.sheet_names(), g.mode, list(g.libs)) == before
    assert g.cells[0][0].text == "keep"
    g.setcell(0, 0, "hello")  # the dep graph still drives recalcs
    assert g.cells[1][0].val == 5


def test_a_withheld_code_block_is_written_back_on_save(tmp_path: Path) -> None:
    original = json.loads(HYBRID.read_text())
    g = loader.load_workbook(HYBRID, LoadPolicy.formulas_only())
    assert g.code == ""
    assert not any("code block" in e for e in g.validate_for_mode(Mode.EXCEL))
    out = tmp_path / "saved.json"
    loader.save_workbook(g, out)
    saved = json.loads(out.read_text())
    assert saved["code"] == original["code"]
    assert saved.get("requires", []) == original.get("requires", [])
    # Approving the saved file runs the code it kept.
    trusted = loader.load_workbook(out, LoadPolicy.trust_all(saved.get("requires")))
    assert trusted.code == original["code"]
    assert trusted.withheld_code == ""


def test_new_code_replaces_withheld_code_on_save(tmp_path: Path) -> None:
    g = loader.load_workbook(HYBRID, LoadPolicy.formulas_only())
    g.code = "def f():\n    return 1\n"
    out = tmp_path / "saved.json"
    loader.save_workbook(g, out)
    assert json.loads(out.read_text())["code"] == g.code


def test_a_later_load_forgets_withheld_code(tmp_path: Path) -> None:
    g = loader.load_workbook(HYBRID, LoadPolicy.formulas_only())
    plain = tmp_path / "plain.json"
    _excel().jsonsave(str(plain))
    assert g.jsonload(str(plain)) == 0
    assert g.withheld_code == ""


# --- CSV and pandas -------------------------------------------------------------


def test_csv_load_recalcs_once_in_python_mode(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "d.csv"
    f.write_text("\n".join(",".join(str(c * r) for c in range(10)) for r in range(50)))
    g = Grid()
    assert g.mode == Mode.PYTHON
    calls = []
    monkeypatch.setattr(g, "_recalc_python", lambda: calls.append(1))
    assert g.csvload(str(f)) == 0
    assert len(calls) == 1
    assert g.cells[9][49].text == str(9 * 49)


def test_csv_load_of_non_utf8_bytes_fails_cleanly(tmp_path: Path) -> None:
    f = tmp_path / "latin1.csv"
    f.write_bytes("caf\xe9,1\n".encode("latin-1"))
    g = _excel()
    g.setcell(0, 0, "keep")
    assert g.csvload(str(f)) == -1
    assert g.io_error
    assert g.cells[0][0].text == "keep"


_ENCODING_CHILD = """
import importlib.util, sys
from gridcalc.engine import Grid, Mode
from gridcalc.sandbox import inspect_file

d, text = sys.argv[1], sys.argv[2]
g = Grid()
g.mode = Mode.EXCEL
g._apply_mode_libs()
g.setcell(0, 0, "h")
g.setcell(0, 1, text)
exts = ["json", "csv"] + (["pd.json"] if importlib.util.find_spec("pandas") else [])
for ext in exts:
    path = f"{d}/book.{ext}"
    save, load = {"json": ("jsonsave", "jsonload"), "csv": ("csvsave", "csvload")}.get(
        ext, ("pdsave", "pdload")
    )
    assert getattr(g, save)(path) == 0, (ext, g.io_error)
    h = Grid()
    h.mode = Mode.EXCEL
    h._apply_mode_libs()
    assert getattr(h, load)(path) == 0, (ext, h.io_error)
    assert h.cells[0][1].text == text, (ext, h.cells[0][1].text)
assert inspect_file(f"{d}/book.json") is not None
"""


def test_text_files_are_utf8_whatever_the_locale(tmp_path: Path) -> None:
    # Windows' locale encoding is cp1252, so an open() without encoding= wrote
    # workbooks other platforms could not read. The warning finds such calls anywhere.
    proc = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning"]
        + ["-c", _ENCODING_CHILD, str(tmp_path), "caf\u00e9 \u6570\u5b57"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "GRIDCALC_SANDBOX": "1"},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def test_pd_load_recalcs_once_in_python_mode(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    f = tmp_path / "d.csv"
    f.write_text("a,b\n" + "\n".join(f"{r},{r / 3}" for r in range(50)))
    g = Grid()
    calls = []
    monkeypatch.setattr(g, "_recalc_python", lambda: calls.append(1))
    assert g.pdload(str(f)) == 0
    assert len(calls) == 1
    assert g.cells[1][50].val == 49 / 3  # every digit, not "%g"


def test_csv_writes_computed_text_booleans_and_full_precision(tmp_path: Path) -> None:
    g = _excel()
    g.setcell(0, 0, "=1>2")
    g.setcell(1, 0, '="big"')
    g.setcell(2, 0, "=1/0")
    g.setcell(3, 0, "1234567.891")
    g.setcell(4, 0, '"=not a formula')
    f = tmp_path / "v.csv"
    assert g.csvsave(str(f)) == 0
    row = next(csv.reader(f.open()))
    assert row == ["FALSE", "big", "", "1234567.891", "=not a formula"]


def test_pd_save_writes_text_results(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    g = _excel()
    g.setcell(0, 0, "head")
    g.setcell(0, 1, '="big"')
    f = tmp_path / "v.csv"
    assert g.pdsave(str(f)) == 0
    assert f.read_text().splitlines() == ["head", "big"]


def _cells(g: Grid) -> list[tuple[int, int, int, str]]:
    return sorted((c, r, cl.type, cl.text) for (c, r), cl in g._cells.items() if cl.type)


@pytest.mark.parametrize("ext", [".csv", ".tsv"])
def test_pd_load_reads_delimited_text_as_csv_load_does(tmp_path: Path, ext: str) -> None:
    pytest.importorskip("pandas")
    sep = "\t" if ext == ".tsv" else ","
    rows = [
        ["country", "code", "val", "big"],
        ["Namibia", "NA", "0.30000000000000004", "9007199254740993"],
        ["None", "N/A", "TRUE", ""],
        ["null", "", "1e400", "-0", "extra"],
        ["short"],
    ]
    f = tmp_path / ("d" + ext)
    f.write_text("\n".join(sep.join(r) for r in rows) + "\n")
    csv_f = tmp_path / "d.csv"
    csv_f.write_text("\n".join(",".join(r) for r in rows) + "\n")
    g, h = _excel(), _excel()
    assert g.pdload(str(f)) == 0
    assert h.csvload(str(csv_f)) == 0
    assert _cells(g) == _cells(h)


def test_pd_load_keeps_json_value_types(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    f = tmp_path / "d.json"
    records = [
        {"date": "2024-01-02", "s": "007", "f": 0.30000000000000004, "b": True, "n": None, "i": 1},
        {"date": "=x", "s": "abc", "f": 2.5, "b": False, "n": 2, "i": 9007199254740993},
    ]
    f.write_text(json.dumps(records))
    g = _excel()
    assert g.pdload(str(f)) == 0
    got = {(c, r): (t, text) for c, r, t, text in _cells(g)}
    assert got[(0, 1)] == (LABEL, "2024-01-02")
    assert got[(1, 1)] == (LABEL, '"007')
    assert got[(2, 1)] == (NUM, "0.30000000000000004")
    assert got[(3, 1)] == (FORMULA, "=TRUE")
    assert (4, 1) not in got
    assert got[(0, 2)] == (LABEL, '"=x')
    assert got[(5, 2)] == (NUM, "9007199254740993")
    assert got[(4, 2)] == (NUM, "2")
    assert got[(0, 0)] == (LABEL, "date")


def test_pd_save_writes_plain_values(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    g = _excel()
    for c, t in enumerate(['"code', "qty", "ok", "f", "err"]):
        g.setcell(c, 0, t)
    for c, t in enumerate(['"007', "120", "=1<2", "0.30000000000000004", "=1/0"]):
        g.setcell(c, 1, t)
    f = tmp_path / "v.csv"
    assert g.pdsave(str(f)) == 0
    assert list(csv.reader(f.open())) == [
        ["code", "qty", "ok", "f", "err"],
        ["007", "120", "TRUE", "0.30000000000000004", ""],
    ]
    j = tmp_path / "v.json"
    assert g.pdsave(str(j)) == 0
    assert json.loads(j.read_text()) == [
        {"code": "007", "qty": 120, "ok": True, "f": 0.30000000000000004, "err": None}
    ]


def test_pd_json_round_trip_keeps_types(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    g = _excel()
    g.setcells_bulk(
        [(0, 0, "name"), (1, 0, "code"), (2, 0, "ok"), (3, 0, "x")]
        + [(0, 1, "a"), (1, 1, '"00123'), (2, 1, "=TRUE"), (3, 1, PRECISE[1])]
    )
    f = tmp_path / "rt.json"
    assert g.pdsave(str(f)) == 0
    h = _excel()
    assert h.pdload(str(f)) == 0
    assert _cells(h) == _cells(g)


@pytest.mark.parametrize("name", ["book.xlsx", "book.parquet", "book.xls"])
def test_pd_refuses_file_types_it_does_not_handle(tmp_path: Path, name: str) -> None:
    pytest.importorskip("pandas")
    g = _excel()
    g.setcell(0, 0, "keep")
    f = tmp_path / name
    assert g.pdsave(str(f)) == -1
    assert g.io_error
    assert not f.exists()
    f.write_bytes(b"PK")
    assert g.pdload(str(f)) == -1
    assert g.cells[0][0].text == "keep"


def test_pd_json_save_refuses_repeated_headers(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    g = _excel()
    g.setcells_bulk([(0, 0, "x"), (1, 0, "x"), (0, 1, "1"), (1, 1, "2")])
    f = tmp_path / "dup.json"
    assert g.pdsave(str(f)) == -1
    assert g.io_error
    assert not f.exists()


# --- xlsx save ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a/b", "Sheet[1]", "x" * 32, "History", "", "'q"])
def test_xlsx_refuses_a_sheet_name_excel_rejects(tmp_path: Path, name: str) -> None:
    g = _excel()
    g.setcell(0, 0, "1")
    g.sheets[0].name = name
    target = tmp_path / "out.xlsx"
    target.write_bytes(b"old")
    assert g.xlsxsave(str(target)) == -1
    assert "sheet name" in (g.io_error or "")
    assert target.read_bytes() == b"old"
    with pytest.raises(OSError, match="sheet name"):
        loader.save_workbook(g, target)


def test_xlsx_formula_cached_values_keep_their_type(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    g = _excel()
    g.setcell(0, 0, "=1>2")
    g.setcell(1, 0, '="big"')
    g.setcell(2, 0, "=1/0")
    g.setcell(3, 0, "=2*3")
    f = tmp_path / "c.xlsx"
    assert g.xlsxsave(str(f)) == 0
    ws = openpyxl.load_workbook(str(f), data_only=True).active
    assert ws["A1"].value is False
    assert ws["B1"].value is None  # no cached value rather than a wrong 0
    assert ws["C1"].value is None
    assert ws["D1"].value == 6


def test_xlsx_values_only_export_keeps_text_and_boolean_results(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    g = Grid()  # PYTHON mode writes values only
    g.setcell(0, 0, '"=quoted label')
    g.setcell(1, 0, "=1+1")
    f = tmp_path / "v.xlsx"
    assert g.xlsxsave(str(f)) == 0
    ws = openpyxl.load_workbook(str(f)).active
    assert ws["A1"].value == "=quoted label"
    assert ws["B1"].value == 2


# --- xlsx load --------------------------------------------------------------------


def _xlsx(tmp_path: Path, fill) -> str:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    fill(wb)
    f = tmp_path / "in.xlsx"
    wb.save(str(f))
    return str(f)


def test_xlsx_import_keeps_every_digit_of_a_double(tmp_path: Path) -> None:
    def fill(wb):
        wb.active["A1"] = 1234567.891
        wb.active["A2"] = math.pi

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert (g.cells[0][0].val, g.cells[0][1].val) == (1234567.891, math.pi)


def test_xlsx_save_then_load_keeps_every_digit_of_a_double(tmp_path: Path) -> None:
    g = _excel()
    g.setcells_bulk((0, r, t) for r, t in enumerate(PRECISE))
    f = tmp_path / "p.xlsx"
    assert g.xlsxsave(str(f)) == 0
    h = Grid()
    assert h.xlsxload(str(f)) == 0
    assert [h.cells[0][r].val for r in range(len(PRECISE))] == [float(t) for t in PRECISE]


def test_xlsx_import_keeps_text_as_text_and_booleans_as_booleans(tmp_path: Path) -> None:
    def fill(wb):
        ws = wb.active
        ws["A1"].value = "=SUM(1,2)"
        ws["A1"].data_type = "s"
        ws["A2"] = "00123"
        ws["A3"] = True
        ws["A4"] = '"quoted'
        ws["A5"] = "plain"

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    a1, a2, a3, a4, a5 = (g.cells[0][r] for r in range(5))
    assert a1.type == LABEL and a1.val == 0
    assert a2.type == LABEL
    assert a3.type == FORMULA and a3.val is True
    assert a4.type == LABEL
    g.setcell(1, 0, "=A3+1")
    g.setcell(1, 1, '=A1&"|"&A2&"|"&A4&"|"&A5')
    assert g.cells[1][0].val == 2
    assert g.cells[1][1].sval == '=SUM(1,2)|00123|"quoted|plain'
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    h = Grid()
    assert h.xlsxload(str(out)) == 0
    assert [h.cells[0][r].type for r in range(5)] == [LABEL, LABEL, FORMULA, LABEL, LABEL]


def test_xlsx_import_keeps_error_values(tmp_path: Path) -> None:
    from gridcalc.formula.errors import ExcelError

    def fill(wb):
        ws = wb.active
        ws["A1"].value = "#N/A"
        ws["A1"].data_type = "e"
        ws["A2"] = "=A1"

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert g.cells[0][0].err is ExcelError.NA
    assert g.cells[0][1].err is ExcelError.NA


def test_xlsx_import_reports_cells_beyond_the_grid(tmp_path: Path) -> None:
    def fill(wb):
        ws = wb.active
        ws["A1"] = 1
        ws.cell(row=1, column=300, value=2)
        ws.cell(row=2000, column=1, value=3)

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert any("2 cells" in w for w in g.load_warnings), g.load_warnings


def test_xlsx_import_keeps_empty_worksheets(tmp_path: Path) -> None:
    def fill(wb):
        wb.active.title = "Data"
        wb.active["A1"] = 1
        wb.create_sheet("Blank")
        wb.create_sheet("Last")["A1"] = 2

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert g.sheet_names() == ["Data", "Blank", "Last"]


def test_xlsx_import_resets_workbook_fields(tmp_path: Path) -> None:
    def fill(wb):
        wb.active["A1"] = 1

    g = loader.load_workbook(HYBRID, LoadPolicy.trust_all())
    assert g.code
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert (g.code, g.withheld_code, g.models, g.requires) == ("", "", {}, [])
    assert g.validate_for_mode(Mode.EXCEL) == []


def test_xlsx_1904_dates_shift_to_the_1900_system(tmp_path: Path) -> None:
    import datetime as dt

    def fill(wb):
        wb.epoch = __import__("openpyxl").utils.datetime.CALENDAR_MAC_1904
        wb.active["A1"] = dt.datetime(2024, 1, 1)

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    assert g.cells[0][0].val == 45292.0  # 2024-01-01 in the 1900 system


def test_a_failed_xlsx_load_says_why(tmp_path: Path) -> None:
    f = tmp_path / "junk.xlsx"
    f.write_bytes(b"not a zip")
    g = Grid()
    assert g.xlsxload(str(f)) == -1
    assert g.io_error
    with pytest.raises(OSError, match=r"could not load workbook: .*junk\.xlsx \(.+\)"):
        loader.load_workbook(f)


def test_tui_style_formulas_only_open_then_save_keeps_code(tmp_path: Path) -> None:
    # The curses `:o` and startup paths call jsonload with the prompt's policy,
    # and `:w` calls save_workbook.
    g = _excel()
    assert g.jsonload(str(HYBRID), policy=LoadPolicy.formulas_only()) == 0
    out = tmp_path / "w.json"
    loader.save_workbook(g, out)
    assert json.loads(out.read_text())["code"] == json.loads(HYBRID.read_text())["code"]


def test_json_keeps_a_label_that_looks_like_a_number_or_formula(tmp_path: Path) -> None:
    def fill(wb):
        wb.active["A1"] = "00123"
        wb.active["A2"].value = "=SUM(1,2)"
        wb.active["A2"].data_type = "s"

    g = Grid()
    assert g.xlsxload(_xlsx(tmp_path, fill)) == 0
    out = tmp_path / "l.json"
    assert g.jsonsave(str(out)) == 0
    h = Grid()
    assert h.jsonload(str(out)) == 0
    assert [(h.cells[0][r].type, h.cells[0][r].text) for r in range(2)] == [
        (LABEL, "00123"),
        (LABEL, "=SUM(1,2)"),
    ]


def test_save_losses_counts_withheld_code() -> None:
    g = loader.load_workbook(HYBRID, LoadPolicy.formulas_only())
    assert "code" in loader.save_losses(g, "out.xlsx")
