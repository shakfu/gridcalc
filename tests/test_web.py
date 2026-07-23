"""Tests for the experimental web frontend (`gridcalc.web`).

The `pywebview` dependency is optional and imported lazily, so these tests
never need it or a display: the `Api` bridge is plain Python and is exercised
directly, exactly as the browser view would call it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from gridcalc.engine import NCOL, NROW, Grid, Mode
from gridcalc.web import Api

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


def test_dims_reports_sheet_extent() -> None:
    api = Api(_grid())
    d = api.dims()
    assert d["ncol"] == NCOL
    assert d["nrow"] == NROW
    assert d["filename"] == ""


def test_viewport_returns_only_nonempty_cells_with_alignment() -> None:
    g = _grid()
    g.setcell(0, 0, "label")
    g.setcell(1, 0, "42")
    g.setcell(2, 0, "=1+2")
    g.recalc()
    api = Api(g)
    vp = api.viewport(0, 0, 5, 5)
    by_rc = {(cell["r"], cell["c"]): cell for cell in vp["cells"]}

    assert set(by_rc) == {(0, 0), (0, 1), (0, 2)}  # empties omitted
    assert by_rc[(0, 0)]["text"] == "label"
    assert by_rc[(0, 0)]["align"] == "l"  # label -> left
    assert by_rc[(0, 1)]["text"] == "42"
    assert by_rc[(0, 1)]["align"] == "r"  # number -> right
    assert by_rc[(0, 2)]["text"] == "3"
    assert by_rc[(0, 2)]["align"] == "r"  # formula -> right


def test_viewport_clamps_to_sheet_bounds() -> None:
    api = Api(_grid())
    vp = api.viewport(-5, -5, 10, 10)
    assert vp["r0"] == 0 and vp["c0"] == 0
    vp2 = api.viewport(NROW - 2, NCOL - 2, 100, 100)
    assert vp2["rows"] == 2 and vp2["cols"] == 2


def test_cell_source_returns_editable_text() -> None:
    g = _grid()
    g.setcell(0, 0, "=1+2")
    g.recalc()
    api = Api(g)
    assert api.cell_source(0, 0) == "=1+2"  # formula text, not the value "3"
    assert api.cell_source(9, 9) == ""  # empty cell


def test_set_cell_writes_and_recalcs_dependents() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.setcell(1, 0, "=A1*2")
    g.recalc()
    api = Api(g)
    # Editing A1 must propagate to the dependent B1 through recalc.
    api.set_cell(0, 0, "25")
    vp = api.viewport(0, 0, 1, 2)
    by_rc = {(cell["r"], cell["c"]): cell["text"] for cell in vp["cells"]}
    assert by_rc[(0, 0)] == "25"
    assert by_rc[(0, 1)] == "50"


def test_sheets_and_set_active() -> None:
    g = _grid()
    g.add_sheet("Data")
    api = Api(g)
    assert api.sheets() == {"active": 0, "names": ["Sheet1", "Data"]}
    assert api.set_active(1)["active"] == 1
    api.set_active(99)  # out of range -> ignored, no raise
    assert api.sheets()["active"] == 1


def test_api_over_a_loaded_workbook() -> None:
    from gridcalc.web import load_workbook

    g = load_workbook(EXAMPLES / "example_excel.json")
    api = Api(g)
    vp = api.viewport(0, 0, 20, 10)
    # Round-trips without error and every returned cell has the expected shape:
    # the base keys always, plus optional style flags when set.
    for cell in vp["cells"]:
        assert {"r", "c", "text", "align"} <= set(cell)
        assert set(cell) <= {"r", "c", "text", "align", "bold", "italic", "underline"}
        assert cell["align"] in ("r", "l")


def test_clear_range_blanks_cells_and_recalcs() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.setcell(1, 0, "2")
    g.setcell(0, 1, "3")
    g.setcell(3, 0, "=A1+B1")  # depends on the cleared cells
    g.recalc()
    api = Api(g)
    api.clear_range(0, 0, 1, 1)  # clear A1:B2
    vp = api.viewport(0, 0, 2, 2)
    assert vp["cells"] == []  # everything in the rectangle is now empty
    # The dependent recalculated against the now-blank inputs.
    assert api.cell_source(0, 3) == "=A1+B1"
    assert g.cell(3, 0).val == 0.0


def test_clear_range_normalizes_reversed_corners() -> None:
    g = _grid()
    g.setcell(2, 2, "x")
    g.recalc()
    Api(g).clear_range(3, 3, 1, 1)  # r0/c0 > r1/c1 -> normalized
    assert g.cell(2, 2) is None or g.cell(2, 2).type == 0  # EMPTY


def test_copy_paste_adjusts_relative_references() -> None:
    g = _grid()
    g.setcell(0, 0, "10")  # A1
    g.setcell(1, 0, "=A1*2")  # B1 -> 20
    g.recalc()
    api = Api(g)
    res = api.copy(0, 0, 0, 1)  # copy A1:B1 (row 0, cols 0-1)
    assert res["tsv"] == "10\t20"  # values, tab-separated
    api.paste(1, 1)  # paste with top-left at B2
    assert api.cell_source(1, 1) == "10"  # B2 = A1's value text
    assert api.cell_source(1, 2) == "=B2*2"  # C2 formula shifted from =A1*2
    assert g.cell(2, 1).val == 20.0  # =B2*2 recalculated


def test_copy_preserves_absolute_references() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.setcell(1, 0, "=$A$1+1")  # absolute ref
    g.recalc()
    api = Api(g)
    api.copy(0, 1, 0, 1)  # copy B1 (row 0, col 1)
    api.paste(3, 3)  # paste to D4
    assert api.cell_source(3, 3) == "=$A$1+1"  # absolute ref unchanged


def test_cut_clears_the_source() -> None:
    g = _grid()
    g.setcell(0, 0, "7")
    g.recalc()
    api = Api(g)
    api.copy(0, 0, 0, 0, cut=True)
    api.paste(2, 2)  # move A1 -> C3
    assert g.cell(0, 0) is None or g.cell(0, 0).type == 0  # source cleared
    assert api.cell_source(2, 2) == "7"


def test_paste_with_empty_buffer_is_a_noop() -> None:
    api = Api(_grid())
    assert api.paste(0, 0) == {"ok": False}


def test_save_writes_json_and_roundtrips(tmp_path) -> None:
    from gridcalc.web import load_workbook

    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "42")
    api.set_cell(0, 1, "=A1+1")  # B1
    dest = tmp_path / "book.json"
    res = api.save(str(dest))
    assert res == {"ok": True, "path": str(dest)}
    assert dest.exists()
    # Reload it and confirm the edits and formula survived.
    reloaded = load_workbook(dest)
    assert reloaded.cell(0, 0).val == 42.0
    assert reloaded.cell(1, 0).val == 43.0


def test_save_uses_the_current_filename_when_no_path(tmp_path) -> None:
    dest = tmp_path / "wb.json"
    g = _grid()
    g.filename = str(dest)
    api = Api(g)
    api.set_cell(0, 0, "1")
    assert api.save()["path"] == str(dest)
    assert dest.exists()


def test_save_without_a_filename_needs_a_path() -> None:
    api = Api(_grid())  # demo grid has no filename
    assert api.save() == {"ok": False, "needs_path": True}


def test_undo_redo_restores_and_reapplies_an_edit() -> None:
    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "5")
    api.set_cell(0, 0, "9")
    assert g.cell(0, 0).val == 9.0
    api.undo()
    assert api.cell_source(0, 0) == "5"  # back to the previous value
    api.undo()
    assert api.cell_source(0, 0) == ""  # back to empty
    api.redo()
    assert api.cell_source(0, 0) == "5"  # re-applied


def test_undo_recomputes_dependents() -> None:
    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "10")  # A1  (set_cell is (r, c))
    api.set_cell(0, 1, "=A1*2")  # B1 = 20
    api.set_cell(0, 0, "100")  # A1 -> 100, B1 recalculates to 200
    assert g.cell(1, 0).val == 200.0  # B1 = cell(c=1, r=0)
    api.undo()  # A1 back to 10
    assert g.cell(0, 0).val == 10.0
    assert g.cell(1, 0).val == 20.0  # dependent recomputed on undo


def test_undo_reverts_a_paste() -> None:
    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "7")
    api.copy(0, 0, 0, 0)
    api.paste(2, 2)  # C3 = 7
    assert g.cell(2, 2).val == 7.0
    api.undo()
    assert g.cell(2, 2) is None or g.cell(2, 2).type == 0  # paste reverted


def test_undo_with_empty_history_is_harmless() -> None:
    api = Api(_grid())
    assert api.undo() == {"ok": True}  # no-op, no raise
    assert api.redo() == {"ok": True}


def test_fill_down_adjusts_references() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.setcell(0, 1, "2")
    g.setcell(0, 2, "3")
    g.setcell(1, 0, "=A1*10")  # B1
    g.recalc()
    api = Api(g)
    api.fill(0, 1, 2, 1, "down")  # fill B1 down over B1:B3
    assert api.cell_source(1, 1) == "=A2*10"  # B2
    assert api.cell_source(2, 1) == "=A3*10"  # B3
    assert g.cell(1, 2).val == 30.0  # =A3*10 = 3*10


def test_fill_right_adjusts_references() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.setcell(0, 1, "=A1")  # A2 -> refers up
    g.recalc()
    api = Api(g)
    g.setcell(0, 3, "=A1")  # A4 as the left-column source
    g.recalc()
    api.fill(3, 0, 3, 2, "right")  # fill A4 right over A4:C4
    assert api.cell_source(3, 1) == "=B1"  # B4
    assert api.cell_source(3, 2) == "=C1"  # C4


def test_fill_repeats_a_plain_value() -> None:
    g = _grid()
    g.setcell(0, 0, "hi")
    g.recalc()
    api = Api(g)
    api.fill(0, 0, 2, 0, "down")
    assert api.cell_source(1, 0) == "hi"
    assert api.cell_source(2, 0) == "hi"


def test_fill_bad_direction_is_a_noop() -> None:
    api = Api(_grid())
    assert api.fill(0, 0, 2, 0, "sideways") == {"ok": False}


def test_chart_data_uses_label_column_and_numeric_series() -> None:
    from gridcalc.web import demo_grid

    api = Api(demo_grid())
    data = api.chart_data("A4:D6")
    assert data["title"] == "A4:D6"
    assert data["labels"] == ["Widget", "Gadget", "Gizmo"]  # column A -> categories
    names = [s["name"] for s in data["series"]]
    assert names == ["B", "C", "D"]  # A consumed as labels
    d_series = next(s for s in data["series"] if s["name"] == "D")
    assert d_series["values"] == [25.0, 36.0, 22.75]  # =B*C per row


def test_chart_data_single_column_uses_row_numbers() -> None:
    from gridcalc.web import demo_grid

    api = Api(demo_grid())
    data = api.chart_data("D4:D6")
    assert data["labels"] == ["4", "5", "6"]  # no label column -> row numbers
    assert len(data["series"]) == 1
    assert data["series"][0] == {"name": "D", "values": [25.0, 36.0, 22.75]}


def test_chart_data_reflects_edits() -> None:
    g = _grid()
    g.setcell(0, 0, "3")
    g.setcell(0, 1, "5")
    g.recalc()
    api = Api(g)
    assert api.chart_data("A1:A2")["series"][0]["values"] == [3.0, 5.0]
    api.set_cell(0, 0, "100")  # edit -> recalc -> chart reflects it
    assert api.chart_data("A1:A2")["series"][0]["values"] == [100.0, 5.0]


def test_chart_data_non_numeric_is_a_gap() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.setcell(0, 1, "text")
    g.setcell(0, 2, "3")
    g.recalc()
    api = Api(g)
    assert api.chart_data("A1:A3")["series"][0]["values"] == [1.0, None, 3.0]


def test_chart_data_rejects_a_bad_range() -> None:
    api = Api(_grid())
    assert "error" in api.chart_data("not-a-range")
    assert "error" in api.chart_data("A1:B")  # trailing garbage
    assert "error" in api.chart_data("")


def test_open_file_replaces_the_workbook(tmp_path) -> None:
    from gridcalc.web import demo_grid

    other = _grid()
    other.setcell(0, 0, "99")
    other.recalc()
    dest = tmp_path / "other.json"
    assert other.jsonsave(str(dest)) >= 0

    api = Api(demo_grid())
    assert api.cell_source(0, 0) == "gridcalc demo"  # the demo before opening
    res = api.open_file(str(dest))
    assert res == {"ok": True, "filename": str(dest)}
    assert api.cell_source(0, 0) == "99"  # now the loaded workbook
    assert api.dims()["filename"] == str(dest)


def test_open_file_loads_csv(tmp_path) -> None:
    src = tmp_path / "data.csv"
    src.write_text("a,b\n1,2\n")
    api = Api(_grid())
    assert api.open_file(str(src))["ok"] is True
    assert api.cell_source(0, 0) == "a"
    assert api.cell_source(1, 1) == "2"  # (r=1, c=1) -> B2


def test_open_file_missing_returns_error_and_keeps_current() -> None:
    g = _grid()
    g.setcell(0, 0, "keep")
    g.recalc()
    api = Api(g)
    res = api.open_file("/no/such/workbook.json")
    assert res["ok"] is False and "error" in res
    assert api.cell_source(0, 0) == "keep"  # current workbook untouched


def test_open_file_resets_undo_and_clipboard(tmp_path) -> None:
    other = _grid()
    other.setcell(1, 1, "5")  # B2
    other.recalc()
    dest = tmp_path / "wb.json"
    assert other.jsonsave(str(dest)) >= 0

    api = Api(_grid())
    api.set_cell(0, 0, "old")  # an undoable edit on the first workbook
    api.copy(0, 0, 0, 0)  # something in the copy buffer
    api.open_file(str(dest))
    # Undo history from the previous workbook must not apply to the new one.
    api.undo()
    assert api.cell_source(1, 1) == "5"  # loaded cell intact
    # The copy buffer is cleared, so a paste is a no-op.
    assert api.paste(3, 3) == {"ok": False}


def test_paste_text_writes_a_tsv_block() -> None:
    g = _grid()
    api = Api(g)
    api.paste_text(0, 0, "1\t2\n3\t4")
    assert g.cell(0, 0).val == 1.0  # A1
    assert g.cell(1, 0).val == 2.0  # B1
    assert g.cell(0, 1).val == 3.0  # A2
    assert g.cell(1, 1).val == 4.0  # B2


def test_paste_text_starts_at_the_active_cell_and_ignores_trailing_newline() -> None:
    g = _grid()
    api = Api(g)
    api.paste_text(2, 2, "x\ty\n")  # top-left at (r=2, c=2) = C3
    assert api.cell_source(2, 2) == "x"  # C3
    assert api.cell_source(2, 3) == "y"  # D3 (r=2, c=3)
    assert api.cell_source(3, 2) == ""  # no phantom row from the trailing newline


def test_paste_text_treats_a_leading_equals_as_a_formula() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.recalc()
    api = Api(g)
    api.paste_text(0, 1, "=A1*2")  # B1
    assert g.cell(1, 0).val == 20.0


def test_paste_text_empty_is_a_noop() -> None:
    assert Api(_grid()).paste_text(0, 0, "") == {"ok": False}


def test_paste_text_is_undoable() -> None:
    g = _grid()
    api = Api(g)
    api.paste_text(0, 0, "1\t2")
    api.undo()
    assert g.cell(0, 0) is None or g.cell(0, 0).type == 0
    assert g.cell(1, 0) is None or g.cell(1, 0).type == 0


def _wyndor() -> Grid:
    """Wyndor Glass LP laid out spatially (as in tests/test_opt.py):
    maximize 3*x1 + 5*x2 s.t. x1<=4, 2*x2<=12, 3*x1+2*x2<=18. Optimum 36 at
    x1=2 (A2), x2=6 (A3)."""
    g = _grid()
    g.setcell(0, 0, '"Product')  # label, so infer_model has a header to skip
    g.setcell(0, 1, "0")  # A2 = x1
    g.setcell(0, 2, "0")  # A3 = x2
    g.setcell(1, 1, "=3*A2+5*A3")  # B2 objective
    g.setcell(2, 1, "=A2<=4")  # C2
    g.setcell(2, 2, "=2*A3<=12")  # C3
    g.setcell(2, 3, "=3*A2+2*A3<=18")  # C4
    g.recalc()
    return g


def test_key_and_a1_roundtrip() -> None:
    assert Api._key("B4") == (1, 3)  # (col, row), zero-based
    assert Api._key("$B$4") == (1, 3)  # absolute markers ignored
    assert Api._a1((1, 3)) == "B4"
    for bad in ("", "notacell", "A1:B2", "4"):
        with pytest.raises(ValueError):
            Api._key(bad)


def test_num_maps_non_finite_to_none() -> None:
    assert Api._num(3.5) == 3.5
    assert Api._num(0) == 0
    assert Api._num(float("inf")) is None
    assert Api._num(float("-inf")) is None
    assert Api._num(float("nan")) is None


def test_solve_model_maximizes_and_writes_back() -> None:
    g = _wyndor()
    api = Api(g)
    res = api.solve_model(
        {"sense": "max", "objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"}
    )
    assert res["ok"] is True
    assert res["status"] == "OPTIMAL" and res["optimal"] is True
    assert res["objective"] == pytest.approx(36.0)
    assert res["values"]["A2"] == pytest.approx(2.0)
    assert res["values"]["A3"] == pytest.approx(6.0)
    assert res["applied"] is True
    # Decision cells were actually written and recalculated.
    assert g.cell(0, 1).val == pytest.approx(2.0)  # A2
    assert g.cell(1, 1).val == pytest.approx(36.0)  # B2 objective cell


def test_solve_model_returns_lp_sensitivity() -> None:
    g = _wyndor()
    res = Api(g).solve_model(
        {"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4", "sensitivity": True}
    )
    assert "sensitivity" in res
    con = {c["cell"] for c in res["sensitivity"]["constraints"]}
    assert con == {"C2", "C3", "C4"}
    var = {v["cell"] for v in res["sensitivity"]["variables"]}
    assert var == {"A2", "A3"}
    # Ranging endpoints are finite-or-None (no raw inf leaks across the bridge).
    for c in res["sensitivity"]["constraints"]:
        assert c["rhs_from"] is None or isinstance(c["rhs_from"], (int, float))


def test_solve_model_is_undoable() -> None:
    g = _wyndor()
    api = Api(g)
    api.solve_model({"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"})
    assert g.cell(0, 1).val == pytest.approx(2.0)
    api.undo()
    assert g.cell(0, 1).val == pytest.approx(0.0)  # back to the typed 0


def test_solve_model_bad_spec_returns_error() -> None:
    res = Api(_grid()).solve_model({"objective": "B2", "vars": "nope", "constraints": "C1"})
    assert res["ok"] is False and "error" in res


def test_solve_infeasible_reports_and_leaves_undo_clean() -> None:
    g = _grid()
    g.setcell(0, 0, "0")  # A1 decision var (default lower bound 0)
    g.setcell(1, 0, "=A1")  # B1 objective
    g.setcell(2, 0, "=A1<=-1")  # C1 constraint -- contradicts x>=0
    g.recalc()
    api = Api(g)
    res = api.solve_model(
        {"sense": "max", "objective": "B1", "vars": "A1", "constraints": "C1", "diagnose": True}
    )
    assert res["ok"] is True
    assert res["status"] == "INFEASIBLE" and res["optimal"] is False
    assert "conflict" in res and res["conflict"]  # diagnostics identify the clash
    # Nothing was written, and the guard snapshot was discarded (no no-op undo).
    assert api._undo.undo_stack == []


def test_solve_selection_infers_and_solves() -> None:
    g = _wyndor()
    # Selection rows 0..3, cols 0..2 (r, c order); infer_model reads the block.
    res = Api(g).solve_selection(0, 0, 3, 2, "max")
    assert res["ok"] is True
    assert res["status"] == "OPTIMAL"
    assert res["objective"] == pytest.approx(36.0)


def test_goal_seek_solves_and_applies() -> None:
    g = _grid()
    g.setcell(0, 0, "0")  # A1 variable
    g.setcell(1, 0, "=A1*2")  # B1 = 2*A1
    g.recalc()
    api = Api(g)
    res = api.goal_seek("B1", 10, "A1")
    assert res["ok"] is True and res["converged"] is True and res["applied"] is True
    assert res["var_value"] == pytest.approx(5.0, abs=1e-6)
    assert g.cell(0, 0).val == pytest.approx(5.0, abs=1e-6)


def test_goal_seek_is_undoable() -> None:
    g = _grid()
    g.setcell(0, 0, "0")
    g.setcell(1, 0, "=A1*2")
    g.recalc()
    api = Api(g)
    api.goal_seek("B1", 10, "A1")
    api.undo()
    assert g.cell(0, 0).val == pytest.approx(0.0)  # variable restored


def test_goal_seek_bad_ref_returns_error() -> None:
    res = Api(_grid()).goal_seek("B1", 10, "not")
    assert res["ok"] is False and "error" in res


def test_opt_sweep_returns_points_without_mutating() -> None:
    g = _wyndor()
    api = Api(g)
    res = api.opt_sweep(
        {
            "objective": "B2",
            "vars": "A2:A3",
            "constraints": "C2:C4",
            "constraint": "C2",
            "lo": 0,
            "hi": 8,
            "steps": 4,
        }
    )
    assert res["ok"] is True
    assert len(res["points"]) == 5  # steps + 1, inclusive
    assert set(res["points"][0]) == {
        "rhs",
        "status",
        "objective",
        "shadow_price",
        "delta",
        "breakpoint",
    }
    # A sweep is what-if only: the sheet is never written.
    assert g.cell(0, 1).val == pytest.approx(0.0)  # A2 still its typed 0
    assert api._undo.undo_stack == []


def test_set_format_bold_toggles_and_viewport_reports_it() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, "b")  # (r0, c0, r1, c1) -> A1
    assert g.cell(0, 0).bold == 1
    assert api.viewport(0, 0, 1, 1)["cells"][0]["bold"] is True
    api.set_format(0, 0, 0, 0, "b")  # toggle off
    assert g.cell(0, 0).bold == 0
    assert "bold" not in api.viewport(0, 0, 1, 1)["cells"][0]


def test_set_format_number_format_bakes_into_the_text() -> None:
    g = _grid()
    g.setcell(0, 0, "99.5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, "$")
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "99.50"
    api.set_format(0, 0, 0, 0, "%")
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "9950.00%"


def test_set_format_python_spec_sets_fmtstr() -> None:
    g = _grid()
    g.setcell(0, 0, "1234.5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, ",.2f")
    assert g.cell(0, 0).fmtstr == ",.2f"
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "1,234.50"


def test_set_global_format_changes_default_display() -> None:
    g = _grid()
    g.setcell(0, 0, "0.25")  # a number with no explicit format
    g.recalc()
    api = Api(g)
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "0.25"
    api.set_global_format("%")
    assert g.fmt == "%"
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "25.00%"
    api.set_global_format("bad")  # not a valid single char -> cleared
    assert g.fmt == ""


def test_set_format_is_undoable() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, "bi")  # bold + italic
    assert g.cell(0, 0).bold == 1 and g.cell(0, 0).italic == 1
    api.undo()
    assert g.cell(0, 0).bold == 0 and g.cell(0, 0).italic == 0


def test_load_html_returns_the_built_bundle_or_raises() -> None:
    """`run()` serves the built React bundle. When the frontend has been built
    (`make web-build`) the bundle is a self-contained document that mounts the
    app and talks to the bridge; without it, `_load_html` raises a directive
    error rather than opening a blank window."""
    from gridcalc import web

    bundle = Path(web.__file__).resolve().parent / "static" / "index.html"
    if bundle.exists():
        html = web._load_html()
        assert 'id="root"' in html  # the React mount point
        assert "pywebviewready" in html  # the inlined app awaits the bridge
    else:
        with pytest.raises(OSError, match="web UI bundle not found"):
            web._load_html()


def test_importing_web_does_not_load_pywebview() -> None:
    """`import gridcalc.web` must stay cheap: the native webview stack is pulled
    in only when a window is opened, so the module and its `Api` import without
    the optional `web` extra installed."""
    program = (
        "import sys\n"
        "import gridcalc.web\n"
        "print('LOADED' if 'webview' in sys.modules else 'CLEAN')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CLEAN"
