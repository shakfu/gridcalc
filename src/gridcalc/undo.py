"""Undo/redo history -- engine-adjacent, shared by frontends, no view deps.

`UndoManager` snapshots state before a mutation and restores it on undo,
recomputing derived values through `recalc`. It has no `curses`/view
dependency, so both the curses TUI and the web frontend reuse it; the split
here mirrors `display.py` / `loader.py`. `tests/test_architecture.py` keeps it
curses-free. The cell *clipboard* (OS interchange) stays in `tui/` -- it is
view-facing; this module is only the history.

Entries come in three sizes. `save_region` records cells on one sheet.
`save_global` records workbook metadata (default format, names, mode).
`save_grid` records the whole workbook: every sheet's cells, name, widths and
cursor, the sheet order, the active sheet, and the metadata. Structural and
sheet operations use it because they rewrite formulas on every sheet. A full
snapshot of 25k cells over 3 sheets costs ~6 MB and ~20 ms, against ~110 ms
for the recalc every restore runs anyway.

Entries refer to sheets by `Sheet` object, not by name: a rename keeps the
object, so older entries still find their sheet, and a new sheet that reuses
the old name is a different object.
"""

from __future__ import annotations

from .engine import EMPTY, Cell, Grid, Mode, NamedRange, Sheet

UNDO_MAX = 64

# (sheet, name, cells, widths, cc, cr) for one sheet of a workbook snapshot.
_SheetSnap = tuple[Sheet, str, list[tuple[int, int, Cell]], dict[int, int], int, int]


def _copy_names(names: list[NamedRange]) -> list[NamedRange]:
    """Deep-copy a name list for a snapshot.

    A structural edit rewrites `NamedRange` objects *in place* and drops the
    ones that lose every line they covered, so a shallow list copy would be
    mutated by the very edit it is meant to record.
    """
    return [
        NamedRange(name=n.name, c1=n.c1, r1=n.r1, c2=n.c2, r2=n.r2, sheet=n.sheet) for n in names
    ]


def _book(g: Grid) -> list[_SheetSnap]:
    return [
        (
            s,
            s.name,
            [(c, r, cl.snapshot()) for (c, r), cl in s._cells.items() if cl.type != EMPTY],
            dict(s.widths),
            s.cc,
            s.cr,
        )
        for s in g.sheets
    ]


class UndoEntry:
    __slots__ = ("cells", "cc", "cr", "fmt", "sheet", "names", "mode", "book", "active")

    def __init__(self) -> None:
        self.cells: list[tuple[int, int, Cell]] = []
        self.cc: int = 0
        self.cr: int = 0
        # The workbook's default number format at snapshot time, or None for an
        # entry that does not care about it.
        self.fmt: str | None = None
        # The sheet `cells` belong to. `_apply` switches to it first; None means
        # "wherever we are" (a workbook entry restores the active sheet itself).
        self.sheet: Sheet | None = None
        # Workbook metadata; None means "do not touch", so a cell undo does not
        # revert a later `:name` that has its own entry.
        self.names: list[NamedRange] | None = None
        self.mode: Mode | None = None
        # Whole-workbook snapshot (see the module docstring), or None.
        self.book: list[_SheetSnap] | None = None
        self.active: Sheet | None = None


def _new_entry(g: Grid, sheet: Sheet | None) -> UndoEntry:
    e = UndoEntry()
    e.cc = g.cc
    e.cr = g.cr
    e.fmt = g.fmt
    e.sheet = sheet
    return e


def _capture(g: Grid, like: UndoEntry) -> UndoEntry:
    """Snapshot, from ``g`` as it is now, the same state ``like`` covers."""
    e = _new_entry(g, like.sheet)
    if like.names is not None:
        e.names = _copy_names(g.names)
        e.mode = g.mode
    if like.book is not None:
        e.book = _book(g)
        e.active = g._active
    for c, r, _ in like.cells:
        cl = g.cell(c, r)
        e.cells.append((c, r, cl.snapshot() if cl else Cell()))
    return e


def _restore(g: Grid, e: UndoEntry) -> None:
    if e.book is not None and e.active is not None:
        g.sheets = [snap[0] for snap in e.book]
        for s, name, cells, widths, cc, cr in e.book:
            s.name, s.widths, s.cc, s.cr = name, dict(widths), cc, cr
            s._cells = {(c, r): snap.snapshot() for c, r, snap in cells}
            s._circular = set()
        g.active = g.sheets.index(e.active)
        g._dep_graph_built = False
    for c, r, snap in e.cells:
        if snap.type == EMPTY:
            g._cells.pop((c, r), None)
        else:
            g._ensure_cell(c, r).copy_from(snap)
    g.cc = e.cc
    g.cr = e.cr
    if e.fmt is not None:
        g.fmt = e.fmt
    if e.names is not None:
        g.names = _copy_names(e.names)
    if e.mode is not None:
        g.mode = e.mode
        g._apply_mode_libs()
    g.recalc()


class UndoManager:
    def __init__(self) -> None:
        self.undo_stack: list[UndoEntry] = []
        self.redo_stack: list[UndoEntry] = []
        # The latest entry saved and the redo stack its save cleared, so
        # `discard_last` can put that redo stack back.
        self._cleared: tuple[UndoEntry, list[UndoEntry]] | None = None

    def _push(self, e: UndoEntry) -> None:
        self.undo_stack.append(e)
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self._cleared = (e, self.redo_stack)
        self.redo_stack = []

    def save_region(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> None:
        e = _new_entry(g, g._active)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                e.cells.append((c, r, cl.snapshot() if cl else Cell()))
        self._push(e)

    def save_cell(self, g: Grid, c: int, r: int) -> None:
        self.save_region(g, c, r, c, r)

    def save_global(self, g: Grid) -> None:
        """Snapshot workbook metadata only: default format, names and mode.

        For edits that touch no cell (`:gformat`, `:name`, `:unname`, `:mode`).
        """
        e = _new_entry(g, None)
        e.names = _copy_names(g.names)
        e.mode = g.mode
        self._push(e)

    def save_grid(self, g: Grid) -> None:
        """Snapshot the whole workbook, for structural and sheet operations."""
        e = _new_entry(g, None)
        e.names = _copy_names(g.names)
        e.mode = g.mode
        e.book = _book(g)
        e.active = g._active
        self._push(e)

    def discard_last(self) -> None:
        """Drop the most recent snapshot when the mutation it guarded did not
        happen, and put back the redo stack its save cleared."""
        if self.undo_stack:
            self._restore_redo(self.undo_stack.pop())

    def rollback(self, g: Grid) -> bool:
        """Restore and drop the most recent snapshot, for an operation that
        failed part-way. Creates no redo entry and does not dirty the grid."""
        if not self.undo_stack:
            return False
        e = self.undo_stack[-1]
        applied = self._apply(g, self.undo_stack, None)
        self._restore_redo(e)
        return applied

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._cleared = None

    def _restore_redo(self, e: UndoEntry) -> None:
        if self._cleared is not None and self._cleared[0] is e:
            self.redo_stack = self._cleared[1]
        self._cleared = None

    def _apply(
        self, g: Grid, from_stack: list[UndoEntry], to_stack: list[UndoEntry] | None
    ) -> bool:
        if not from_stack:
            return False
        e = from_stack[-1]

        # Cell keys are per-sheet, so go back to the entry's sheet first. This
        # also puts the view where the change being undone happened.
        if not self._enter_sheet(g, e):
            from_stack.pop()  # its sheet is gone; the entry can never apply
            return False

        # Capture the rollback snapshot before mutating, so a failed restore
        # can put the grid back and leave `e` on `from_stack` for a retry.
        re = _capture(g, e)
        try:
            _restore(g, e)
        except Exception:
            _restore(g, re)
            raise

        from_stack.pop()
        if to_stack is not None:
            to_stack.append(re)
        return True

    @staticmethod
    def _enter_sheet(g: Grid, e: UndoEntry) -> bool:
        """Make ``e``'s sheet active. False if that sheet is no longer in ``g``."""
        if e.sheet is None or e.sheet is g._active:
            return True
        if e.sheet not in g.sheets:
            return False
        g.active = g.sheets.index(e.sheet)
        return True

    def _step(self, g: Grid, from_stack: list[UndoEntry], to_stack: list[UndoEntry]) -> bool:
        applied = self._apply(g, from_stack, to_stack)
        if applied:
            g.dirty = 1
            self._cleared = None
        return applied

    def undo(self, g: Grid) -> bool:
        """Undo the last entry. False when there was nothing to apply."""
        return self._step(g, self.undo_stack, self.redo_stack)

    def redo(self, g: Grid) -> bool:
        """Redo the last undone entry. False when there was nothing to apply."""
        return self._step(g, self.redo_stack, self.undo_stack)
