"""Frontend-neutral command registry -- the shared half of `:` commands.

Both frontends used to implement each command twice: the TUI as a branch of
`cmdexec`'s name dispatch, the web view as an `Api` method plus a palette
entry, with nothing tying the two together. Behaviour was duplicated, the
parity table in `docs/web.md` was kept by hand, and a command added to one
frontend was invisible to the other.

This module holds the operation itself: a name, its aliases, the arguments it
takes, and a function over a :class:`Context`. Nothing here imports a view --
`tests/test_architecture.py` keeps it that way -- so `tui/commands.py`
dispatches registry commands by typed name and `web.Api` dispatches them by
palette selection, over one implementation.

**The split is: the view resolves arguments, the registry does the work.**
A terminal prompts on the status line, a GUI opens a field, and both then hand
the same strings to the same function. That is deliberately where the seam
sits, because argument *collection* is exactly the part that cannot be shared
-- everything after it can.

What stays view-owned, and why it is not a gap: commands whose whole body is
interaction. `:e` shells out to `$EDITOR`, `:view` draws a scrollable table,
`:sheets` opens a picker, `:q` asks before quitting, `:m`/`:r` run modal
range prompts, `:csv`/`:xlsx`/`:pd` prompt for a path. Those keep living in
`tui/commands.py`; a GUI equivalent is a different interaction, not a shared
function.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .engine import (
    EMPTY,
    FORMULA,
    MAXNAMES,
    NCOL,
    NROW,
    NUM,
    Cell,
    Grid,
    Mode,
    NamedRange,
    col_name,
    ref,
)
from .undo import UndoManager


@dataclass(frozen=True)
class Arg:
    """One argument a command takes.

    ``kind`` is a hint for whoever collects the value -- a GUI can show a
    number field for ``int`` or prefill a range from the selection for
    ``range`` -- not a validator. Validation belongs to the command, which is
    the only thing that knows what a usable value is.
    """

    name: str
    help: str = ""
    required: bool = True
    kind: str = "text"  # text | int | ref | range | choice
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    """What a command reports back.

    One shape for both frontends: the TUI shows ``message`` on the status
    line, the web view returns it across the bridge. ``ok=False`` means
    nothing was changed and ``message`` says why.
    """

    ok: bool = True
    message: str = ""
    # True when the workbook was modified, so a frontend knows to mark it
    # dirty and refetch. Separate from `ok`: a command can succeed and change
    # nothing (`:names` lists, `:mode` to the current mode is a no-op).
    changed: bool = False
    # List-shaped output, for the commands that answer with a listing rather
    # than a sentence. Both are filled: `message` is the one-line form a status
    # bar can hold, `lines` the full form a pager or panel can show. Sharing
    # the *data* this way is what keeps the two presentations from drifting.
    lines: tuple[str, ...] = ()


def ok(message: str = "", *, changed: bool = False, lines: Sequence[str] = ()) -> Result:
    return Result(ok=True, message=message, changed=changed, lines=tuple(lines))


def fail(message: str) -> Result:
    return Result(ok=False, message=message)


@dataclass
class Context:
    """Everything a command acts on.

    ``selection`` is ``(c1, r1, c2, r2)`` inclusive and **column-first**,
    matching the engine and `UndoManager.save_region`. The web `Api` speaks
    row-first, so it converts on the way in -- the mismatch has bitten before,
    which is why the convention is stated here and normalized in one place.
    None means "no range selected"; commands that can fall back to the cursor
    cell do so themselves.
    """

    grid: Grid
    undo: UndoManager
    args: Sequence[str] = field(default_factory=tuple)
    selection: tuple[int, int, int, int] | None = None

    def arg(self, i: int, default: str = "") -> str:
        """Positional argument ``i``, or ``default`` when not supplied."""
        return self.args[i] if i < len(self.args) and self.args[i] else default

    def rect(self) -> tuple[int, int, int, int]:
        """The selection, or the cursor cell as a 1x1 rectangle."""
        if self.selection is not None:
            c1, r1, c2, r2 = self.selection
            return (min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))
        g = self.grid
        return (g.cc, g.cr, g.cc, g.cr)


# -- helpers shared by the command bodies -------------------------------


def parse_range(spec: str) -> tuple[int, int, int, int] | None:
    """Parse ``A1`` or ``A1:B3`` to ``(c1, r1, c2, r2)``, normalized.

    Rejects trailing garbage, so ``A1junk`` is not silently read as ``A1``.
    """
    s = (spec or "").strip().replace("$", "")
    if not s:
        return None
    a, _, b = s.partition(":")
    b = b or a
    ra, rb = ref(a.strip()), ref(b.strip())
    if ra is None or rb is None:
        return None
    na, ca, rowa = ra
    nb, cb, rowb = rb
    if na != len(a.strip()) or nb != len(b.strip()):
        return None
    c1, c2 = sorted((ca, cb))
    r1, r2 = sorted((rowa, rowb))
    return (c1, r1, c2, r2)


def range_a1(c1: int, r1: int, c2: int, r2: int) -> str:
    """Render a rectangle as ``A1`` or ``A1:B3``."""
    start = f"{col_name(c1)}{r1 + 1}"
    if (c1, r1) == (c2, r2):
        return start
    return f"{start}:{col_name(c2)}{r2 + 1}"


def valid_name(name: str) -> bool:
    """A letter, then letters/digits/underscores."""
    return bool(name) and name[0].isalpha() and all(ch.isalnum() or ch == "_" for ch in name)


def apply_format(g: Grid, undo: UndoManager, c1: int, r1: int, c2: int, r2: int, spec: str) -> bool:
    """Apply a format ``spec`` to the non-empty cells of a rectangle.

    Four shapes, in the order the TUI's `:format` has always accepted them:
    a style string drawn from ``bui`` (toggles, so applying `b` twice is
    unbold), a single number-format char from ``LRIGD$%*``, a Python format
    spec like ``,.2f``, or an xlsx date format like ``yyyy-mm-dd``. Returns
    False only for an empty spec -- anything else is stored in ``fmtstr``,
    since that is the open-ended case, and the display layer decides at render
    time which of the two languages it is written in.
    """
    if not spec:
        return False
    undo.save_region(g, c1, r1, c2, r2)
    style = all(ch in "bui" for ch in spec)
    single = len(spec) == 1 and spec.upper() in "LRIGD$%*"
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cl = g.cell(c, r)
            if not cl or cl.type == EMPTY:
                continue
            if style:
                for ch in spec:
                    if ch == "b":
                        cl.bold = 1 - cl.bold
                    elif ch == "u":
                        cl.underline = 1 - cl.underline
                    elif ch == "i":
                        cl.italic = 1 - cl.italic
            elif single:
                cl.fmt = spec.upper()
                cl.fmtstr = ""
            else:
                cl.fmtstr = spec[:31]
                cl.fmt = ""
    return True


def sort_rows(
    g: Grid, undo: UndoManager, c1: int, r1: int, c2: int, r2: int, sort_col: int, descending: bool
) -> None:
    """Reorder the rows of a rectangle by the values in ``sort_col``.

    Ordering is numbers before labels before empties: a mixed column has no
    single natural order, and putting blanks last keeps a partially filled
    column readable. Whole rows move together -- cells are lifted as snapshots
    and written back -- so a row's cells stay aligned with each other.

    Formula *text* is left exactly as written and is not re-pointed at the new
    row: `=A2*2` moved to row 5 still reads A2. That matches the TUI's
    long-standing behaviour, and is the honest one for a sort, where there is
    no single answer to what a relative reference should now mean.
    """
    undo.save_grid(g)
    rows: list[tuple[float, str, list[tuple[int, Cell | None]]]] = []
    for r in range(r1, r2 + 1):
        key_cl = g.cell(sort_col, r)
        if key_cl and key_cl.type in (NUM, FORMULA) and not math.isnan(key_cl.val):
            key_val = key_cl.val
        else:
            key_val = float("inf")
        key_text = key_cl.text if key_cl and key_cl.type != EMPTY else ""
        lifted: list[tuple[int, Cell | None]] = []
        for c in range(c1, c2 + 1):
            cl = g.cell(c, r)
            lifted.append((c, cl.snapshot() if cl else None))
        rows.append((key_val, key_text, lifted))

    def key(item: tuple[float, str, list[tuple[int, Cell | None]]]) -> tuple[int, float, str]:
        val, text, _ = item
        if val < float("inf"):
            return (0, val, "")
        if text:
            return (1, 0.0, text.lower())
        return (2, 0.0, "")

    rows.sort(key=key, reverse=descending)
    for offset, (_, _, lifted) in enumerate(rows):
        target = r1 + offset
        for c, snap in lifted:
            if snap is None:
                g._cells.pop((c, target), None)
            else:
                g._ensure_cell(c, target).copy_from(snap)
    g.recalc()
    g.dirty = 1


# -- the commands -------------------------------------------------------


def _blank(ctx: Context) -> Result:
    g = ctx.grid
    c1, r1, c2, r2 = ctx.rect()
    ctx.undo.save_region(g, c1, r1, c2, r2)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            g.setcell(c, r, "")
    g.recalc()
    return ok(changed=True)


def _format(ctx: Context) -> Result:
    spec = ctx.arg(0)
    if not spec:
        return fail(
            "give a format: b u i, one of LRIGD$%*, a Python spec like ,.2f, "
            "or a date format like yyyy-mm-dd"
        )
    c1, r1, c2, r2 = ctx.rect()
    if not apply_format(ctx.grid, ctx.undo, c1, r1, c2, r2, spec):
        return fail(f"unusable format: {spec}")
    return ok(changed=True)


def _gformat(ctx: Context) -> Result:
    ch = ctx.arg(0)[:1].upper()
    if ch not in "LRIGD$%*":
        return fail("invalid format -- use one of L R I G D $ % *")
    ctx.undo.save_global(ctx.grid)
    ctx.grid.fmt = ch
    return ok(f"default format {ch}", changed=True)


def _insert_lines(ctx: Context, axis: str) -> Result:
    """Insert as many rows/columns as the selection spans, at its near edge.

    A selection-sized insert is what the delete side has always done, and what
    the menu label in the web view promises; inserting exactly one row while
    three are selected was the odd one out.
    """
    g = ctx.grid
    c1, r1, c2, r2 = ctx.rect()
    at, count = (r1, r2 - r1 + 1) if axis == "row" else (c1, c2 - c1 + 1)
    limit = NROW if axis == "row" else NCOL
    if not (0 <= at < limit):
        return fail(f"out of range: {at}")
    word = "row" if axis == "row" else "column"
    # Check the whole insert before touching anything: the sheet is a fixed
    # NROW x NCOL grid, so an insert near the end used to push the last lines
    # off the edge and drop them while still reporting success. Refusing
    # up-front also keeps this all-or-nothing -- no half-applied insert, and no
    # undo entry recorded for an edit that never happened.
    if not g.can_insert("R" if axis == "row" else "C", at, count):
        return fail(
            f"cannot insert {count} {word}{'s' if count > 1 else ''}: "
            f"that would push data off the end of the sheet"
        )
    ctx.undo.save_grid(g)
    op = g.insertrow if axis == "row" else g.insertcol
    for _ in range(count):
        op(at)
    g.recalc()
    return ok(f"inserted {count} {word}{'s' if count > 1 else ''}", changed=True)


def _delete_lines(ctx: Context, axis: str) -> Result:
    g = ctx.grid
    c1, r1, c2, r2 = ctx.rect()
    lo, hi = (r1, r2) if axis == "row" else (c1, c2)
    ctx.undo.save_grid(g)
    op = g.deleterow if axis == "row" else g.deletecol
    # Bottom-up, so each call sees indices that have not yet shifted.
    for i in range(hi, lo - 1, -1):
        op(i)
    g.recalc()
    word = "row" if axis == "row" else "column"
    n = hi - lo + 1
    return ok(f"deleted {n} {word}{'s' if n > 1 else ''}", changed=True)


def _name(ctx: Context) -> Result:
    g = ctx.grid
    key = ctx.arg(0).strip()
    if not valid_name(key):
        return fail(f"not a usable name: {key!r} -- a letter, then letters/digits/underscores")
    if parse_range(key) is not None:
        return fail(f"{key} is a cell reference, not a name")
    spec = ctx.arg(1)
    rect = parse_range(spec) if spec else ctx.rect()
    if rect is None:
        return fail(f"bad range: {spec}")
    c1, r1, c2, r2 = rect
    for nr in g.names:
        if nr.name == key:
            nr.c1, nr.r1, nr.c2, nr.r2 = c1, r1, c2, r2
            g.recalc()
            return ok(f"{key} = {range_a1(c1, r1, c2, r2)}", changed=True)
    if len(g.names) >= MAXNAMES:
        return fail(f"too many names (limit {MAXNAMES})")
    g.names.append(NamedRange(key, c1, r1, c2, r2))
    g.recalc()
    return ok(f"{key} = {range_a1(c1, r1, c2, r2)}", changed=True)


def _names(ctx: Context) -> Result:
    listed = sorted(ctx.grid.names, key=lambda n: n.name.lower())
    if not listed:
        return ok("no named ranges")
    pairs = [(nr.name, range_a1(nr.c1, nr.r1, nr.c2, nr.r2)) for nr in listed]
    return ok(
        "  ".join(f"{name}={rng}" for name, rng in pairs),
        lines=[f"{name} = {rng}" for name, rng in pairs],
    )


def _unname(ctx: Context) -> Result:
    target = ctx.arg(0).strip()
    g = ctx.grid
    for i, nr in enumerate(g.names):
        if nr.name == target:
            g.names.pop(i)
            g.recalc()
            g.dirty = 1
            return ok(f"removed {target}", changed=True)
    return fail(f"no such name: {target}")


def _sort(ctx: Context) -> Result:
    g = ctx.grid
    c1, r1, c2, r2 = ctx.rect()
    if ctx.selection is None:
        # No selection: sort the sheet's whole data extent, as `:sort` does.
        maxr = maxc = -1
        for (c, r), cl in g._cells.items():
            if cl.type != EMPTY:
                maxr = max(maxr, r)
                maxc = max(maxc, c)
        if maxr < 0:
            return ok("nothing to sort")
        c1, r1, c2, r2 = 0, 0, maxc, maxr

    col_spec = ctx.arg(0)
    if col_spec:
        parsed = ref(col_spec.strip().upper() + "1")
        if parsed is None:
            return fail(f"invalid column: {col_spec}")
        sort_col = parsed[1]
    else:
        sort_col = ctx.selection[0] if ctx.selection is not None else g.cc
    if not (c1 <= sort_col <= c2):
        return fail(f"column {col_name(sort_col)} is outside the sorted range")

    descending = ctx.arg(1).lower() in ("desc", "d", "reverse", "r")
    sort_rows(g, ctx.undo, c1, r1, c2, r2, sort_col, descending)
    order = "descending" if descending else "ascending"
    return ok(f"sorted {range_a1(c1, r1, c2, r2)} by {col_name(sort_col)} {order}", changed=True)


def _mode(ctx: Context) -> Result:
    g = ctx.grid
    arg = ctx.arg(0).strip()
    if not arg:
        return ok(f"mode: {g.mode.name.lower()} ({int(g.mode)})")
    parsed = Mode.parse(arg)
    if parsed is None:
        return fail("invalid mode -- use 1|excel, 2|hybrid, 3|python")
    if parsed == g.mode:
        return ok(f"already {parsed.name.lower()}")
    errors = g.validate_for_mode(parsed)
    if errors:
        return fail(f"cannot switch to {parsed.name.lower()}: {errors[0]}")
    g.mode = parsed
    g._apply_mode_libs()
    g.recalc()
    return ok(f"mode: {parsed.name.lower()}", changed=True)


def _title(ctx: Context) -> Result:
    """Freeze rows/columns at the cursor (the TUI's `:tv`/`:th`/`:tb`/`:tn`)."""
    g = ctx.grid
    ch = ctx.arg(0)[:1].upper()
    if ch == "V":
        g.tc, g.tr = g.cc + 1, 0
        g.cc += 1
    elif ch == "H":
        g.tr, g.tc = g.cr + 1, 0
        g.cr += 1
    elif ch == "B":
        g.tc, g.tr = g.cc + 1, g.cr + 1
        g.cc += 1
        g.cr += 1
    elif ch == "N":
        g.tc = g.tr = g.vc = g.vr = 0
    else:
        return fail("use v (vertical), h (horizontal), b (both), or n (none)")
    return ok(changed=True)


def _recalc(ctx: Context) -> Result:
    """Recompute every formula (the TUI's `!`).

    Not marked as changing the workbook: asking for the values you already had
    is not an edit, so it must not dirty a saved file.
    """
    ctx.grid.recalc()
    return ok("recalculated")


@dataclass(frozen=True)
class Command:
    """One shared command. ``run`` does the work; the view collects ``args``."""

    name: str
    title: str
    group: str
    run: Callable[[Context], Result]
    aliases: tuple[str, ...] = ()
    args: tuple[Arg, ...] = ()
    # Acts on the selection (falling back to the cursor cell). A GUI uses this
    # to hide the command when there is nothing to act on.
    needs_selection: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


COMMANDS: tuple[Command, ...] = (
    Command(
        name="blank",
        aliases=("b",),
        title="Clear cells",
        group="Edit",
        needs_selection=True,
        run=_blank,
    ),
    Command(
        name="format",
        aliases=("f",),
        title="Format cells",
        group="Format",
        needs_selection=True,
        args=(
            Arg(
                "spec",
                "b u i, one of LRIGD$%*, a Python spec like ,.2f, or a date format like yyyy-mm-dd",
            ),
        ),
        run=_format,
    ),
    Command(
        name="gformat",
        aliases=("gf",),
        title="Workbook default number format",
        group="Format",
        args=(Arg("format", "one of L R I G D $ % *", kind="choice", choices=tuple("LRIGD$%*")),),
        run=_gformat,
    ),
    Command(
        name="insrow",
        aliases=("ir",),
        title="Insert rows",
        group="Insert",
        needs_selection=True,
        run=lambda ctx: _insert_lines(ctx, "row"),
    ),
    Command(
        name="inscol",
        aliases=("ic",),
        title="Insert columns",
        group="Insert",
        needs_selection=True,
        run=lambda ctx: _insert_lines(ctx, "col"),
    ),
    Command(
        name="delrow",
        aliases=("dr",),
        title="Delete rows",
        group="Insert",
        needs_selection=True,
        run=lambda ctx: _delete_lines(ctx, "row"),
    ),
    Command(
        name="delcol",
        aliases=("dc",),
        title="Delete columns",
        group="Insert",
        needs_selection=True,
        run=lambda ctx: _delete_lines(ctx, "col"),
    ),
    Command(
        name="name",
        title="Define name for selection",
        group="Name",
        needs_selection=True,
        args=(
            Arg("name", "the name to define"),
            Arg("range", "A1:B3 (defaults to the selection)", required=False, kind="range"),
        ),
        run=_name,
    ),
    Command(name="names", title="List named ranges", group="Name", run=_names),
    Command(
        name="unname",
        title="Delete named range",
        group="Name",
        args=(Arg("name", "the name to remove"),),
        run=_unname,
    ),
    Command(
        name="sort",
        title="Sort rows",
        group="Data",
        needs_selection=True,
        args=(
            Arg("column", "column letter to sort by", required=False, kind="ref"),
            Arg("direction", "asc or desc", required=False, kind="choice", choices=("asc", "desc")),
        ),
        run=_sort,
    ),
    Command(
        name="mode",
        title="Formula mode",
        group="Data",
        args=(
            Arg(
                "mode",
                "excel, hybrid, or python",
                required=False,
                kind="choice",
                choices=("excel", "hybrid", "python"),
            ),
        ),
        run=_mode,
    ),
    Command(
        name="title",
        title="Freeze panes at cursor",
        group="View",
        args=(
            Arg(
                "which",
                "v vertical, h horizontal, b both, n none",
                kind="choice",
                choices=("v", "h", "b", "n"),
            ),
        ),
        run=_title,
    ),
    Command(name="recalc", title="Recalculate", group="Data", run=_recalc),
)


BY_NAME: dict[str, Command] = {n: c for c in COMMANDS for n in c.names}


def lookup(name: str) -> Command | None:
    """Find a command by canonical name or alias, case-insensitively."""
    return BY_NAME.get((name or "").strip().lower())


def run(
    name: str,
    grid: Grid,
    undo: UndoManager,
    args: Sequence[str] = (),
    selection: tuple[int, int, int, int] | None = None,
) -> Result:
    """Look up and run a command, reporting an unknown name as a failure."""
    cmd = lookup(name)
    if cmd is None:
        return fail(f"unknown command: {name}")
    return cmd.run(Context(grid=grid, undo=undo, args=tuple(args), selection=selection))


def describe() -> list[dict[str, Any]]:
    """The registry as plain data, for a frontend that has to build a menu.

    JSON-serializable on purpose: the web view sends this straight across the
    pywebview bridge and builds its palette entries from it, so a command
    registered here shows up there without a second edit.
    """
    return [
        {
            "name": cmd.name,
            "aliases": list(cmd.aliases),
            "title": cmd.title,
            "group": cmd.group,
            "needs_selection": cmd.needs_selection,
            "args": [
                {
                    "name": a.name,
                    "help": a.help,
                    "required": a.required,
                    "kind": a.kind,
                    "choices": list(a.choices),
                }
                for a in cmd.args
            ],
        }
        for cmd in COMMANDS
    ]
