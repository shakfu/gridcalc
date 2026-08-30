from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ast_nodes import (
    Apply,
    BinOp,
    Bool,
    Call,
    CellRef,
    ErrorLit,
    Name,
    Node,
    Number,
    Percent,
    PyCall,
    RangeRef,
    SpillRef,
    String,
    UnaryOp,
)
from .errors import ExcelError, first_error

Value = Any


@dataclass(frozen=True)
class Reference:
    """A location (single cell or rectangular range), distinct from the
    value(s) it points at. Produced by ``OFFSET`` and consumed by the
    reference-aware functions (``ROW``/``COLUMN``/``ROWS``/``COLUMNS``/
    ``FORMULATEXT``/``AREAS``). Anywhere a plain value is expected -- a
    normal function argument, an arithmetic operand, a formula's result --
    a Reference materialises to a scalar (1x1) or a Vec, via ``_deref``.
    Coordinates are 0-based inclusive."""

    c1: int
    r1: int
    c2: int
    r2: int
    sheet: str | None = None


class Env:
    def __init__(
        self,
        cell_value: Callable[..., object],
        builtins: dict[str, Callable[..., Any]],
        named_ranges: dict[str, Node] | None = None,
        py_registry: dict[str, Callable[..., Any]] | None = None,
        cell_is_formula: Callable[..., bool] | None = None,
        cell_spill_value: Callable[..., object] | None = None,
        cell_formula_text: Callable[..., object] | None = None,
    ) -> None:
        # `cell_value` is `(c, r, sheet=None) -> object`; `cell_is_formula`
        # is `(c, r, sheet=None) -> bool`. The single-sheet case keeps
        # `sheet=None` so existing callers that pass two-arg lambdas
        # still work.
        self.cell_value = cell_value
        # `cell_spill_value(c, r, sheet=None)` returns the whole spilled
        # array anchored at (c, r) as a Vec (or the scalar for a
        # non-array cell). Backs the `A1#` operator. Defaults to
        # `cell_value` so an Env built without spill support degrades to
        # reading the anchor's own value.
        self.cell_spill_value = cell_spill_value or cell_value
        self._builtins = {k.lower(): v for k, v in builtins.items()}
        self._named = {k.lower(): v for k, v in (named_ranges or {}).items()}
        self.py_registry = py_registry or {}
        self.cell_is_formula = cell_is_formula or (lambda _c, _r, _s=None: False)
        # `cell_formula_text(c, r, sheet=None)` returns the formula text
        # (leading '=' included) of a formula cell, else None. Backs
        # FORMULATEXT.
        self.cell_formula_text = cell_formula_text or (lambda _c, _r, _s=None: None)
        # `refs_used` keys are `(sheet, c, r)`; sheet is None for refs
        # that resolve against the formula's home sheet.
        self.refs_used: set[tuple[str | None, int, int]] = set()
        # Set by recalc before evaluating each formula. Functions in
        # `RAW_ARG_FUNCS` (e.g. ROW(), COLUMN()) consult this when called
        # with no arguments.
        self.current_cell: tuple[int, int] | None = None
        # Per-recalc cache for materialised range Vecs. Key is
        # `(sheet, c1, r1, c2, r2)`. Cleared at the start of each recalc
        # pass -- downstream consumers re-evaluate when sources change,
        # so cache liveness is bounded by the closure pass.
        self._range_cache: dict[tuple[str | None, int, int, int, int], Any] = {}
        # Lexical scope stack for LET bindings. Each frame maps a
        # lowercased local name to an already-evaluated value. Searched
        # top-down so inner LETs shadow outer ones and named ranges.
        self._local_scopes: list[dict[str, Any]] = []

    def clear_range_cache(self) -> None:
        self._range_cache.clear()

    def push_scope(self) -> dict[str, Any]:
        """Push a fresh local scope and return it so a caller can add
        bindings incrementally. Must be paired with ``pop_scope``."""
        scope: dict[str, Any] = {}
        self._local_scopes.append(scope)
        return scope

    def pop_scope(self) -> None:
        self._local_scopes.pop()

    def lookup_local(self, name: str) -> tuple[bool, Any]:
        """Resolve a LET-bound local. Returns ``(found, value)`` so a
        legitimately-bound ``None`` is distinguishable from a miss."""
        key = name.lower()
        for scope in reversed(self._local_scopes):
            if key in scope:
                return True, scope[key]
        return False, None

    def lookup_func(self, name: str) -> Callable[..., Any] | None:
        return self._builtins.get(name.lower())

    def lookup_name(self, name: str) -> Node | None:
        return self._named.get(name.lower())

    def get_cell(self, c: int, r: int, sheet: str | None = None) -> object:
        self.refs_used.add((sheet, c, r))
        return self.cell_value(c, r, sheet)

    def get_spill(self, c: int, r: int, sheet: str | None = None) -> object:
        self.refs_used.add((sheet, c, r))
        return self.cell_spill_value(c, r, sheet)

    def eval_node(self, node: Node) -> Any:
        """Evaluate a sub-expression AST node in this environment. Used by
        reference-aware functions to compute their non-reference arguments."""
        return _eval(node, self)

    def resolve_ref(self, node: Node) -> Reference | None:
        """Resolve an AST node to a Reference, or None if it is not a
        reference. Cell/range refs resolve statically; a call (e.g. a
        nested OFFSET) is evaluated and accepted only if it yields a
        Reference."""
        if isinstance(node, CellRef):
            return Reference(node.col, node.row, node.col, node.row, node.sheet)
        if isinstance(node, RangeRef):
            s, e = node.start, node.end
            return Reference(
                min(s.col, e.col),
                min(s.row, e.row),
                max(s.col, e.col),
                max(s.row, e.row),
                s.sheet,
            )
        if isinstance(node, Name):
            target = self.lookup_name(node.name)
            return self.resolve_ref(target) if target is not None else None
        if isinstance(node, (Call, Apply)):
            v = _eval(node, self)
            return v if isinstance(v, Reference) else None
        return None


class LambdaValue:
    """A first-class function produced by ``LAMBDA(param..., body)``.

    Closes over the local scopes in effect where it was defined (a
    shallow snapshot, since scopes are mutated and popped as evaluation
    proceeds). Calling it swaps that captured scope stack in for the
    duration of the body, then restores the caller's -- so lexical
    scoping and re-entrancy both hold. ``refs_used`` and the range cache
    stay on the shared ``Env`` so cell reads inside a lambda body are
    still tracked as dependencies.
    """

    __slots__ = ("params", "body", "env", "captured")

    def __init__(
        self, params: tuple[str, ...], body: Node, env: Env, captured: list[dict[str, Any]]
    ) -> None:
        self.params = params
        self.body = body
        self.env = env
        self.captured = captured

    def __call__(self, *args: Any) -> Any:
        if len(args) != len(self.params):
            return ExcelError.VALUE
        env = self.env
        saved = env._local_scopes
        env._local_scopes = list(self.captured)
        scope = env.push_scope()
        try:
            for name, value in zip(self.params, args, strict=True):
                scope[name] = 0.0 if value is None else value
            return _eval(self.body, env)
        finally:
            env._local_scopes = saved


def _materialize_ref(ref: Reference, env: Env) -> Any:
    """Read the cells a Reference points at: a scalar for a 1x1 reference,
    otherwise a Vec carrying the rectangle's 2D shape."""
    if ref.c1 == ref.c2 and ref.r1 == ref.r2:
        return env.get_cell(ref.c1, ref.r1, ref.sheet)
    from ..engine import Vec  # lazy import to break cycle

    data: list[Any] = []
    for r in range(ref.r1, ref.r2 + 1):
        for c in range(ref.c1, ref.c2 + 1):
            v = env.get_cell(c, r, ref.sheet)
            data.append(0.0 if v is None else v)
    return Vec(data, cols=ref.c2 - ref.c1 + 1)


def _deref(v: Any, env: Env) -> Any:
    """Materialise a Reference to its value(s); pass everything else through
    unchanged. A no-op for every value that is not a Reference, so formulas
    that never touch OFFSET are unaffected."""
    return _materialize_ref(v, env) if isinstance(v, Reference) else v


def _to_number(v: object) -> float | ExcelError:
    if isinstance(v, ExcelError):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return ExcelError.VALUE
    return ExcelError.VALUE


def _to_number_or_zero(v: object) -> float | ExcelError:
    if isinstance(v, ExcelError):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


def _to_string(v: object) -> str | ExcelError:
    if isinstance(v, ExcelError):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _to_bool(v: object) -> bool | ExcelError:
    if isinstance(v, ExcelError):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        u = v.upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        return ExcelError.VALUE
    return ExcelError.VALUE


def _is_vec(v: object) -> bool:
    # Vec is engine.Vec; we duck-type to avoid a circular import.
    return type(v).__name__ == "Vec" and hasattr(v, "data")


def _vec_data(v: object) -> list[Any]:
    return list(v.data)  # type: ignore[attr-defined]


def _make_vec(data: list[Any], cols: int | None = None) -> Any:
    from ..engine import Vec  # lazy import to break cycle

    return Vec(data, cols=cols)


def _vec_cols(v: object) -> int | None:
    return getattr(v, "cols", None)


def _vec_shape(v: object) -> tuple[int, int]:
    return getattr(v, "shape", (len(_vec_data(v)), 1))


def _vec_apply2(op: Callable[[Any, Any], Any], a: Any, b: Any) -> Any:
    if _is_vec(a) and _is_vec(b):
        ad, bd = _vec_data(a), _vec_data(b)
        if len(ad) != len(bd):
            return ExcelError.VALUE
        ca, cb = _vec_cols(a), _vec_cols(b)
        # Two 2D shapes must match exactly; mismatch -> per-element #VALUE!.
        if ca and cb and _vec_shape(a) != _vec_shape(b):
            return _make_vec([ExcelError.VALUE] * len(ad), cols=ca)
        out_cols = ca if ca else cb
        return _make_vec([op(x, y) for x, y in zip(ad, bd, strict=False)], cols=out_cols)
    if _is_vec(a):
        return _make_vec([op(x, b) for x in _vec_data(a)], cols=_vec_cols(a))
    if _is_vec(b):
        return _make_vec([op(a, y) for y in _vec_data(b)], cols=_vec_cols(b))
    return op(a, b)


def _vec_apply1(op: Callable[[Any], Any], a: Any) -> Any:
    if _is_vec(a):
        return _make_vec([op(x) for x in _vec_data(a)], cols=_vec_cols(a))
    return op(a)


def _add(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    na = _to_number(a)
    if isinstance(na, ExcelError):
        return na
    nb = _to_number(b)
    if isinstance(nb, ExcelError):
        return nb
    return na + nb


def _sub(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    na = _to_number(a)
    if isinstance(na, ExcelError):
        return na
    nb = _to_number(b)
    if isinstance(nb, ExcelError):
        return nb
    return na - nb


def _mul(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    na = _to_number(a)
    if isinstance(na, ExcelError):
        return na
    nb = _to_number(b)
    if isinstance(nb, ExcelError):
        return nb
    return na * nb


def _div(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    na = _to_number(a)
    if isinstance(na, ExcelError):
        return na
    nb = _to_number(b)
    if isinstance(nb, ExcelError):
        return nb
    if nb == 0:
        return ExcelError.DIV0
    return na / nb


def _pow(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    na = _to_number(a)
    if isinstance(na, ExcelError):
        return na
    nb = _to_number(b)
    if isinstance(nb, ExcelError):
        return nb
    try:
        r = na**nb
    except (ValueError, OverflowError, ZeroDivisionError):
        return ExcelError.NUM
    if isinstance(r, complex):
        return ExcelError.NUM
    return r


def _concat(a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    sa = _to_string(a)
    if isinstance(sa, ExcelError):
        return sa
    sb = _to_string(b)
    if isinstance(sb, ExcelError):
        return sb
    return sa + sb


def _empty_as(other: Any) -> Any:
    """The value an empty cell takes when compared against ``other``.

    Excel gives an empty cell the type of the value it is compared against,
    and that type's zero. Returns ``None`` unchanged when ``other`` is not a
    scalar, leaving the type-ranking path below to deal with it.
    """
    if isinstance(other, bool):
        return False
    if isinstance(other, str):
        return ""
    if isinstance(other, (int, float)):
        return 0.0
    return None


def _compare(op: str, a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
    # An empty cell is `None` here, and `None` compares with nothing: ordering
    # two of them raised a TypeError that surfaced as a bare NaN with no error
    # set, and `=A1=0` answered FALSE where Excel answers TRUE. Arithmetic
    # already reads an empty cell as 0 (`_to_number`); this makes comparison
    # agree with it.
    if a is None and b is None:
        a = b = 0.0
    elif a is None:
        a = _empty_as(b)
    elif b is None:
        b = _empty_as(a)
    a_is_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_is_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_is_num and b_is_num:
        x: Any = a
        y: Any = b
    elif (isinstance(a, str) and isinstance(b, str)) or (
        isinstance(a, bool) and isinstance(b, bool)
    ):
        x, y = a, b
    else:
        # mixed: rank by type (number < string < bool) approximating Excel
        def rk(v: Any) -> int:
            if isinstance(v, bool):
                return 2
            if isinstance(v, str):
                return 1
            if isinstance(v, (int, float)):
                return 0
            return 3

        ra, rb = rk(a), rk(b)
        if ra != rb:
            x, y = ra, rb
        else:
            x, y = a, b
    if op == "=":
        return x == y
    if op == "<>":
        return x != y
    # Ordering can still meet a pair Python refuses to compare (a Vec against
    # None, say). Report that as #VALUE!, not as an exception that becomes a
    # valueless NaN further up.
    try:
        if op == "<":
            return x < y
        if op == ">":
            return x > y
        if op == "<=":
            return x <= y
        if op == ">=":
            return x >= y
    except TypeError:
        return ExcelError.VALUE
    raise AssertionError(f"unknown compare op {op}")


_BINOP: dict[str, Callable[[Any, Any], Any]] = {
    "+": _add,
    "-": _sub,
    "*": _mul,
    "/": _div,
    "^": _pow,
    "&": _concat,
}


def evaluate(node: Node, env: Env) -> Value:
    # A formula whose result is a bare Reference (e.g. `=OFFSET(A1,1,1)`)
    # materialises to the referenced value(s) for storage/display.
    return _deref(_eval(node, env), env)


def _eval(node: Node, env: Env) -> Value:
    if isinstance(node, Number):
        return node.value
    if isinstance(node, String):
        return node.value
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, ErrorLit):
        return node.error
    if isinstance(node, CellRef):
        return env.get_cell(node.col, node.row, node.sheet)
    if isinstance(node, RangeRef):
        return _eval_range(node, env)
    if isinstance(node, SpillRef):
        return _eval_spill(node, env)
    if isinstance(node, Name):
        return _eval_name(node, env)
    if isinstance(node, Call):
        return _eval_call(node, env)
    if isinstance(node, Apply):
        return _eval_apply(node, env)
    if isinstance(node, PyCall):
        return _eval_pycall(node, env)
    if isinstance(node, BinOp):
        return _eval_binop(node, env)
    if isinstance(node, UnaryOp):
        return _eval_unary(node, env)
    if isinstance(node, Percent):
        return _eval_percent(node, env)
    raise AssertionError(f"unknown node {type(node).__name__}")


def _eval_range(node: RangeRef, env: Env, keep_errors: bool = False) -> Any:
    """Evaluate a range to a ``Vec``, or to the first cell error in it.

    ``keep_errors`` puts the errors *in* the Vec instead, for the handful of
    functions Excel defines as ignoring them -- see
    ``_RANGE_ERROR_TOLERANT_FUNCS``. That result is not cached: the cache is
    keyed by rectangle alone, and the two forms of the same rectangle differ.
    """
    # Normalise B3:A1 -> A1:B3. Matches Excel's range semantics.
    c1, c2 = sorted([node.start.col, node.end.col])
    r1, r2 = sorted([node.start.row, node.end.row])
    sheet = node.start.sheet  # parser guarantees start.sheet == end.sheet
    key = (sheet, c1, r1, c2, r2)
    cached = None if keep_errors else env._range_cache.get(key)
    if cached is not None:
        # Re-register dependencies even on a cache hit -- consumers
        # rely on `refs_used` to know which cells they touched.
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                env.refs_used.add((sheet, c, r))
        return cached
    data: list[Any] = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = env.get_cell(c, r, sheet)
            if isinstance(v, ExcelError):
                if not keep_errors:
                    return v
                data.append(v)
                continue
            if v is None:
                data.append(0.0)
            elif isinstance(v, bool):
                data.append(v)
            elif isinstance(v, (int, float)):
                data.append(float(v))
            else:
                data.append(v)
    from ..engine import Vec  # lazy import to break cycle

    result = Vec(data, cols=c2 - c1 + 1)
    if not keep_errors:
        env._range_cache[key] = result
    return result


def _eval_spill(node: SpillRef, env: Env) -> Any:
    a = node.anchor
    return env.get_spill(a.col, a.row, a.sheet)


def _eval_name(node: Name, env: Env) -> Any:
    found, value = env.lookup_local(node.name)
    if found:
        return value
    target = env.lookup_name(node.name)
    if target is None:
        return ExcelError.NAME
    return _eval(target, env)


# Functions that see an error argument instead of being short-circuited by it.
# The IS-predicates answer FALSE for an error rather than propagating it, and
# the two type reporters exist to describe one: `ERROR.TYPE(A1)` over a
# `#DIV/0!` is 2, not `#DIV/0!`. `ISEVEN`/`ISODD` are deliberately absent --
# Excel propagates through those.
_ERROR_AWARE_FUNCS = frozenset(
    {
        "iferror",
        "ifna",
        "iserror",
        "iserr",
        "isna",
        "isblank",
        "islogical",
        "isnumber",
        "istext",
        "error.type",
        "type",
    }
)

# Functions whose *range* arguments tolerate cell errors instead of collapsing
# to them: Excel's COUNT family ignores error values inside a reference, where
# every other aggregate propagates (`=SUM(A1:A3)` over a `#DIV/0!` is
# `#DIV/0!`, `=COUNT(A1:A3)` is the count of the numbers beside it). COUNTA
# counts the error cell, which falls out of counting everything non-empty.
# A scalar error argument still short-circuits: only the range read changes.
_RANGE_ERROR_TOLERANT_FUNCS = frozenset({"count", "counta", "countblank", "countif", "countifs"})

# Functions that receive raw AST nodes (CellRef/RangeRef/...) plus the
# Env, instead of evaluated values. Used for functions whose semantics
# depend on the *reference* rather than the cell's value -- ROW(A5),
# COLUMN(A5), ROWS(A1:B10), COLUMNS(A1:B10).
# Conditional functions evaluate only the arguments their result depends on.
# `=IF(A1=0, "n/a", B1/A1)` is the standard guard against dividing by zero;
# evaluating both branches made it report the very error it exists to prevent,
# because the eager path materialised every argument and then propagated the
# first error it found.
#
# Dependency extraction still walks every branch (see `deps.py`), so a cell
# read only by the branch not taken stays a dependency. That is deliberate:
# the condition can change, and a graph whose shape depended on the current
# values could not be topologically ordered before evaluating it. A
# self-reference in an untaken branch is therefore still circular.
LAZY_FUNCS = frozenset({"if", "ifs", "switch", "iferror", "ifna", "choose"})


def _eval_lazy(name: str, node: Call, env: Env) -> Any:
    """Evaluate a conditional function, materialising only the arguments that
    determine its result. Argument-count errors mirror what the eager path
    produced by way of a TypeError from the underlying function."""
    args = node.args

    def val(i: int) -> Any:
        return _deref(_eval(args[i], env), env)

    if name == "if":
        if not 2 <= len(args) <= 3:
            return ExcelError.VALUE
        cond = val(0)
        if isinstance(cond, ExcelError):
            return cond
        if cond:
            return val(1)
        # Two-argument IF answers 0, matching the library function's default.
        return val(2) if len(args) == 3 else 0

    if name == "ifs":
        if not args or len(args) % 2 != 0:
            return ExcelError.NA
        for i in range(0, len(args), 2):
            cond = val(i)
            if isinstance(cond, ExcelError):
                return cond
            if cond:
                return val(i + 1)
        return ExcelError.NA

    if name == "switch":
        if not args:
            return ExcelError.VALUE
        subject = val(0)
        if isinstance(subject, ExcelError):
            return subject
        rest = len(args) - 1
        for i in range(rest // 2):
            match = val(1 + 2 * i)
            if isinstance(match, ExcelError):
                return match
            if subject == match:
                return val(2 + 2 * i)
        # A trailing unpaired argument is the default.
        return val(len(args) - 1) if rest % 2 == 1 else ExcelError.NA

    if name == "iferror":
        if len(args) != 2:
            return ExcelError.VALUE
        v = val(0)
        if isinstance(v, ExcelError) or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return val(1)
        return v

    if name == "ifna":
        if len(args) != 2:
            return ExcelError.VALUE
        v = val(0)
        return val(1) if v is ExcelError.NA else v

    if name == "choose":
        if len(args) < 2:
            return ExcelError.VALUE
        index = val(0)
        if isinstance(index, ExcelError):
            return index
        i = int(index)
        return val(i) if 1 <= i <= len(args) - 1 else ExcelError.VALUE

    raise AssertionError(f"unhandled lazy function {name}")


RAW_ARG_FUNCS = frozenset(
    {
        "row",
        "column",
        "rows",
        "columns",
        "isref",
        "isformula",
        "offset",
        "formulatext",
        "areas",
    }
)


def _eval_let(node: Call, env: Env) -> Any:
    """Evaluate LET(name1, value1, [name2, value2, ...], calculation).

    Binding forms cannot go through the eager call-by-value dispatch:
    the odd arguments are identifiers being *declared*, and the final
    calculation reads them. So LET is handled here, binding each value
    into a pushed scope (later pairs may reference earlier ones) before
    evaluating the calculation. A blank cell used as a value binds 0.0,
    matching how ranges materialise elsewhere.
    """
    args = node.args
    # Valid shape: an odd count >= 3 (>=1 name/value pair plus the final
    # calculation). Anything else is a #VALUE! in Excel.
    if len(args) < 3 or len(args) % 2 == 0:
        return ExcelError.VALUE
    scope = env.push_scope()
    try:
        for i in range(0, len(args) - 1, 2):
            name_node = args[i]
            if not isinstance(name_node, Name):
                return ExcelError.VALUE
            value = _eval(args[i + 1], env)
            if value is None:
                value = 0.0
            scope[name_node.name.lower()] = value
        return _eval(args[-1], env)
    finally:
        env.pop_scope()


def _make_lambda(node: Call, env: Env) -> Any:
    """Build a LambdaValue from LAMBDA(param1, ..., paramN, calculation).

    Every argument but the last is a parameter *name* being declared;
    the last is the body. Zero parameters is legal (a thunk). The
    current local scopes are snapshotted so the lambda closes over any
    enclosing LET bindings.
    """
    args = node.args
    if len(args) < 1:
        return ExcelError.VALUE
    params = args[:-1]
    body = args[-1]
    names: list[str] = []
    for p in params:
        if not isinstance(p, Name):
            return ExcelError.VALUE
        names.append(p.name.lower())
    captured = [dict(s) for s in env._local_scopes]
    return LambdaValue(tuple(names), body, env, captured)


def _apply_named(fn: Any, node: Call | Apply, env: Env) -> Any:
    """Evaluate the arguments of a call/apply and invoke a LambdaValue.

    Errors in arguments are passed through to the body rather than
    short-circuited, so a lambda wrapping IFERROR can still see them.
    """
    args = [_deref(_eval(a, env), env) for a in node.args]
    return fn(*args)


def _eval_apply(node: Apply, env: Env) -> Any:
    fn = _eval(node.func, env)
    if isinstance(fn, ExcelError):
        return fn
    if not isinstance(fn, LambdaValue):
        return ExcelError.VALUE
    return _apply_named(fn, node, env)


def _eval_call(node: Call, env: Env) -> Any:
    name_lower = node.name.lower()
    if name_lower == "let":
        return _eval_let(node, env)
    if name_lower == "lambda":
        return _make_lambda(node, env)
    # A LET-bound name used as a function: apply it if it is a lambda.
    found, local = env.lookup_local(node.name)
    if found:
        if isinstance(local, LambdaValue):
            return _apply_named(local, node, env)
        return ExcelError.VALUE
    # A named-range/Name-Manager lambda (`=LAMBDA(...)`), resolved
    # dynamically each call so a self-referential named lambda recurses.
    # Restricted to syntactic LAMBDA definitions so ordinary named ranges
    # (cell references) are not evaluated here for their side effects.
    named = env.lookup_name(node.name)
    if isinstance(named, Call) and named.name.lower() == "lambda":
        target = _eval(named, env)
        if isinstance(target, LambdaValue):
            return _apply_named(target, node, env)
    fn = env.lookup_func(node.name)
    if fn is None:
        return ExcelError.NAME
    if name_lower in LAZY_FUNCS:
        try:
            return _eval_lazy(name_lower, node, env)
        except ZeroDivisionError:
            return ExcelError.DIV0
        except (ValueError, OverflowError, ArithmeticError):
            return ExcelError.NUM
        except (TypeError, AttributeError):
            return ExcelError.VALUE
    if name_lower in RAW_ARG_FUNCS:
        try:
            return fn(env, *node.args)
        except ZeroDivisionError:
            return ExcelError.DIV0
        except (ValueError, OverflowError, ArithmeticError):
            return ExcelError.NUM
        except (TypeError, AttributeError):
            return ExcelError.VALUE
    # Normal (value) functions receive materialised values: any Reference
    # argument (from a nested OFFSET) is dereferenced before the call.
    if name_lower in _RANGE_ERROR_TOLERANT_FUNCS:
        args = [
            _eval_range(a, env, keep_errors=True)
            if isinstance(a, RangeRef)
            else _deref(_eval(a, env), env)
            for a in node.args
        ]
    else:
        args = [_deref(_eval(a, env), env) for a in node.args]
    if name_lower not in _ERROR_AWARE_FUNCS:
        err = first_error(*args)
        if err:
            return err
    try:
        return fn(*args)
    except ZeroDivisionError:
        return ExcelError.DIV0
    except (ValueError, OverflowError, ArithmeticError):
        return ExcelError.NUM
    except (TypeError, AttributeError):
        return ExcelError.VALUE


def _eval_pycall(node: PyCall, env: Env) -> Any:
    fn = env.py_registry.get(node.name)
    if fn is None:
        return ExcelError.NAME
    args = [_eval(a, env) for a in node.args]
    err = first_error(*args)
    if err:
        return err
    try:
        return fn(*args)
    except ZeroDivisionError:
        return ExcelError.DIV0
    except (ValueError, OverflowError, ArithmeticError):
        return ExcelError.NUM
    except Exception:
        return ExcelError.VALUE


def _eval_binop(node: BinOp, env: Env) -> Any:
    a = _deref(_eval(node.left, env), env)
    b = _deref(_eval(node.right, env), env)
    if node.op in ("=", "<>", "<", ">", "<=", ">="):
        return _vec_apply2(lambda x, y: _compare(node.op, x, y), a, b)
    op = _BINOP[node.op]
    return _vec_apply2(op, a, b)


def _eval_unary(node: UnaryOp, env: Env) -> Any:
    v = _deref(_eval(node.operand, env), env)
    if isinstance(v, ExcelError):
        return v
    if node.op == "+":
        return _vec_apply1(lambda x: _to_number(x), v)

    # minus
    def neg(x: Any) -> Any:
        n = _to_number(x)
        return n if isinstance(n, ExcelError) else -n

    return _vec_apply1(neg, v)


def _eval_percent(node: Percent, env: Env) -> Any:
    v = _deref(_eval(node.operand, env), env)
    if isinstance(v, ExcelError):
        return v

    def pct(x: Any) -> Any:
        n = _to_number(x)
        return n if isinstance(n, ExcelError) else n / 100.0

    return _vec_apply1(pct, v)
