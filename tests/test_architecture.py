"""Architectural fitness tests: the core must not depend on the view.

gridcalc is layered as a headless spreadsheet engine with a curses view on
top. Dependencies run one way -- `tui` imports the engine, never the
reverse -- which is what keeps the engine usable as a library, testable
without a terminal, and free to outlive the current TUI.

Nothing enforced that until this file. The layering held by habit, and
habit does not survive a hurried change. These tests are the boundary that
a package split would otherwise provide; keep them if the split ever
happens, since a shared package still needs the direction pinned.

The check is static (`ast` over the source) rather than import-based:
importing a module to inspect `sys.modules` would run its imports, which
both hides conditional imports and makes the test depend on import order.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "gridcalc"

# The headless core. Anything here must be importable on a machine with no
# terminal, no curses, and no TUI installed.
CORE_MODULES = (
    "engine.py",
    "display.py",
    "loader.py",
    "undo.py",
    "search.py",
    "commands.py",
    "opt.py",
    "goalseek.py",
    "config.py",
    "sandbox.py",
    "formula/ast_nodes.py",
    "formula/deps.py",
    "formula/errors.py",
    "formula/evaluator.py",
    "formula/lexer.py",
    "formula/parser.py",
    "libs/xlsx.py",
)

# Presentation layer. `tui` is the curses view; `web` (pywebview) is the
# experimental editable view (docs/gui.md). Both depend on the engine, never
# the reverse.
VIEW_MODULES = ("tui", "web")

# `keys.py` straddles the boundary by design: parsing a keyspec is pure data
# work the core needs (`config.py` calls it at load time), while resolving a
# spec to a keycode needs a live curses runtime. It may therefore use curses,
# but only behind a function-local import -- see
# `test_boundary_module_does_not_import_curses_at_module_scope`.
BOUNDARY_MODULES = ("keys.py",)

FORBIDDEN_IN_CORE = ("curses", "gridcalc.tui")

# The public core API a library consumer would import. Kept separate from
# CORE_MODULES because this is what the import-time test actually exercises.
CORE_IMPORTS = (
    "gridcalc.engine",
    "gridcalc.display",
    "gridcalc.loader",
    "gridcalc.undo",
    "gridcalc.config",
    "gridcalc.opt",
    "gridcalc.goalseek",
    "gridcalc.sandbox",
    "gridcalc.keys",
)


def _imported_names(path: Path) -> set[str]:
    """Every module name imported by `path`, including conditional and
    function-local imports (`ast.walk` reaches them; a top-level-only scan
    would not)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import: resolve to a dotted path under gridcalc
                # so `from ..tui import x` inside formula/ is caught.
                parts = path.relative_to(SRC).parts[:-1]
                base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                names.add(".".join(("gridcalc", *base, node.module or "")).rstrip("."))
            elif node.module:
                names.add(node.module)
    return names


def _violates(imported: str, forbidden: str) -> bool:
    """True when `imported` is `forbidden` or a submodule of it."""
    return imported == forbidden or imported.startswith(forbidden + ".")


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_does_not_import_the_view(module: str) -> None:
    path = SRC / module
    assert path.exists(), f"CORE_MODULES lists a module that no longer exists: {module}"
    offenders = sorted(
        name
        for name in _imported_names(path)
        for forbidden in FORBIDDEN_IN_CORE
        if _violates(name, forbidden)
    )
    assert not offenders, (
        f"{module} imports the view layer: {offenders}. The engine must stay "
        "headless -- move the shared code down into the core, or invert the "
        "call so the view depends on the engine rather than the reverse."
    )


def test_core_module_list_covers_every_non_view_module() -> None:
    """Guards the guard: a new core module added without being listed here
    would silently escape the import check."""
    view_paths = {SRC / m for m in VIEW_MODULES}
    on_disk = {
        p
        for p in SRC.rglob("*.py")
        if p.name != "__init__.py"
        and p.name != "__main__.py"
        and not any(p == v or v in p.parents for v in view_paths)
    }
    listed = {SRC / m for m in (*CORE_MODULES, *BOUNDARY_MODULES)}
    unlisted = sorted(str(p.relative_to(SRC)) for p in on_disk - listed)
    assert not unlisted, (
        f"new modules are unclassified: {unlisted}. Add each to CORE_MODULES, "
        "VIEW_MODULES, or BOUNDARY_MODULES so the layering check covers it."
    )


@pytest.mark.parametrize("module", BOUNDARY_MODULES)
def test_boundary_module_does_not_import_curses_at_module_scope(module: str) -> None:
    """A boundary module may call curses, but importing it must not require
    curses to be present. Only top-level imports are inspected here -- the
    function-local import is the sanctioned form."""
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    top_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module)
    assert "curses" not in top_level, (
        f"{module} imports curses at module scope. Move it inside the "
        "function that needs it -- `config.py` imports this module, and "
        "`config` must stay importable without a terminal."
    )


def test_importing_the_core_does_not_load_curses() -> None:
    """The assertion that actually matters, checked by behaviour rather than
    by reading source: a fresh interpreter that imports the public core must
    not end up with curses in `sys.modules`.

    This catches the leak regardless of how it is spelled -- a re-added
    module-level import, a new core module that pulls in the view, or a
    transitive path through some future third module. It runs in a
    subprocess because this test session has already imported curses.
    """
    program = (
        "import sys\n"
        f"for name in {CORE_IMPORTS!r}:\n"
        "    __import__(name)\n"
        "leaked = 'curses' in sys.modules\n"
        "print('LEAKED' if leaked else 'CLEAN')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"core import failed:\n{result.stderr}"
    assert result.stdout.strip() == "CLEAN", (
        "importing the core pulled curses into sys.modules. Some core module "
        "now depends on the view layer at import time; "
        f"stderr:\n{result.stderr}"
    )


def test_view_may_import_the_core() -> None:
    """The permitted direction, asserted so the rule reads as a direction
    rather than a blanket ban on coupling."""
    imported = _imported_names(SRC / "tui" / "commands.py")
    assert any(
        _violates(name, "gridcalc.engine") or name.endswith("engine") for name in imported
    ), "expected the view to import the engine; the extractor is probably broken"
