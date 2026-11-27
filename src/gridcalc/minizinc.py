"""MiniZinc models: checking the text, writing JSON data, reading `--json-stream` output.

A MiniZinc model runs under the `minizinc` program, which the user installs.
Data items the model declares as parameters are written to a JSON data file;
results fill output items whose name matches an output variable. Design:
``docs/dev/crosstab-model.md``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Comments, strings and words; enough to find `include` statements.
_TOKEN = re.compile(
    r"/\*.*?\*/|%[^\n]*"  # comments, dropped
    r"|(?P<str>\"(?:\\.|[^\"\\])*\")"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>[^\s])",
    re.DOTALL,
)
# A library file by bare name: found in the model's directory or the stdlib.
_INCLUDE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.mzn")
_SOLVER_LINE = re.compile(r"^[ \t]*%[ \t]*solver:[ \t]*(\S*)[ \t]*$", re.MULTILINE)
_SOLVER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# `--json-stream` status words as the text the other backends report.
_STATUS = {
    "OPTIMAL_SOLUTION": "Optimal",
    "ALL_SOLUTIONS": "Optimal",
    "SATISFIED": "Feasible",
    "UNSATISFIABLE": "Infeasible",
    "UNBOUNDED": "Unbounded",
    "UNSAT_OR_UNBOUNDED": "Infeasible or unbounded",
    "UNKNOWN": "Unknown",
    "ERROR": "Error",
}


def solver(text: str) -> str | None:
    """The solver a `% solver: ID` comment names, or None for MiniZinc's default."""
    m = _SOLVER_LINE.search(text)
    return m.group(1) if m else None


def problems(text: str) -> list[str]:
    """Includes that name a path, and a solver comment that is not a plain name.

    `include` reads any file it names; a bare `name.mzn` is looked up only in
    the run's directory and MiniZinc's libraries.
    """
    out = []
    toks = [
        (m.lastgroup, m.group(), text.count("\n", 0, m.start()) + 1)
        for m in _TOKEN.finditer(text)
        if m.lastgroup
    ]
    for i, (kind, tok, line) in enumerate(toks):
        if kind == "word" and tok == "include" and i + 1 < len(toks):
            nkind, ntok, _ = toks[i + 1]
            if nkind != "str" or not _INCLUDE_NAME.fullmatch(json.loads(ntok)):
                out.append(f"line {line}: include only a library file by name, as 'globals.mzn'")
    name = solver(text)
    if name is not None and not _SOLVER_NAME.fullmatch(name):
        out.append(f"'% solver: {name}' must name an installed solver's id or tag")
    return out


def solver_known(name: str, solvers: list[dict[str, Any]]) -> bool:
    """Whether ``name`` is an id, an id's last part or a tag of an installed solver.

    `--solver` also takes a path to a solver configuration, which names a
    program to start, so nothing else is passed.
    """
    for s in solvers:
        if s.get("isGUIApplication"):  # Gist opens a window; it shares Gecode's `cp` tag
            continue
        sid = str(s.get("id", ""))
        if name in (sid, sid.rsplit(".", 1)[-1]) or name in s.get("tags", []):
            return True
    return False


def _order(values: list[Any]) -> list[Any]:
    """An index set's members in MiniZinc's order: numbers ascending, enum members as listed."""
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return sorted(values)
    return list(values)


def _member(v: Any) -> Any:
    """An index set member as JSON: a whole number as int, a string as an enum member."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return {"e": v} if isinstance(v, str) else v


def _scalar(name: str, v: Any, decl: dict[str, Any], errors: list[str]) -> Any:
    if isinstance(v, str):
        return {"e": v} if decl.get("type") == "int" else v
    if decl.get("type") == "int" and isinstance(v, float):
        if v.is_integer():
            return int(v)
        errors.append(f"{name}: the model declares int, the cell holds {v!r}")
    return v


def index_orders(
    name: str, spec: dict[str, Any], items: dict[str, dict[str, Any]]
) -> list[list[Any]] | str:
    """Each dimension's keys in MiniZinc's order, or why there are none."""
    index = spec.get("index") or []
    if not index:
        return f"{name}: a table item cannot be a MiniZinc array; use a cross-tab"
    orders = []
    for set_name in index:
        members = items.get(set_name, {}).get("value")
        if not isinstance(members, list):
            return f"{name}: its index {set_name} is not a set item"
        orders.append(_order([_key_part(v) for v in members]))
    return orders


def _key_part(v: Any) -> Any:
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _key(parts: list[Any]) -> Any:
    return parts[0] if len(parts) == 1 else tuple(parts)


def _nested(orders: list[list[Any]], at: Any, prefix: list[Any] | None = None) -> Any:
    """A nested list over ``orders``, each leaf ``at(key)``."""
    prefix = prefix or []
    if len(prefix) == len(orders):
        return at(_key(prefix))
    return [_nested(orders, at, [*prefix, k]) for k in orders[len(prefix)]]


def _array(
    name: str,
    spec: dict[str, Any],
    orders: list[list[Any]],
    decl: dict[str, Any],
    errors: list[str],
) -> Any:
    """An indexed item as a nested list over ``orders``; a blank needs ``missing``."""
    values = {
        _key([_key_part(p) for p in k]) if isinstance(k, list) else _key_part(k): v
        for k, v in spec["values"]
    }
    default = spec["missing"]

    def at(key: Any) -> Any:
        if key in values:
            return _scalar(name, values[key], decl, errors)
        if default:
            return _scalar(name, default[0], decl, errors)
        errors.append(f"{name}[{key!r}] is blank; give the item missing=VALUE")
        return None

    return _nested(orders, at)


def data(
    items: dict[str, dict[str, Any]], inputs: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """The JSON data for the items the model declares (``inputs``), and problems with them.

    ``items`` is the request's item specs (see `modelrun._request_items`).
    Output items are the model's variables, so they are not data.
    """
    out: dict[str, Any] = {}
    errors: list[str] = []
    for name, spec in items.items():
        decl = inputs.get(name)
        if decl is None or spec.get("output"):
            continue
        if spec["kind"] == "indexed":
            orders = index_orders(name, spec, items)
            if isinstance(orders, str):
                errors.append(orders)
                continue
            out[name] = _array(name, spec, orders, decl, errors)
            continue
        value = spec["value"]
        if isinstance(value, list):
            members = [_member(v) for v in _order(value)]
            out[name] = members if any(isinstance(m, dict) for m in members) else {"set": members}
        elif value is not None:
            out[name] = _scalar(name, value, decl, errors)
    return out, errors


def plain(v: Any) -> Any:
    """A JSON output value for a cell: an enum member as its name; a set is refused."""
    if isinstance(v, dict) and "e" in v:
        return v["e"]
    if isinstance(v, dict) and "set" in v:
        raise ValueError("a set value cannot be written to a cell")
    return v


def pairs(orders: list[list[Any]], value: Any) -> list[list[Any]]:
    """``[[key, cell value], ...]`` from a nested output array over ``orders``."""
    out: list[list[Any]] = []

    def walk(v: Any, prefix: list[Any]) -> None:
        if len(prefix) == len(orders):
            key = _key(prefix)
            out.append([list(key) if isinstance(key, tuple) else key, plain(v)])
            return
        if not isinstance(v, list) or len(v) != len(orders[len(prefix)]):
            raise ValueError("its array does not match the sizes of its index sets")
        for k, sub in zip(orders[len(prefix)], v, strict=True):
            walk(sub, [*prefix, k])

    walk(value, [])
    return out


def read_stream(text: str) -> dict[str, Any]:
    """`--json-stream` output: the last solution, interface inputs, status, errors, other text.

    A satisfaction model's one solution comes with no status message.
    """
    solution: dict[str, Any] | None = None
    inputs: dict[str, Any] = {}
    status = ""
    errors: list[dict[str, Any]] = []
    log: list[str] = []
    for line in text.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            log.append(line)
            continue
        if not isinstance(msg, dict):
            log.append(line)
            continue
        kind = msg.get("type")
        if kind == "solution":
            solution = msg.get("output", {}).get("json")
            log.extend(t for t in [msg.get("output", {}).get("default")] if t)
        elif kind == "interface":
            inputs = msg.get("input") or {}
        elif kind == "status":
            status = str(msg.get("status", ""))
        elif kind == "error":
            errors.append(msg)
        elif kind in ("warning", "trace", "comment"):
            log.append(str(msg.get("message") or msg.get("comment") or msg.get("value") or ""))
    if not status and solution is not None:
        status = "SATISFIED"
    return {
        "solution": solution,
        "inputs": inputs,
        "status": _STATUS.get(status, status.replace("_", " ").capitalize() or "Unknown"),
        "errors": errors,
        "log": "\n".join(s.rstrip("\n") for s in log),
    }
