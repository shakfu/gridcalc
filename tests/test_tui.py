"""Tests for TUI components that don't require a live curses terminal."""

import curses
import importlib.util

import pytest

from gridcalc.engine import Grid
from gridcalc.tui import UndoManager

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None
_HAS_PANDAS = importlib.util.find_spec("pandas") is not None


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
