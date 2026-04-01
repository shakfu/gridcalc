"""Tests for TUI components that don't require a live curses terminal."""

import curses

from gridcalc.engine import Grid
from gridcalc.tui import UndoManager


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
