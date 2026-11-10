"""Hidden and filtered rows in SUBTOTAL and AGGREGATE, against Excel for Mac 16.114.

`tests/xlsx/hidden_input.xlsx` is built by `scripts/build_hidden_model.py`;
`hidden_excel.xlsx` is the same file recalculated and saved by Excel. Its five
sheets hide the same rows by hand, by a sheet filter with and without a
criterion, and by a table filter with and without one
(`docs/dev/hidden-rows.md`).
"""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from gridcalc.engine import Grid, Mode, _shift_autofilter
from gridcalc.undo import UndoManager

_ROOT = Path(__file__).resolve().parent.parent
INPUT = _ROOT / "tests" / "xlsx" / "hidden_input.xlsx"
SAVED = _ROOT / "tests" / "xlsx" / "hidden_excel.xlsx"


def _excel_corpus():
    pytest.importorskip("openpyxl")
    spec = importlib.util.spec_from_file_location(
        "excel_corpus", _ROOT / "scripts" / "excel_corpus.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wrong(ec, g) -> list:
    formulas, saved = ec.excel_values(SAVED)
    return [
        (k, formulas[k], saved[k], got)
        for k in formulas
        if not ec.same(saved[k], got := ec.gridcalc_value(g, k), 0)
    ]


def test_every_cell_matches_excel() -> None:
    from gridcalc.loader import load_workbook

    ec = _excel_corpus()
    formulas, saved = ec.excel_values(SAVED)
    assert "Excel" in ec.application(SAVED)
    assert set(saved) == set(formulas) and len(formulas) == 95  # 90 totals, 5 =NA()
    assert _wrong(ec, load_workbook(str(INPUT))) == []


def test_only_rows_under_a_filter_criterion_count_as_filtered() -> None:
    from gridcalc.loader import load_workbook

    g = load_workbook(str(INPUT))
    filtered = {s.name: sorted(s.filtered_rows) for s in g.sheets}
    assert all(sorted(s.hidden_rows) == [2, 4, 8] for s in g.sheets)
    assert filtered == {
        "manual": [],
        "sheet_filter": [2, 4, 8],
        "sheet_filter_no_criterion": [],
        "table_filter": [2, 4, 8],
        "table": [],
    }


def test_an_xlsx_save_keeps_hidden_rows_and_the_sheet_filter(tmp_path: Path) -> None:
    """Excel read gridcalc's save of the input with the same results (docs/dev)."""
    from gridcalc.loader import load_workbook

    ec = _excel_corpus()
    out = tmp_path / "out.xlsx"
    assert load_workbook(str(INPUT)).xlsxsave(str(out)) == 0
    with zipfile.ZipFile(out) as z:
        names = {n for n in z.namelist() if n.startswith("xl/worksheets/sheet")}
        sheet = next(n for n in names if b"<filterColumn" in z.read(n))
        xml = z.read(sheet)
    assert xml.count(b'hidden="1"') == 3
    assert xml.index(b"<autoFilter") > xml.index(b"</sheetData>")
    g = load_workbook(str(out))
    assert sorted(g.sheets[1].filtered_rows) == [2, 4, 8]
    assert _wrong(ec, g) == []


def _hidden_grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for r, v in enumerate([1, 2, 4, 8, 16]):
        g.setcell(0, r, str(v))
    g.setcell(2, 0, "=SUBTOTAL(109,A1:A5)")
    g.setcell(2, 1, "=SUBTOTAL(9,A1:A5)")
    g._active.hidden_rows = {1, 3}
    g._active.filtered_rows = {3}
    g.recalc()
    return g


def _vals(g: Grid) -> tuple[float, float]:
    return g._cells[(2, 0)].val, g._cells[(2, 1)].val


def test_subtotal_reads_the_hidden_rows_of_the_sheet() -> None:
    assert _vals(_hidden_grid()) == (21.0, 23.0)


def test_hidden_rows_round_trip_through_json(tmp_path: Path) -> None:
    g = _hidden_grid()
    g.jsonsave(str(tmp_path / "w.json"))
    entry = json.loads((tmp_path / "w.json").read_text())["sheets"][0]
    assert entry["hidden_rows"] == [1, 3] and entry["filtered_rows"] == [3]
    h = Grid()
    h.jsonload(str(tmp_path / "w.json"))
    assert (h._active.hidden_rows, h._active.filtered_rows) == ({1, 3}, {3})
    assert _vals(h) == (21.0, 23.0)


def test_json_drops_bad_rows_and_filtered_rows_that_are_not_hidden(tmp_path: Path) -> None:
    p = tmp_path / "w.json"
    sheet = {"name": "S", "cells": [[1]], "hidden_rows": [1, -1, "2", 5000000, True, 4]}
    sheet["filtered_rows"] = [1, 7]
    p.write_text(json.dumps({"version": 2, "mode": "EXCEL", "sheets": [sheet]}))
    g = Grid()
    g.jsonload(str(p))
    assert (g._active.hidden_rows, g._active.filtered_rows) == ({1, 4}, {1})


def test_row_insert_and_delete_move_hidden_rows() -> None:
    g = _hidden_grid()
    g.cr = 0
    g.insertrow(0)
    assert (g._active.hidden_rows, g._active.filtered_rows) == ({2, 4}, {4})
    g.deleterow(2)  # a hidden row goes with its row
    assert (g._active.hidden_rows, g._active.filtered_rows) == ({3}, {3})


def test_undo_restores_hidden_rows() -> None:
    g, u = _hidden_grid(), UndoManager()
    u.save_grid(g)
    g.deleterow(1)
    assert g._active.hidden_rows == {2}
    assert u.undo(g)
    assert (g._active.hidden_rows, g._active.filtered_rows) == ({1, 3}, {3})


_AF = (
    '<autoFilter ref="B2:D9"><filterColumn colId="0"><filters><filter val="1"/></filters>'
    '</filterColumn><filterColumn colId="2"><filters><filter val="2"/></filters></filterColumn>'
    '<sortState ref="B3:D9"><sortCondition ref="B3:B9"/></sortState></autoFilter>'
)


def test_the_sheet_filter_moves_with_rows_and_loses_its_sort() -> None:
    assert _shift_autofilter(_AF, "R", 0, +1).startswith('<autoFilter ref="B3:D10">')
    assert "<sortState" not in _shift_autofilter(_AF, "R", 0, +1)
    assert _shift_autofilter(_AF, "R", 20, +1) == _AF  # below it: unchanged
    assert _shift_autofilter(_AF, "R", 1, -1) is None  # its header row deleted


def test_the_sheet_filter_keeps_its_criteria_on_their_columns() -> None:
    moved = _shift_autofilter(_AF, "C", 2, +1)  # a column inside, before D
    assert moved.startswith('<autoFilter ref="B2:E9">')
    assert 'colId="0"' in moved and 'colId="3"' in moved and 'colId="2"' not in moved
    gone = _shift_autofilter(_AF, "C", 1, -1)  # delete B, the first criterion's column
    assert gone.startswith('<autoFilter ref="B2:C9">')
    assert gone.count("<filterColumn") == 1 and 'colId="1"' in gone
    assert _shift_autofilter(_AF, "C", 0, +1).startswith('<autoFilter ref="C2:E9">')
