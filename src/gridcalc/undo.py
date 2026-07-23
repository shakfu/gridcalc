"""Undo/redo history -- engine-adjacent, shared by frontends, no view deps.

`UndoManager` snapshots cells before a mutation and restores them on undo,
recomputing derived values through `recalc`. It has no `curses`/view
dependency, so both the curses TUI and the web frontend reuse it; the split
here mirrors `display.py` / `loader.py`. `tests/test_architecture.py` keeps it
curses-free. The cell *clipboard* (OS interchange) stays in `tui/` -- it is
view-facing; this module is only the history.
"""

from __future__ import annotations

from .engine import EMPTY, Cell, Grid

UNDO_MAX = 64


class UndoEntry:
    __slots__ = ("cells", "cc", "cr", "is_grid")

    def __init__(self) -> None:
        self.cells: list[tuple[int, int, Cell]] = []
        self.cc: int = 0
        self.cr: int = 0
        self.is_grid: bool = False


class UndoManager:
    def __init__(self) -> None:
        self.undo_stack: list[UndoEntry] = []
        self.redo_stack: list[UndoEntry] = []

    def save_region(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> None:
        e = UndoEntry()
        e.cc = g.cc
        e.cr = g.cr
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                # Save a snapshot (or empty Cell) so undo can restore the state
                e.cells.append((c, r, cl.snapshot() if cl else Cell()))
        self.undo_stack.append(e)
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def save_cell(self, g: Grid, c: int, r: int) -> None:
        self.save_region(g, c, r, c, r)

    def discard_last(self) -> None:
        """Drop the most recent snapshot when the mutation it guarded did not
        happen (e.g. an applied solve that raised or came back non-optimal, so
        the grid was never written). Leaves the redo stack alone."""
        if self.undo_stack:
            self.undo_stack.pop()

    def save_grid(self, g: Grid) -> None:
        e = UndoEntry()
        e.cc = g.cc
        e.cr = g.cr
        e.is_grid = True
        for (c, r), cl in g._cells.items():
            if cl.type != EMPTY:
                e.cells.append((c, r, cl.snapshot()))
        self.undo_stack.append(e)
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _apply(self, g: Grid, from_stack: list[UndoEntry], to_stack: list[UndoEntry]) -> None:
        if not from_stack:
            return
        e = from_stack[-1]

        # Phase 1: capture the rollback snapshot. No mutation yet, so if
        # this raises the stacks and grid are untouched.
        re = UndoEntry()
        re.cc = g.cc
        re.cr = g.cr
        re.is_grid = e.is_grid
        if e.is_grid:
            for (c, r), cl in g._cells.items():
                if cl.type != EMPTY:
                    re.cells.append((c, r, cl.snapshot()))
        else:
            for c, r, _ in e.cells:
                maybe_cl: Cell | None = g.cell(c, r)
                re.cells.append((c, r, maybe_cl.snapshot() if maybe_cl else Cell()))

        # Phase 2: apply the restore. If anything raises, roll back from
        # `re` and leave `e` on `from_stack` so the user can retry.
        try:
            if e.is_grid:
                g.clear_all()
            for c, r, snap in e.cells:
                if snap.type == EMPTY:
                    g._cells.pop((c, r), None)
                else:
                    cl = g._ensure_cell(c, r)
                    cl.copy_from(snap)
            g.cc = e.cc
            g.cr = e.cr
            g.recalc()
        except Exception:
            if re.is_grid:
                g.clear_all()
            else:
                for c, r, _snap in re.cells:
                    g._cells.pop((c, r), None)
            for c, r, snap in re.cells:
                if snap.type != EMPTY:
                    cl = g._ensure_cell(c, r)
                    cl.copy_from(snap)
            g.cc = re.cc
            g.cr = re.cr
            g.recalc()
            raise

        # Both phases succeeded; commit.
        from_stack.pop()
        to_stack.append(re)

    def undo(self, g: Grid) -> None:
        self._apply(g, self.undo_stack, self.redo_stack)

    def redo(self, g: Grid) -> None:
        self._apply(g, self.redo_stack, self.undo_stack)
