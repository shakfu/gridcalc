"""Parsers for the ``:opt`` / ``:goal`` command syntax, free of any frontend.

These were private helpers in ``tui/solve.py``, which imports curses. The
headless CLI needs the identical grammar -- `gridcalc book.json --solve 'max B4
vars A4:A5 st D4:D6'` must mean exactly what `:opt max B4 vars A4:A5 st D4:D6`
means, or the terminal and a script disagree about the same string. Sharing the
parser is the only way to guarantee that; the alternative is two grammars that
start identical and drift, which is the failure `commands.py` was built to end.

Everything here is pure: text in, a spec object or :class:`ValueError` out. The
error messages are user-facing, so each frontend prefixes them (``opt:`` /
``goal:``) and shows them its own way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .engine import ref
from .opt import OptModel, _parse_bound_value, parse_bounds, parse_cells

CellKey = tuple[int, int]

OPT_USAGE = (
    "usage: max|min <cell> vars <cells> st <cells> [bounds <spec>] [int <cells>] [bin <cells>]"
)
GOAL_USAGE = "usage: goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]"
SWEEP_USAGE = "usage: opt sweep <cell> <lo>:<hi> [steps] [model]"

# The clause keywords that may follow `st`, in any order.
_CLAUSE_KEYWORDS = ("bounds", "int", "bin")


def looks_like_cellref(s: str) -> bool:
    """Quick syntactic check that ``s`` is a single cell ref (no range)."""
    m = ref(s)
    return m is not None and m[0] == len(s)


def parse_single_cell(s: str) -> CellKey:
    m = ref(s)
    if not m or m[0] != len(s):
        raise ValueError(f"bad cell ref: {s}")
    _, c, r = m
    return (c, r)


def parse_inline_model(parts: list[str]) -> OptModel:
    """Parse ``max|min <cell> vars <cells> st <cells> [...]`` into an OptModel.

    The returned model stores the *spec strings* as the user wrote them, not
    pre-resolved cell coordinates -- resolution happens at run time, which
    matches how saved models round-trip through the JSON file.
    """
    if len(parts) < 5 or parts[0].lower() not in ("max", "min") or parts[2].lower() != "vars":
        raise ValueError(OPT_USAGE)

    sense = parts[0].lower()
    obj_str = parts[1]

    try:
        st_idx = next(i for i in range(3, len(parts)) if parts[i].lower() in ("st", "subject"))
    except StopIteration as e:
        raise ValueError("expected 'st' keyword for constraints") from e

    # Locate every optional-clause keyword that follows `st`. Order is
    # flexible: bounds / int / bin may appear in any sequence. Each clause
    # runs from the keyword to the next keyword (or end of input).
    clause_positions: list[tuple[int, str]] = []
    for i in range(st_idx + 1, len(parts)):
        low = parts[i].lower()
        if low in _CLAUSE_KEYWORDS:
            clause_positions.append((i, low))

    vars_spec = " ".join(parts[3:st_idx])
    first_clause = clause_positions[0][0] if clause_positions else len(parts)
    st_spec = " ".join(parts[st_idx + 1 : first_clause])

    clauses: dict[str, str] = {"bounds": "", "int": "", "bin": ""}
    for j, (pos, kw) in enumerate(clause_positions):
        end = clause_positions[j + 1][0] if j + 1 < len(clause_positions) else len(parts)
        if clauses[kw]:
            raise ValueError(f"'{kw}' clause appears more than once")
        clauses[kw] = " ".join(parts[pos + 1 : end])

    if not looks_like_cellref(obj_str):
        raise ValueError(f"bad objective cell: {obj_str}")

    return OptModel(
        sense=sense,
        objective=obj_str,
        vars=vars_spec,
        constraints=st_spec,
        bounds=clauses["bounds"],
        integers=clauses["int"],
        binaries=clauses["bin"],
    )


ResolvedModel = tuple[
    CellKey,
    list[CellKey],
    list[CellKey],
    dict[CellKey, tuple[float, float]] | None,
    set[CellKey] | None,
    set[CellKey] | None,
]


def resolve_model(model: OptModel) -> ResolvedModel:
    """Turn a saved model's spec strings into cell coordinates.

    Raises ``ValueError`` with a user-facing message; callers report it.
    Shared by every command that runs a model so the specs cannot be
    interpreted one way by ``:opt run`` and another by ``:opt sweep``.
    """
    obj_match = ref(model.objective)
    if not obj_match or obj_match[0] != len(model.objective):
        raise ValueError(f"bad objective cell: {model.objective}")
    _, oc, or_ = obj_match
    return (
        (oc, or_),
        parse_cells(model.vars),
        parse_cells(model.constraints),
        parse_bounds(model.bounds) if model.bounds else None,
        set(parse_cells(model.integers)) if model.integers else None,
        set(parse_cells(model.binaries)) if model.binaries else None,
    )


@dataclass
class GoalSpec:
    """A parsed ``:goal`` request."""

    formula_cell: CellKey
    target: float
    var_cell: CellKey
    lo: float | None = None
    hi: float | None = None


def parse_goal(args: str) -> GoalSpec:
    """Parse ``<formula_cell> = <target> by <var_cell> [in <lo>:<hi>]``."""
    parts = args.split()
    if len(parts) < 5 or parts[1] != "=" or parts[3].lower() != "by":
        raise ValueError(GOAL_USAGE)

    in_idx: int | None = None
    for i in range(5, len(parts)):
        if parts[i].lower() == "in":
            in_idx = i
            break

    lo: float | None = None
    hi: float | None = None
    if in_idx is not None:
        bracket_spec = " ".join(parts[in_idx + 1 :]).strip()
        if ":" not in bracket_spec:
            raise ValueError("bracket needs 'lo:hi' after 'in'")
        lo_s, hi_s = bracket_spec.split(":", 1)
        try:
            lo = _parse_bound_value(lo_s, positive=False)
            hi = _parse_bound_value(hi_s, positive=True)
        except (ValueError, RuntimeError) as e:
            raise ValueError(f"bad bracket: {e}") from e
    elif len(parts) > 5:
        # Trailing junk that isn't `in ...` is a syntax error rather than
        # silently ignored, so typos surface immediately.
        raise ValueError(GOAL_USAGE)

    return GoalSpec(
        formula_cell=parse_single_cell(parts[0]),
        target=float(parts[2]),
        var_cell=parse_single_cell(parts[4]),
        lo=lo,
        hi=hi,
    )


@dataclass
class SweepSpec:
    """A parsed ``:opt sweep`` request. ``model`` names a saved model."""

    constraint: CellKey
    lo: float
    hi: float
    steps: int = 10
    model: str = "default"


def parse_sweep(args: list[str]) -> SweepSpec:
    """Parse ``<cell> <lo>:<hi> [steps] [model]``.

    ``steps`` and the model name are positional-but-unordered: an all-digit
    token is the step count and anything else is the model, so both
    `sweep D5 6:24 9 plan` and `sweep D5 6:24 plan 9` work.
    """
    if len(args) < 2:
        raise ValueError(SWEEP_USAGE)

    cell_str, range_str = args[0], args[1]
    steps = 10
    name = "default"
    for extra in args[2:]:
        if extra.isdigit():
            steps = int(extra)
        else:
            name = extra

    m = ref(cell_str)
    if not m or m[0] != len(cell_str):
        raise ValueError(f"bad constraint cell: {cell_str}")
    _, cc, cr = m
    if ":" not in range_str:
        raise ValueError(f"sweep range needs 'lo:hi': {range_str}")
    lo_s, hi_s = range_str.split(":", 1)
    lo, hi = float(lo_s), float(hi_s)
    if math.isnan(lo) or math.isnan(hi):
        raise ValueError(f"sweep range is not numeric: {range_str}")

    return SweepSpec(constraint=(cc, cr), lo=lo, hi=hi, steps=steps, model=name)
