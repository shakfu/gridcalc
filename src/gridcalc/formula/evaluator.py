from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .ast_nodes import (
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
    String,
    UnaryOp,
)
from .errors import ExcelError, first_error

Value = Any


class Env:
    def __init__(
        self,
        cell_value: Callable[[int, int], object],
        builtins: dict[str, Callable[..., Any]],
        named_ranges: dict[str, Node] | None = None,
        py_registry: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self.cell_value = cell_value
        self._builtins = {k.lower(): v for k, v in builtins.items()}
        self._named = {k.lower(): v for k, v in (named_ranges or {}).items()}
        self.py_registry = py_registry or {}
        self.refs_used: set[tuple[int, int]] = set()
        # Set by recalc before evaluating each formula. Functions in
        # `RAW_ARG_FUNCS` (e.g. ROW(), COLUMN()) consult this when called
        # with no arguments.
        self.current_cell: tuple[int, int] | None = None

    def lookup_func(self, name: str) -> Callable[..., Any] | None:
        return self._builtins.get(name.lower())

    def lookup_name(self, name: str) -> Node | None:
        return self._named.get(name.lower())

    def get_cell(self, c: int, r: int) -> object:
        self.refs_used.add((c, r))
        return self.cell_value(c, r)


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


def _make_vec(data: list[Any]) -> Any:
    from ..engine import Vec  # lazy import to break cycle

    return Vec(data)


def _vec_apply2(op: Callable[[Any, Any], Any], a: Any, b: Any) -> Any:
    if _is_vec(a) and _is_vec(b):
        ad, bd = _vec_data(a), _vec_data(b)
        if len(ad) != len(bd):
            return ExcelError.VALUE
        return _make_vec([op(x, y) for x, y in zip(ad, bd, strict=False)])
    if _is_vec(a):
        return _make_vec([op(x, b) for x in _vec_data(a)])
    if _is_vec(b):
        return _make_vec([op(a, y) for y in _vec_data(b)])
    return op(a, b)


def _vec_apply1(op: Callable[[Any], Any], a: Any) -> Any:
    if _is_vec(a):
        return _make_vec([op(x) for x in _vec_data(a)])
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


def _compare(op: str, a: Any, b: Any) -> Any:
    err = first_error(a, b)
    if err:
        return err
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
    if op == "<":
        return x < y
    if op == ">":
        return x > y
    if op == "<=":
        return x <= y
    if op == ">=":
        return x >= y
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
    return _eval(node, env)


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
        return env.get_cell(node.col, node.row)
    if isinstance(node, RangeRef):
        return _eval_range(node, env)
    if isinstance(node, Name):
        return _eval_name(node, env)
    if isinstance(node, Call):
        return _eval_call(node, env)
    if isinstance(node, PyCall):
        return _eval_pycall(node, env)
    if isinstance(node, BinOp):
        return _eval_binop(node, env)
    if isinstance(node, UnaryOp):
        return _eval_unary(node, env)
    if isinstance(node, Percent):
        return _eval_percent(node, env)
    raise AssertionError(f"unknown node {type(node).__name__}")


def _eval_range(node: RangeRef, env: Env) -> Any:
    # Normalise B3:A1 -> A1:B3. Matches Excel's range semantics.
    c1, c2 = sorted([node.start.col, node.end.col])
    r1, r2 = sorted([node.start.row, node.end.row])
    data: list[Any] = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = env.get_cell(c, r)
            if isinstance(v, ExcelError):
                return v
            data.append(_to_number_or_zero(v))
    return _make_vec(data)


def _eval_name(node: Name, env: Env) -> Any:
    target = env.lookup_name(node.name)
    if target is None:
        return ExcelError.NAME
    return _eval(target, env)


_ERROR_AWARE_FUNCS = frozenset({"iferror", "ifna", "iserror", "iserr", "isna"})

# Functions that receive raw AST nodes (CellRef/RangeRef/...) plus the
# Env, instead of evaluated values. Used for functions whose semantics
# depend on the *reference* rather than the cell's value -- ROW(A5),
# COLUMN(A5), ROWS(A1:B10), COLUMNS(A1:B10).
RAW_ARG_FUNCS = frozenset({"row", "column", "rows", "columns"})


def _eval_call(node: Call, env: Env) -> Any:
    fn = env.lookup_func(node.name)
    if fn is None:
        return ExcelError.NAME
    name_lower = node.name.lower()
    if name_lower in RAW_ARG_FUNCS:
        try:
            return fn(env, *node.args)
        except ZeroDivisionError:
            return ExcelError.DIV0
        except (ValueError, OverflowError, ArithmeticError):
            return ExcelError.NUM
        except (TypeError, AttributeError):
            return ExcelError.VALUE
    args = [_eval(a, env) for a in node.args]
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
    a = _eval(node.left, env)
    b = _eval(node.right, env)
    if node.op in ("=", "<>", "<", ">", "<=", ">="):
        return _vec_apply2(lambda x, y: _compare(node.op, x, y), a, b)
    op = _BINOP[node.op]
    return _vec_apply2(op, a, b)


def _eval_unary(node: UnaryOp, env: Env) -> Any:
    v = _eval(node.operand, env)
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
    v = _eval(node.operand, env)
    if isinstance(v, ExcelError):
        return v

    def pct(x: Any) -> Any:
        n = _to_number(x)
        return n if isinstance(n, ExcelError) else n / 100.0

    return _vec_apply1(pct, v)
