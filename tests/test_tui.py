"""Tests for TUI components that don't require a live curses terminal."""

import curses
import importlib.util
import json
import math
from pathlib import Path

import pytest

from gridcalc.engine import Grid, NamedRange, col_name
from gridcalc.opt import OptModel
from gridcalc.tui import UndoManager

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None
_HAS_PANDAS = importlib.util.find_spec("pandas") is not None

# Resolve example fixtures relative to this file, not the process CWD, so the
# tests pass wherever pytest is invoked from -- e.g. cibuildwheel runs the
# suite from a temporary directory, where a bare "examples/..." path would
# silently miss and leave the grid empty.
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestUndoManagerSaveCell:
    def test_undo_restores_value(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        assert g.cells[0][0].val == 20.0
        undo.undo(g)
        assert g.cells[0][0].val == 10.0

    def test_redo_restores_new_value(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        undo.undo(g)
        assert g.cells[0][0].val == 10.0
        undo.redo(g)
        assert g.cells[0][0].val == 20.0

    def test_undo_empty_to_populated(self):
        """Undo of adding a value to an empty cell restores emptiness."""
        g = Grid()
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "42")
        assert g.cells[0][0].val == 42.0
        undo.undo(g)
        assert g.cell(0, 0) is None

    def test_undo_populated_to_empty(self):
        """Undo of clearing a cell restores the value."""
        g = Grid()
        g.setcell(0, 0, "99")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "")
        assert g.cell(0, 0) is None
        undo.undo(g)
        assert g.cells[0][0].val == 99.0

    def test_undo_empty_stack_noop(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.undo(g)  # should not crash
        assert g.cells[0][0].val == 10.0

    def test_undo_atomic_on_apply_failure(self, monkeypatch):
        """If the restore mutation raises, grid and stacks roll back together."""
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        undo = UndoManager()
        undo.save_region(g, 0, 0, 1, 0)
        g.setcell(0, 0, "100")
        g.setcell(1, 0, "200")

        # Force the second copy_from in the restore loop to raise.
        from gridcalc.engine import Cell as _Cell

        original = _Cell.copy_from
        calls = {"n": 0}

        def flaky(self, src):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated mid-restore failure")
            original(self, src)

        monkeypatch.setattr(_Cell, "copy_from", flaky)

        with pytest.raises(RuntimeError):
            undo.undo(g)

        # Grid restored to the post-edit state (pre-undo).
        assert g.cells[0][0].val == 100.0
        assert g.cells[1][0].val == 200.0
        # Undo entry remained on the stack so the user can retry.
        assert len(undo.undo_stack) == 1
        # Nothing pushed to redo despite the failed apply.
        assert len(undo.redo_stack) == 0

    def test_redo_empty_stack_noop(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.redo(g)  # should not crash
        assert g.cells[0][0].val == 10.0

    def test_new_edit_clears_redo(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        undo.undo(g)
        # Now make a new edit instead of redo
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "30")
        # Redo stack should be cleared
        undo.redo(g)  # should be noop
        assert g.cells[0][0].val == 30.0

    def test_multiple_undo(self):
        g = Grid()
        undo = UndoManager()
        g.setcell(0, 0, "10")
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "30")
        assert g.cells[0][0].val == 30.0
        undo.undo(g)
        assert g.cells[0][0].val == 20.0
        undo.undo(g)
        assert g.cells[0][0].val == 10.0

    def test_undo_preserves_style(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.cell(0, 0).bold = 1
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        g.cell(0, 0).bold = 0
        undo.undo(g)
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][0].bold == 1


class TestUndoManagerSaveGrid:
    def test_grid_undo(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        undo = UndoManager()
        undo.save_grid(g)
        g.clear_all()
        assert g.cell(0, 0) is None
        assert g.cell(1, 0) is None
        undo.undo(g)
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].val == 20.0

    def test_grid_undo_redo(self):
        g = Grid()
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_grid(g)
        g.clear_all()
        undo.undo(g)
        assert g.cells[0][0].val == 10.0
        undo.redo(g)
        assert g.cell(0, 0) is None


class TestUndoManagerSaveRegion:
    def test_region_undo(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(0, 1, "30")
        g.setcell(1, 1, "40")
        undo = UndoManager()
        undo.save_region(g, 0, 0, 1, 1)
        g.setcell(0, 0, "100")
        g.setcell(1, 0, "200")
        g.setcell(0, 1, "300")
        g.setcell(1, 1, "400")
        undo.undo(g)
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].val == 20.0
        assert g.cells[0][1].val == 30.0
        assert g.cells[1][1].val == 40.0

    def test_undo_limit(self):
        g = Grid()
        g.setcell(0, 0, "0")
        undo = UndoManager()
        for i in range(1, 100):
            undo.save_cell(g, 0, 0)
            g.setcell(0, 0, str(i))
        # Undo stack is capped at 64
        assert len(undo.undo_stack) == 64


class TestUndoManagerAcrossSheets:
    """Cell coordinates are per-sheet, so history has to remember which sheet
    a snapshot came from -- otherwise an undo taken after switching tabs
    restores the old cells into whichever sheet happens to be active."""

    def test_undo_restores_to_the_sheet_the_edit_happened_on(self):
        g = Grid()
        g.add_sheet("Data")
        g.setcell(0, 0, "10")  # on Sheet1
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        g.set_active("Data")
        g.setcell(0, 0, "999")  # a real value on the other sheet

        undo.undo(g)

        assert g.active == 0  # followed the entry back to Sheet1
        assert g.sheets[0]._cells[(0, 0)].val == 10.0
        assert g.sheets[1]._cells[(0, 0)].val == 999.0  # untouched

    def test_grid_wide_undo_does_not_wipe_another_sheet(self):
        g = Grid()
        g.add_sheet("Data")
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_grid(g)  # is_grid entries clear_all() before restoring
        g.setcell(1, 0, "extra")
        g.set_active("Data")
        g.setcell(0, 0, "keepme")

        undo.undo(g)

        assert g.sheets[1]._cells[(0, 0)].text == "keepme"
        assert g.sheets[0]._cells[(0, 0)].val == 10.0
        assert (1, 0) not in g.sheets[0]._cells

    def test_redo_returns_to_that_sheet_too(self):
        g = Grid()
        g.add_sheet("Data")
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        undo.undo(g)
        g.set_active("Data")

        undo.redo(g)

        assert g.active == 0
        assert g.sheets[0]._cells[(0, 0)].val == 20.0

    def test_entry_for_a_deleted_sheet_is_dropped_not_misapplied(self):
        g = Grid()
        g.add_sheet("Data")
        g.set_active("Data")
        g.setcell(0, 0, "10")
        undo = UndoManager()
        undo.save_cell(g, 0, 0)
        g.setcell(0, 0, "20")
        g.remove_sheet("Data")
        g.setcell(0, 0, "sheet1 value")

        undo.undo(g)

        assert g.cells[0][0].text == "sheet1 value"  # not clobbered
        assert undo.undo_stack == []  # the unusable entry is gone


# -- cmdexec tests using a mock stdscr --


class MockStdscr:
    """Minimal mock for curses stdscr to test command dispatch."""

    def __init__(self):
        self._getch_queue = []
        self._last_addnstr = ""

    def queue_getch(self, *keys):
        self._getch_queue.extend(keys)

    def getch(self):
        if self._getch_queue:
            return self._getch_queue.pop(0)
        return 27  # ESC by default

    def addnstr(self, y, x, s, n, *args):
        self._last_addnstr = s

    def move(self, y, x):
        pass

    def clrtoeol(self):
        pass

    def refresh(self):
        pass

    def erase(self):
        pass

    def attron(self, attr):
        pass

    def attroff(self, attr):
        pass


def _setup_curses_constants():
    """Set curses module constants needed by draw/cmdexec without initscr."""
    curses.COLS = 80
    curses.LINES = 24
    # Stub curses.color_pair so the format picker works without initscr
    if not hasattr(curses, "_orig_color_pair"):
        curses._orig_color_pair = curses.color_pair
        curses.color_pair = lambda n: 0


class TestCmdexec:
    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_quit_clean(self):
        from gridcalc.tui import cmdexec

        result = cmdexec(self.stdscr, self.g, self.undo, "q")
        assert result is True

    def test_force_quit(self):
        from gridcalc.tui import cmdexec

        self.g.dirty = 1
        result = cmdexec(self.stdscr, self.g, self.undo, "q!")
        assert result is True

    def test_quit_dirty_denied(self):
        from gridcalc.tui import cmdexec

        self.g.dirty = 1
        # getch returns 'n' to deny quit
        self.stdscr.queue_getch(ord("n"))
        result = cmdexec(self.stdscr, self.g, self.undo, "q")
        assert result is not True

    def test_quit_dirty_confirmed(self):
        from gridcalc.tui import cmdexec

        self.g.dirty = 1
        self.stdscr.queue_getch(ord("y"))
        result = cmdexec(self.stdscr, self.g, self.undo, "q")
        assert result is True

    def test_blank_clears_cell(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "42")
        self.g.cc = 0
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "b")
        assert self.g.cell(0, 0) is None

    def test_blank_alias(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "42")
        self.g.cc = 0
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "blank")
        assert self.g.cell(0, 0) is None

    def test_width_valid(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "width 12")
        assert self.g.cw == 12

    def test_width_out_of_range(self):
        from gridcalc.tui import cmdexec

        old_cw = self.g.cw
        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "width 2")
        assert self.g.cw == old_cw

    def test_delete_row(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.setcell(0, 2, "30")
        self.g.cr = 1
        cmdexec(self.stdscr, self.g, self.undo, "dr")
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[0][1].val == 30.0

    def test_delete_row_alias(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "delrow")
        assert self.g.cells[0][0].val == 20.0

    def test_insert_row(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.cr = 1
        cmdexec(self.stdscr, self.g, self.undo, "ir")
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cell(0, 1) is None
        assert self.g.cells[0][2].val == 20.0

    def test_insert_col(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        self.g.cc = 1
        cmdexec(self.stdscr, self.g, self.undo, "ic")
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cell(1, 0) is None
        assert self.g.cells[2][0].val == 20.0

    def test_delete_col(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        self.g.setcell(2, 0, "30")
        self.g.cc = 1
        cmdexec(self.stdscr, self.g, self.undo, "dc")
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[1][0].val == 30.0

    def test_unknown_command(self):
        from gridcalc.tui import cmdexec

        self.stdscr.queue_getch(27)  # dismiss error
        result = cmdexec(self.stdscr, self.g, self.undo, "nosuchcmd")
        assert result is False
        assert "Unknown command" in self.stdscr._last_addnstr

    def test_empty_command(self):
        from gridcalc.tui import cmdexec

        result = cmdexec(self.stdscr, self.g, self.undo, "")
        assert result is False

    def test_save_roundtrip(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "42")
        self.g.dirty = 1
        f = tmp_path / "test.json"
        cmdexec(self.stdscr, self.g, self.undo, f"w {f}")
        assert self.g.dirty == 0
        assert self.g.filename == str(f)
        # Verify the file is loadable
        g2 = Grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.cells[0][0].val == 42.0

    def test_savequit(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "99")
        self.g.dirty = 1
        f = tmp_path / "test.json"
        result = cmdexec(self.stdscr, self.g, self.undo, f"wq {f}")
        assert result is True
        assert self.g.dirty == 0

    def test_clear_confirmed(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        self.stdscr.queue_getch(ord("y"))
        cmdexec(self.stdscr, self.g, self.undo, "clear")
        assert self.g.cell(0, 0) is None
        assert self.g.cell(1, 0) is None

    def test_clear_denied(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.stdscr.queue_getch(ord("n"))
        cmdexec(self.stdscr, self.g, self.undo, "clear")
        assert self.g.cells[0][0].val == 10.0

    def test_format_dollar(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "100")
        self.g.cc = 0
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "f $")
        assert self.g.cell(0, 0).fmt == "$"

    def test_format_bold(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "hello")
        self.g.cc = 0
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "f b")
        assert self.g.cell(0, 0).bold == 1

    def test_format_fmtstr(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "1234")
        self.g.cc = 0
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "f ,.0f")
        assert self.g.cell(0, 0).fmtstr == ",.0f"

    def test_global_format(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "gf $")
        assert self.g.fmt == "$"

    def test_title_commands(self):
        from gridcalc.tui import cmdexec

        self.g.cc = 2
        self.g.cr = 3
        cmdexec(self.stdscr, self.g, self.undo, "tv")
        assert self.g.tc == 3
        cmdexec(self.stdscr, self.g, self.undo, "tn")
        assert self.g.tc == 0
        assert self.g.tr == 0

    def test_dr_undo(self):
        """Delete row via cmdexec is undoable."""
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.cr = 0
        cmdexec(self.stdscr, self.g, self.undo, "dr")
        assert self.g.cells[0][0].val == 20.0
        self.undo.undo(self.g)
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[0][1].val == 20.0


class TestCmdSheet:
    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_sheet_add(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Data")
        assert self.g.sheet_names() == ["Sheet1", "Data"]
        # Active stays on Sheet1 (add does not switch).
        assert self.g.active == 0

    def test_sheet_switch_by_name(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Data")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Data")
        assert self.g.active == 1

    def test_sheet_switch_by_index(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Two")
        cmdexec(self.stdscr, self.g, self.undo, "sheet add Three")
        cmdexec(self.stdscr, self.g, self.undo, "sheet 2")
        assert self.g.active == 2
        cmdexec(self.stdscr, self.g, self.undo, "sheet 0")
        assert self.g.active == 0

    def test_sheet_unknown_name_warns_but_does_not_switch(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Data")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Nope")
        # Active unchanged (still on Sheet1).
        assert self.g.active == 0

    def test_sheet_index_out_of_range_does_not_switch(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet 5")
        assert self.g.active == 0

    def test_sheet_del(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Tmp")
        cmdexec(self.stdscr, self.g, self.undo, "sheet del Tmp")
        assert self.g.sheet_names() == ["Sheet1"]

    def test_sheet_del_last_refused(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet del Sheet1")
        # Refused; last sheet remains.
        assert self.g.sheet_names() == ["Sheet1"]

    def test_sheet_rename(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet rename Sheet1 Data")
        assert self.g.sheet_names() == ["Data"]

    def test_sheet_move_reorders(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add B")
        cmdexec(self.stdscr, self.g, self.undo, "sheet add C")
        cmdexec(self.stdscr, self.g, self.undo, "sheet move Sheet1 2")
        assert self.g.sheet_names() == ["B", "C", "Sheet1"]

    def test_sheet_move_bad_index_does_not_reorder(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add B")
        cmdexec(self.stdscr, self.g, self.undo, "sheet move Sheet1 99")
        # Out-of-range index keeps order untouched.
        assert self.g.sheet_names() == ["Sheet1", "B"]

    def test_sheet_move_non_numeric_index_warns(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add B")
        cmdexec(self.stdscr, self.g, self.undo, "sheet move Sheet1 oops")
        assert self.g.sheet_names() == ["Sheet1", "B"]

    def test_sheet_rename_changes_internal_name(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Other")
        cmdexec(self.stdscr, self.g, self.undo, "sheet rename Other Renamed")
        assert self.g.sheet_names() == ["Sheet1", "Renamed"]

    def test_sheet_rename_rewrites_formula_text(self):
        # Phase 4: `:sheet rename` walks every formula and rewrites
        # `<old>!` prefixes to `<new>!`. After rename, the formula
        # still resolves to the renamed sheet's data.
        from gridcalc.engine import Mode
        from gridcalc.tui import cmdexec

        self.g.mode = Mode.EXCEL
        self.g._apply_mode_libs()
        cmdexec(self.stdscr, self.g, self.undo, "sheet add Other")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Other")
        self.g.setcell(0, 0, "42")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Sheet1")
        self.g.setcell(0, 0, "=Other!A1")
        assert self.g.cells[0][0].val == 42.0
        cmdexec(self.stdscr, self.g, self.undo, "sheet rename Other Renamed")
        # Formula text was rewritten and re-parsed.
        assert self.g.cells[0][0].text == "=Renamed!A1"
        assert self.g.cells[0][0].val == 42.0
        # Editing the source under the new name still propagates.
        cmdexec(self.stdscr, self.g, self.undo, "sheet Renamed")
        self.g.setcell(0, 0, "100")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Sheet1")
        assert self.g.cells[0][0].val == 100.0

    def test_sheets_picker_switches_to_selection(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Data")
        cmdexec(self.stdscr, self.g, self.undo, "sheet add More")
        assert self.g.active == 0
        # Move down twice from the active row, then Enter -> index 2.
        self.stdscr.queue_getch(ord("j"), ord("j"), 10)
        cmdexec(self.stdscr, self.g, self.undo, "sheets")
        assert self.g.active == 2

    def test_sheets_picker_escape_keeps_active(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "sheet add Data")
        cmdexec(self.stdscr, self.g, self.undo, "sheet Data")
        assert self.g.active == 1
        self.stdscr.queue_getch(ord("j"), 27)  # move but cancel
        cmdexec(self.stdscr, self.g, self.undo, "sheets")
        assert self.g.active == 1

    def test_sheets_picker_single_sheet_is_noop(self):
        from gridcalc.tui import cmdexec

        # One sheet: nothing to pick; reports and stays put.
        self.stdscr.queue_getch(27)  # dismiss the info message
        cmdexec(self.stdscr, self.g, self.undo, "sheets")
        assert self.g.active == 0


class TestVisualSelectFormat:
    """Test range formatting via cmdexec with sel= parameter (visual mode path)."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_format_range_dollar(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "100")
        self.g.setcell(1, 0, "200")
        self.g.setcell(0, 1, "300")
        sel = (0, 0, 1, 1)
        cmdexec(self.stdscr, self.g, self.undo, "f $", sel=sel)
        assert self.g.cell(0, 0).fmt == "$"
        assert self.g.cell(1, 0).fmt == "$"
        assert self.g.cell(0, 1).fmt == "$"

    def test_format_range_bold(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        self.g.setcell(2, 0, "30")
        sel = (0, 0, 2, 0)
        cmdexec(self.stdscr, self.g, self.undo, "f b", sel=sel)
        assert self.g.cell(0, 0).bold == 1
        assert self.g.cell(1, 0).bold == 1
        assert self.g.cell(2, 0).bold == 1

    def test_format_range_fmtstr(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "1000")
        self.g.setcell(0, 1, "2000")
        sel = (0, 0, 0, 1)
        cmdexec(self.stdscr, self.g, self.undo, "f ,.0f", sel=sel)
        assert self.g.cell(0, 0).fmtstr == ",.0f"
        assert self.g.cell(0, 1).fmtstr == ",.0f"

    def test_format_range_skips_empty(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        # (1, 0) is empty
        self.g.setcell(2, 0, "30")
        sel = (0, 0, 2, 0)
        cmdexec(self.stdscr, self.g, self.undo, "f $", sel=sel)
        assert self.g.cell(0, 0).fmt == "$"
        assert self.g.cell(1, 0) is None
        assert self.g.cell(2, 0).fmt == "$"

    def test_format_range_undo(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        sel = (0, 0, 1, 0)
        cmdexec(self.stdscr, self.g, self.undo, "f $", sel=sel)
        assert self.g.cell(0, 0).fmt == "$"
        assert self.g.cell(1, 0).fmt == "$"
        self.undo.undo(self.g)
        assert self.g.cell(0, 0).fmt == ""
        assert self.g.cell(1, 0).fmt == ""

    def test_format_range_percent(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "0.5")
        self.g.setcell(0, 1, "0.75")
        sel = (0, 0, 0, 1)
        cmdexec(self.stdscr, self.g, self.undo, "f %", sel=sel)
        assert self.g.cell(0, 0).fmt == "%"
        assert self.g.cell(0, 1).fmt == "%"

    def test_format_range_interactive(self):
        """When no format arg given, prompt interactively."""
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        sel = (0, 0, 1, 0)
        self.stdscr.queue_getch(ord("$"))
        cmdexec(self.stdscr, self.g, self.undo, "f", sel=sel)
        assert self.g.cell(0, 0).fmt == "$"
        assert self.g.cell(1, 0).fmt == "$"

    def test_format_range_combined_styles(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "hello")
        self.g.setcell(1, 0, "world")
        sel = (0, 0, 1, 0)
        cmdexec(self.stdscr, self.g, self.undo, "f bi", sel=sel)
        assert self.g.cell(0, 0).bold == 1
        assert self.g.cell(0, 0).italic == 1
        assert self.g.cell(1, 0).bold == 1
        assert self.g.cell(1, 0).italic == 1


class TestVisualSelectBlank:
    """Test blanking a range via cmdexec with sel= parameter."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_blank_range(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        self.g.setcell(0, 1, "30")
        self.g.setcell(1, 1, "40")
        sel = (0, 0, 1, 1)
        cmdexec(self.stdscr, self.g, self.undo, "b", sel=sel)
        assert self.g.cell(0, 0) is None
        assert self.g.cell(1, 0) is None
        assert self.g.cell(0, 1) is None
        assert self.g.cell(1, 1) is None

    def test_blank_range_undo(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(1, 0, "20")
        sel = (0, 0, 1, 0)
        cmdexec(self.stdscr, self.g, self.undo, "b", sel=sel)
        assert self.g.cell(0, 0) is None
        assert self.g.cell(1, 0) is None
        self.undo.undo(self.g)
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[1][0].val == 20.0

    def test_blank_range_partial(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        # (1, 0) is empty
        self.g.setcell(2, 0, "30")
        sel = (0, 0, 2, 0)
        cmdexec(self.stdscr, self.g, self.undo, "b", sel=sel)
        assert self.g.cell(0, 0) is None
        assert self.g.cell(1, 0) is None
        assert self.g.cell(2, 0) is None


class TestVisualSelectDeleteRows:
    """Test deleting rows/cols via visual selection."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_delete_selected_rows(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.setcell(0, 2, "30")
        self.g.setcell(0, 3, "40")
        # Select rows 1 and 2 (0-indexed)
        sel = (0, 1, 0, 2)
        cmdexec(self.stdscr, self.g, self.undo, "dr", sel=sel)
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[0][1].val == 40.0
        assert self.g.cell(0, 2) is None

    def test_delete_selected_cols(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "A")
        self.g.setcell(1, 0, "B")
        self.g.setcell(2, 0, "C")
        self.g.setcell(3, 0, "D")
        # Select cols 1 and 2
        sel = (1, 0, 2, 0)
        cmdexec(self.stdscr, self.g, self.undo, "dc", sel=sel)
        assert self.g.cells[0][0].text == "A"
        assert self.g.cells[1][0].text == "D"
        assert self.g.cell(2, 0) is None

    def test_delete_selected_rows_undo(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "20")
        self.g.setcell(0, 2, "30")
        sel = (0, 1, 0, 1)
        cmdexec(self.stdscr, self.g, self.undo, "dr", sel=sel)
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[0][1].val == 30.0
        self.undo.undo(self.g)
        assert self.g.cells[0][0].val == 10.0
        assert self.g.cells[0][1].val == 20.0
        assert self.g.cells[0][2].val == 30.0


class TestSearch:
    """Test search functionality."""

    def setup_method(self):
        _setup_curses_constants()
        self.g = Grid()

    def test_search_finds_label(self):
        from gridcalc.tui import _search_grid

        self.g.setcell(0, 0, "Hello")
        self.g.setcell(1, 0, "World")
        self.g.setcell(0, 1, "hello again")
        matches = _search_grid(self.g, "hello")
        assert len(matches) == 2
        assert (0, 0) in matches
        assert (0, 1) in matches

    def test_search_finds_number(self):
        from gridcalc.tui import _search_grid

        self.g.setcell(0, 0, "42")
        self.g.setcell(1, 0, "100")
        self.g.setcell(2, 0, "420")
        matches = _search_grid(self.g, "42")
        assert (0, 0) in matches
        assert (2, 0) in matches
        assert (1, 0) not in matches

    def test_search_finds_formula_value(self):
        from gridcalc.tui import _search_grid

        self.g.setcell(0, 0, "21")
        self.g.setcell(1, 0, "=A1*2")
        matches = _search_grid(self.g, "42")
        assert (1, 0) in matches

    def test_search_case_insensitive(self):
        from gridcalc.tui import _search_grid

        self.g.setcell(0, 0, "HELLO")
        self.g.setcell(1, 0, "hello")
        matches = _search_grid(self.g, "Hello")
        assert len(matches) == 2

    def test_search_no_match(self):
        from gridcalc.tui import _search_grid

        self.g.setcell(0, 0, "foo")
        matches = _search_grid(self.g, "bar")
        assert len(matches) == 0

    def test_search_next_forward(self):
        from gridcalc.tui import search_next

        self.g.setcell(0, 0, "x")
        self.g.setcell(0, 1, "x")
        self.g.setcell(0, 2, "x")
        matches = [(0, 0), (0, 1), (0, 2)]
        self.g.cc, self.g.cr = 0, 0
        search_next(self.g, matches, forward=True)
        assert self.g.cc == 0 and self.g.cr == 1

    def test_search_next_wraps(self):
        from gridcalc.tui import search_next

        self.g.setcell(0, 0, "x")
        self.g.setcell(0, 1, "x")
        matches = [(0, 0), (0, 1)]
        self.g.cc, self.g.cr = 0, 1
        search_next(self.g, matches, forward=True)
        # Should wrap to first match
        assert self.g.cc == 0 and self.g.cr == 0

    def test_search_prev(self):
        from gridcalc.tui import search_next

        self.g.setcell(0, 0, "x")
        self.g.setcell(0, 1, "x")
        self.g.setcell(0, 2, "x")
        matches = [(0, 0), (0, 1), (0, 2)]
        self.g.cc, self.g.cr = 0, 2
        search_next(self.g, matches, forward=False)
        assert self.g.cc == 0 and self.g.cr == 1

    def test_search_prev_wraps(self):
        from gridcalc.tui import search_next

        self.g.setcell(0, 0, "x")
        self.g.setcell(0, 1, "x")
        matches = [(0, 0), (0, 1)]
        self.g.cc, self.g.cr = 0, 0
        search_next(self.g, matches, forward=False)
        assert self.g.cc == 0 and self.g.cr == 1

    def test_search_empty_matches_noop(self):
        from gridcalc.tui import search_next

        self.g.cc, self.g.cr = 3, 5
        search_next(self.g, [], forward=True)
        assert self.g.cc == 3 and self.g.cr == 5


class TestCsvCommands:
    """Test CSV save/load via cmdexec."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_csv_save(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "Name")
        self.g.setcell(1, 0, "42")
        path = str(tmp_path / "out.csv")
        self.stdscr.queue_getch(27)  # dismiss success message
        cmdexec(self.stdscr, self.g, self.undo, f"csv save {path}")
        with open(path) as f:
            content = f.read()
        assert "Name" in content
        assert "42" in content

    def test_csv_load(self, tmp_path):
        from gridcalc.tui import cmdexec

        path = str(tmp_path / "in.csv")
        with open(path, "w") as f:
            f.write("Hello,100\nWorld,200\n")
        cmdexec(self.stdscr, self.g, self.undo, f"csv load {path}")
        assert self.g.cells[0][0].text == "Hello"
        assert self.g.cells[1][0].val == 100.0
        assert self.g.cells[0][1].text == "World"
        assert self.g.cells[1][1].val == 200.0

    def test_csv_load_undo(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "original")
        path = str(tmp_path / "in.csv")
        with open(path, "w") as f:
            f.write("replaced\n")
        cmdexec(self.stdscr, self.g, self.undo, f"csv load {path}")
        assert self.g.cells[0][0].text == "replaced"
        self.undo.undo(self.g)
        assert self.g.cells[0][0].text == "original"

    def test_csv_bad_subcommand(self):
        from gridcalc.tui import cmdexec

        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "csv foo")

    def test_csv_no_args(self):
        from gridcalc.tui import cmdexec

        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "csv")


class TestClipboard:
    """Test cell copy/paste via Clipboard."""

    def setup_method(self):
        _setup_curses_constants()
        self.g = Grid()
        self.undo = UndoManager()

    def test_yank_single_cell(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "42")
        cb = Clipboard()
        count = cb.yank(self.g, 0, 0, 0, 0)
        assert count == 1
        assert not cb.empty

    def test_yank_empty_cell(self):
        from gridcalc.tui import Clipboard

        cb = Clipboard()
        count = cb.yank(self.g, 0, 0, 0, 0)
        assert count == 0
        assert cb.empty

    def test_paste_single_cell(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "42")
        cb = Clipboard()
        cb.yank(self.g, 0, 0, 0, 0)
        cb.paste(self.g, self.undo, 1, 0)
        assert self.g.cells[1][0].val == 42.0

    def test_paste_preserves_style(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "42")
        self.g.cell(0, 0).bold = 1
        self.g.cell(0, 0).fmt = "$"
        cb = Clipboard()
        cb.yank(self.g, 0, 0, 0, 0)
        cb.paste(self.g, self.undo, 1, 0)
        assert self.g.cell(1, 0).bold == 1
        assert self.g.cell(1, 0).fmt == "$"

    def test_yank_range(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "A")
        self.g.setcell(1, 0, "B")
        self.g.setcell(0, 1, "C")
        self.g.setcell(1, 1, "D")
        cb = Clipboard()
        count = cb.yank(self.g, 0, 0, 1, 1)
        assert count == 4
        assert cb.width == 2
        assert cb.height == 2

    def test_paste_range(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "A")
        self.g.setcell(1, 0, "B")
        self.g.setcell(0, 1, "C")
        self.g.setcell(1, 1, "D")
        cb = Clipboard()
        cb.yank(self.g, 0, 0, 1, 1)
        cb.paste(self.g, self.undo, 3, 3)
        assert self.g.cells[3][3].text == "A"
        assert self.g.cells[4][3].text == "B"
        assert self.g.cells[3][4].text == "C"
        assert self.g.cells[4][4].text == "D"

    def test_paste_undo(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "source")
        self.g.setcell(1, 0, "existing")
        cb = Clipboard()
        cb.yank(self.g, 0, 0, 0, 0)
        cb.paste(self.g, self.undo, 1, 0)
        assert self.g.cells[1][0].text == "source"
        self.undo.undo(self.g)
        assert self.g.cells[1][0].text == "existing"

    def test_paste_formula_verbatim(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "=A2+1")
        cb = Clipboard()
        cb.yank(self.g, 0, 0, 0, 0)
        cb.paste(self.g, self.undo, 2, 0)
        # Formula should be copied verbatim (no ref adjustment)
        assert self.g.cells[2][0].text == "=A2+1"

    def test_paste_empty_clipboard_noop(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "keep")
        cb = Clipboard()
        cb.paste(self.g, self.undo, 0, 0)
        assert self.g.cells[0][0].text == "keep"


class _FakeSystemClipboard:
    """In-memory stand-in for the OS clipboard, so tests never shell out."""

    def __init__(self, initial=None):
        self.buf = initial
        self.copies = 0

    @property
    def available(self):
        return True

    def copy_text(self, text):
        self.buf = text
        self.copies += 1
        return True

    def paste_text(self):
        return self.buf


class TestTsvSerialization:
    """Pure TSV helpers used by the system-clipboard interchange path."""

    def test_rows_to_tsv_round_trip(self):
        from gridcalc.tui.osclip import rows_to_tsv, tsv_to_rows

        rows = [["a", "1"], ["b", "2"]]
        assert rows_to_tsv(rows) == "a\t1\nb\t2"
        assert tsv_to_rows(rows_to_tsv(rows)) == rows

    def test_rows_to_tsv_sanitizes_delimiters(self):
        from gridcalc.tui.osclip import rows_to_tsv

        # Embedded tabs/newlines become spaces (TSV has no quoting).
        assert rows_to_tsv([["x\ty", "a\nb"]]) == "x y\ta b"

    def test_tsv_to_rows_trailing_newline_and_empty(self):
        from gridcalc.tui.osclip import tsv_to_rows

        assert tsv_to_rows("a\t1\nb\t2\n") == [["a", "1"], ["b", "2"]]
        assert tsv_to_rows("a\t1\r\nb\t2\r\n") == [["a", "1"], ["b", "2"]]
        assert tsv_to_rows("") == []
        assert tsv_to_rows("\n") == []

    def test_cell_clip_value(self):
        from gridcalc.display import cell_clip_value

        g = Grid()
        g.setcell(0, 0, "42")
        g.setcell(1, 0, "hello")
        g.setcell(2, 0, "=A1+8")  # -> 50
        g.recalc()
        assert cell_clip_value(g.cell(0, 0)) == "42"
        assert cell_clip_value(g.cell(1, 0)) == "hello"
        assert cell_clip_value(g.cell(2, 0)) == "50"  # value, not formula text
        assert cell_clip_value(g.cell(9, 9)) == ""  # empty


class TestSystemClipboard:
    """Clipboard <-> OS interchange, driven by an in-memory fake backend."""

    def setup_method(self):
        _setup_curses_constants()
        self.g = Grid()
        self.undo = UndoManager()

    def test_yank_pushes_values_to_os(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "5")
        self.g.setcell(1, 0, "7")
        self.g.setcell(2, 0, "=A1+B1")  # 12
        self.g.recalc()
        fake = _FakeSystemClipboard()
        cb = Clipboard(fake)
        cb.yank(self.g, 0, 0, 2, 0)
        assert fake.buf == "5\t7\t12"  # display values, tab-separated

    def test_internal_copy_paste_keeps_formula(self):
        # When the OS clipboard still holds our own push, paste uses the
        # full-fidelity internal store, preserving formula text.
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "3")
        self.g.setcell(1, 0, "=A1*2")
        self.g.recalc()
        fake = _FakeSystemClipboard()
        cb = Clipboard(fake)
        cb.yank(self.g, 1, 0, 1, 0)
        cb.paste(self.g, self.undo, 1, 5)  # B6
        assert self.g.cell(1, 5).text == "=A1*2"

    def test_external_content_pastes_values(self):
        from gridcalc.tui import Clipboard

        fake = _FakeSystemClipboard("hello\t99\nfoo\t=1+1")
        cb = Clipboard(fake)
        cb.paste(self.g, self.undo, 0, 0)
        assert self.g.cell(0, 0).text == "hello"
        assert self.g.cell(1, 0).val == 99.0
        assert self.g.cell(0, 1).text == "foo"
        assert self.g.cell(1, 1).val == 2.0  # "=1+1" pasted as a live formula

    def test_external_blank_cells_do_not_clobber(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(1, 0, "keep")  # B1
        fake = _FakeSystemClipboard("x\t\ny")  # A1="x", B1="", A2="y"
        cb = Clipboard(fake)
        cb.paste(self.g, self.undo, 0, 0)
        assert self.g.cell(0, 0).text == "x"
        assert self.g.cell(1, 0).text == "keep"  # empty TSV cell left alone
        assert self.g.cell(0, 1).text == "y"

    def test_external_paste_is_undoable(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "original")
        fake = _FakeSystemClipboard("pasted")
        cb = Clipboard(fake)
        cb.paste(self.g, self.undo, 0, 0)
        assert self.g.cell(0, 0).text == "pasted"
        self.undo.undo(self.g)
        assert self.g.cell(0, 0).text == "original"

    def test_no_system_backend_is_internal_only(self):
        from gridcalc.tui import Clipboard

        self.g.setcell(0, 0, "=1+1")
        self.g.recalc()
        cb = Clipboard()  # no backend -> never touches the OS
        cb.yank(self.g, 0, 0, 0, 0)
        cb.paste(self.g, self.undo, 1, 0)
        assert self.g.cell(1, 0).text == "=1+1"

    def test_unavailable_backend_degrades(self):
        # A real SystemClipboard with no tool present: available is False
        # and reads/writes no-op rather than raising.
        from gridcalc.tui.osclip import SystemClipboard

        sc = SystemClipboard()
        sc._cmds = None  # simulate "no clipboard tool on PATH"
        assert sc.available is False
        assert sc.copy_text("x") is False
        assert sc.paste_text() is None


class TestSort:
    """Test sort command."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_sort_by_column(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "Charlie")
        self.g.setcell(1, 0, "30")
        self.g.setcell(0, 1, "Alice")
        self.g.setcell(1, 1, "10")
        self.g.setcell(0, 2, "Bob")
        self.g.setcell(1, 2, "20")
        cmdexec(self.stdscr, self.g, self.undo, "sort B")
        # Sorted by column B numerically: 10, 20, 30
        assert self.g.cells[1][0].val == 10.0
        assert self.g.cells[0][0].text == "Alice"
        assert self.g.cells[1][1].val == 20.0
        assert self.g.cells[0][1].text == "Bob"
        assert self.g.cells[1][2].val == 30.0
        assert self.g.cells[0][2].text == "Charlie"

    def test_sort_descending(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.g.setcell(0, 1, "30")
        self.g.setcell(0, 2, "20")
        cmdexec(self.stdscr, self.g, self.undo, "sort A desc")
        assert self.g.cells[0][0].val == 30.0
        assert self.g.cells[0][1].val == 20.0
        assert self.g.cells[0][2].val == 10.0

    def test_sort_labels_alphabetically(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "Cherry")
        self.g.setcell(0, 1, "Apple")
        self.g.setcell(0, 2, "Banana")
        cmdexec(self.stdscr, self.g, self.undo, "sort A")
        assert self.g.cells[0][0].text == "Apple"
        assert self.g.cells[0][1].text == "Banana"
        assert self.g.cells[0][2].text == "Cherry"

    def test_sort_numbers_before_labels(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "Zebra")
        self.g.setcell(0, 1, "5")
        self.g.setcell(0, 2, "Apple")
        self.g.setcell(0, 3, "1")
        cmdexec(self.stdscr, self.g, self.undo, "sort A")
        # Numbers first (sorted), then labels (sorted)
        assert self.g.cells[0][0].val == 1.0
        assert self.g.cells[0][1].val == 5.0
        assert self.g.cells[0][2].text == "Apple"
        assert self.g.cells[0][3].text == "Zebra"

    def test_sort_with_visual_selection(self):
        from gridcalc.tui import cmdexec

        # Header row (should not be sorted)
        self.g.setcell(0, 0, "Name")
        self.g.setcell(1, 0, "Score")
        # Data rows
        self.g.setcell(0, 1, "Charlie")
        self.g.setcell(1, 1, "30")
        self.g.setcell(0, 2, "Alice")
        self.g.setcell(1, 2, "10")
        self.g.setcell(0, 3, "Bob")
        self.g.setcell(1, 3, "20")
        # Sort only data rows (1-3) by leftmost col
        sel = (0, 1, 1, 3)
        cmdexec(self.stdscr, self.g, self.undo, "sort", sel=sel)
        # Header unchanged
        assert self.g.cells[0][0].text == "Name"
        # Data sorted alphabetically by column A (leftmost in sel)
        assert self.g.cells[0][1].text == "Alice"
        assert self.g.cells[0][2].text == "Bob"
        assert self.g.cells[0][3].text == "Charlie"

    def test_sort_undo(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "30")
        self.g.setcell(0, 1, "10")
        self.g.setcell(0, 2, "20")
        cmdexec(self.stdscr, self.g, self.undo, "sort A")
        assert self.g.cells[0][0].val == 10.0
        self.undo.undo(self.g)
        assert self.g.cells[0][0].val == 30.0
        assert self.g.cells[0][1].val == 10.0
        assert self.g.cells[0][2].val == 20.0

    def test_sort_invalid_column(self):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "10")
        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "sort ???")


class TestSearchIndicator:
    """Test search indicator string."""

    def setup_method(self):
        self.g = Grid()

    def test_indicator_on_match(self):
        from gridcalc.tui import search_indicator

        matches = [(0, 0), (1, 0), (2, 0)]
        self.g.cc, self.g.cr = 1, 0
        assert search_indicator(self.g, matches) == "[2/3]"

    def test_indicator_first_match(self):
        from gridcalc.tui import search_indicator

        matches = [(0, 0), (1, 0)]
        self.g.cc, self.g.cr = 0, 0
        assert search_indicator(self.g, matches) == "[1/2]"

    def test_indicator_not_on_match(self):
        from gridcalc.tui import search_indicator

        matches = [(0, 0), (2, 0)]
        self.g.cc, self.g.cr = 1, 0
        assert search_indicator(self.g, matches) == "[?/2]"

    def test_indicator_no_matches(self):
        from gridcalc.tui import search_indicator

        assert search_indicator(self.g, []) == ""


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
class TestPdCommands:
    """Test pandas load/save via cmdexec."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()

    def test_pd_load(self, tmp_path):
        from gridcalc.tui import cmdexec

        path = str(tmp_path / "data.csv")
        with open(path, "w") as f:
            f.write("Name,Score\nAlice,95\nBob,87\n")
        cmdexec(self.stdscr, self.g, self.undo, f"pd load {path}")
        assert self.g.cells[0][0].text == "Name"
        assert self.g.cells[1][0].text == "Score"
        assert self.g.cells[0][1].text == "Alice"
        assert self.g.cells[1][1].val == 95.0

    def test_pd_save(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "X")
        self.g.setcell(1, 0, "Y")
        self.g.setcell(0, 1, "1")
        self.g.setcell(1, 1, "2")
        path = str(tmp_path / "out.csv")
        self.stdscr.queue_getch(27)  # dismiss success message
        cmdexec(self.stdscr, self.g, self.undo, f"pd save {path}")
        with open(path) as f:
            content = f.read()
        assert "X" in content
        assert "Y" in content

    def test_pd_load_undo(self, tmp_path):
        from gridcalc.tui import cmdexec

        self.g.setcell(0, 0, "original")
        path = str(tmp_path / "data.csv")
        with open(path, "w") as f:
            f.write("replaced\n")
        cmdexec(self.stdscr, self.g, self.undo, f"pd load {path}")
        assert self.g.cells[0][0].text == "replaced"
        self.undo.undo(self.g)
        assert self.g.cells[0][0].text == "original"

    def test_pd_no_args(self):
        from gridcalc.tui import cmdexec

        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "pd")

    def test_pd_bad_subcommand(self):
        from gridcalc.tui import cmdexec

        self.stdscr.queue_getch(27)  # dismiss error
        cmdexec(self.stdscr, self.g, self.undo, "pd foo")


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
class TestDataFrameDisplay:
    """Test DataFrame cell display formatting."""

    def setup_method(self):
        _setup_curses_constants()
        self.g = Grid()
        self.g.load_requires(["pandas"])

    def test_fmtcell_dataframe(self):
        from gridcalc.tui import fmtcell

        self.g.setcell(0, 0, "=pd.DataFrame({'a': [1,2], 'b': [3,4]})")
        cl = self.g.cell(0, 0)
        result = fmtcell(cl, 10)
        assert "df[2x2]" in result

    def test_fmtcell_dataframe_wide(self):
        from gridcalc.tui import fmtcell

        cols = {f"c{i}": [i] for i in range(10)}
        self.g.setcell(0, 0, f"=pd.DataFrame({cols})")
        cl = self.g.cell(0, 0)
        result = fmtcell(cl, 14)
        assert "df[1x10]" in result


class TestFmtVal:
    def test_integer(self):
        from gridcalc.tui import _fmt_val

        assert _fmt_val("3.0") == "3"
        assert _fmt_val("42") == "42"

    def test_float(self):
        from gridcalc.tui import _fmt_val

        assert _fmt_val("3.14") == "3.14"

    def test_string(self):
        from gridcalc.tui import _fmt_val

        assert _fmt_val("hello") == "'hello'"


class TestBuildFormula:
    def test_vec(self):
        from gridcalc.tui import _build_formula

        data = [["1"], ["2"], ["3"]]
        result = _build_formula("vec", data, None)
        assert result == "=Vec([1, 2, 3])"

    def test_ndarray_1d(self):
        from gridcalc.tui import _build_formula

        data = [["1.5"], ["2.0"], ["3.0"]]
        result = _build_formula("ndarray", data, None)
        assert result == "=np.array([1.5, 2, 3])"

    def test_ndarray_2d(self):
        from gridcalc.tui import _build_formula

        data = [["1", "2"], ["3", "4"]]
        result = _build_formula("ndarray", data, None)
        assert result == "=np.array([[1, 2], [3, 4]])"

    def test_dataframe(self):
        from gridcalc.tui import _build_formula

        data = [["1", "3"], ["2", "4"]]
        headers = ["a", "b"]
        result = _build_formula("dataframe", data, headers)
        assert result == "=pd.DataFrame({'a': [1, 2], 'b': [3, 4]})"

    def test_vec_roundtrip(self):
        """Build formula, set it on grid, verify result matches."""
        from gridcalc.tui import _build_formula

        data = [["10"], ["20"], ["30"]]
        formula = _build_formula("vec", data, None)
        g = Grid()
        g.setcell(0, 0, formula)
        cl = g.cell(0, 0)
        assert cl.arr == [10.0, 20.0, 30.0]

    @pytest.mark.skipif(not _HAS_NUMPY, reason="numpy not installed")
    def test_ndarray_2d_roundtrip(self):
        from gridcalc.tui import _build_formula

        data = [["1", "2"], ["3", "4"]]
        formula = _build_formula("ndarray", data, None)
        g = Grid()
        g.load_requires(["numpy"])
        g.setcell(0, 0, formula)
        cl = g.cell(0, 0)
        assert cl.matrix is not None
        assert cl.matrix.tolist() == [[1, 2], [3, 4]]

    @pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
    def test_dataframe_roundtrip(self):
        from gridcalc.tui import _build_formula

        data = [["1", "3"], ["2", "4"]]
        headers = ["a", "b"]
        formula = _build_formula("dataframe", data, headers)
        g = Grid()
        g.load_requires(["pandas"])
        g.setcell(0, 0, formula)
        cl = g.cell(0, 0)
        assert cl.matrix is not None
        assert list(cl.matrix.columns) == ["a", "b"]
        assert cl.matrix["a"].tolist() == [1, 2]
        assert cl.matrix["b"].tolist() == [3, 4]


class TestDispatchGridKey:
    """Unit tests for the grid-context keymap dispatcher.

    Exercises the dispatcher in isolation -- no curses, no
    ``mainloop``. Builds a resolved keymap from a synthetic
    ``Config.keys`` and verifies that a hit fires the action and
    short-circuits the chain.
    """

    def _resolve(self, user_keys):
        from gridcalc.keys import build_resolved_keymap

        resolved, _warnings = build_resolved_keymap(user_keys)
        return resolved.get("grid", {})

    def _parse(self, spec):
        from gridcalc.keys import parse_keyspec

        pk, err = parse_keyspec(spec)
        assert err is None, err
        return pk

    def test_unbound_key_falls_through(self):
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        # Empty resolved map -- nothing is bound.
        assert _dispatch_grid_key(g, {}, ord("Z"), 0, 0) is False

    def test_next_sheet_via_tab(self):
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        g.add_sheet("Sheet2")
        resolved_grid = self._resolve({"grid": {"next_sheet": [self._parse("Tab")]}})
        assert _dispatch_grid_key(g, resolved_grid, 9, 0, 0) is True
        assert g.active == 1

    def test_prev_sheet_via_shift_tab(self):
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        g.add_sheet("Sheet2")
        resolved_grid = self._resolve({"grid": {"prev_sheet": [self._parse("S-Tab")]}})
        assert _dispatch_grid_key(g, resolved_grid, curses.KEY_BTAB, 0, 0) is True
        # Wraps from Sheet1 -> Sheet2.
        assert g.active == 1

    def test_cursor_right_respects_clamp(self):
        from gridcalc.engine import NCOL
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        g.cc = NCOL - 1
        resolved_grid = self._resolve({"grid": {"cursor_right": [self._parse("l")]}})
        assert _dispatch_grid_key(g, resolved_grid, ord("l"), 0, 0) is True
        # Already at the rightmost column -- stays put.
        assert g.cc == NCOL - 1

    def test_cursor_right_advances(self):
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        g.cc = 3
        resolved_grid = self._resolve({"grid": {"cursor_right": [self._parse("l")]}})
        assert _dispatch_grid_key(g, resolved_grid, ord("l"), 0, 0) is True
        assert g.cc == 4

    def test_cursor_left_respects_locked_column(self):
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        g.cc = 5
        resolved_grid = self._resolve({"grid": {"cursor_left": [self._parse("h")]}})
        # Locked column is 5 -- cursor cannot move left of it.
        assert _dispatch_grid_key(g, resolved_grid, ord("h"), 5, 0) is True
        assert g.cc == 5

    def test_unknown_action_falls_through(self):
        """An action name in the resolved map that has no callable in
        ``_GRID_ACTIONS`` should not crash; the dispatcher returns
        False so the hardcoded fallback chain handles the key."""
        from gridcalc.tui import _dispatch_grid_key

        g = Grid()
        resolved_grid = {ord("x"): "warp_drive"}
        assert _dispatch_grid_key(g, resolved_grid, ord("x"), 0, 0) is False


class TestBuildResolvedKeymap:
    def test_empty_user_keys(self):
        from gridcalc.keys import build_resolved_keymap

        resolved, warnings = build_resolved_keymap({})
        assert warnings == []
        assert resolved["grid"] == {}

    def test_resolves_named_keys(self):
        from gridcalc.keys import build_resolved_keymap, parse_keyspec

        pk_tab, _ = parse_keyspec("Tab")
        pk_btab, _ = parse_keyspec("S-Tab")
        resolved, warnings = build_resolved_keymap(
            {"grid": {"next_sheet": [pk_tab], "prev_sheet": [pk_btab]}}
        )
        assert warnings == []
        assert resolved["grid"][9] == "next_sheet"
        assert resolved["grid"][curses.KEY_BTAB] == "prev_sheet"

    def test_conflict_within_context_warns(self):
        from gridcalc.keys import build_resolved_keymap, parse_keyspec

        pk_tab, _ = parse_keyspec("Tab")
        # Same key bound to two actions in the same context.
        resolved, warnings = build_resolved_keymap(
            {"grid": {"next_sheet": [pk_tab], "cursor_right": [pk_tab]}}
        )
        assert len(warnings) == 1
        assert "Tab" in warnings[0]
        # Latest binding wins; which one depends on dict iteration
        # order, but exactly one action survives at keycode 9.
        assert resolved["grid"][9] in ("next_sheet", "cursor_right")


class TestActionFor:
    """Per-context lookup with the text-input self-insert override."""

    def setup_method(self):
        # Snapshot and clear the module-level resolved keymap so
        # individual tests can install their own without polluting
        # neighbours.
        from gridcalc import tui

        self._saved = tui._resolved_keymap
        tui._resolved_keymap = {}

    def teardown_method(self):
        from gridcalc import tui

        tui._resolved_keymap = self._saved

    def test_grid_dispatches_printable(self):
        from gridcalc import tui

        tui._resolved_keymap = {"grid": {ord("h"): "cursor_left"}}
        assert tui._action_for("grid", ord("h")) == "cursor_left"

    def test_visual_dispatches_printable(self):
        from gridcalc import tui

        tui._resolved_keymap = {"visual": {ord("h"): "cursor_left"}}
        assert tui._action_for("visual", ord("h")) == "cursor_left"

    def test_entry_self_inserts_printable(self):
        """The whole point of option A: a stray
        ``[keys.entry] cancel = ["a"]`` must NOT lock the user out of
        typing ``a`` into the cell buffer."""
        from gridcalc import tui

        tui._resolved_keymap = {"entry": {ord("a"): "cancel"}}
        assert tui._action_for("entry", ord("a")) is None

    def test_entry_dispatches_non_printable(self):
        from gridcalc import tui

        tui._resolved_keymap = {"entry": {curses.KEY_F0 + 5: "cancel"}}
        assert tui._action_for("entry", curses.KEY_F0 + 5) == "cancel"

    def test_cmdline_self_inserts_printable(self):
        from gridcalc import tui

        tui._resolved_keymap = {"cmdline": {ord(":"): "cancel"}}
        assert tui._action_for("cmdline", ord(":")) is None

    def test_search_self_inserts_printable(self):
        from gridcalc import tui

        tui._resolved_keymap = {"search": {ord("/"): "cancel"}}
        assert tui._action_for("search", ord("/")) is None

    def test_text_input_dispatches_esc(self):
        # Esc (27) is non-printable, so it dispatches even in entry.
        from gridcalc import tui

        tui._resolved_keymap = {"entry": {27: "cancel"}}
        assert tui._action_for("entry", 27) == "cancel"

    def test_text_input_dispatches_ctrl_letter(self):
        # C-x = 0x18, non-printable -- dispatches in text-input contexts.
        from gridcalc import tui

        tui._resolved_keymap = {"entry": {0x18: "cancel"}}
        assert tui._action_for("entry", 0x18) == "cancel"

    def test_unbound_returns_none(self):
        from gridcalc import tui

        tui._resolved_keymap = {"grid": {}}
        assert tui._action_for("grid", ord("Z")) is None

    def test_unknown_context_returns_none(self):
        from gridcalc import tui

        assert tui._action_for("nonexistent", ord("a")) is None

    def test_printable_boundary(self):
        """``32 <= ch < 127`` is the self-insert range. ``31`` and
        ``127`` are outside, ``32`` and ``126`` are inside."""
        from gridcalc import tui

        tui._resolved_keymap = {"entry": {31: "cancel", 32: "cancel", 126: "cancel", 127: "cancel"}}
        assert tui._action_for("entry", 31) == "cancel"
        assert tui._action_for("entry", 32) is None
        assert tui._action_for("entry", 126) is None
        assert tui._action_for("entry", 127) == "cancel"


# -- :opt command -----------------------------------------------------------


class TestParseOptHelpers:
    def test_parse_cells_range(self):
        from gridcalc.tui import _parse_cells

        assert _parse_cells("A1:B2") == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_parse_cells_list(self):
        from gridcalc.tui import _parse_cells

        assert _parse_cells("A1, A3, B5") == [(0, 0), (0, 2), (1, 4)]

    def test_parse_cells_mixed(self):
        from gridcalc.tui import _parse_cells

        assert _parse_cells("A1:A2, C5") == [(0, 0), (0, 1), (2, 4)]

    def test_parse_cells_rejects_garbage(self):
        from gridcalc.tui import _parse_cells

        with pytest.raises(ValueError):
            _parse_cells("not_a_ref")

    def test_parse_bounds_basic(self):
        import math

        from gridcalc.tui import _parse_bounds

        b = _parse_bounds("A1=-inf:10, B2=0:inf")
        assert b[(0, 0)] == (-math.inf, 10.0)
        assert b[(1, 1)] == (0.0, math.inf)

    def test_parse_bounds_rejects_missing_eq(self):
        from gridcalc.tui import _parse_bounds

        with pytest.raises(ValueError, match="="):
            _parse_bounds("A1:0:10")


class TestCmdOpt:
    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # Build the textbook 2-var LP as a sheet.
        self.g.setcell(0, 0, "0")  # A1 (decision)
        self.g.setcell(0, 1, "0")  # A2 (decision)
        self.g.setcell(2, 0, "=3*A1+5*A2")  # C1 (objective)
        self.g.setcell(3, 0, "=A1<=4")  # D1
        self.g.setcell(3, 1, "=2*A2<=12")  # D2
        self.g.setcell(3, 2, "=3*A1+2*A2<=18")  # D3

    def test_opt_max_textbook_dispatches_via_cmdexec(self):
        from gridcalc.tui import cmdexec

        ret = cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1:D3")
        assert ret is False
        assert self.g.cells[0][0].val == pytest.approx(2.0)
        assert self.g.cells[0][1].val == pytest.approx(6.0)
        assert self.g.cells[2][0].val == pytest.approx(36.0)
        assert "OPTIMAL" in self.stdscr._last_addnstr
        assert "36" in self.stdscr._last_addnstr
        # Successful run leaves an undo entry the user can roll back.
        assert len(self.undo.undo_stack) == 1

    def test_opt_undo_restores_decision_cells(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1:D3")
        # Roll back: A1, A2 should return to 0.
        self.undo._apply(self.g, self.undo.undo_stack, self.undo.redo_stack)
        self.g.recalc()
        assert self.g.cells[0][0].val == 0.0
        assert self.g.cells[0][1].val == 0.0

    def test_opt_infeasible_does_not_mutate_or_leave_undo(self):
        from gridcalc.tui import cmdexec

        # Add a contradiction
        self.g.setcell(3, 3, "=A1>=100")
        ret = cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1:D4")
        assert ret is False
        assert self.g.cells[0][0].val == 0.0
        assert self.g.cells[0][1].val == 0.0
        assert "INFEASIBLE" in self.stdscr._last_addnstr
        # No undo entry should remain since nothing was mutated.
        assert len(self.undo.undo_stack) == 0

    def test_opt_bad_args_shows_usage_and_no_undo(self):
        from gridcalc.tui import cmdexec

        ret = cmdexec(self.stdscr, self.g, self.undo, "opt max C1")
        assert ret is False
        assert "usage" in self.stdscr._last_addnstr.lower()
        assert len(self.undo.undo_stack) == 0

    def test_opt_min_with_bounds(self):
        from gridcalc.tui import cmdexec

        # Force A2 to be at most 5; rest unchanged. Min of -3*A1-5*A2
        # without bounds would be unbounded; the bound makes it well-posed.
        self.g.setcell(2, 0, "=-3*A1-5*A2")
        ret = cmdexec(
            self.stdscr, self.g, self.undo, "opt min C1 vars A1:A2 st D1:D3 bounds A2=0:5"
        )
        assert ret is False
        assert "OPTIMAL" in self.stdscr._last_addnstr
        assert self.g.cells[0][1].val == pytest.approx(5.0)


# -- cmdline() keypress simulation -----------------------------------------


class TestCmdlineKeypath:
    """Drive the colon-prompt input loop one keystroke at a time.

    These tests are the only place that exercise the full ``:cmd``
    pipeline: the cmdline buffer accumulation, backspace handling, ENTER
    dispatch, and ESC cancellation. ``cmdexec`` tests above bypass the
    keypress loop entirely.
    """

    @pytest.fixture(autouse=True)
    def stub_draw(self, monkeypatch):
        # cmdline() calls draw() which expects a real curses window;
        # we don't care about rendering for these tests, only the
        # buffer-and-dispatch behavior.
        from gridcalc import tui

        monkeypatch.setattr(tui, "draw", lambda *a, **kw: None)
        monkeypatch.setattr(tui, "_resolved_keymap", {})

    def _load_lp(self):
        _setup_curses_constants()
        g = Grid()
        lp = EXAMPLES / "example_lp.json"
        assert lp.is_file(), f"missing example fixture: {lp}"
        g.jsonload(str(lp))
        g.recalc()
        return g

    def test_full_command_via_keypresses_finds_optimum(self):
        from gridcalc.tui import cmdline

        stdscr = MockStdscr()
        g = self._load_lp()
        undo = UndoManager()
        keys = [ord(c) for c in "opt max B4 vars A4:A5 st D4:D6"] + [10]
        stdscr.queue_getch(*keys)
        ret = cmdline(stdscr, g, undo)
        assert ret is False
        assert g.cells[0][3].val == pytest.approx(2.0)
        assert g.cells[0][4].val == pytest.approx(6.0)
        assert g.cells[1][3].val == pytest.approx(36.0)
        assert "OPTIMAL" in stdscr._last_addnstr
        assert len(undo.undo_stack) == 1

    def test_backspace_correction_then_dispatch(self):
        from gridcalc.tui import cmdline

        stdscr = MockStdscr()
        g = self._load_lp()
        undo = UndoManager()
        # Type "vrs" (typo), backspace 3 chars, type "vars ..." correctly.
        keys = [ord(c) for c in "opt max B4 vrs"]
        keys += [127, 127, 127]
        keys += [ord(c) for c in "vars A4:A5 st D4:D6"]
        keys += [10]
        stdscr.queue_getch(*keys)
        cmdline(stdscr, g, undo)
        assert g.cells[0][3].val == pytest.approx(2.0)
        assert g.cells[1][3].val == pytest.approx(36.0)

    def test_esc_cancels_without_dispatch(self):
        from gridcalc.tui import cmdline

        stdscr = MockStdscr()
        g = self._load_lp()
        undo = UndoManager()
        keys = [ord(c) for c in "opt max B4 vars A4:A5 st D4:D6"] + [27]
        stdscr.queue_getch(*keys)
        ret = cmdline(stdscr, g, undo)
        assert ret is False
        # No mutation, no undo entry.
        assert g.cells[0][3].val == 0.0
        assert g.cells[0][4].val == 0.0
        assert len(undo.undo_stack) == 0

    def test_enter_on_empty_buffer_is_noop(self):
        from gridcalc.tui import cmdline

        stdscr = MockStdscr()
        g = self._load_lp()
        undo = UndoManager()
        stdscr.queue_getch(10)
        ret = cmdline(stdscr, g, undo)
        assert ret is False
        assert g.cells[0][3].val == 0.0
        assert len(undo.undo_stack) == 0


class TestCmdOptDispatcher:
    """Tests for the subcommand dispatch added in the persistent-model rework.

    The inline form ``:opt max ...`` (covered by TestCmdOpt above) still
    works and additionally writes the model to ``g.models["default"]`` so
    bare ``:opt`` can re-run it.
    """

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        self.g.setcell(0, 0, "0")
        self.g.setcell(0, 1, "0")
        self.g.setcell(2, 0, "=3*A1+5*A2")
        self.g.setcell(3, 0, "=A1<=4")
        self.g.setcell(3, 1, "=2*A2<=12")
        self.g.setcell(3, 2, "=3*A1+2*A2<=18")

    def test_inline_form_captures_default_model(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1:D3")
        # Both: solve worked AND model was captured.
        assert self.g.cells[0][0].val == pytest.approx(2.0)
        assert "default" in self.g.models
        m = self.g.models["default"]
        assert m.sense == "max"
        assert m.objective == "C1"
        assert m.vars == "A1:A2"
        assert m.constraints == "D1:D3"

    def test_bare_opt_reruns_default_model(self):
        from gridcalc.tui import cmdexec

        # First, capture a default model via the inline form.
        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1:D3")
        # Undo to reset cells to 0 (the model itself stays in g.models).
        self.undo._apply(self.g, self.undo.undo_stack, self.undo.redo_stack)
        self.g.recalc()
        assert self.g.cells[0][0].val == 0.0
        # Bare :opt should re-run the default and reach the optimum again.
        cmdexec(self.stdscr, self.g, self.undo, "opt")
        assert self.g.cells[0][0].val == pytest.approx(2.0)
        assert self.g.cells[0][1].val == pytest.approx(6.0)

    def test_bare_opt_with_no_default_shows_error(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt")
        assert "no 'default' model" in self.stdscr._last_addnstr
        assert self.g.cells[0][0].val == 0.0

    def test_def_saves_without_executing(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def textbook max C1 vars A1:A2 st D1:D3")
        assert "defined model 'textbook'" in self.stdscr._last_addnstr
        # Crucially: no mutation of the decision cells.
        assert self.g.cells[0][0].val == 0.0
        assert self.g.cells[0][1].val == 0.0
        # No undo entry was created (nothing to roll back).
        assert len(self.undo.undo_stack) == 0
        # But the model is in the workbook.
        assert "textbook" in self.g.models

    def test_run_executes_named_model(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def textbook max C1 vars A1:A2 st D1:D3")
        cmdexec(self.stdscr, self.g, self.undo, "opt run textbook")
        assert self.g.cells[0][0].val == pytest.approx(2.0)
        assert self.g.cells[0][1].val == pytest.approx(6.0)
        assert "OPTIMAL" in self.stdscr._last_addnstr

    def test_run_with_no_args_uses_default(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def default max C1 vars A1:A2 st D1:D3")
        cmdexec(self.stdscr, self.g, self.undo, "opt run")
        assert self.g.cells[0][0].val == pytest.approx(2.0)

    def test_run_missing_model_shows_error(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt run nonexistent")
        assert "no model named 'nonexistent'" in self.stdscr._last_addnstr

    def test_list_shows_model_names(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def alpha max C1 vars A1:A2 st D1:D3")
        cmdexec(self.stdscr, self.g, self.undo, "opt def beta min C1 vars A1:A2 st D1:D3")
        cmdexec(self.stdscr, self.g, self.undo, "opt list")
        assert "alpha" in self.stdscr._last_addnstr
        assert "beta" in self.stdscr._last_addnstr

    def test_list_empty_shows_error(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt list")
        assert "no models defined" in self.stdscr._last_addnstr

    def test_undef_removes_model(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def temp max C1 vars A1:A2 st D1:D3")
        assert "temp" in self.g.models
        cmdexec(self.stdscr, self.g, self.undo, "opt undef temp")
        assert "temp" not in self.g.models
        assert "removed model 'temp'" in self.stdscr._last_addnstr

    def test_undef_missing_model_shows_error(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt undef nope")
        assert "no model named 'nope'" in self.stdscr._last_addnstr


class TestCmdOptMIP:
    """End-to-end tests of the int / bin clauses through the colon dispatcher."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # 2-var problem with a fractional continuous optimum.
        self.g.setcell(0, 0, "0")
        self.g.setcell(0, 1, "0")
        self.g.setcell(2, 0, "=A1+A2")
        self.g.setcell(3, 0, "=A1+A2<=5.5")

    def test_inline_int_clause_produces_integer_solution(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1 int A1:A2")
        assert "OPTIMAL" in self.stdscr._last_addnstr
        # Integer optimum is 5, not the continuous 5.5.
        assert self.g.cells[2][0].val == pytest.approx(5.0)
        for v in (self.g.cells[0][0].val, self.g.cells[0][1].val):
            assert v == pytest.approx(round(v))
        # Model captured with the integers clause for re-runs.
        m = self.g.models["default"]
        assert m.integers == "A1:A2"
        assert m.binaries == ""

    def test_inline_bin_clause_produces_binary_solution(self):
        from gridcalc.tui import cmdexec

        # max A1 + 2*A2  s.t. A1+A2<=1, both binary -> A1=0, A2=1, obj=2
        self.g.setcell(2, 0, "=A1+2*A2")
        self.g.setcell(3, 0, "=A1+A2<=1")
        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1 bin A1:A2")
        assert "OPTIMAL" in self.stdscr._last_addnstr
        assert self.g.cells[0][0].val == pytest.approx(0.0)
        assert self.g.cells[0][1].val == pytest.approx(1.0)
        assert self.g.cells[2][0].val == pytest.approx(2.0)
        assert self.g.models["default"].binaries == "A1:A2"

    def test_inline_clauses_in_arbitrary_order(self):
        """bounds / int / bin can appear in any order after st."""
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1 int A1 bounds A2=0:2")
        m = self.g.models["default"]
        assert m.integers == "A1"
        assert m.bounds == "A2=0:2"

    def test_inline_rejects_duplicate_clause(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt max C1 vars A1:A2 st D1 int A1 int A2")
        assert "'int'" in self.stdscr._last_addnstr
        assert "more than once" in self.stdscr._last_addnstr
        # No mutation, no undo entry, and no model captured.
        assert "default" not in self.g.models
        assert len(self.undo.undo_stack) == 0

    def test_saved_mip_model_roundtrips_through_jsonsave(self, tmp_path):
        """Define a MIP via the dispatcher, save the workbook, reload, and
        re-run the saved model from disk."""
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "opt def mip max C1 vars A1:A2 st D1 int A1:A2")
        assert "mip" in self.g.models
        path = tmp_path / "mip.json"
        assert self.g.jsonsave(str(path)) == 0

        # Fresh grid, reload, re-run.
        g2 = Grid()
        assert g2.jsonload(str(path)) == 0
        g2.recalc()
        assert "mip" in g2.models
        assert g2.models["mip"].integers == "A1:A2"

        stdscr2 = MockStdscr()
        undo2 = UndoManager()
        cmdexec(stdscr2, g2, undo2, "opt run mip")
        assert "OPTIMAL" in stdscr2._last_addnstr
        # Integer optimum, not continuous.
        assert g2.cells[2][0].val == pytest.approx(5.0)


class TestCmdGoal:
    """Dispatcher tests for the :goal command."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # f(A1) = 2*A1 + 3; target 11 -> A1 should become 4.
        self.g.setcell(0, 0, "0")
        self.g.setcell(1, 0, "=2*A1+3")

    def test_goal_linear_via_dispatcher(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "goal B1 = 11 by A1")
        assert self.g.cells[0][0].val == pytest.approx(4.0)
        assert self.g.cells[1][0].val == pytest.approx(11.0)
        assert "converged" in self.stdscr._last_addnstr
        # Snapshot present so 'u' can roll back.
        assert len(self.undo.undo_stack) == 1

    def test_goal_explicit_bracket(self):
        from gridcalc.tui import cmdexec

        # Quadratic with two roots; bracket picks the negative one.
        self.g.setcell(1, 0, "=A1*A1")
        cmdexec(self.stdscr, self.g, self.undo, "goal B1 = 16 by A1 in -10:-0.1")
        assert self.g.cells[0][0].val == pytest.approx(-4.0)

    def test_goal_undo_restores_cells(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "goal B1 = 11 by A1")
        self.undo._apply(self.g, self.undo.undo_stack, self.undo.redo_stack)
        self.g.recalc()
        assert self.g.cells[0][0].val == 0.0
        assert self.g.cells[1][0].val == pytest.approx(3.0)

    def test_goal_bad_syntax_shows_usage(self):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "goal B1 11 A1")  # missing = and by
        assert "usage" in self.stdscr._last_addnstr.lower()
        # No mutation, no undo entry.
        assert self.g.cells[0][0].val == 0.0
        assert len(self.undo.undo_stack) == 0

    def test_goal_unreachable_target_does_not_mutate(self):
        """Var doesn't influence target -> error path -> no mutation, no
        spurious undo entry."""
        from gridcalc.tui import cmdexec

        self.g.setcell(2, 0, "1")
        self.g.setcell(1, 0, "=C1*2")  # B1 doesn't depend on A1
        cmdexec(self.stdscr, self.g, self.undo, "goal B1 = 99 by A1")
        assert self.g.cells[0][0].val == 0.0
        assert len(self.undo.undo_stack) == 0
        assert "goal:" in self.stdscr._last_addnstr

    def test_goal_rejects_trailing_garbage(self):
        """Tokens after the var cell that aren't `in ...` are a typo, not
        silently ignored."""
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, "goal B1 = 11 by A1 oops")
        assert "usage" in self.stdscr._last_addnstr.lower()


class _RecordingStdscr(MockStdscr):
    """Like MockStdscr but records every addnstr call (y, x, text, n)."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[int, int, str, int]] = []

    def addnstr(self, y, x, s, n, *args):
        super().addnstr(y, x, s, n, *args)
        self.calls.append((y, x, s, n))


class TestLabelOverflow:
    """Excel-style spillover: a LABEL whose text exceeds its column width
    visually overflows into adjacent empty cells to the right.

    Verified by calling the internal helper directly against a populated
    Grid; the end-to-end integration test in tests/integration/ covers the
    real-curses path."""

    def setup_method(self):
        _setup_curses_constants()
        self.g = Grid()
        self.g.cw = 14  # match the example file

    def _paint(self, sel=None):
        from gridcalc.tui import _paint_label_overflow

        stdscr = _RecordingStdscr()
        # Row 0, painted at y=3 (the TUI's first grid row). lc=0, fc=10.
        _paint_label_overflow(stdscr, self.g, row=0, y=3, lc=0, fc=10, sel=sel)
        return stdscr.calls

    def test_long_label_overflows_into_empty_neighbors(self):
        label_with_prefix = '"This is a very long label that should overflow'
        stripped = label_with_prefix[1:]  # gridcalc strips the leading `"`
        self.g.setcell(0, 0, label_with_prefix)
        # B1..D1 are empty -> the spill should happen.
        calls = self._paint()
        # Exactly one paint -- the helper paints only the overflow portion.
        assert len(calls) == 1
        y, x, text, n = calls[0]
        assert y == 3
        # Overflow paints into B1, which starts at GW + 1*cw.
        from gridcalc.tui import GW

        assert x == GW + self.g.cw
        # The painted text is the slice [cw : cw+n] of the stripped label.
        assert text == stripped[self.g.cw : self.g.cw + n]

    def test_short_label_does_not_overflow(self):
        self.g.setcell(0, 0, '"short')
        calls = self._paint()
        assert calls == []  # nothing to overflow

    def test_overflow_stops_at_non_empty_neighbor(self):
        self.g.setcell(0, 0, '"long label exceeding the cell width by a lot')
        self.g.setcell(2, 0, "stop")  # C1 has content -> block past B1
        calls = self._paint()
        assert len(calls) == 1
        _, _, _, n = calls[0]
        # paint_cells = 2 (the label cell + one empty B1); n = avail
        # = 2*cw - cw = cw = 14 (the width of just B1).
        assert n == self.g.cw

    def test_overflow_stops_at_cursor_cell(self):
        """The cursor cell must keep its own visual state; overflow must
        not paint over it."""
        self.g.setcell(0, 0, '"long label exceeding the cell width by a lot')
        self.g.cc = 2  # cursor on C1
        self.g.cr = 0
        calls = self._paint()
        # Spill is allowed into B1 only -> avail = cw
        assert len(calls) == 1
        assert calls[0][3] == self.g.cw

    def test_overflow_stops_at_selection(self):
        self.g.setcell(0, 0, '"long label exceeding the cell width by a lot')
        sel = (3, 0, 3, 0)  # D1 selected
        calls = self._paint(sel=sel)
        # Spill allowed into B1 and C1; clipped at D1.
        # paint_cells = 3 -> avail = 3*cw - cw = 2*cw
        assert calls[0][3] == 2 * self.g.cw

    def test_label_with_leading_quote_strips_for_overflow(self):
        """Labels typed with a leading `"` (gridcalc's label-prefix) have
        the quote stripped for display; overflow must use the stripped
        text, not the raw cell.text including the quote."""
        label_with_prefix = '"a label long enough to spill across cells'
        stripped = label_with_prefix[1:]
        self.g.setcell(0, 0, label_with_prefix)
        calls = self._paint()
        text = calls[0][2]
        # The overflow starts at the stripped string's offset cw, so the
        # quote character must NOT shift the slice -- if it did, this
        # equality would fail by one position.
        assert text == stripped[self.g.cw : self.g.cw + len(text)]


class TestSensitivityReport:
    """`:opt sens` -- the sensitivity report and its formatter.

    `cmd_opt` had no unit coverage before this (only the PTY suite reached
    it), so these drive the dispatcher directly through a recording stdscr.
    """

    class RecordingStdscr(MockStdscr):
        """MockStdscr keeps only the last addnstr; the pager writes a whole
        screen, so record every line."""

        def __init__(self):
            super().__init__()
            self.written = []

        def addnstr(self, y, x, s, n, *args):
            super().addnstr(y, x, s, n, *args)
            self.written.append(s)

        @property
        def screen(self):
            return "\n".join(self.written)

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = self.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # The Wyndor Glass LP: max 3x+5y, x<=4, 2y<=12, 3x+2y<=18.
        # Optimum x=2 y=6 obj=36; shadow prices 0, 3/2, 1.
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=3*A1+5*A2"),
            (3, 0, "=A1<=4"),
            (3, 1, "=2*A2<=12"),
            (3, 2, "=3*A1+2*A2<=18"),
        ]:
            self.g.setcell(c, r, t)
        self.g.models["default"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1:D3"
        )

    def _run(self, args):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, args)

    def test_sens_renders_report_with_shadow_prices(self):
        self._run("opt sens")
        screen = self.stdscr.screen
        assert "Constraints" in screen
        assert "shadow" in screen
        # D2's shadow price is 3/2 and D1's is 0.
        assert "1.5" in screen
        assert "OPTIMAL" in screen

    def test_sens_marks_binding_constraints(self):
        self._run("opt sens")
        rows = [ln for ln in self.stdscr.written if ln.strip().startswith(("*", "D"))]
        binding = [ln for ln in rows if ln.lstrip().startswith("*")]
        # D2 and D3 bind; D1 has slack.
        assert len(binding) == 2
        assert all("D2" in ln or "D3" in ln for ln in binding)

    def test_sens_applies_the_optimum_like_a_plain_run(self):
        """The report describes the optimum that was written to the sheet, so
        the cells must actually be updated."""
        self._run("opt sens")
        assert self.g.cells[0][0].val == pytest.approx(2.0)
        assert self.g.cells[0][1].val == pytest.approx(6.0)
        assert self.g.cells[2][0].val == pytest.approx(36.0)

    def test_sens_is_undoable(self):
        self._run("opt sens")
        self.undo.undo(self.g)
        assert self.g.cells[0][0].val == pytest.approx(0.0)

    def test_sens_unknown_model_errors(self):
        self._run("opt sens nosuch")
        assert "no model named" in self.stdscr.screen

    def test_sens_on_mip_explains_why_no_report(self):
        self.g.models["mip"] = OptModel(
            sense="max",
            objective="C1",
            vars="A1:A2",
            constraints="D1:D3",
            integers="A1:A2",
        )
        self._run("opt sens mip")
        screen = self.stdscr.screen
        assert "no sensitivity" in screen
        assert "OPTIMAL" in screen, "the solve itself should still have succeeded"

    def test_plain_run_shows_no_report(self):
        self._run("opt run")
        assert "shadow" not in self.stdscr.screen


class TestFormatSensitivity:
    """The formatter is pure, so assert its layout contract directly."""

    def _sens(self):
        from gridcalc.opt import solve

        g = Grid()
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=3*A1+5*A2"),
            (3, 0, "=A1<=4"),
            (3, 1, "=2*A2<=12"),
            (3, 2, "=3*A1+2*A2<=18"),
        ]:
            g.setcell(c, r, t)
        res = solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0), (0, 1)],
            constraint_cells=[(3, 0), (3, 1), (3, 2)],
            maximize=True,
            sensitivity=True,
        )
        return res.sensitivity

    def _lines(self):
        from gridcalc.engine import cellname
        from gridcalc.tui.format import format_sensitivity

        return format_sensitivity(self._sens(), cellname)

    def test_fits_an_80_column_terminal(self):
        """The pager indents by two and truncates rather than wraps, so a
        line over ~78 loses digits off the right edge silently."""
        widest = max(len(ln) for ln in self._lines())
        assert widest <= 78, f"widest line is {widest} chars"

    def test_labels_rows_by_cell_name(self):
        text = "\n".join(self._lines())
        for name in ("A1", "A2", "D1", "D2", "D3"):
            assert name in text

    def test_infinite_ranges_render_as_words(self):
        text = "\n".join(self._lines())
        assert "inf" in text
        assert "1e+30" not in text, "a solver infinity sentinel leaked into the report"

    def test_binding_marker_is_leading_not_trailing(self):
        """A trailing label is the first thing lost to truncation, so the
        marker has to be on the left."""
        lines = self._lines()
        d2 = next(ln for ln in lines if "D2" in ln)
        d1 = next(ln for ln in lines if "D1" in ln)
        assert d2.lstrip().startswith("*")
        assert not d1.lstrip().startswith("*")


class TestInfeasibilityDiagnosis:
    """`:opt` on an infeasible model names the contradictory cells."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # D1..D5; only D1 and D2 contradict each other.
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=A1+A2"),
            (3, 0, "=A1>=10"),
            (3, 1, "=A1<=5"),
            (3, 2, "=A2<=100"),
            (3, 3, "=A2>=1"),
            (3, 4, "=A1+A2<=1000"),
        ]:
            self.g.setcell(c, r, t)
        self.g.models["default"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1:D5"
        )

    def _run(self, args="opt"):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, args)

    def test_names_the_conflicting_cells(self):
        self._run()
        screen = self.stdscr.screen
        assert "INFEASIBLE" in screen
        assert "D1" in screen and "D2" in screen

    def test_omits_constraints_not_in_the_conflict(self):
        """The value is in the narrowing -- listing all five would be no
        better than the bare status."""
        self._run()
        line = next(ln for ln in self.stdscr.written if "conflict" in ln)
        for innocent in ("D3", "D4", "D5"):
            assert innocent not in line

    def test_reports_the_subset_size(self):
        self._run()
        line = next(ln for ln in self.stdscr.written if "conflict" in ln)
        assert "2 of 5" in line

    def test_message_fits_the_status_bar(self):
        self._run()
        line = next(ln for ln in self.stdscr.written if "conflict" in ln)
        assert len(line) <= 79, f"status line is {len(line)} chars: {line!r}"

    def test_failed_solve_leaves_the_sheet_and_undo_stack_alone(self):
        depth = len(self.undo.undo_stack)
        self._run()
        assert self.g.cells[0][0].val == pytest.approx(0.0)
        assert len(self.undo.undo_stack) == depth


class TestFormatConflict:
    def _names(self, c, r):
        from gridcalc.engine import cellname

        return cellname(c, r)

    def test_lists_cells_with_counts(self):
        from gridcalc.tui.format import format_conflict

        out = format_conflict([(3, 0), (3, 1)], 5, self._names)
        assert out == "conflict: D1, D2 (2 of 5 constraints)"

    def test_truncates_long_lists(self):
        from gridcalc.tui.format import format_conflict

        cells = [(3, i) for i in range(12)]
        out = format_conflict(cells, 20, self._names, max_cells=3)
        assert "D1, D2, D3, +9 more" in out
        assert "(12 of 20 constraints)" in out

    def test_empty_conflict_points_at_bounds(self):
        from gridcalc.tui.format import format_conflict

        out = format_conflict([], 3, self._names)
        assert "bounds" in out
        assert "conflict:" not in out


class TestBadBoundsDoNotCrashTheTui:
    """A reversed bound used to raise ValueError from the C++ bridge, which
    `_execute_model` did not catch -- tearing down curses and losing the
    user's unsaved sheet."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        for c, r, t in [(0, 0, "0"), (2, 0, "=A1"), (3, 0, "=A1<=5")]:
            self.g.setcell(c, r, t)

    def _model(self, bounds):
        return OptModel(sense="max", objective="C1", vars="A1", constraints="D1", bounds=bounds)

    def _run(self, bounds):
        from gridcalc.tui import cmdexec

        self.g.models["default"] = self._model(bounds)
        return cmdexec(self.stdscr, self.g, self.undo, "opt")

    def test_reversed_bounds_report_instead_of_raising(self):
        self._run("A1=20:10")  # must not raise
        assert "reversed" in self.stdscr.screen

    def test_nan_bounds_report_instead_of_raising(self):
        self._run("A1=nan:10")
        assert "not numeric" in self.stdscr.screen

    def test_bad_bounds_leave_no_dangling_undo_entry(self):
        """`save_grid` runs before the solve, so a failure path that forgets
        to pop leaves `u` as a silent no-op afterwards."""
        depth = len(self.undo.undo_stack)
        self._run("A1=20:10")
        assert len(self.undo.undo_stack) == depth


class TestUnboundedDiagnosis:
    """`:opt` on an unbounded model names the runaway variable."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        # A1 capped by D1; A2 free above -> A2 runs away.
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=A1+A2"),
            (3, 0, "=A1<=4"),
        ]:
            self.g.setcell(c, r, t)
        self.g.models["default"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1"
        )

    def _run(self):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, "opt")

    def test_names_the_runaway_variable(self):
        self._run()
        screen = self.stdscr.screen
        assert "UNBOUNDED" in screen
        assert "A2" in screen

    def test_omits_the_bounded_variable(self):
        self._run()
        line = next(ln for ln in self.stdscr.written if "unbounded:" in ln)
        assert "A1" not in line

    def test_suggests_a_remedy(self):
        self._run()
        line = next(ln for ln in self.stdscr.written if "unbounded:" in ln)
        assert "upper bound" in line or "constraint" in line

    def test_message_fits_the_status_bar(self):
        self._run()
        line = next(ln for ln in self.stdscr.written if "unbounded:" in ln)
        assert len(line) <= 79, f"status line is {len(line)} chars: {line!r}"

    def test_leaves_the_sheet_and_undo_stack_alone(self):
        depth = len(self.undo.undo_stack)
        self._run()
        assert self.g.cells[0][0].val == pytest.approx(0.0)
        assert len(self.undo.undo_stack) == depth


class TestFormatUnbounded:
    def _names(self, c, r):
        from gridcalc.engine import cellname

        return cellname(c, r)

    def test_single_variable(self):
        from gridcalc.tui.format import format_unbounded

        out = format_unbounded([(0, 1)], self._names)
        assert out.startswith("unbounded: A2")
        assert "upper bound" in out

    def test_multiple_variables_pluralise(self):
        from gridcalc.tui.format import format_unbounded

        out = format_unbounded([(0, 0), (0, 1)], self._names)
        assert "A1, A2" in out
        assert out.endswith("add upper bounds or constraints")

    def test_single_variable_remedy_is_singular(self):
        """Guards the grammar in both directions -- a naive `+ "s"` produces
        'add an upper bound or a constraints'."""
        from gridcalc.tui.format import format_unbounded

        out = format_unbounded([(0, 1)], self._names)
        assert out.endswith("add an upper bound or a constraint")

    def test_truncates_long_lists(self):
        from gridcalc.tui.format import format_unbounded

        out = format_unbounded([(0, i) for i in range(12)], self._names, max_cells=3)
        assert "A1, A2, A3, +9 more" in out

    def test_empty_declines_to_guess(self):
        """The probe returns nothing when its bounded re-solves do not
        converge; saying so beats naming an arbitrary variable."""
        from gridcalc.tui.format import format_unbounded

        out = format_unbounded([], self._names)
        assert "could not identify" in out
        assert "unbounded:" not in out


class TestSweepCommand:
    """`:opt sweep <cell> <lo>:<hi> [steps] [model]`."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=3*A1+5*A2"),
            (3, 0, "=A1<=4"),
            (3, 1, "=2*A2<=12"),
            (3, 2, "=3*A1+2*A2<=18"),
        ]:
            self.g.setcell(c, r, t)
        self.g.models["default"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1:D3"
        )

    def _run(self, args):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, args)

    def test_renders_the_series(self):
        self._run("opt sweep D2 6:24 9")
        screen = self.stdscr.screen
        assert "right-hand side" in screen
        assert "shadow" in screen
        assert "1.5" in screen

    def test_is_read_only(self):
        """A sweep is a question, not an edit. It must not move the decision
        cells or push an undo entry the user would have to unwind."""
        depth = len(self.undo.undo_stack)
        self._run("opt sweep D2 6:24 4")
        assert self.g.cells[0][0].val == pytest.approx(0.0)
        assert self.g.cells[0][1].val == pytest.approx(0.0)
        assert len(self.undo.undo_stack) == depth

    def test_missing_arguments_show_usage(self):
        self._run("opt sweep D2")
        assert "usage" in self.stdscr.screen

    def test_bad_range_reports(self):
        self._run("opt sweep D2 notarange")
        assert "lo:hi" in self.stdscr.screen

    def test_non_constraint_cell_reports(self):
        self._run("opt sweep A1 1:10")
        assert "not one of the constraint cells" in self.stdscr.screen

    def test_unknown_model_reports(self):
        self._run("opt sweep D2 6:24 5 nosuch")
        assert "no model named" in self.stdscr.screen

    def test_steps_argument_controls_the_sampled_points(self):
        """steps=3 spans 6..24 in three intervals, so four rows at 6/12/18/24.

        Data rows are matched on "optional marker then a number", because a
        starred breakpoint row does not begin with its rhs value and the
        pager indents everything by two.
        """
        import re

        self._run("opt sweep D2 6:24 3")
        rows = [ln for ln in self.stdscr.written if re.match(r"^\s+\*?\s*-?\d", ln)]
        sampled = []
        for ln in rows:
            toks = ln.split()
            sampled.append(float(toks[1] if toks[0] == "*" else toks[0]))
        assert sampled == [6.0, 12.0, 18.0, 24.0]


class TestFormatSweep:
    def _points(self):
        from gridcalc.opt import sweep

        g = Grid()
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=3*A1+5*A2"),
            (3, 0, "=A1<=4"),
            (3, 1, "=2*A2<=12"),
            (3, 2, "=3*A1+2*A2<=18"),
        ]:
            g.setcell(c, r, t)
        return sweep(
            g,
            (2, 0),
            [(0, 0), (0, 1)],
            [(3, 0), (3, 1), (3, 2)],
            constraint=(3, 1),
            lo=6.0,
            hi=24.0,
            steps=9,
            maximize=True,
        )

    def _lines(self):
        from gridcalc.tui.format import format_sweep

        return format_sweep(self._points(), "D2")

    def test_fits_an_80_column_terminal(self):
        widest = max(len(ln) for ln in self._lines())
        assert widest <= 78, f"widest line is {widest} chars"

    def test_header_states_the_range_once(self):
        header = self._lines()[0]
        assert "D2" in header and "from 6 to 24" in header

    def test_marks_breakpoints(self):
        marked = [ln for ln in self._lines() if ln.lstrip().startswith("*")]
        assert len(marked) == 2

    def test_constant_marginal_value_says_so(self):
        """A sweep entirely inside one ranging interval has nothing to show;
        saying 'widen the range' beats an unmarked table the user has to
        squint at."""
        from gridcalc.opt import SweepPoint
        from gridcalc.tui.format import format_sweep

        flat = [
            SweepPoint(
                rhs=float(i),
                status_name="OPTIMAL",
                objective=float(i),
                shadow_price=1.0,
                delta=1.0 if i else None,
                breakpoint=False,
            )
            for i in range(3)
        ]
        text = "\n".join(format_sweep(flat, "D2"))
        assert "constant across this range" in text


class TestInfinityDoesNotCrashDisplay:
    """`=1e308*10` overflows to infinity in any mode, and every place that
    formatted a cell value used `v == int(v) and abs(v) < N`. Python
    evaluates `int(v)` before the magnitude guard can short-circuit, so
    OverflowError propagated out of `draw()` and killed the session. NaN was
    guarded two lines away; infinity was missed.
    """

    def _inf_grid(self):
        g = Grid()
        g.setcell(0, 0, "=1e308*10")
        g.setcell(0, 1, "=-1e308*10")
        g.recalc()
        return g

    def test_fmtcell_renders_infinity(self):
        from gridcalc.display import fmtcell

        g = self._inf_grid()
        assert fmtcell(g.cells[0][0], 10).strip() == "inf"
        assert fmtcell(g.cells[0][1], 10).strip() == "-inf"

    @pytest.mark.parametrize("spec", ["I", "*", "$", "%", "L", "D", ""])
    def test_fmtcell_survives_every_format_spec(self, spec):
        """`I` and `*` call int() unconditionally, so the guard has to come
        before the format dispatch rather than inside it."""
        from gridcalc.display import fmtcell

        cl = self._inf_grid().cells[0][0]
        cl.fmt = spec
        assert "inf" in fmtcell(cl, 12)

    def test_fmtcell_survives_a_number_format_string(self):
        from gridcalc.display import fmtcell

        cl = self._inf_grid().cells[0][0]
        cl.fmtstr = ",.2f"
        assert "inf" in fmtcell(cl, 12)

    def test_clipboard_value_survives_infinity(self):
        from gridcalc.display import cell_clip_value

        g = self._inf_grid()
        assert cell_clip_value(g.cells[0][0]) == "inf"
        assert cell_clip_value(g.cells[0][1]) == "-inf"

    def test_search_survives_infinity(self):
        """Search stringifies every numeric cell to match against, so it hit
        the same idiom."""
        from gridcalc.tui.search import _search_grid

        g = self._inf_grid()
        assert _search_grid(g, "zzz") == []
        assert _search_grid(g, "inf") == [(0, 0), (0, 1)]

    def test_json_roundtrip_survives_infinity(self, tmp_path):
        g = self._inf_grid()
        p = tmp_path / "inf.json"
        assert g.jsonsave(str(p)) == 0
        g2 = Grid()
        assert g2.jsonload(str(p)) == 0

    def test_csv_export_survives_infinity(self, tmp_path):
        g = self._inf_grid()
        p = tmp_path / "inf.csv"
        g.csvsave(str(p))  # must not raise


class TestSensitivityIntoCells:
    """`:opt sens [<name>] into[!] <cell>` writes the report into the grid.

    The point is composability: the numbers land as NUM cells so downstream
    formulas can reference them, which a paged report cannot offer.
    """

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        for c, r, t in [
            (0, 0, "0"),
            (0, 1, "0"),
            (2, 0, "=3*A1+5*A2"),
            (3, 0, "=A1<=4"),
            (3, 1, "=2*A2<=12"),
            (3, 2, "=3*A1+2*A2<=18"),
        ]:
            self.g.setcell(c, r, t)
        self.g.models["default"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1:D3"
        )

    def _run(self, args):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, args)

    def test_writes_a_block_at_the_anchor(self):
        self._run("opt sens into F1")
        assert self.g.cells[5][0].text == "Variables"
        assert self.g.cells[5][1].text == "A1"
        assert "written at F1" in self.stdscr.screen

    def test_numbers_are_numeric_not_labels(self):
        """A LABEL would render the same but break every downstream formula,
        which is the entire reason for writing into cells."""
        from gridcalc.engine import NUM

        self._run("opt sens into F1")
        shadow = self.g.cells[6][6]  # G7: shadow price of D2
        assert shadow.type == NUM
        assert shadow.val == pytest.approx(1.5)

    def test_written_values_are_referenceable_from_formulas(self):
        self._run("opt sens into F1")
        self.g.setcell(5, 12, "=G7*100")
        self.g.recalc()
        assert self.g.cells[5][12].val == pytest.approx(150.0)

    def test_writes_infinities_without_crashing_the_display(self):
        from gridcalc.display import fmtcell

        self._run("opt sens into F1")
        # A2's objective-coefficient upper range is unbounded.
        coef_till = self.g.cells[10][2]
        assert math.isinf(coef_till.val)
        assert fmtcell(coef_till, 10).strip() == "inf"

    def test_refuses_to_overwrite_without_force(self):
        self.g.setcell(6, 3, "precious")
        self._run("opt sens into F1")
        assert "not empty" in self.stdscr.screen
        assert self.g.cells[6][3].text == "precious", "nothing may be written"

    def test_force_overwrites(self):
        self.g.setcell(6, 3, "precious")
        self._run("opt sens into! F1")
        assert self.g.cells[6][3].text != "precious"
        assert "written at F1" in self.stdscr.screen

    def test_refusal_names_the_blocking_cell(self):
        self.g.setcell(6, 3, "precious")
        self._run("opt sens into F1")
        assert "G4" in self.stdscr.screen

    def test_is_undoable(self):
        self._run("opt sens into F1")
        assert self.g.cells[5][0].text == "Variables"
        self.undo.undo(self.g)
        assert self.g.cells[5][0].type == 0

    def test_refuses_a_block_that_would_not_fit(self):
        from gridcalc.engine import NCOL

        col = col_name(NCOL - 2)
        self._run(f"opt sens into {col}1")
        assert "does not fit" in self.stdscr.screen

    def test_bad_target_cell_reports(self):
        self._run("opt sens into notacell")
        assert "bad target cell" in self.stdscr.screen

    def test_missing_target_shows_usage(self):
        self._run("opt sens into")
        assert "usage" in self.stdscr.screen

    def test_named_model_with_target(self):
        self.g.models["alt"] = OptModel(
            sense="max", objective="C1", vars="A1:A2", constraints="D1:D3"
        )
        self._run("opt sens alt into F1")
        assert self.g.cells[5][0].text == "Variables"

    def test_without_into_still_pages_the_report(self):
        self._run("opt sens")
        assert self.g.cells[5][0].type == 0, "no target means no writing"
        assert "shadow" in self.stdscr.screen

    def test_clears_the_gap_row_inside_the_block(self):
        """The separator row between the two tables is part of the report's
        rectangle. Leaving a user's value there would read as report data."""
        self.g.setcell(6, 3, "stray")
        self._run("opt sens into! F1")
        assert self.g.cells[6][3].type == 0


class TestOptOnVisualSelection:
    """`:opt max|min` with a visual selection infers the model from the block."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = TestSensitivityReport.RecordingStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        self.g.setcell(0, 0, '"Product')
        self.g.setcell(0, 1, "0")
        self.g.setcell(0, 2, "0")
        self.g.setcell(1, 1, "=3*A2+5*A3")
        self.g.setcell(2, 1, "=A2<=4")
        self.g.setcell(2, 2, "=2*A3<=12")
        self.g.setcell(2, 3, "=3*A2+2*A3<=18")

    def _run(self, args, sel=(0, 0, 2, 3)):
        from gridcalc.tui import cmdexec

        return cmdexec(self.stdscr, self.g, self.undo, args, sel=sel)

    def test_solves_from_the_selection(self):
        self._run("opt max")
        assert "OPTIMAL" in self.stdscr.screen
        assert self.g.cells[0][1].val == pytest.approx(2.0)
        assert self.g.cells[0][2].val == pytest.approx(6.0)

    def test_min_sense_is_honoured(self):
        self._run("opt min")
        assert "OPTIMAL" in self.stdscr.screen
        assert self.g.cells[1][1].val == pytest.approx(0.0)

    def test_saves_the_inferred_model_as_default(self):
        """The block only has to be selected once; `:opt` re-runs it after."""
        self._run("opt max")
        m = self.g.models["default"]
        assert m.sense == "max"
        assert m.objective == "B2"
        assert m.vars == "A2:A3"
        assert m.constraints == "C2:C4"

    def test_saved_model_reruns_without_a_selection(self):
        self._run("opt max")
        self.g.setcell(0, 1, "0")
        self.g.setcell(0, 2, "0")
        self._run("opt", sel=None)
        assert self.g.cells[0][1].val == pytest.approx(2.0)

    def test_is_undoable(self):
        self._run("opt max")
        self.undo.undo(self.g)
        assert self.g.cells[0][1].val == pytest.approx(0.0)

    def test_ambiguous_objective_reports(self):
        self.g.setcell(1, 2, "=A2+A3")
        self._run("opt max")
        assert "candidate objective" in self.stdscr.screen

    def test_selection_without_constraints_reports(self):
        self._run("opt max", sel=(0, 0, 1, 3))
        assert "no constraint formulas" in self.stdscr.screen

    def test_explicit_form_still_works_with_a_selection_active(self):
        """A fully-specified command must not be hijacked by the selection."""
        self._run("opt max B2 vars A2:A3 st C2:C4")
        assert "OPTIMAL" in self.stdscr.screen
        assert self.g.models["default"].vars == "A2:A3"

    def test_no_selection_means_no_inference(self):
        self._run("opt max", sel=None)
        assert "usage" in self.stdscr.screen


class TestSpillRendering:
    """Display polish for dynamic-array spill (engine covered in test_spill)."""

    def _excel_grid(self):
        from gridcalc.engine import Mode

        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        return g

    def test_fmtcell_spilling_anchor_shows_scalar_not_badge(self):
        from gridcalc.tui import fmtcell

        g = self._excel_grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        out = fmtcell(g.cell(0, 0), 8)
        assert out.strip() == "1"  # top-left scalar, not "1[3]"
        assert "[" not in out

    def test_fmtcell_spill_cell_shows_value(self):
        from gridcalc.tui import fmtcell

        g = self._excel_grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        assert fmtcell(g.cell(0, 1), 8).strip() == "2"
        assert fmtcell(g.cell(0, 2), 8).strip() == "3"

    def test_fmtcell_python_mode_array_keeps_badge(self):
        # PYTHON mode does not spill, so the array badge is still the display.
        from gridcalc.tui import fmtcell

        g = Grid()  # PYTHON mode by default
        g.setcell(0, 0, "0")
        g.setcell(0, 1, "1")
        g.setcell(0, 2, "2")
        g.setcell(1, 0, "=A1:A3 * 2")
        out = fmtcell(g.cell(1, 0), 8)
        assert "[3]" in out

    def test_status_bar_notes_spill_provenance(self):
        from gridcalc.tui import draw

        _setup_curses_constants()
        g = self._excel_grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.cc, g.cr = 0, 1  # cursor on the spilled A2
        stdscr = _RecordingStdscr()
        draw(stdscr, g, mode="", buf="")
        status = next(s for (y, x, s, n) in stdscr.calls if y == 0)
        assert "spill from A1" in status

    def test_sheet_tabs_drawn_only_when_multisheet(self):
        from gridcalc.tui import cmdexec, draw

        _setup_curses_constants()
        g = Grid()
        y_last = curses.LINES - 1

        # Single sheet: no tab strip on the bottom line.
        stdscr = _RecordingStdscr()
        draw(stdscr, g, mode="", buf="")
        assert not [s for (yy, x, s, n) in stdscr.calls if yy == y_last and s.strip()]

        # Add a second sheet: strip appears with both names and an i/n counter.
        cmdexec(stdscr, g, UndoManager(), "sheet add Data")
        stdscr = _RecordingStdscr()
        draw(stdscr, g, mode="", buf="")
        bottom = "".join(s for (yy, x, s, n) in stdscr.calls if yy == y_last)
        assert "Sheet1" in bottom
        assert "Data" in bottom
        assert "1/2" in bottom

    def test_status_bar_explains_spill_error(self):
        from gridcalc.tui import draw

        _setup_curses_constants()
        g = self._excel_grid()
        g.setcell(0, 1, "X")  # block the spill
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.cc, g.cr = 0, 0  # cursor on the blocked anchor
        stdscr = _RecordingStdscr()
        draw(stdscr, g, mode="", buf="")
        status = next(s for (y, x, s, n) in stdscr.calls if y == 0)
        assert "#SPILL!" in status
        assert "blocked" in status


class TestOpenPreservesWorkbookOnFailure:
    """`:open` used to clear the sheet before attempting the load, so any file
    the loader refused left the user with an empty workbook -- the open failed
    and destroyed the open sheet with it."""

    def setup_method(self):
        _setup_curses_constants()
        self.stdscr = MockStdscr()
        self.g = Grid()
        self.undo = UndoManager()
        self.g.setcell(0, 0, "keep")
        self.g.names.append(NamedRange(name="keep", c1=0, r1=0, c2=0, r2=0))
        self.g.recalc()

    def _assert_intact(self):
        assert self.g.cell(0, 0).text == "keep"
        assert [n.name for n in self.g.names] == ["keep"]

    def test_missing_file(self, tmp_path):
        from gridcalc.tui import cmdexec

        cmdexec(self.stdscr, self.g, self.undo, f"open {tmp_path / 'nope.json'}")
        self._assert_intact()

    def test_unparseable_file(self, tmp_path):
        from gridcalc.tui import cmdexec

        f = tmp_path / "bad.json"
        f.write_text("{not json")
        cmdexec(self.stdscr, self.g, self.undo, f"open {f}")
        self._assert_intact()

    def test_valid_json_that_is_not_a_workbook(self, tmp_path):
        from gridcalc.tui import cmdexec

        f = tmp_path / "arr.json"
        f.write_text("[]")
        cmdexec(self.stdscr, self.g, self.undo, f"open {f}")
        self._assert_intact()

    def test_malformed_code_field(self, tmp_path):
        from gridcalc.tui import cmdexec

        f = tmp_path / "badcode.json"
        f.write_text(json.dumps({"version": 2, "code": 123}))
        cmdexec(self.stdscr, self.g, self.undo, f"open {f}")
        self._assert_intact()


class TestCommandLine:
    """The `gridcalc` / `gridcalc-web` argument parsers.

    Hand-rolled `sys.argv` checks got the conventions wrong in four ways --
    `--help` exited 1 on stderr, the two entry points disagreed about the exit
    code, `--version` was taken as a filename, and `-h` was only recognised as
    the sole argument. These pin the conventions rather than the wording.
    """

    @staticmethod
    def _parsers():
        from gridcalc.tui import cli_parser as tui_parser
        from gridcalc.web import cli_parser as web_parser

        return [tui_parser(), web_parser()]

    def test_no_argument_means_no_file(self):
        for p in self._parsers():
            assert p.parse_args([]).file is None

    def test_a_workbook_is_the_one_positional(self):
        for p in self._parsers():
            assert p.parse_args(["book.json"]).file == "book.json"

    @pytest.mark.parametrize("flag", ["-h", "--help", "-V", "--version"])
    def test_help_and_version_succeed(self, flag, capsys):
        """An explicit request is answered, on stdout, with exit 0 -- so
        `gridcalc --help | less` shows something."""
        for p in self._parsers():
            with pytest.raises(SystemExit) as exc:
                p.parse_args([flag])
            assert exc.value.code == 0
            out = capsys.readouterr()
            assert out.out and not out.err

    def test_help_is_recognised_after_a_filename(self):
        """`len(sys.argv) == 2` made this open a workbook called `-h`."""
        for p in self._parsers():
            with pytest.raises(SystemExit) as exc:
                p.parse_args(["book.json", "-h"])
            assert exc.value.code == 0

    def test_an_unknown_flag_is_an_error_not_a_filename(self):
        for p in self._parsers():
            with pytest.raises(SystemExit) as exc:
                p.parse_args(["--bogus"])
            assert exc.value.code == 2

    def test_the_program_name_is_the_command(self, capsys):
        """`sys.argv[0]` printed the absolute path of the venv shim."""
        from gridcalc.tui import cli_parser

        with pytest.raises(SystemExit):
            cli_parser().parse_args(["--help"])
        assert capsys.readouterr().out.startswith("usage: gridcalc ")

    def test_version_reports_the_packaged_version(self, capsys):
        from gridcalc import __version__
        from gridcalc.tui import cli_parser

        with pytest.raises(SystemExit):
            cli_parser().parse_args(["--version"])
        assert capsys.readouterr().out.strip() == f"gridcalc {__version__}"


class TestTheVersionIsDeclaredOnce:
    """`pyproject.toml` is the only place the version is written.

    `__version__` reads it back from the metadata the build wrote, and
    `--version` prints that -- so a number nobody shipped is not expressible.
    The alternative, a literal in the package, is a copy maintained by hand
    against one maintained by `make release`, which bumps only pyproject.
    """

    @staticmethod
    def _declared() -> str:
        try:
            import tomllib
        except ModuleNotFoundError:  # 3.10
            import tomli as tomllib

        root = Path(__file__).resolve().parents[1]
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])

    def test_the_package_reports_what_pyproject_declares(self):
        """Fails on a stale editable install as well as on a second copy --
        both mean the version being reported is not the one in the source."""
        from gridcalc import __version__

        assert __version__ == self._declared()

    def test_the_package_holds_no_release_number_of_its_own(self):
        """The read is what keeps the two in step; a hardcoded number here
        would pass the test above until the next release and fail after it.
        The not-installed sentinel is a literal too, and is meant to be -- it
        is precisely not a release number."""
        import re

        root = Path(__file__).resolve().parents[1]
        source = (root / "src" / "gridcalc" / "__init__.py").read_text(encoding="utf-8")
        assigned = re.findall(r"""__version__\s*=\s*["']([^"']+)""", source)
        assert assigned, "the attribute has to exist"
        assert [v for v in assigned if re.match(r"^\d+(\.\d+)+", v)] == []

    def test_an_uninstalled_source_tree_says_so(self, monkeypatch):
        """No metadata is not a number. Guessing one gives every uninstalled
        checkout the same plausible, wrong answer."""
        import importlib
        import importlib.metadata

        def missing(name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(importlib.metadata, "version", missing)
        mod = importlib.reload(importlib.import_module("gridcalc"))
        try:
            assert "unknown" in mod.__version__
        finally:
            monkeypatch.undo()
            importlib.reload(mod)

    def test_the_release_target_bumps_pyproject(self):
        root = Path(__file__).resolve().parents[1]
        makefile = (root / "Makefile").read_text(encoding="utf-8")
        assert 's/^version = .*/version = \\"$$version\\"/" pyproject.toml' in makefile
