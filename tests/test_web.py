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

from gridcalc.engine import EMPTY, NCOL, NROW, Grid, Mode
from gridcalc.loader import load_workbook
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


@pytest.mark.parametrize(
    ("r0", "c0", "rows", "cols"),
    [
        (999999, 0, 10, 10),  # origin far past the last row
        (0, 99999, 10, 10),  # ...and past the last column
        (999999, 99999, 10, 10),  # entirely outside the sheet
        (NROW, NCOL, 10, 10),  # exactly one past the end
        (-5, -5, 10, 10),  # negative origin
        (0, 0, -5, -5),  # negative extent
        (0, 0, 0, 0),  # degenerate but legal
    ],
)
def test_viewport_never_reports_a_negative_size(r0, c0, rows, cols) -> None:
    """`rows`/`cols` describe a rectangle, so they cannot be negative.

    The origin was clamped only at zero and the ends derived from the unclamped
    value, so an out-of-range origin returned e.g. `rows: -998975`. A
    virtualising client sizes its spacers from these numbers, and this is a
    bridge boundary that should not hand back impossible geometry.
    """
    vp = Api(_grid()).viewport(r0, c0, rows, cols)
    assert vp["rows"] >= 0
    assert vp["cols"] >= 0
    assert 0 <= vp["r0"] <= NROW
    assert 0 <= vp["c0"] <= NCOL
    assert vp["r0"] + vp["rows"] <= NROW
    assert vp["c0"] + vp["cols"] <= NCOL
    assert vp["cells"] == [] or all(
        vp["r0"] <= cell["r"] < vp["r0"] + vp["rows"] for cell in vp["cells"]
    )


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
    """No raise, and -- since nothing changed -- no dirty flag either."""
    api = Api(_grid())
    assert api.undo() == {"ok": True, "dirty": False}
    assert api.redo() == {"ok": True, "dirty": False}


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


def test_solve_selection_applies_by_default() -> None:
    """The default writes the optimum into the decision cells, as `:opt max` does."""
    g = _wyndor()
    res = Api(g).solve_selection(0, 0, 3, 2, "max")
    assert res["applied"] is True
    assert g.cell(0, 1).val == pytest.approx(2.0)  # A2 = x1
    assert g.cell(0, 2).val == pytest.approx(6.0)  # A3 = x2


def test_solve_selection_without_apply_does_not_touch_the_sheet() -> None:
    """Unchecking "write the solution to the sheet" must mean no write.

    The dialog puts that checkbox in the same row as the "Solve selection"
    button, so a solve that wrote anyway would silently overwrite the decision
    cells the user was protecting. The result still reports the optimum -- only
    the sheet is left alone -- and nothing lands on the undo stack, because
    there is no mutation to undo.
    """
    g = _wyndor()
    api = Api(g)

    def snapshot() -> dict[tuple[int, int], str | None]:
        # cell() is None for an empty cell, so read through getattr.
        return {(c, r): getattr(g.cell(c, r), "text", None) for c in range(4) for r in range(4)}

    before = snapshot()

    res = api.solve_selection(0, 0, 3, 2, "max", apply=False)

    assert res["ok"] is True
    assert res["status"] == "OPTIMAL"
    assert res["objective"] == pytest.approx(36.0)  # still solved
    assert res["applied"] is False
    assert snapshot() == before
    assert g.cell(0, 1).val == pytest.approx(0.0)  # A2 still the starting 0
    assert g.cell(0, 2).val == pytest.approx(0.0)  # A3 too
    assert api._undo.undo_stack == []


def test_solve_selection_without_apply_still_stores_the_inferred_model() -> None:
    """`apply` governs writing the *solution*, not remembering the selection.

    Storing the inferred block as `default` is what lets the user re-run or edit
    it later, and it is not a change to any cell.
    """
    g = _wyndor()
    assert Api(g).solve_selection(0, 0, 3, 2, "max", apply=False)["ok"] is True
    assert "default" in g.models


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


def test_saved_models_round_trip_through_the_workbook(tmp_path) -> None:
    """Models are workbook state, not session state: a model defined in the web
    view is the same object `:opt run` reads in the TUI, and survives save."""
    g = _wyndor()
    api = Api(g)
    spec = {"sense": "max", "objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"}
    assert api.save_model("wyndor", spec)["ok"] is True

    listed = api.list_models()["models"]
    assert [m["name"] for m in listed] == ["wyndor"]
    assert listed[0]["objective"] == "B2" and listed[0]["sense"] == "max"

    path = tmp_path / "book.json"
    api.save(str(path))
    reopened = Api(load_workbook(str(path)))
    assert [m["name"] for m in reopened.list_models()["models"]] == ["wyndor"]


def test_run_model_solves_a_saved_model() -> None:
    g = _wyndor()
    api = Api(g)
    api.save_model("wyndor", {"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"})
    res = api.run_model("wyndor")
    assert res["ok"] is True and res["status"] == "OPTIMAL"
    assert res["objective"] == pytest.approx(36.0)
    assert res["values"]["A2"] == pytest.approx(2.0)
    assert res["values"]["A3"] == pytest.approx(6.0)


def test_run_model_honours_the_apply_switch() -> None:
    g = _wyndor()
    api = Api(g)
    api.save_model("wyndor", {"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"})
    res = api.run_model("wyndor", {"apply": False})
    assert res["ok"] is True and res["applied"] is False
    assert g.cell(0, 1).val == pytest.approx(0.0)  # A2 untouched


def test_run_missing_model_reports_rather_than_raises() -> None:
    api = Api(_wyndor())
    assert api.run_model("nope") == {"ok": False, "error": "no such model: nope"}


def test_save_model_rejects_an_incomplete_spec() -> None:
    api = Api(_wyndor())
    res = api.save_model("bad", {"objective": "B2", "vars": "", "constraints": "C2:C4"})
    assert res["ok"] is False and "vars" in res["error"]
    assert api.list_models()["models"] == []


def test_save_model_needs_a_name() -> None:
    api = Api(_wyndor())
    res = api.save_model("  ", {"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"})
    assert res["ok"] is False


def test_delete_model_removes_it() -> None:
    api = Api(_wyndor())
    api.save_model("wyndor", {"objective": "B2", "vars": "A2:A3", "constraints": "C2:C4"})
    assert api.delete_model("wyndor")["ok"] is True
    assert api.list_models()["models"] == []
    assert api.delete_model("wyndor")["ok"] is False  # already gone


def test_a_model_with_an_unresolvable_ref_lists_but_fails_on_run() -> None:
    """Spec strings resolve at run time, not at save time. A model that names
    something unparseable still lists -- the error arrives when it is used,
    with a message -- rather than being rejected or corrupting the listing."""
    api = Api(_wyndor())
    api.save_model("broken", {"objective": "B2", "vars": "not-a-ref", "constraints": "C2:C4"})
    assert [m["name"] for m in api.list_models()["models"]] == ["broken"]
    res = api.run_model("broken")
    assert res["ok"] is False and "bad model spec" in res["error"]


def test_solve_selection_stores_the_inferred_model_as_default() -> None:
    g = _wyndor()
    api = Api(g)
    assert api.solve_selection(0, 0, 3, 2, "max")["ok"] is True
    models = {m["name"]: m for m in api.list_models()["models"]}
    assert "default" in models
    assert models["default"]["sense"] == "max"
    assert models["default"]["objective"] == "B2"
    # Re-runnable without a selection, which is the point of storing it.
    assert api.run_model("default")["status"] == "OPTIMAL"


def test_infer_model_spec_describes_a_selection_without_solving() -> None:
    g = _wyndor()
    api = Api(g)
    res = api.infer_model_spec(0, 0, 3, 2, "min")
    assert res["ok"] is True
    assert res["sense"] == "min"
    assert res["objective"] == "B2"
    assert res["vars"] == "A2:A3"
    # Nothing ran: no write, no undo entry, no stored model.
    assert g.cell(0, 1).val == pytest.approx(0.0)
    assert api._undo.undo_stack == []
    assert api.list_models()["models"] == []


def test_infer_model_spec_reports_an_unusable_selection() -> None:
    api = Api(_grid())  # empty sheet: nothing to infer
    res = api.infer_model_spec(0, 0, 3, 3)
    assert res["ok"] is False and res["error"]


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


def test_set_global_format_is_undoable() -> None:
    """The global format touches no cell, so it needs a grid-level snapshot --
    without one, undo would silently skip a user-visible change."""
    g = _grid()
    g.setcell(0, 0, "0.25")
    g.recalc()
    api = Api(g)
    api.set_global_format("%")
    assert g.fmt == "%"
    api.undo()
    assert g.fmt == ""
    assert api.viewport(0, 0, 1, 1)["cells"][0]["text"] == "0.25"
    api.redo()
    assert g.fmt == "%"


def test_stats_aggregates_the_numeric_cells_in_a_rectangle() -> None:
    g = _grid()
    g.setcell(0, 0, "label")  # counted, but not numeric
    g.setcell(0, 1, "10")
    g.setcell(0, 2, "4")
    g.setcell(1, 1, "=1+5")  # a formula's value counts
    g.recalc()
    api = Api(g)
    s = api.stats(0, 0, 2, 1)
    assert s["count"] == 4
    assert s["numeric"] == 3
    assert s["sum"] == 20
    assert s["avg"] == pytest.approx(20 / 3)
    assert s["min"] == 4
    assert s["max"] == 10


def test_stats_over_an_empty_selection_has_no_aggregates() -> None:
    api = Api(_grid())
    s = api.stats(5, 5, 8, 8)
    assert s["count"] == 0 and s["numeric"] == 0
    assert s["sum"] is None and s["avg"] is None
    assert s["min"] is None and s["max"] is None


def test_stats_normalizes_reversed_corners_and_clamps() -> None:
    g = _grid()
    g.setcell(0, 0, "3")
    g.recalc()
    api = Api(g)
    assert api.stats(2, 2, -5, -5)["sum"] == 3  # reversed and out of bounds


def test_dirty_tracks_unsaved_changes(tmp_path) -> None:
    """A freshly loaded workbook is clean; any mutation dirties it; saving
    clears it again. The engine's own `dirty` flag is left in step."""
    g = _grid()
    g.setcell(0, 0, "1")
    g.recalc()
    api = Api(g)
    assert api.dims()["dirty"] is False  # construction normalizes
    assert g.dirty == 0

    assert api.set_cell(0, 1, "2")["dirty"] is True
    assert api.dims()["dirty"] is True
    assert g.dirty == 1

    path = tmp_path / "book.json"
    api.save(str(path))
    assert api.dims()["dirty"] is False
    assert g.dirty == 0

    api.set_format(0, 0, 0, 0, "b")  # formatting counts as a change
    assert api.dims()["dirty"] is True


def test_undo_marks_the_workbook_dirty() -> None:
    """Undo moves the workbook away from what is on disk just as an edit
    does, so it must not leave the title claiming the file is saved."""
    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "1")
    api._mark_clean()  # stand in for a save
    assert api.dims()["dirty"] is False
    api.undo()
    assert api.dims()["dirty"] is True


def test_open_file_clears_the_dirty_flag(tmp_path) -> None:
    src = tmp_path / "src.json"
    g0 = _grid()
    g0.setcell(0, 0, "7")
    g0.recalc()
    g0.jsonsave(str(src))

    api = Api(_grid())
    api.set_cell(0, 0, "1")
    assert api.dims()["dirty"] is True
    assert api.open_file(str(src))["ok"] is True
    assert api.dims()["dirty"] is False


def test_set_format_is_undoable() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, "bi")  # bold + italic
    assert g.cell(0, 0).bold == 1 and g.cell(0, 0).italic == 1
    api.undo()
    assert g.cell(0, 0).bold == 0 and g.cell(0, 0).italic == 0


# -- shared commands ----------------------------------------------------
#
# The behaviour of each command is tested in `test_commands.py`, against the
# registry. What matters here is only what this bridge adds: the coordinate
# conversion, the dirty propagation, and the shape the client receives.


def test_list_commands_exposes_the_whole_registry() -> None:
    """The client builds its palette from this, so a command registered in
    `gridcalc.commands` must arrive here without another edit."""
    from gridcalc import commands as shared

    exposed = Api(_grid()).list_commands()["commands"]
    assert {c["name"] for c in exposed} == {c.name for c in shared.COMMANDS}


def test_run_command_converts_the_selection_to_column_first() -> None:
    """The bridge speaks row-first and the registry column-first. Getting this
    backwards would silently act on the transposed rectangle, so it is pinned:
    B3:D5 row-first must reach the command as B3:D5, not C2:E4.
    """
    g = _grid()
    api = Api(g)
    r = api.run_command("name", ["Block"], {"r0": 2, "c0": 1, "r1": 4, "c1": 3})
    assert r["ok"] is True
    assert "B3:D5" in r["message"]


def test_run_command_reports_a_mutation_as_dirty() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.recalc()
    api = Api(g)
    assert api.dims()["dirty"] is False
    r = api.run_command("blank", [], {"r0": 0, "c0": 0, "r1": 0, "c1": 0})
    assert r["changed"] is True and r["dirty"] is True
    assert api.dims()["dirty"] is True


def test_a_query_command_does_not_dirty_the_workbook() -> None:
    """Listing named ranges must not make a saved file look modified."""
    api = Api(_grid())
    r = api.run_command("names")
    assert r["ok"] is True and r["changed"] is False
    assert api.dims()["dirty"] is False


def test_run_command_returns_list_output_for_a_listing() -> None:
    api = Api(_grid())
    api.run_command("name", ["Alpha", "A1:A3"])
    r = api.run_command("names")
    assert r["lines"] == ["Alpha = A1:A3"]


def test_run_command_reports_a_refusal_without_mutating() -> None:
    api = Api(_grid())
    r = api.run_command("name", ["9bad", "A1"])
    assert r["ok"] is False and "not a usable name" in r["message"]
    assert api.dims()["dirty"] is False


def test_run_command_with_no_selection_uses_the_cursor() -> None:
    g = _grid()
    g.setcell(0, 0, "x")
    g.recalc()
    g.cc, g.cr = 0, 0
    assert Api(g).run_command("blank")["ok"] is True
    assert g.cell(0, 0) is None or g.cell(0, 0).type == EMPTY


def test_run_command_tolerates_a_malformed_selection() -> None:
    """A partial selection object from the client must not raise across the
    bridge -- it falls back to the cursor."""
    g = _grid()
    g.setcell(0, 0, "x")
    g.recalc()
    assert Api(g).run_command("blank", [], {"r0": 0})["ok"] is True


def test_run_command_rejects_an_unknown_name() -> None:
    r = Api(_grid()).run_command("nonesuch")
    assert r["ok"] is False and "unknown command" in r["message"]


def test_structural_edits_reach_the_registry_through_the_bridge() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "=A1*2")
    g.recalc()
    api = Api(g)
    assert api.run_command("insrow", [], {"r0": 0, "c0": 0, "r1": 0, "c1": 0})["ok"] is True
    assert g.cell(0, 1).val == 10.0
    assert g.cell(0, 2).text == "=A2*2"


def test_set_format_and_clear_range_run_the_shared_commands() -> None:
    """Both are keyboard entry points carrying an explicit rectangle rather
    than the selection, but they must not be a second implementation."""
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    api = Api(g)
    api.set_format(0, 0, 0, 0, "$")
    assert g.cell(0, 0).fmt == "$"
    api.clear_range(0, 0, 0, 0)
    assert g.cell(0, 0) is None or g.cell(0, 0).type == EMPTY


def test_set_format_reports_a_refusal() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    assert Api(g).set_format(0, 0, 0, 0, "")["ok"] is False


def test_set_format_clamps_an_out_of_bounds_rectangle() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    assert Api(g).set_format(-5, -5, NROW + 9, NCOL + 9, "b")["ok"] is True
    assert g.cell(0, 0).bold == 1


# -- search -------------------------------------------------------------


def test_search_matches_text_and_computed_values() -> None:
    """A formula is findable by its source *and* its result -- the client only
    ever holds formatted text for the cells currently in view, so it cannot do
    this itself."""
    g = _grid()
    g.setcell(0, 0, "hello world")
    g.setcell(1, 0, "=21*2")
    g.setcell(0, 1, "other")
    g.recalc()
    api = Api(g)

    assert [m["ref"] for m in api.search("hello")["matches"]] == ["A1"]
    assert [m["ref"] for m in api.search("21*2")["matches"]] == ["B1"]  # source
    assert [m["ref"] for m in api.search("42")["matches"]] == ["B1"]  # value


def test_search_is_case_insensitive_and_in_reading_order() -> None:
    g = _grid()
    g.setcell(2, 1, "Beta")  # C2
    g.setcell(0, 0, "alpha")  # A1
    g.setcell(1, 1, "ALPHABET")  # B2
    g.recalc()
    api = Api(g)
    assert [m["ref"] for m in api.search("alpha")["matches"]] == ["A1", "B2"]


def test_search_reports_coordinates_alongside_the_ref() -> None:
    g = _grid()
    g.setcell(2, 3, "target")
    g.recalc()
    assert Api(g).search("target")["matches"] == [{"r": 3, "c": 2, "ref": "C4"}]


def test_empty_pattern_matches_nothing() -> None:
    """An empty find box should report nothing, not every populated cell."""
    g = _grid()
    g.setcell(0, 0, "x")
    g.recalc()
    assert Api(g).search("")["total"] == 0


def test_search_does_not_move_or_dirty_anything() -> None:
    g = _grid()
    g.setcell(0, 0, "x")
    g.recalc()
    api = Api(g)
    before = (g.cc, g.cr)
    api.search("x")
    assert (g.cc, g.cr) == before
    assert api.dims()["dirty"] is False


def test_search_caps_the_returned_list_but_not_the_count() -> None:
    """A capped list must not read as the whole story -- `total` stays true."""
    from gridcalc.web import MAX_SEARCH_MATCHES

    g = _grid()
    n = MAX_SEARCH_MATCHES + 25  # more than one column holds (NROW is 1024)
    for i in range(n):
        g.setcell(i // NROW, i % NROW, "hit")
    g.recalc()
    res = Api(g).search("hit")
    assert len(res["matches"]) == MAX_SEARCH_MATCHES
    assert res["total"] == n
    assert res["truncated"] is True


# -- column widths ------------------------------------------------------


def test_col_widths_start_empty_and_record_a_resize() -> None:
    api = Api(_grid())
    assert api.col_widths() == {"widths": {}}
    assert api.set_col_width(1, 140)["ok"] is True
    assert api.col_widths()["widths"] == {"1": 140}


def test_set_col_width_rejects_a_bad_column_or_size() -> None:
    api = Api(_grid())
    assert api.set_col_width(NCOL, 100)["ok"] is False
    assert api.set_col_width(0, 2)["ok"] is False  # narrower than the minimum
    assert api.set_col_width(0, 99999)["ok"] is False
    assert api.col_widths()["widths"] == {}


def test_col_widths_are_per_sheet() -> None:
    g = _grid()
    api = Api(g)
    api.set_col_width(0, 140)
    api.add_sheet("Data")  # switches to it
    assert api.col_widths()["widths"] == {}
    api.set_col_width(0, 60)
    api.set_active(0)
    assert api.col_widths()["widths"] == {"0": 140}


def test_col_widths_survive_a_save_and_reload(tmp_path) -> None:
    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "1")
    api.set_col_width(0, 140)
    api.set_col_width(3, 60)
    path = tmp_path / "book.json"
    api.save(str(path))

    reopened = Api(load_workbook(str(path)))
    assert reopened.col_widths()["widths"] == {"0": 140, "3": 60}


def test_a_workbook_with_no_widths_does_not_grow_a_widths_key(tmp_path) -> None:
    """The field is additive: a workbook never touched by a graphical frontend
    must serialize exactly as it did before."""
    import json

    g = _grid()
    api = Api(g)
    api.set_cell(0, 0, "1")
    path = tmp_path / "book.json"
    api.save(str(path))
    data = json.loads(path.read_text())
    assert all("widths" not in sheet for sheet in data["sheets"])


def test_a_malformed_width_is_dropped_rather_than_trusted(tmp_path) -> None:
    import json

    g = _grid()
    g.setcell(0, 0, "1")
    g.recalc()
    path = tmp_path / "book.json"
    g.jsonsave(str(path))
    data = json.loads(path.read_text())
    data["sheets"][0]["widths"] = {"0": 140, "1": "wide", "2": 999999, "zz": 100, "-1": 50}
    path.write_text(json.dumps(data))

    reopened = Api(load_workbook(str(path)))
    assert reopened.col_widths()["widths"] == {"0": 140}


def test_setting_a_width_marks_the_workbook_dirty() -> None:
    api = Api(_grid())
    assert api.dims()["dirty"] is False
    api.set_col_width(0, 140)
    assert api.dims()["dirty"] is True


# -- sheet management ---------------------------------------------------


def test_add_sheet_appends_and_switches_to_it() -> None:
    api = Api(_grid())
    r = api.add_sheet("Data")
    assert r["ok"] is True
    assert r["names"] == ["Sheet1", "Data"]
    assert r["active"] == 1
    assert r["dirty"] is True


def test_add_sheet_rejects_a_duplicate_name_and_reports_the_tab_list() -> None:
    api = Api(_grid())
    api.add_sheet("Data")
    r = api.add_sheet("Data")
    assert r["ok"] is False and "already exists" in r["error"]
    assert r["names"] == ["Sheet1", "Data"]  # the client can still redraw


def test_add_sheet_needs_a_name() -> None:
    api = Api(_grid())
    assert api.add_sheet("   ")["ok"] is False


def test_delete_sheet_removes_it_and_keeps_the_active_index_valid() -> None:
    api = Api(_grid())
    api.add_sheet("Data")  # active -> 1
    r = api.delete_sheet("Data")
    assert r["ok"] is True
    assert r["names"] == ["Sheet1"]
    assert r["active"] == 0


def test_delete_sheet_refuses_the_last_sheet() -> None:
    api = Api(_grid())
    r = api.delete_sheet("Sheet1")
    assert r["ok"] is False and "last sheet" in r["error"]


def test_delete_unknown_sheet_names_the_sheet_rather_than_raising_a_key() -> None:
    api = Api(_grid())
    api.add_sheet("Data")  # so the last-sheet guard is not what fires
    r = api.delete_sheet("Nope")
    assert r["ok"] is False and r["error"] == "no such sheet: Nope"


def test_rename_sheet_rewrites_cross_sheet_references() -> None:
    g = _grid()
    api = Api(g)
    api.add_sheet("Data")
    g.set_active("Data")
    g.setcell(0, 0, "7")
    g.set_active("Sheet1")
    g.setcell(0, 0, "=Data!A1*2")
    g.recalc()
    assert g.cell(0, 0).val == 14.0

    r = api.rename_sheet("Data", "Inputs")
    assert r["ok"] is True
    assert r["names"] == ["Sheet1", "Inputs"]
    assert g.cell(0, 0).text == "=Inputs!A1*2"
    assert g.cell(0, 0).val == 14.0  # the graph was rebuilt, not left stale


def test_rename_sheet_rejects_an_empty_or_taken_name() -> None:
    api = Api(_grid())
    api.add_sheet("Data")
    assert api.rename_sheet("Data", "  ")["ok"] is False
    assert api.rename_sheet("Data", "Sheet1")["ok"] is False
    assert api.rename_sheet("Nope", "X")["error"] == "no such sheet: Nope"


def test_move_sheet_reorders_and_keeps_the_same_sheet_active() -> None:
    api = Api(_grid())
    api.add_sheet("Data")  # active -> Data at index 1
    r = api.move_sheet("Data", 0)
    assert r["ok"] is True
    assert r["names"] == ["Data", "Sheet1"]
    assert r["active"] == 0  # Data followed the move


def test_move_sheet_rejects_an_out_of_range_index() -> None:
    api = Api(_grid())
    api.add_sheet("Data")
    r = api.move_sheet("Data", 9)
    assert r["ok"] is False and "out of range" in r["error"]
    assert r["names"] == ["Sheet1", "Data"]


# -- close guard --------------------------------------------------------


class _FakeWindow:
    """Enough of a pywebview window for the close-guard tests.

    `confirm_close` and `localization` are plain attributes on the real
    `Window` too, read by its close handler at close time -- which is what
    makes toggling them a valid way to arm the prompt.
    """

    def __init__(self) -> None:
        self.confirm_close = False
        self.localization: dict[str, str] = {
            "global.quitConfirmation": "Do you really want to quit?"
        }
        self.title = ""

    def set_title(self, t: str) -> None:
        self.title = t


def test_a_clean_workbook_closes_without_being_asked() -> None:
    api = Api(_grid())
    api._window = _FakeWindow()
    api._sync_close_guard()
    assert api._window.confirm_close is False


def test_editing_arms_the_close_confirmation() -> None:
    api = Api(_grid())
    win = _FakeWindow()
    api._window = win
    api.set_cell(0, 0, "1")
    assert win.confirm_close is True


def test_the_close_prompt_names_the_workbook() -> None:
    g = _grid()
    g.filename = "/tmp/budget.json"
    api = Api(g)
    win = _FakeWindow()
    api._window = win
    api.set_cell(0, 0, "1")
    assert "budget.json" in win.localization["global.quitConfirmation"]
    assert "unsaved changes" in win.localization["global.quitConfirmation"]


def test_saving_disarms_the_close_confirmation(tmp_path) -> None:
    api = Api(_grid())
    win = _FakeWindow()
    api._window = win
    api.set_cell(0, 0, "1")
    assert win.confirm_close is True
    api.save(str(tmp_path / "book.json"))
    assert win.confirm_close is False


def test_the_close_guard_never_calls_a_dialog_itself() -> None:
    """Regression: asking from inside the close path deadlocked the app.

    `create_confirmation_dialog` schedules its dialog onto the UI thread and
    blocks waiting for it, so calling it *from* that thread -- which is where
    a `closing` subscriber runs -- froze the window with no way out but a
    force quit. The guard must only set flags the toolkit reads later.
    """

    class _ExplodingWindow(_FakeWindow):
        def create_confirmation_dialog(self, *a: object, **k: object) -> bool:
            raise AssertionError("the close guard must not open a dialog itself")

    api = Api(_grid())
    api._window = _ExplodingWindow()
    api.set_cell(0, 0, "1")  # dirties, and so arms the guard
    api._sync_close_guard()


def test_the_close_guard_does_not_subscribe_to_the_closing_event() -> None:
    """The other half of the same deadlock.

    `closing` subscribers run synchronously on the UI thread, so anything
    there that waits on the UI thread hangs the app. Checked against the
    source because the failure is a freeze in a real window, which no unit
    test can reproduce -- the mocked version of this passed while the app
    locked up.
    """
    import ast

    from gridcalc import web

    tree = ast.parse(Path(web.__file__).with_suffix(".py").read_text())
    # Attribute *accesses*, so the explanation in the docstrings does not
    # itself trip the check.
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "closing" not in attrs
    assert "create_confirmation_dialog" not in attrs


def test_confirm_close_is_a_real_settable_attribute_of_a_pywebview_window() -> None:
    """Pins the assumption the guard rests on against the actual library.

    Mocking a window is what let the previous, deadlocking guard look correct;
    this asserts the flag exists on the real `Window` and can be toggled after
    construction, which is what makes arming it at edit time work at all.
    """
    webview = pytest.importorskip("webview")

    win = webview.create_window("probe", html="<p>probe</p>", hidden=True)
    try:
        assert win.confirm_close is False
        win.confirm_close = True
        assert win.confirm_close is True
    finally:
        webview.windows.clear()  # never started; drop it from the registry


def test_the_close_guard_tolerates_a_window_that_rejects_the_flag() -> None:
    """A toolkit that does not expose `confirm_close` must not break editing:
    the guard is best-effort, and an edit failing because of it would be far
    worse than a missing prompt."""

    class _StubbornWindow(_FakeWindow):
        def __setattr__(self, name: str, value: object) -> None:
            if name == "confirm_close" and value is True:
                raise RuntimeError("read-only")
            super().__setattr__(name, value)

    api = Api(_grid())
    api._window = _StubbornWindow()
    assert api.set_cell(0, 0, "1")["ok"] is True


def test_load_html_returns_the_built_bundle_or_raises() -> None:
    """`run()` serves the built React bundle. When the frontend has been built
    (`make web-build`) the bundle is a self-contained document that mounts the
    app and talks to the bridge; without it, `_load_html` raises a directive
    error rather than opening a blank window."""
    from gridcalc import web

    bundle = Path(web.__file__).resolve().parent / "static" / "index.html"
    if bundle.exists() and web.PLACEHOLDER_MARKER not in bundle.read_text():
        html = web._load_html()
        assert 'id="root"' in html  # the React mount point
        assert "pywebviewready" in html  # the inlined app awaits the bridge
    else:
        with pytest.raises(OSError, match="web UI bundle not built"):
            web._load_html()


def test_load_html_rejects_the_packaging_placeholder(tmp_path: Path) -> None:
    """`make build` writes a stand-in bundle when the real one is absent, because
    packaging force-includes that path and will not build without *some* file
    there. The stand-in must not be served: opening it would give a window with
    no app in it, so it fails with the same directive as a missing bundle."""
    from gridcalc import web

    placeholder = tmp_path / "index.html"
    placeholder.write_text(
        f"<!doctype html>\n<!-- {web.PLACEHOLDER_MARKER} -->\n<p>not built",
        encoding="utf-8",
    )
    with pytest.raises(OSError, match="web UI bundle not built"):
        web._load_html(placeholder)


def test_load_html_reports_a_missing_bundle_rather_than_blanking(tmp_path: Path) -> None:
    """A checkout that has never run `make web-build` has no bundle at all."""
    from gridcalc import web

    with pytest.raises(OSError, match="web UI bundle not built"):
        web._load_html(tmp_path / "absent.html")


def test_load_html_serves_a_real_bundle(tmp_path: Path) -> None:
    """Anything without the placeholder marker is a real build and is served."""
    from gridcalc import web

    real = tmp_path / "index.html"
    real.write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    assert web._load_html(real) == '<!doctype html><div id="root"></div>'


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


# --- the trust decision ----------------------------------------------------
# A workbook's code block does not run until someone says so. The curses
# frontend asks at the prompt; the web frontend asks in a dialog, and these
# cover the bridge half of it -- what is reported, and what each answer loads.

HYBRID = EXAMPLES / "example_hybrid.json"


def _tax_cell(api: Api) -> str:
    """C2 of example_hybrid.json: `=py.progressive_tax(B2)`. Reads `#NAME?`
    while the code block is withheld and 4340 once it has run."""
    from gridcalc.display import cell_text

    return cell_text(api._g.cell(2, 1))


def test_inspect_says_nothing_to_decide_for_a_plain_workbook() -> None:
    api = Api(_grid())
    assert api.inspect(str(EXAMPLES / "example_excel.json"))["needs_trust"] is False


def test_inspect_reports_what_the_file_would_run() -> None:
    api = Api(_grid())
    info = api.inspect(str(HYBRID))
    assert info["needs_trust"] is True
    assert info["name"] == "example_hybrid.json"
    assert info["has_code"] is True
    assert info["code_lines"] == 27
    assert "def progressive_tax" in info["code"]
    assert info["cells"] > 0 and info["formulas"] > 0
    assert info["blocked"] == [] and info["unknown"] == []


def test_inspect_runs_nothing() -> None:
    """The metadata comes from parsing the file. Inspecting it must not load
    it, let alone execute the code it is asking about."""
    api = Api(_grid())
    api.set_cell(0, 0, "keep")
    api.inspect(str(HYBRID))
    assert api.cell_source(0, 0) == "keep"


def test_open_without_a_policy_refuses_and_asks() -> None:
    api = Api(_grid())
    api.set_cell(0, 0, "keep")
    res = api.open_file(str(HYBRID))
    assert res["ok"] is False
    assert res["needs_trust"] is True
    assert "def progressive_tax" in res["code"]
    assert api.cell_source(0, 0) == "keep"  # nothing was loaded


def test_declining_the_code_loads_the_formulas() -> None:
    api = Api(_grid())
    res = api.open_file(str(HYBRID), {"load_code": False})
    assert res["ok"] is True
    assert _tax_cell(api) == "#NAME?"  # the py.* call has nothing to call


def test_approving_the_code_runs_it() -> None:
    api = Api(_grid())
    res = api.open_file(str(HYBRID), {"load_code": True})
    assert res["ok"] is True
    assert _tax_cell(api) == "4340"


def test_a_malformed_answer_withholds_the_code() -> None:
    """Anything but an explicit `load_code` is formulas only: a client bug
    must not be able to run a workbook by accident."""
    for answer in ({}, {"load_code": False}, {"allow_unknown": True}, {"load_code": ""}):
        api = Api(_grid())
        assert api.open_file(str(HYBRID), answer)["ok"] is True
        assert _tax_cell(api) == "#NAME?", answer


def test_a_workbook_with_no_code_opens_without_asking() -> None:
    api = Api(_grid())
    assert api.open_file(str(EXAMPLES / "example_excel.json")) == {
        "ok": True,
        "filename": str(EXAMPLES / "example_excel.json"),
    }


def test_policy_never_approves_a_blocked_module() -> None:
    from gridcalc.sandbox import FileInfo

    info = FileInfo()
    info.requires = ["numpy", "socket"]
    info.blocked_modules = ["socket"]
    policy = Api._policy_from(info, {"load_code": True, "allow_unknown": True})
    assert policy.load_code is True
    assert policy.approved_modules == ["numpy"]
    assert policy.allow_unknown is True


def test_unknown_modules_need_their_own_answer() -> None:
    """Approving the file vouches for what the lists know about; an
    unclassified module is a second answer, as it is at the curses prompt."""
    from gridcalc.sandbox import FileInfo

    info = FileInfo()
    info.requires = ["mystery"]
    info.unknown_modules = ["mystery"]
    assert Api._policy_from(info, {"load_code": True}).allow_unknown is False
    assert Api._policy_from(info, {"load_code": True, "allow_unknown": True}).allow_unknown is True


def test_pending_trust_is_empty_until_a_startup_file_sets_it() -> None:
    api = Api(_grid())
    assert api.pending_trust() == {"needs_trust": False}
    api._pending_trust = str(HYBRID)
    assert api.pending_trust()["needs_trust"] is True


def test_answering_the_startup_decision_clears_it() -> None:
    api = Api(load_workbook(str(HYBRID)))
    api._pending_trust = str(HYBRID)
    api.open_file(str(HYBRID), {"load_code": True})
    assert api.pending_trust() == {"needs_trust": False}
    assert _tax_cell(api) == "4340"


def test_needs_trust_covers_only_files_that_can_carry_code(tmp_path) -> None:
    from gridcalc.loader import needs_trust

    assert needs_trust(EXAMPLES / "example_excel.json") is None
    assert needs_trust(EXAMPLES / "example_multisheet.xlsx") is None
    csv = tmp_path / "d.csv"
    csv.write_text("a,b\n1,2\n")
    assert needs_trust(csv) is None
    assert needs_trust("/no/such/file.json") is None  # the load reports that
    assert needs_trust(HYBRID) is not None


def test_nothing_is_withheld_when_the_sandbox_is_off(monkeypatch) -> None:
    """With the sandbox disabled there is nothing to ask about, so the dialog
    must not appear -- and the code has to load, or the file is broken for the
    user who turned the sandbox off precisely to run it."""
    from gridcalc import sandbox
    from gridcalc.loader import needs_trust

    monkeypatch.setattr(sandbox, "SANDBOX_ENABLED", False)
    assert needs_trust(HYBRID) is None
    api = Api(_grid())
    assert api.inspect(str(HYBRID))["needs_trust"] is False
    assert api.open_file(str(HYBRID))["ok"] is True
    assert _tax_cell(api) == "4340"
