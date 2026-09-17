"""Tests for `gridcalc.undo`, focused on what a snapshot has to carry.

A structural edit (insert/delete row or column) moves more than cells: named
ranges shift with the lines they cover and are dropped when they lose all of
them, and column widths travel with their column. `save_grid` recorded only
cells, so undo put the cells back and left the metadata shifted -- a name then
pointed a row off its data and formulas over it computed a plausible, wrong
answer with no error anywhere.
"""

from __future__ import annotations

import pytest

from gridcalc import commands as C
from gridcalc.engine import Grid, Mode, NamedRange
from gridcalc.undo import UndoManager


def _col_grid() -> Grid:
    """A1:A5 = 10..50, with `block` covering A3:A5 (rows 2-4)."""
    g = Grid()
    for r in range(5):
        g.setcell(0, r, str((r + 1) * 10))
    g.names.append(NamedRange(name="block", c1=0, r1=2, c2=0, r2=4))
    g.recalc()
    return g


def _rows(g: Grid, name: str = "block") -> tuple[int, int]:
    nr = next(n for n in g.names if n.name == name)
    return (nr.r1, nr.r2)


def _col_a(g: Grid) -> list[float | None]:
    return [None if g.cell(0, r) is None else g.cell(0, r).val for r in range(6)]


class TestStructuralUndoRestoresNamedRanges:
    def test_undoing_a_row_insert_puts_the_name_back(self):
        g = _col_grid()
        u = UndoManager()
        assert _rows(g) == (2, 4)

        u.save_grid(g)
        g.insertrow(0)
        g.recalc()
        assert _rows(g) == (3, 5)  # the name followed its data down

        u.undo(g)
        g.recalc()
        assert _rows(g) == (2, 4)  # ...and comes back with it
        assert _col_a(g) == [10.0, 20.0, 30.0, 40.0, 50.0, None]

    def test_redo_reapplies_the_shift(self):
        """The rollback entry has to carry the metadata too, not just undo."""
        g = _col_grid()
        u = UndoManager()
        u.save_grid(g)
        g.insertrow(0)
        g.recalc()
        u.undo(g)
        g.recalc()
        assert _rows(g) == (2, 4)  # asserted here too, so the test cannot pass
        u.redo(g)  # trivially by undo never having moved it
        g.recalc()
        assert _rows(g) == (3, 5)
        assert _col_a(g) == [None, 10.0, 20.0, 30.0, 40.0, 50.0]

    def test_a_name_that_lost_every_row_is_resurrected(self):
        """Deleting the only row a name covers drops it from the list entirely,
        so undo has to restore membership, not just coordinates."""
        g = Grid()
        for r in range(3):
            g.setcell(0, r, str((r + 1) * 10))
        g.names.append(NamedRange(name="solo", c1=0, r1=1, c2=0, r2=1))
        g.recalc()

        u = UndoManager()
        u.save_grid(g)
        g.deleterow(1)
        g.recalc()
        assert [n.name for n in g.names] == []

        u.undo(g)
        g.recalc()
        assert [n.name for n in g.names] == ["solo"]
        assert _rows(g, "solo") == (1, 1)

    def test_the_snapshot_is_not_aliased_to_the_live_names(self):
        """`NamedRange` is edited in place, so a shallow copy would be rewritten
        by the very edit the snapshot is meant to record."""
        g = _col_grid()
        u = UndoManager()
        u.save_grid(g)
        entry = u.undo_stack[-1]
        g.insertrow(0)
        g.recalc()
        assert entry.names is not None
        assert (entry.names[0].r1, entry.names[0].r2) == (2, 4)  # unmoved


class TestStructuralUndoRestoresColumnWidths:
    def test_undoing_a_column_insert_puts_the_widths_back(self):
        g = Grid()
        for c in range(4):
            g.setcell(c, 0, str((c + 1) * 10))
        g._active.widths = {0: 20, 1: 21, 2: 22, 3: 23}
        g.recalc()

        u = UndoManager()
        u.save_grid(g)
        g.insertcol(1)
        g.recalc()
        assert g._active.widths == {0: 20, 2: 21, 3: 22, 4: 23}  # travelled right

        u.undo(g)
        g.recalc()
        assert g._active.widths == {0: 20, 1: 21, 2: 22, 3: 23}

        u.redo(g)
        g.recalc()
        assert g._active.widths == {0: 20, 2: 21, 3: 22, 4: 23}


class TestCellUndoLeavesMetadataAlone:
    """Only grid-level snapshots carry metadata; `None` means "do not touch".

    Otherwise undoing a one-cell edit would also revert a `:name` the user
    created afterwards, which is not what they asked to undo.
    """

    def test_undoing_a_cell_edit_keeps_a_later_name(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.recalc()

        u = UndoManager()
        u.save_cell(g, 0, 0)
        g.setcell(0, 0, "99")
        g.names.append(NamedRange(name="added", c1=0, r1=0, c2=0, r2=0))
        g.recalc()

        u.undo(g)
        g.recalc()
        assert g.cell(0, 0).val == 10.0  # the edit is undone
        assert [n.name for n in g.names] == ["added"]  # the name survives

    def test_a_cell_entry_records_no_metadata(self):
        g = _col_grid()
        u = UndoManager()
        u.save_cell(g, 0, 0)
        entry = u.undo_stack[-1]
        assert entry.names is None
        assert entry.book is None


def _two_sheets() -> Grid:
    """Sheet1!A1:A3 = 1..3; S2!A1 = =Sheet1!A2*2 (EXCEL mode)."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for r in range(3):
        g.setcell(0, r, str(r + 1))
    g.add_sheet("S2")
    g.set_active("S2")
    g.setcell(0, 0, "=Sheet1!A2*2")
    g.set_active(0)
    g.recalc()
    return g


def _s2a1(g: Grid) -> tuple[str, float]:
    cl = next(s for s in g.sheets if s.name == "S2")._cells[(0, 0)]
    return (cl.text, cl.val)


class TestStructuralUndoRestoresEverySheet:
    """T4: an insert/delete on one sheet rewrites references on every sheet."""

    @pytest.mark.parametrize(
        ("name", "sel"),
        [("insrow", (0, 0, 0, 0)), ("delrow", (0, 0, 0, 0)), ("inscol", (0, 0, 0, 0))],
    )
    def test_undo_puts_other_sheets_formulas_back(self, name, sel):
        g = _two_sheets()
        u = UndoManager()
        assert C.run(name, g, u, [], sel).ok
        assert _s2a1(g)[0] != "=Sheet1!A2*2"
        assert u.undo(g) is True
        assert _s2a1(g) == ("=Sheet1!A2*2", 4.0)
        g.setcell(0, 1, "5")
        assert _s2a1(g) == ("=Sheet1!A2*2", 10.0)


class TestSheetOpsAreUndoable:
    """T10: a sheet op snapshots the workbook; cell entries follow the sheet."""

    def test_undo_restores_a_deleted_sheet_with_its_cells(self):
        g = _two_sheets()
        u = UndoManager()
        g.set_active("S2")
        u.save_cell(g, 1, 0)
        g.setcell(1, 0, "keep")
        g.set_active(0)
        u.save_grid(g)
        g.remove_sheet("S2")
        g.recalc()
        assert u.undo(g) is True
        assert g.sheet_names() == ["Sheet1", "S2"]
        assert _s2a1(g) == ("=Sheet1!A2*2", 4.0)
        assert u.undo(g) is True  # the earlier edit on S2 still applies
        assert (1, 0) not in g.sheets[1]._cells
        assert u.redo(g) and u.redo(g)
        assert g.sheet_names() == ["Sheet1"]

    def test_undo_of_add_move_and_rename(self):
        g = _two_sheets()
        u = UndoManager()
        u.save_grid(g)
        g.add_sheet("S3")
        u.save_grid(g)
        g.move_sheet("S3", 0)
        u.save_grid(g)
        g.rename_sheet("Sheet1", "Main")
        g.recalc()
        assert _s2a1(g)[0] == "=Main!A2*2"
        u.undo(g)
        assert g.sheet_names() == ["S3", "Sheet1", "S2"]
        assert _s2a1(g) == ("=Sheet1!A2*2", 4.0)
        u.undo(g)
        assert g.sheet_names() == ["Sheet1", "S2", "S3"]
        u.undo(g)
        assert g.sheet_names() == ["Sheet1", "S2"]
        assert g.active == 0

    def test_cell_entry_follows_its_sheet_through_a_rename(self):
        g = _two_sheets()
        u = UndoManager()
        g.set_active("S2")
        u.save_cell(g, 2, 0)
        g.setcell(2, 0, "edited")
        g.set_active(0)
        g.rename_sheet("S2", "Data")  # not recorded: the entry must still apply
        assert u.undo(g) is True
        assert g.sheets[1].name == "Data"
        assert (2, 0) not in g.sheets[1]._cells

    def test_rename_then_readd_old_name_does_not_misdirect_undo(self):
        g = _two_sheets()
        u = UndoManager()
        g.set_active("S2")
        u.save_cell(g, 2, 0)
        g.setcell(2, 0, "edited")
        g.set_active(0)
        g.rename_sheet("S2", "Data")
        g.add_sheet("S2")
        g.set_active("S2")
        g.setcell(2, 0, "other")
        u.undo(g)
        assert g.sheets[2]._cells[(2, 0)].text == "other"
        assert (2, 0) not in g.sheets[1]._cells


class TestNamesAndModeAreUndoable:
    """T11: `:name`, `:unname`, `:mode` record an entry, so `u` undoes them."""

    def _edited(self) -> tuple[Grid, UndoManager]:
        g = _two_sheets()
        u = UndoManager()
        u.save_cell(g, 1, 0)
        g.setcell(1, 0, "=SUM(A1:A3)")
        return g, u

    @pytest.mark.parametrize(
        "args", [("name", "Tot", "A1:A2"), ("mode", "python"), ("gformat", "$")]
    )
    def test_undo_reverts_the_command_not_the_earlier_edit(self, args):
        g, u = self._edited()
        before = (_names(g), g.mode, g.fmt)
        res = C.run(args[0], g, u, list(args[1:]))
        assert res.ok and res.changed
        assert u.undo(g) is True
        assert (_names(g), g.mode, g.fmt) == before
        assert g.cell(1, 0).text == "=SUM(A1:A3)"
        assert u.redo(g) is True
        assert (_names(g), g.mode, g.fmt) != before

    def test_unname_and_redefine(self):
        g, u = self._edited()
        g.names.append(NamedRange("Tot", 0, 0, 0, 2))
        assert C.run("name", g, u, ["Tot", "A1"]).ok
        assert C.run("unname", g, u, ["Tot"]).ok
        u.undo(g)
        assert _names(g) == [("Tot", 0, 0, 0, 0)]
        u.undo(g)
        assert _names(g) == [("Tot", 0, 0, 0, 2)]
        assert g.cell(1, 0).text == "=SUM(A1:A3)"


def _names(g: Grid) -> list[tuple[str, int, int, int, int]]:
    return [(n.name, n.c1, n.r1, n.c2, n.r2) for n in g.names]


class TestManagerApi:
    def test_undo_and_redo_report_whether_they_applied(self):
        g = Grid()
        u = UndoManager()
        assert u.undo(g) is False and u.redo(g) is False
        u.save_cell(g, 0, 0)
        g.setcell(0, 0, "1")
        assert u.undo(g) is True and u.redo(g) is True

    def test_applying_an_entry_dirties_the_grid(self):
        g = Grid()
        u = UndoManager()
        u.save_cell(g, 0, 0)
        g.setcell(0, 0, "1")
        g.dirty = 0
        u.undo(g)
        assert g.dirty == 1

    def test_clear_drops_both_stacks(self):
        g = Grid()
        u = UndoManager()
        u.save_cell(g, 0, 0)
        u.save_cell(g, 0, 0)
        u.undo(g)
        u.clear()
        assert u.undo_stack == [] and u.redo_stack == []

    def _with_redo(self) -> tuple[Grid, UndoManager]:
        g = Grid()
        u = UndoManager()
        u.save_cell(g, 0, 0)
        g.setcell(0, 0, "1")
        u.undo(g)
        assert len(u.redo_stack) == 1
        return g, u

    def test_discard_last_restores_the_redo_stack_a_save_cleared(self):
        g, u = self._with_redo()
        u.save_grid(g)
        assert u.redo_stack == []
        u.discard_last()
        assert u.undo_stack == [] and len(u.redo_stack) == 1
        assert u.redo(g) is True
        assert g.cell(0, 0).val == 1.0

    def test_rollback_restores_without_a_redo_entry(self):
        g, u = self._with_redo()
        g.setcell(1, 0, "keep")
        g.dirty = 0
        u.save_grid(g)
        g.clear_all()
        assert u.rollback(g) is True
        assert g.cell(1, 0).text == "keep"
        assert u.undo_stack == [] and len(u.redo_stack) == 1
        assert g.dirty == 0
