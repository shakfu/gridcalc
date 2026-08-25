"""Tests for `gridcalc.undo`, focused on what a snapshot has to carry.

A structural edit (insert/delete row or column) moves more than cells: named
ranges shift with the lines they cover and are dropped when they lose all of
them, and column widths travel with their column. `save_grid` recorded only
cells, so undo put the cells back and left the metadata shifted -- a name then
pointed a row off its data and formulas over it computed a plausible, wrong
answer with no error anywhere.
"""

from __future__ import annotations

from gridcalc.engine import Grid, NamedRange
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
        assert entry.widths is None
