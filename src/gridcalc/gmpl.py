"""GMPL (GNU MathProg) models: checking the text, writing data, reading glpsol's report.

A GMPL model runs under `glpsol` from GLPK, which the user installs; GLPK is
GPL-3 and gridcalc only starts it as a program. Data items the model declares
as a `set` or `param` are written to a data file. Results come back from
glpsol's solution report and fill output items whose name matches a variable
or the objective. Design: ``docs/dev/crosstab-model.md``.
"""

from __future__ import annotations

import re
from typing import Any

# Comments, strings, names, numbers and operators; enough to tell statements apart.
_TOKEN = re.compile(
    r"/\*.*?\*/|#[^\n]*"  # comments, dropped
    r"|(?P<str>'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)"
    r"|(?P<op>>>|<>|<=|>=|:=|\.\.|[^\s])",
    re.DOTALL,
)


def _tokens(text: str) -> list[tuple[str, str, int]]:
    """``(kind, text, line)`` for each token, comments left out."""
    out = []
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup
        if kind is None:
            continue
        out.append((kind, m.group(), text.count("\n", 0, m.start()) + 1))
    return out


def problems(text: str) -> list[str]:
    """Statements that reach outside the run: `table` and output redirection.

    `table ... OUT` writes files and its ODBC/MySQL drivers open connections;
    `printf ... > "file"` and `display ... > "file"` write files. glpsol runs
    in the confined child either way, but only macOS confines a native program.
    """
    toks = _tokens(text)
    out = []
    for i, (kind, tok, line) in enumerate(toks):
        if kind == "word" and tok == "table":
            out.append(f"line {line}: a model may not use table statements")
        elif kind == "op" and tok in (">", ">>") and i + 1 < len(toks) and toks[i + 1][0] == "str":
            out.append(f"line {line}: a model may not send output to a file")
    return out


def declared(text: str) -> dict[str, str]:
    """Each name a `set` or `param` statement declares, mapped to that keyword."""
    out: dict[str, str] = {}
    start = True  # at the start of a statement
    toks = _tokens(text)
    for i, (kind, tok, _line) in enumerate(toks):
        if start and kind == "word" and tok in ("set", "param") and i + 1 < len(toks):
            nxt = toks[i + 1]
            if nxt[0] == "word":
                out.setdefault(nxt[1], tok)
        start = kind == "op" and tok == ";"
    return out


def symbol(v: Any) -> str:
    """A value as a GMPL data symbol: a number as itself, anything else quoted."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def data_file(items: dict[str, dict[str, Any]], decl: dict[str, str]) -> tuple[str, list[str]]:
    """The data section for the items ``decl`` names, and problems with them.

    ``items`` is the request's item specs (see `modelrun._request_items`).
    Output items are the model's variables, so they are not data.
    """
    lines = ["data;"]
    errors: list[str] = []
    for name, spec in items.items():
        kind = decl.get(name)
        if kind is None or spec.get("output"):
            continue
        if spec["kind"] == "indexed":
            if kind != "param":
                errors.append(f"{name}: an indexed data item must be declared as a param")
                continue
            default = f" default {symbol(spec['missing'][0])}" if spec["missing"] else ""
            records = []
            for k, v in spec["values"]:
                key = k if isinstance(k, list) else [k]
                records.append(" ".join(symbol(x) for x in [*key, v]))
            lines.append(f"param {name}{default} :=\n  " + "\n  ".join(records) + ";")
            continue
        value = spec["value"]
        if kind == "set":
            if not isinstance(value, list):
                errors.append(f"{name}: a set must come from a row or column of values")
                continue
            lines.append(f"set {name} := " + " ".join(symbol(x) for x in value) + ";")
        elif isinstance(value, list):
            errors.append(f"{name}: declared as a param, but it is a set of values")
        elif value is not None:
            lines.append(f"param {name} := {symbol(value)};")
    lines.append("end;")
    return "\n".join(lines) + "\n", errors


def _subscripts(text: str) -> list[Any]:
    """`A,1` or `'New York',2` as values: numbers parsed, quotes removed."""
    out: list[Any] = []
    for m in re.finditer(r"'((?:''|[^'])*)'|([^,]+)", text):
        if m.group(1) is not None:
            out.append(m.group(1).replace("''", "'"))
            continue
        raw = m.group(2).strip()
        try:
            num = float(raw)
            out.append(int(num) if num.is_integer() else num)
        except ValueError:
            out.append(raw)
    return out


def parse_name(name: str) -> tuple[str, Any]:
    """`flow[A,1]` as ``("flow", ("A", 1))``; one subscript is a plain key, none is None."""
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(.*)\])?", name)
    if m is None:
        return name, None
    if m.group(2) is None:
        return m.group(1), None
    subs = _subscripts(m.group(2))
    return m.group(1), subs[0] if len(subs) == 1 else tuple(subs)


def read_report(text: str) -> dict[str, Any]:
    """glpsol's `-o` report: ``status``, ``objective`` (name, value) and ``columns``.

    Names over 12 characters take a line of their own, with the values on the
    next; an integer column has `*` before its activity.
    """
    status = ""
    objective: tuple[str, float] | None = None
    columns: dict[str, float] = {}
    lines = text.splitlines()
    section = ""
    pending: str | None = None
    for line in lines:
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip()
        elif line.startswith("Objective:"):
            m = re.match(r"Objective:\s+(\S+)\s+=\s+(\S+)", line)
            if m:
                objective = (m.group(1), float(m.group(2)))
        elif re.match(r"\s+No\.\s+Column name", line):
            section = "columns"
        elif re.match(r"\s+No\.\s+Row name", line):
            section = "rows"
        elif section == "columns":
            if not line.strip():
                if columns:
                    section = ""
                continue
            if pending is not None:
                columns[pending] = _activity(line) or 0.0
                pending = None
                continue
            m = re.match(r"\s*\d+ (.*)$", line)
            if m is None:
                continue
            body = m.group(1)
            # A long name fills the line; a short one is padded to 12 and
            # followed by numbers. Names hold no space outside quotes, so the
            # fields past column 12 hold a bare number only on a short line.
            if _activity(body[12:]) is None:
                pending = body.rstrip()
            else:
                columns[body[:12].rstrip()] = _activity(body[12:]) or 0.0
    return {"status": status, "objective": objective, "columns": columns}


def _activity(rest: str) -> float | None:
    """The first number in a report line's value fields, past `St` or `*`; None if none."""
    for tok in rest.split():
        try:
            return float(tok)
        except ValueError:
            continue
    return None


def status_text(status: str) -> str:
    """glpsol's status as the LpStatus text the other backends report."""
    s = status.upper()
    if "OPTIMAL" in s:
        return "Optimal"
    if "INFEASIBLE" in s or "EMPTY" in s:
        return "Infeasible"
    if "UNBOUNDED" in s:
        return "Unbounded"
    return "Undefined"
