"""Workbook loading and saving shared by frontends -- engine + sandbox only, no view.

A frontend (the web view today, `gridcalc.web`) needs to open a workbook and
show a first-run demo. That logic is frontend-neutral, so it lives here below
the view boundary rather than inside a view. Keeping it here also means a
second frontend could reuse it unchanged. `tests/test_architecture.py` guards
this module curses-free, the same as the rest of the core.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
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
        # A CSV names no mode. The PYTHON default would eval its formulas unprompted.
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
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

    Empty for JSON. xlsx keeps every sheet and named range but not the code
    block or saved models, and keeps formulas only in EXCEL mode. Saving over
    an existing xlsx also drops what :func:`xlsx_extras` finds in it. csv keeps the
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
    if csv and g.names:
        lost.append("names")
    if g.models:
        lost.append("models")
    if g.code or g.withheld_code:
        lost.append("code")
    if not csv and Path(path).is_file():
        lost += xlsx_extras(path)
    return lost


# Worksheet markup gridcalc never writes, and what a user calls it.
_SHEET_MARKERS = (
    (b"<mergeCell ", "merged cells"),
    (b"<conditionalFormatting", "conditional formatting"),
    (b"<dataValidation ", "data validation"),
    (b"<hyperlink ", "hyperlinks"),
    (b"<pane ", "frozen panes"),
    (b'customHeight="1"', "row heights"),
)
# Package parts gridcalc never writes.
_PART_PREFIXES = (
    ("xl/comments", "comments"),
    ("xl/threadedComments/", "comments"),
    ("xl/charts/", "charts"),
    ("xl/media/", "images"),
    ("xl/pivotTables/", "pivot tables"),
    ("xl/tables/", "tables"),
    ("xl/vbaProject.bin", "macros"),
)


def xlsx_extras(path: str | Path) -> list[str]:
    """What the xlsx at ``path`` holds that gridcalc cannot write back.

    Saving over the file rewrites it from the workbook, so these are lost.
    Detection is by markup: a style defined in the file counts even if no cell
    uses it. Returns an empty list for a file that cannot be read. Never raises.
    """
    from .dates import is_date_format
    from .engine import _XLSX_NS, _spec_for_xlsx_code

    found: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            for prefix, label in _PART_PREFIXES:
                if any(n.startswith(prefix) for n in names) and label not in found:
                    found.append(label)
            sheets = [n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")]
            data = b"".join(z.read(n) for n in sheets)
            found += [label for marker, label in _SHEET_MARKERS if marker in data]
            if "xl/styles.xml" in names:
                # ElementTree does not resolve external entities.
                styles = ET.fromstring(z.read("xl/styles.xml"))  # noqa: S314
                found += _style_extras(styles, _XLSX_NS)
                codes = [el.get("formatCode", "") for el in styles.iter(f"{_XLSX_NS}numFmt")]
                if any(
                    c and not is_date_format(c) and not _spec_for_xlsx_code(c, 0) for c in codes
                ):
                    found.append("number formats such as currency")
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return []
    return found


def _style_extras(root: ET.Element, ns: str) -> list[str]:
    """Style-table features beyond bold, italic, underline and left/right alignment."""
    out: list[str] = []
    fonts = root.find(f"{ns}fonts")
    if fonts is not None and len(fonts) > 1:
        # gridcalc copies font 0 and changes only b/i/u.
        def base(font: ET.Element) -> list[tuple[str, dict[str, str]]]:
            return [
                (child.tag, dict(child.attrib))
                for child in font
                if child.tag not in (f"{ns}b", f"{ns}i", f"{ns}u")
            ]

        if any(base(f) != base(fonts[0]) for f in fonts):
            out.append("font sizes, colours or faces")
    fills = root.find(f"{ns}fills")
    if fills is not None and len(fills) > 2:  # 0 none and 1 gray125 are mandatory
        out.append("cell fills")
    borders = root.find(f"{ns}borders")
    if borders is not None and any(side.get("style") for b in borders for side in b):
        out.append("borders")
    xfs = root.find(f"{ns}cellXfs")
    for xf in [] if xfs is None else xfs:
        al = xf.find(f"{ns}alignment")
        if al is not None and (
            al.get("horizontal") not in (None, "general", "left", "right")
            or al.get("vertical") not in (None, "bottom")
            or al.get("wrapText") in ("1", "true")
        ):
            out.append("centred, vertical or wrapped alignment")
            break
    return out


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
    return LoadPolicy.trust_all(info.requires if info else None)


def needs_trust(path: str | Path) -> FileInfo | None:
    """The file's :class:`FileInfo` when opening it is a trust decision.

    A decision exists when the file carries a code block, names modules to
    import, or has PYTHON-mode formulas, and the sandbox is on -- with it off,
    nothing is withheld and there is nothing to ask about. ``None`` means load
    it without a prompt: no code, an unparseable file (the load reports that
    failure itself), or a format with no code path at all.
    """
    p = str(path)
    if p.lower().endswith((".xlsx", ".csv")) or not sandbox.SANDBOX_ENABLED:
        return None
    info = inspect_file(p)
    if info is None or not info.trust_needed:
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
