"""Conformance tests between the user manual and the TUI dispatch tables.

The `u`/`Ctrl-R` undo bug shipped because the docs advertised bindings
the grid keyloop never implemented, and the curses layer is too thinly
covered (`tui/__init__.py` ~15%, `tui/commands.py` ~41%) for a unit test
to have noticed. These tests close that class of drift: every `:` command
and every key the manual advertises must exist in the dispatch chain, and
every command the dispatcher accepts must be documented or declared an
intentional alias.

The manual is the MkDocs site's user-facing pages plus README.md, which
between them replaced the single long README. Design notes, the changelog,
and the generated API pages are deliberately out of scope: they describe
proposals and history rather than the shipped UI, so a command named there
is not a promise to the user.

Both dispatch chains are read statically via `ast` rather than executed.
Executing them would mean actually running `:q`, `:w`, and `:e` (which
spawns `$EDITOR`), and the point here is coverage of the *mapping*, not of
the handlers -- those have their own tests.

If either chain is ever refactored out of its current `if`/`elif` shape,
these extractors need updating; they assert on structure, not behaviour.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"
TOUR = DOCS / "tour.md"
COMMAND_REFERENCE = DOCS / "reference" / "commands.md"
COMMANDS_PY = REPO_ROOT / "src" / "gridcalc" / "tui" / "commands.py"
TUI_INIT_PY = REPO_ROOT / "src" / "gridcalc" / "tui" / "__init__.py"


def _manual_pages() -> list[Path]:
    """The pages a user reads to learn what the app does.

    Globbed rather than listed so a new guide or reference page is covered
    the moment it lands -- the failure mode this file exists to prevent is
    documentation nobody re-checked.
    """
    pages = [README, DOCS / "index.md", DOCS / "install.md", TOUR, DOCS / "desktop.md"]
    pages += sorted((DOCS / "guide").glob("*.md"))
    pages += sorted((DOCS / "reference").glob("*.md"))  # not reference/api/, which is generated
    return pages


# Long-form and shorthand spellings the dispatcher accepts but the manual
# deliberately does not advertise (the documented spelling of each is the
# short form listed in the command reference). A new entry here should be a
# conscious "this alias stays undocumented" decision, not a reflex -- the
# reverse test exists to force that choice when a command is added.
UNDOCUMENTED_ALIASES = frozenset(
    {
        "blank",  # :b
        "delcol",  # :dc
        "delrow",  # :dr
        "edit",  # :e
        "format",  # :f
        "gformat",  # :gf
        "inscol",  # :ic
        "insrow",  # :ir
        "move",  # :m
        "open",  # :o
        "quit",  # :q
        "replicate",  # :r
        "save",  # :w
        "s",  # :sheet
        "title",  # :tv / :th / :tb / :tn take the arg directly
        "v",  # :view
    }
)


def _manual_text() -> str:
    pages = _manual_pages()
    missing = [p for p in pages if not p.is_file()]
    assert not missing, f"manual pages listed in the nav are gone: {missing}"
    return "\n".join(p.read_text(encoding="utf-8") for p in pages)


def _fenced_block(text: str) -> str:
    """The first fenced code block in a page.

    Keys are read from structured regions only. Scanning prose would pull in
    every one-letter word ("a", "I") and every backticked single character
    (`=`, `$`, mode names) and drown the signal.
    """
    m = re.search(r"^```[a-z]*\n(.*?)^```", text, re.M | re.S)
    assert m is not None, "expected a fenced code block and found none"
    return m.group(1)


# -- command conformance --


def _documented_commands(text: str) -> set[str]:
    """Every `:cmd` token in the manual.

    The lookbehind rejects a colon preceded by a word character, which is
    what keeps cell ranges (`A1:B3`), sheet-qualified refs
    (`Sheet1!A1:Sheet2!B5`), and prose ("Lookup order: CWD") out of the
    result. Requiring a letter immediately after the colon drops the
    placeholder ranges in `[in <lo>:<hi>]`.
    """
    return set(re.findall(r"(?<!\w):([a-z]+!?)", text))


def _dispatched_commands() -> set[str]:
    """Every command name the TUI can reach.

    Dispatch is two-part since the shared registry landed: `cmdexec` still
    name-matches the view-owned commands (those whose body is interaction --
    `:e`, `:view`, `:sheets`, ...), while the frontend-neutral ones come from
    `gridcalc.commands` and never appear as a literal here. Both halves count,
    or the manual check would demand that shared commands be re-listed in the
    dispatcher just to be seen.
    """
    from gridcalc import commands as shared
    from gridcalc.tui.commands import _ARG_ALIASES

    names = set(shared.BY_NAME) | set(_ARG_ALIASES)
    return names | _name_matched_commands()


def _name_matched_commands() -> set[str]:
    """Command names `cmdexec` compares `cmd` against directly."""
    tree = ast.parse(COMMANDS_PY.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmdexec")
    names: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)):
            continue
        if node.left.id != "cmd":
            continue
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                names.add(comparator.value)
            elif isinstance(op, ast.In) and isinstance(comparator, ast.Tuple | ast.List):
                names.update(e.value for e in comparator.elts if isinstance(e, ast.Constant))
    return names


def test_documented_commands_are_dispatched() -> None:
    documented = _documented_commands(_manual_text())
    assert documented, "parser found no commands in the manual -- the parser is broken"
    missing = sorted(documented - _dispatched_commands())
    assert not missing, (
        f"the manual documents commands the dispatcher does not handle: {missing}. "
        "Either implement them in cmdexec or correct the docs."
    )


def test_dispatched_commands_are_documented() -> None:
    extra = _dispatched_commands() - _documented_commands(_manual_text())
    undocumented = sorted(extra - UNDOCUMENTED_ALIASES)
    assert not undocumented, (
        f"cmdexec handles commands the manual never mentions: {undocumented}. "
        "Either document them or add them to UNDOCUMENTED_ALIASES."
    )


def test_no_view_owned_command_shadows_a_shared_one() -> None:
    """The parity guarantee, TUI half -- and the way it can actually break.

    Both frontends dispatch shared commands *by name*, so a registry entry is
    reachable by construction; asserting that would be a tautology. The real
    hazard is shadowing: `cmdexec` tries the shared registry first, so a
    view-owned branch matching the same name is dead code, and whichever of the
    two implementations the author meant to keep, one of them is now a lie.
    """
    from gridcalc import commands as shared

    clash = sorted(_name_matched_commands() & set(shared.BY_NAME))
    assert not clash, (
        f"cmdexec name-matches commands the shared registry already owns: {clash}. "
        "The registry runs first, so these branches are unreachable -- delete "
        "them, or rename the shared command if they were meant to differ."
    )


def test_the_web_bridge_exposes_the_registry_unfiltered() -> None:
    """The parity guarantee, web half.

    The client builds its palette from `Api.list_commands`, so the bridge is
    where the web frontend could still lose a command -- by filtering the list,
    or by drifting to a hardcoded one. This pins that it forwards the registry
    whole. (That the *client* then renders one entry per descriptor is asserted
    in the vitest suite, which is where that code lives.)
    """
    from gridcalc import commands as shared
    from gridcalc.engine import Grid
    from gridcalc.web import Api

    exposed = {c["name"] for c in Api(Grid()).list_commands()["commands"]}
    assert exposed == {c.name for c in shared.COMMANDS}


def test_shared_commands_are_documented_in_the_readme() -> None:
    """A shared command is user-facing in both frontends, so it needs to be in
    the command reference like any other."""
    documented = _documented_commands(_manual_text())
    from gridcalc import commands as shared

    undocumented = sorted(c.name for c in shared.COMMANDS if not (set(c.names) & documented))
    assert not undocumented, f"shared commands the manual never mentions: {undocumented}"


# -- keybinding conformance --

_CTRL_RE = re.compile(r"Ctrl-([A-Za-z])")


def _documented_keys() -> tuple[set[str], set[str]]:
    """Return (plain_keys, ctrl_keys) advertised by the manual.

    Read from the two structured regions only -- the command table on the
    Quick tour page and the code block on the command reference page. The
    prose around them is not scanned; see `_fenced_block`.
    """
    plain: set[str] = set()
    ctrl: set[str] = set()

    for line in TOUR.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1]
        for token in re.findall(r"`([^`]+)`", cell):
            if token.startswith(":"):
                continue  # a command, covered above
            m = _CTRL_RE.fullmatch(token)
            if m:
                ctrl.add(m.group(1).lower())
            else:
                # `/text` and `> AA10` document the leading key.
                plain.add(token[0])

    reference = _fenced_block(COMMAND_REFERENCE.read_text(encoding="utf-8"))
    ctrl.update(m.lower() for m in _CTRL_RE.findall(reference))
    for token in reference.split():
        if token.startswith((":", "[", "<", "(")):
            continue
        if _CTRL_RE.match(token):
            continue
        # `y/p` documents two keys; `undo/redo` documents none.
        for part in token.split("/"):
            if len(part) == 1 and not part.isspace():
                plain.add(part)

    return plain, ctrl


def _keyloop_keys() -> tuple[set[str], set[str]]:
    """Return (plain_keys, ctrl_keys) the grid keyloop dispatches on.

    A `ord("x")` call is a control binding only when it is the right
    operand of `0x1F & ...`. Matching by node identity rather than by
    character matters: `u` and `y` appear in both forms (undo/underline,
    yank/redo), so a set difference would erase the plain bindings.
    """
    tree = ast.parse(TUI_INIT_PY.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "mainloop")

    ctrl_call_ids: set[int] = set()
    ctrl: set[str] = set()
    plain: set[str] = set()

    for node in ast.walk(fn):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.BitAnd)
            and isinstance(node.left, ast.Constant)
            and node.left.value == 0x1F
            and isinstance(node.right, ast.Call)
            and getattr(node.right.func, "id", None) == "ord"
            and isinstance(node.right.args[0], ast.Constant)
        ):
            ctrl_call_ids.add(id(node.right))
            ctrl.add(node.right.args[0].value.lower())

    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "ord"
            and id(node) not in ctrl_call_ids
            and isinstance(node.args[0], ast.Constant)
        ):
            plain.add(node.args[0].value)

    return plain, ctrl


def test_documented_plain_keys_are_dispatched() -> None:
    documented, _ = _documented_keys()
    assert documented, "parser found no plain keys in the manual -- the parser is broken"
    handled, _ = _keyloop_keys()
    missing = sorted(documented - handled)
    assert not missing, (
        f"the manual documents keys the grid keyloop does not handle: {missing}. "
        "Note that a printable key must be dispatched before the "
        "`32 <= ch < 127` label-entry fallthrough or it is a no-op."
    )


def test_documented_ctrl_keys_are_dispatched() -> None:
    _, documented = _documented_keys()
    assert documented, "parser found no Ctrl keys in the manual -- the parser is broken"
    _, handled = _keyloop_keys()
    missing = sorted(documented - handled)
    assert not missing, f"the manual documents Ctrl bindings the keyloop lacks: {missing}"


@pytest.mark.parametrize("key", ["u", "y", "p", "v", "n", "N", "E", "e", "/", ">"])
def test_core_vi_keys_bound(key: str) -> None:
    """Regression guard for the specific failure that motivated this file.

    The parsers above are only as good as the docs; these are asserted
    directly so a docs edit cannot silently shrink what is checked.
    """
    plain, _ = _keyloop_keys()
    assert key in plain, f"grid keyloop lost its {key!r} binding"


@pytest.mark.parametrize("key", ["z", "y", "r", "b", "u", "c"])
def test_core_ctrl_keys_bound(key: str) -> None:
    _, ctrl = _keyloop_keys()
    assert key in ctrl, f"grid keyloop lost its Ctrl-{key.upper()} binding"
