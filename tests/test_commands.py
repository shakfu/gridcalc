"""Tests for the frontend-neutral command registry (`gridcalc.commands`).

These exercise the commands directly, with no frontend involved, because that
is now where the behaviour lives: both `cmdexec` and `web.Api.run_command` are
thin dispatchers over these functions. Frontend-specific concerns -- prompting
for a missing argument, presenting a result -- are tested in `test_tui.py` and
`test_web.py` respectively.
"""

from __future__ import annotations

import math

import pytest

from gridcalc import commands as shared
from gridcalc.engine import EMPTY, MAXNAMES, NROW, Grid, Mode
from gridcalc.undo import UndoManager


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


def _run(g: Grid, name: str, *args: str, sel=None) -> shared.Result:
    return shared.run(name, g, UndoManager(), list(args), sel)


# -- registry shape -----------------------------------------------------


def test_every_command_is_reachable_by_name_and_alias() -> None:
    for cmd in shared.COMMANDS:
        for name in cmd.names:
            assert shared.lookup(name) is cmd
    assert shared.lookup("SORT") is shared.lookup("sort")  # case-insensitive


def test_names_and_aliases_are_unique_across_the_registry() -> None:
    """A duplicate would make one command silently unreachable."""
    seen: list[str] = []
    for cmd in shared.COMMANDS:
        seen.extend(cmd.names)
    assert len(seen) == len(set(seen)), sorted({n for n in seen if seen.count(n) > 1})


def test_an_unknown_command_fails_rather_than_raising() -> None:
    r = _run(_grid(), "nonesuch")
    assert r.ok is False and "unknown command" in r.message


def test_describe_is_json_safe_and_complete() -> None:
    """The web view builds its palette from this, so every command must appear
    with the fields the client reads."""
    import json

    described = shared.describe()
    assert len(described) == len(shared.COMMANDS)
    json.dumps(described)  # raises if anything is not serializable
    for entry in described:
        assert {"name", "title", "group", "args", "aliases", "needs_selection"} <= set(entry)
        for arg in entry["args"]:
            assert {"name", "help", "required", "kind", "choices"} <= set(arg)


# -- context ------------------------------------------------------------


def test_rect_falls_back_to_the_cursor_without_a_selection() -> None:
    g = _grid()
    g.cc, g.cr = 3, 7
    ctx = shared.Context(grid=g, undo=UndoManager())
    assert ctx.rect() == (3, 7, 3, 7)


def test_rect_normalizes_a_backwards_selection() -> None:
    ctx = shared.Context(grid=_grid(), undo=UndoManager(), selection=(4, 9, 1, 2))
    assert ctx.rect() == (1, 2, 4, 9)


# -- blank / format -----------------------------------------------------


def test_blank_clears_the_selection_and_recalcs() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.setcell(1, 0, "2")
    g.setcell(3, 0, "=A1+B1")
    g.recalc()
    assert _run(g, "blank", sel=(0, 0, 1, 1)).changed is True
    assert g.cell(0, 0) is None or g.cell(0, 0).type == EMPTY
    assert g.cell(3, 0).val == 0.0  # the dependent recomputed


def test_format_applies_style_number_and_python_specs() -> None:
    g = _grid()
    g.setcell(0, 0, "5")
    g.recalc()
    _run(g, "format", "b", sel=(0, 0, 0, 0))
    assert g.cell(0, 0).bold == 1
    _run(g, "format", "b", sel=(0, 0, 0, 0))
    assert g.cell(0, 0).bold == 0  # a style spec toggles
    _run(g, "format", "$", sel=(0, 0, 0, 0))
    assert g.cell(0, 0).fmt == "$"
    _run(g, "format", ",.2f", sel=(0, 0, 0, 0))
    assert g.cell(0, 0).fmtstr == ",.2f"
    assert g.cell(0, 0).fmt == ""  # a Python spec clears the single-char one


def test_format_without_a_spec_explains_itself() -> None:
    r = _run(_grid(), "format")
    assert r.ok is False and "b u i" in r.message


def test_gformat_sets_the_workbook_default_and_rejects_junk() -> None:
    g = _grid()
    assert _run(g, "gformat", "$").changed is True
    assert g.fmt == "$"
    assert _run(g, "gformat", "z").ok is False
    assert g.fmt == "$"  # unchanged by the refusal


# -- structural edits ---------------------------------------------------


def test_insert_rows_shifts_cells_and_rewrites_references() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "=A1*2")
    g.recalc()
    assert _run(g, "insrow", sel=(0, 0, 0, 0)).ok is True
    assert g.cell(0, 0) is None or g.cell(0, 0).type == EMPTY
    assert g.cell(0, 1).val == 10.0
    assert g.cell(0, 2).text == "=A2*2"  # the reference followed its target
    assert g.cell(0, 2).val == 20.0


def test_insert_rows_inserts_as_many_as_the_selection_spans() -> None:
    """The delete side has always been selection-sized; insert now matches, so
    a three-row selection inserts three rows rather than one."""
    g = _grid()
    g.setcell(0, 0, "10")
    g.recalc()
    _run(g, "insrow", sel=(0, 0, 0, 2))
    assert g.cell(0, 3).val == 10.0


def test_insert_cols_shifts_columns() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.setcell(1, 0, "=A1+1")
    g.recalc()
    _run(g, "inscol", sel=(0, 0, 0, 0))
    assert g.cell(1, 0).val == 10.0
    assert g.cell(2, 0).text == "=B1+1"
    assert g.cell(2, 0).val == 11.0


def test_delete_rows_removes_a_span_bottom_up() -> None:
    """Deleting rows 1..2 must not have the second call act on a shifted
    index -- the whole span goes and row 3 slides up."""
    g = _grid()
    for r in range(5):
        g.setcell(0, r, str(r))
    g.recalc()
    _run(g, "delrow", sel=(0, 1, 0, 2))
    assert g.cell(0, 0).val == 0.0
    assert g.cell(0, 1).val == 3.0
    assert g.cell(0, 2).val == 4.0
    assert g.cell(0, 3) is None or g.cell(0, 3).type == EMPTY


def test_delete_cols_removes_a_span() -> None:
    g = _grid()
    for c in range(4):
        g.setcell(c, 0, str(c))
    g.recalc()
    _run(g, "delcol", sel=(1, 0, 2, 0))
    assert g.cell(0, 0).val == 0.0
    assert g.cell(1, 0).val == 3.0


def test_structural_edits_use_the_cursor_without_a_selection() -> None:
    g = _grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "1")
    g.recalc()
    g.cc, g.cr = 0, 0
    _run(g, "delrow")
    assert g.cell(0, 0).val == 1.0


def test_structural_edits_are_undoable() -> None:
    g = _grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "=A1*2")
    g.recalc()
    undo = UndoManager()
    shared.run("delrow", g, undo, [], (0, 0, 0, 0))
    assert g.cell(0, 1) is None or g.cell(0, 1).type == EMPTY

    undo.undo(g)
    assert g.cell(0, 0).val == 10.0
    assert g.cell(0, 1).text == "=A1*2"
    assert g.cell(0, 1).val == 20.0


def test_insert_out_of_range_is_refused() -> None:
    r = _run(_grid(), "insrow", sel=(0, NROW + 5, 0, NROW + 5))
    assert r.ok is False and "out of range" in r.message


def test_column_insert_carries_saved_widths_with_their_columns() -> None:
    g = _grid()
    g._active.widths = {2: 140}
    _run(g, "inscol", sel=(0, 0, 0, 0))
    assert g._active.widths == {3: 140}
    _run(g, "delcol", sel=(0, 0, 0, 0))
    assert g._active.widths == {2: 140}


# -- named ranges -------------------------------------------------------


def test_name_defines_a_range_formulas_can_use() -> None:
    g = _grid()
    g.setcell(0, 1, "10")
    g.setcell(0, 2, "20")
    g.recalc()
    assert _run(g, "name", "Data", "A2:A3").ok is True
    g.setcell(2, 0, "=SUM(Data)")
    g.recalc()
    assert g.cell(2, 0).val == 30.0


def test_name_defaults_its_range_to_the_selection() -> None:
    g = _grid()
    r = _run(g, "name", "Block", sel=(1, 2, 3, 4))
    assert r.ok is True and "B3:D5" in r.message


def test_name_accepts_a_single_cell() -> None:
    g = _grid()
    _run(g, "name", "Rate", "B7")
    assert _run(g, "names").lines == ("Rate = B7",)


def test_redefining_a_name_moves_it_rather_than_duplicating() -> None:
    g = _grid()
    _run(g, "name", "Data", "A1:A2")
    _run(g, "name", "Data", "B1:B9")
    assert _run(g, "names").lines == ("Data = B1:B9",)


def test_a_name_that_reads_as_a_cell_reference_is_refused() -> None:
    """`B7` as a name would make `=B7` ambiguous; refusing beats inventing a
    precedence rule the user has to learn."""
    r = _run(_grid(), "name", "B7", "A1:A2")
    assert r.ok is False and "cell reference" in r.message


@pytest.mark.parametrize("bad", ["9bad", "", "has-dash"])
def test_name_syntax_is_validated(bad: str) -> None:
    assert _run(_grid(), "name", bad, "A1").ok is False


def test_name_rejects_a_bad_range() -> None:
    r = _run(_grid(), "name", "Data", "not-a-range")
    assert r.ok is False and "bad range" in r.message


def test_names_are_listed_alphabetically_case_insensitively() -> None:
    g = _grid()
    _run(g, "name", "zeta", "A1")
    _run(g, "name", "Alpha", "A2")
    assert _run(g, "names").lines == ("Alpha = A2", "zeta = A1")


def test_names_on_an_empty_workbook_says_so() -> None:
    r = _run(_grid(), "names")
    assert r.ok is True and r.message == "no named ranges" and r.lines == ()


def test_unname_removes_it_and_leaves_users_in_error() -> None:
    g = _grid()
    g.setcell(0, 1, "10")
    g.recalc()
    _run(g, "name", "Data", "A2")
    g.setcell(2, 0, "=SUM(Data)")
    g.recalc()
    assert g.cell(2, 0).val == 10.0

    assert _run(g, "unname", "Data").ok is True
    g.recalc()
    assert math.isnan(g.cell(2, 0).val)  # visible, not silently wrong


def test_unname_on_a_missing_name_reports() -> None:
    r = _run(_grid(), "unname", "Nope")
    assert r.ok is False and r.message == "no such name: Nope"


def test_name_respects_the_workbook_limit() -> None:
    g = _grid()
    for i in range(MAXNAMES):
        # Not "n0", "n1", ...: those parse as column-N cell references.
        assert _run(g, "name", f"name{i}", "A1").ok is True
    r = _run(g, "name", "one_too_many", "A1")
    assert r.ok is False and "too many names" in r.message


# -- sort ---------------------------------------------------------------


def test_sort_orders_rows_by_a_column_ascending_and_descending() -> None:
    g = _grid()
    for r, v in enumerate(["3", "1", "2"]):
        g.setcell(0, r, v)
    g.recalc()
    _run(g, "sort", "A", sel=(0, 0, 0, 2))
    assert [g.cell(0, r).val for r in range(3)] == [1.0, 2.0, 3.0]
    _run(g, "sort", "A", "desc", sel=(0, 0, 0, 2))
    assert [g.cell(0, r).val for r in range(3)] == [3.0, 2.0, 1.0]


def test_sort_moves_whole_rows_together() -> None:
    g = _grid()
    for r, (k, v) in enumerate([("3", "c"), ("1", "a"), ("2", "b")]):
        g.setcell(0, r, k)
        g.setcell(1, r, v)
    g.recalc()
    _run(g, "sort", "A", sel=(0, 0, 1, 2))
    assert [g.cell(1, r).text for r in range(3)] == ["a", "b", "c"]


def test_sort_puts_numbers_before_labels_before_blanks() -> None:
    g = _grid()
    g.setcell(0, 0, "zebra")
    g.setcell(0, 1, "5")
    g.setcell(0, 3, "apple")
    g.recalc()
    _run(g, "sort", "A", sel=(0, 0, 0, 3))
    assert g.cell(0, 0).val == 5.0
    assert g.cell(0, 1).text == "apple"
    assert g.cell(0, 2).text == "zebra"
    assert g.cell(0, 3) is None or g.cell(0, 3).type == EMPTY


def test_sort_defaults_to_the_selections_first_column() -> None:
    g = _grid()
    for r, v in enumerate(["3", "1", "2"]):
        g.setcell(1, r, v)
    g.recalc()
    _run(g, "sort", sel=(1, 0, 1, 2))
    assert [g.cell(1, r).val for r in range(3)] == [1.0, 2.0, 3.0]


def test_sort_rejects_a_column_outside_the_range() -> None:
    g = _grid()
    g.setcell(0, 0, "1")
    g.recalc()
    r = _run(g, "sort", "Z", sel=(0, 0, 0, 0))
    assert r.ok is False and "outside" in r.message


def test_sort_rejects_an_unparseable_column() -> None:
    r = _run(_grid(), "sort", "123", sel=(0, 0, 0, 1))
    assert r.ok is False and "invalid column" in r.message


def test_sort_without_a_selection_uses_the_data_extent() -> None:
    g = _grid()
    for r, v in enumerate(["3", "1", "2"]):
        g.setcell(0, r, v)
    g.recalc()
    g.cc = 0
    _run(g, "sort")
    assert [g.cell(0, r).val for r in range(3)] == [1.0, 2.0, 3.0]


def test_sort_of_an_empty_sheet_is_a_no_op() -> None:
    r = _run(_grid(), "sort")
    assert r.ok is True and r.changed is False


def test_sort_is_undoable() -> None:
    g = _grid()
    for r, v in enumerate(["3", "1", "2"]):
        g.setcell(0, r, v)
    g.recalc()
    undo = UndoManager()
    shared.run("sort", g, undo, ["A"], (0, 0, 0, 2))
    assert [g.cell(0, r).val for r in range(3)] == [1.0, 2.0, 3.0]
    undo.undo(g)
    assert [g.cell(0, r).val for r in range(3)] == [3.0, 1.0, 2.0]


# -- mode / title / recalc ----------------------------------------------


def test_mode_with_no_argument_reports_the_current_mode() -> None:
    r = _run(_grid(), "mode")
    assert r.ok is True and "excel" in r.message and r.changed is False


def test_mode_switches_and_validates() -> None:
    g = _grid()
    assert _run(g, "mode", "hybrid").changed is True
    assert g.mode == Mode.HYBRID
    assert _run(g, "mode", "nonsense").ok is False
    assert g.mode == Mode.HYBRID


def test_switching_to_the_current_mode_changes_nothing() -> None:
    g = _grid()
    r = _run(g, "mode", "excel")
    assert r.ok is True and r.changed is False


def test_title_freezes_and_clears_panes() -> None:
    g = _grid()
    g.cc, g.cr = 2, 3
    _run(g, "title", "b")
    assert (g.tc, g.tr) == (3, 4)
    _run(g, "title", "n")
    assert (g.tc, g.tr) == (0, 0)


def test_title_rejects_an_unknown_kind() -> None:
    r = _run(_grid(), "title", "x")
    assert r.ok is False


def test_recalc_recomputes_without_reporting_a_change() -> None:
    """Asking for the values you already had is not an edit, so it must not
    mark a saved workbook modified."""
    g = _grid()
    g.setcell(0, 0, "2")
    g.setcell(1, 0, "=A1*3")
    g.recalc()
    r = _run(g, "recalc")
    assert r.ok is True and r.changed is False
    assert g.cell(1, 0).val == 6.0
