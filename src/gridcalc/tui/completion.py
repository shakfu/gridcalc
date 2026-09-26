"""Tab completion and `:help` text for the `:` line.

Both read the shared registry (`gridcalc.commands`) and the view-owned table
(`tui.commands.VIEW_COMMANDS`), so a command added to either is completed and
listed without a second edit. Everything here is a pure function of its
arguments and the grid; nothing draws.
"""

from __future__ import annotations

import os

from .. import commands as shared
from ..display import fmt_float
from ..engine import Grid
from .commands import _ARG_ALIASES, _FORMAT_OPTIONS, VIEW_BY_NAME, VIEW_COMMANDS

# Help lists groups in this order; a group not named here follows them.
_GROUP_ORDER = (
    "File",
    "Edit",
    "Format",
    "Insert",
    "Name",
    "Data",
    "Sheets",
    "Import/export",
    "Optimization",
    "View",
    "Help",
)

_IO_SUBCOMMANDS = ["load", "save"]
_SHEET_SUBCOMMANDS = ["add", "del", "list", "move", "rename"]
_OPT_SUBCOMMANDS = ["def", "list", "run", "sens", "sweep", "undef"]

# Specs shown by `:help f`, rendered through `fmt_float` so the examples
# cannot drift from what the formatter does.
_SPEC_EXAMPLES = ((",.2f", 1234.5), (",", 1234.5), (".1%", 0.157), (".2e", 12345.0))


def command_names() -> list[str]:
    """Every canonical command name, shared and view-owned, sorted."""
    return sorted({c.name for c in shared.COMMANDS} | {c.name for c in VIEW_COMMANDS})


def _canonical(name: str) -> str | None:
    """The canonical name for ``name``, or None when it is no command."""
    name = name.lower()
    found = shared.lookup(name)
    if found is not None:
        return found.name
    if name in VIEW_BY_NAME:
        return VIEW_BY_NAME[name].name
    if name in _ARG_ALIASES:
        return name
    return None


def _path_candidates(token: str) -> list[str]:
    """Files and directories completing ``token``; directories end in ``/``."""
    expanded = os.path.expanduser(token)
    directory, base = os.path.split(expanded)
    try:
        entries = sorted(os.listdir(directory or "."))
    except OSError:
        return []
    keep = token[: len(token) - len(base)]
    out: list[str] = []
    for entry in entries:
        if not entry.startswith(base) or (entry.startswith(".") and not base.startswith(".")):
            continue
        is_dir = os.path.isdir(os.path.join(directory, entry))
        out.append(keep + entry + ("/" if is_dir else ""))
    return out


def _arg_candidates(cmd: str, prior: list[str], token: str, g: Grid) -> list[str]:
    """Candidates for argument ``len(prior)`` of ``cmd``, before prefix filtering."""
    i = len(prior)
    sub = prior[0].lower() if prior else ""
    sheets = g.sheet_names()
    if cmd == "format":
        return [key for key, _, _ in _FORMAT_OPTIONS] if i == 0 else []
    if cmd == "unname":
        return [nr.name for nr in g.names] if i == 0 else []
    if cmd in ("w", "wq", "o"):
        return _path_candidates(token) if i == 0 else []
    if cmd in ("csv", "xlsx", "pd"):
        if i == 0:
            return _IO_SUBCOMMANDS
        return _path_candidates(token) if i == 1 else []
    if cmd == "sheet":
        if i == 0:
            return _SHEET_SUBCOMMANDS + sheets
        return sheets if i == 1 and sub in ("del", "rename", "move") else []
    if cmd == "opt":
        if i == 0:
            return _OPT_SUBCOMMANDS
        return sorted(g.models) if i == 1 and sub in ("run", "sens", "undef") else []
    if cmd == "help":
        return command_names() if i == 0 else []
    found = shared.lookup(cmd)
    if found is not None and i < len(found.args):
        return list(found.args[i].choices)
    return []


def complete(buf: str, g: Grid) -> tuple[str, list[str]]:
    """Complete the last word of the `:` line buffer ``buf``.

    Returns the new buffer and the candidates. A unique candidate is filled in
    with a trailing space, or none after a directory. Several candidates fill
    in their common prefix.
    """
    before, sep, token = buf.rpartition(" ")
    words = before.split()
    if not sep or not words:
        before, sep, token = "", "", buf
        cands = [n for n in command_names() if n.startswith(token.lower())]
    else:
        cmd = _canonical(words[0])
        pool = [] if cmd is None else _arg_candidates(cmd, words[1:], token, g)
        cands = [c for c in pool if c.startswith(token)]
    if len(cands) == 1:
        end = "" if cands[0].endswith("/") else " "
        return before + sep + cands[0] + end, cands
    common = os.path.commonprefix(cands) if cands else ""
    if len(common) > len(token):
        return before + sep + common, cands
    return buf, cands


def _aliases(name: str) -> list[str]:
    found = shared.lookup(name)
    view = VIEW_BY_NAME.get(name)
    own = found.aliases if found is not None else view.aliases if view is not None else ()
    return [*own, *(a for a, (target, _) in _ARG_ALIASES.items() if target == name)]


def _usage(cmd: shared.Command) -> str:
    args = " ".join(f"<{a.name}>" if a.required else f"[{a.name}]" for a in cmd.args)
    return f":{cmd.name} {args}".rstrip()


def _overview() -> list[str]:
    entries: dict[str, list[tuple[str, str]]] = {}
    for c in shared.COMMANDS:
        entries.setdefault(c.group, []).append((c.name, c.title))
    for v in VIEW_COMMANDS:
        entries.setdefault(v.group, []).append((v.name, v.summary))
    order = [g for g in _GROUP_ORDER if g in entries] + sorted(set(entries) - set(_GROUP_ORDER))
    lines: list[str] = []
    for group in order:
        lines.append(group)
        for name, summary in entries[group]:
            also = " ".join(":" + a for a in _aliases(name))
            lines.append(f"  :{name:<9} {summary}" + (f"  ({also})" if also else ""))
        lines.append("")
    lines.append("Tab completes command names and arguments.")
    lines.append(":help <command> shows one command's usage.")
    return lines


def help_lines(topic: str) -> list[str] | None:
    """The `:help` text for ``topic``, or the overview when it is empty.

    Returns None when ``topic`` names no command.
    """
    if not topic:
        return _overview()
    name = _canonical(topic)
    if name is None:
        return None
    if name in _ARG_ALIASES:
        target, prefix = _ARG_ALIASES[name]
        return [f":{name} is :{target} {' '.join(prefix)}", "", *(help_lines(target) or [])]
    lines: list[str] = []
    found = shared.lookup(name)
    if found is not None:
        lines += [_usage(found), found.title]
        if found.needs_selection:
            lines.append("Acts on the selection, or the cursor cell without one.")
        if found.args:
            lines += ["", "Arguments:"]
            for a in found.args:
                choices = f" ({' '.join(a.choices)})" if a.choices else ""
                lines.append(f"  {a.name:<10} {a.help}{choices}")
    else:
        view = VIEW_BY_NAME[name]
        lines += [view.usage, view.summary]
    also = _aliases(name)
    if also:
        lines.append("Also: " + " ".join(":" + a for a in also))
    if name == "format":
        lines += ["", "Python specs:"]
        for spec, value in _SPEC_EXAMPLES:
            lines.append(f"  {spec:<10} {value!r:<9} -> {fmt_float(value, spec)}")
        lines.append("  yyyy-mm-dd  a date format; any xlsx date code works")
        lines += ["", "Formats:"]
        lines += [f"  {key:<4} {label:<12} {desc}" for key, label, desc in _FORMAT_OPTIONS]
    return lines
