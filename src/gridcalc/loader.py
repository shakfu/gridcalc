"""Workbook loading and saving shared by frontends -- engine + sandbox only, no view.

A frontend (the web view today, `gridcalc.web`) needs to open a workbook and
show a first-run demo. That logic is frontend-neutral, so it lives here below
the view boundary rather than inside a view. Keeping it here also means a
second frontend could reuse it unchanged. `tests/test_architecture.py` guards
this module curses-free, the same as the rest of the core.
"""

from __future__ import annotations

from pathlib import Path

from . import sandbox
from .engine import FORMULA, Grid, Mode
from .sandbox import FileInfo, LoadPolicy, inspect_file


def load_workbook(path: str | Path, policy: LoadPolicy | None = None) -> Grid:
    """Load a ``.json``, ``.xlsx``, or ``.csv`` workbook (format by extension).

    ``policy`` decides what a JSON file's code block is allowed to do; the
    default is formulas only, so opening a file never runs code the user has
    not been asked about. A frontend that *has* asked -- see
    :func:`needs_trust` and the web view's trust dialog -- passes the policy
    the answer produced. Cells depending on a code block that was not loaded
    show their error state, the safe and honest outcome. ``.xlsx`` and ``.csv``
    carry no code path. The workbook is recalculated before return.
    """
    p = str(path)
    low = p.lower()
    g = Grid()
    if low.endswith(".xlsx"):
        rc = g.xlsxload(p)
    elif low.endswith(".csv"):
        rc = g.csvload(p)
    else:
        rc = g.jsonload(p, policy=policy or _default_policy(p))
    if rc < 0:
        raise OSError(_failure("could not load workbook", p, g))
    g.filename = p
    g.recalc()
    return g


def save_workbook(g: Grid, path: str | Path) -> str:
    """Write ``g`` to ``path`` in the format its extension names; return that format.

    ``.xlsx`` and ``.csv`` go through the grid's exporters, anything else is
    JSON. Raises ``OSError`` when the write fails. :func:`save_losses` says
    what the non-JSON formats would drop.
    """
    p = str(path)
    low = p.lower()
    if low.endswith(".xlsx"):
        fmt, rc = "xlsx", g.xlsxsave(p)
    elif low.endswith(".csv"):
        fmt, rc = "csv", g.csvsave(p)
    else:
        fmt, rc = "json", g.jsonsave(p)
    if rc < 0:
        raise OSError(_failure("could not write workbook", p, g))
    return fmt


def _failure(what: str, path: str, g: Grid) -> str:
    return f"{what}: {path}" + (f" ({g.io_error})" if g.io_error else "")


def save_losses(g: Grid, path: str | Path) -> list[str]:
    """What :func:`save_workbook` would not write for ``g`` at ``path``.

    Empty for JSON. xlsx keeps every sheet but not the code block, saved
    models or names, and keeps formulas only in EXCEL mode. csv keeps the
    active sheet's values only.
    """
    low = str(path).lower()
    csv = low.endswith(".csv")
    if not (csv or low.endswith(".xlsx")):
        return []
    sheets = [g._active] if csv else g.sheets
    lost: list[str] = []
    if (csv or g.mode != Mode.EXCEL) and any(
        cl.type == FORMULA for s in sheets for cl in s._cells.values()
    ):
        lost.append("formulas")
    if csv and len(g.sheets) > 1:
        lost.append("other sheets")
    if g.names:
        lost.append("names")
    if g.models:
        lost.append("models")
    if g.code or g.withheld_code:
        lost.append("code")
    return lost


def _default_policy(path: str) -> LoadPolicy:
    """What to load when no frontend has asked anyone.

    Formulas only while the sandbox is on -- opening a file is not consent to
    run what is in it. With the sandbox off there is nothing to consent to: no
    prompt would be shown, and withholding the code would leave the workbook
    broken for the one user who has said they want it run. That is the same
    rule the curses frontend applies at startup.
    """
    if sandbox.SANDBOX_ENABLED:
        return LoadPolicy.formulas_only()
    info = inspect_file(path)
    if info is None or not (info.has_code or info.requires):
        return LoadPolicy.formulas_only()
    return LoadPolicy.trust_all(info.requires)


def needs_trust(path: str | Path) -> FileInfo | None:
    """The file's :class:`FileInfo` when opening it is a trust decision.

    A decision exists when the file carries a code block or names modules to
    import, and the sandbox is on -- with it off, nothing is withheld and there
    is nothing to ask about. ``None`` means load it without a prompt: no code,
    an unparseable file (the load reports that failure itself), or a format
    with no code path at all.
    """
    p = str(path)
    if p.lower().endswith((".xlsx", ".csv")) or not sandbox.SANDBOX_ENABLED:
        return None
    info = inspect_file(p)
    if info is None or not (info.has_code or info.requires):
        return None
    return info


def demo_grid() -> Grid:
    """A small self-contained workbook shown when no file is given."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcell(0, 0, "gridcalc demo")
    headers = ["Item", "Qty", "Price", "Total"]
    for c, label in enumerate(headers):
        g.setcell(c, 2, label)
    rows = [("Widget", 10, 2.5), ("Gadget", 4, 9.0), ("Gizmo", 7, 3.25)]
    for i, (name, qty, price) in enumerate(rows):
        r = 3 + i
        g.setcell(0, r, name)
        g.setcell(1, r, str(qty))
        g.setcell(2, r, str(price))
        g.setcell(3, r, f"=B{r + 1}*C{r + 1}")
    g.setcell(0, 6, "Total")
    g.setcell(3, 6, "=SUM(D4:D6)")
    g.recalc()
    g.filename = ""
    return g
