"""Undo/redo history and the cell clipboard."""

from __future__ import annotations

from ..display import cell_clip_value
from ..engine import EMPTY, NCOL, NROW, Cell, Grid
from .osclip import SystemClipboard, rows_to_tsv, tsv_to_rows

UNDO_MAX = 64


def _norm_clip(text: str) -> str:
    """Fold line endings and drop trailing newlines so a value we pushed to
    the OS clipboard compares equal to what a paste tool hands back."""
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


class Clipboard:
    """Cell copy/paste with an internal store and optional OS interchange.

    The internal store keeps full fidelity (formula text plus formatting).
    When a :class:`SystemClipboard` is supplied, ``yank`` additionally
    pushes a TSV of display values to the operating-system clipboard, and
    ``paste`` pulls in content copied from another program -- detected as
    OS-clipboard text differing from what this instance last pushed. Its own
    copies round-trip through the internal store, preserving formulas.
    """

    def __init__(self, system: SystemClipboard | None = None) -> None:
        self.cells: list[tuple[int, int, Cell]] = []  # (dc, dr, snapshot) offsets from origin
        self.width: int = 0
        self.height: int = 0
        self.system = system
        # The TSV we last wrote to the OS clipboard, used to tell our own
        # copy apart from content copied elsewhere.
        self._last_pushed: str | None = None

    def yank(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> int:
        """Copy a rectangular region of cells. Returns count of non-empty cells copied."""
        self.cells = []
        self.width = c2 - c1 + 1
        self.height = r2 - r1 + 1
        count = 0
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                if cl and cl.type != EMPTY:
                    self.cells.append((c - c1, r - r1, cl.snapshot()))
                    count += 1
        self._push_to_system(g, c1, r1, c2, r2)
        return count

    def _push_to_system(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> None:
        if self.system is None:
            return
        rows = [
            [cell_clip_value(g.cell(c, r)) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)
        ]
        tsv = rows_to_tsv(rows)
        if self.system.copy_text(tsv):
            self._last_pushed = tsv

    def paste(self, g: Grid, undo: UndoManager, dc: int, dr: int) -> None:
        """Paste at (dc, dr). Prefers external OS-clipboard content when
        present; otherwise pastes the internal store verbatim (formulas and
        formatting included)."""
        if self._paste_from_system(g, undo, dc, dr):
            return
        if not self.cells:
            return
        undo.save_region(g, dc, dr, dc + self.width - 1, dr + self.height - 1)
        for oc, orr, snap in self.cells:
            tc, tr = dc + oc, dr + orr
            if 0 <= tc < NCOL and 0 <= tr < NROW:
                g.setcell(tc, tr, snap.text)
                cl = g.cell(tc, tr)
                if cl:
                    cl.bold = snap.bold
                    cl.underline = snap.underline
                    cl.italic = snap.italic
                    cl.fmt = snap.fmt
                    cl.fmtstr = snap.fmtstr
        g.recalc()

    def _paste_from_system(self, g: Grid, undo: UndoManager, dc: int, dr: int) -> bool:
        """Paste external OS-clipboard content as values if it differs from
        our last push. Returns True when it handled the paste."""
        if self.system is None:
            return False
        text = self.system.paste_text()
        if text is None or _norm_clip(text) == "":
            return False
        if _norm_clip(text) == _norm_clip(self._last_pushed or ""):
            return False  # our own copy -> use the full-fidelity internal store
        rows = tsv_to_rows(text)
        if not rows:
            return False
        width = max(len(row) for row in rows)
        c2 = min(dc + width - 1, NCOL - 1)
        r2 = min(dr + len(rows) - 1, NROW - 1)
        undo.save_region(g, dc, dr, c2, r2)
        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                if val == "":
                    continue
                tc, tr = dc + ci, dr + ri
                if 0 <= tc < NCOL and 0 <= tr < NROW:
                    g.setcell(tc, tr, val)
        g.recalc()
        return True

    @property
    def empty(self) -> bool:
        return len(self.cells) == 0


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
