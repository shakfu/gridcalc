"""A subset of PuLP's modelling API, solved by the builtin HiGHS extension.

Model text written for PuLP runs unchanged when it keeps to these names; a
name outside the subset fails with :class:`PulpError` rather than behaving
differently. Design: ``docs/dev/crosstab-model.md``.

Values follow PuLP 2.x: ``LpVariable`` defaults to a free variable, ``solve``
returns an ``LpStatus`` code, and ``varValue`` is ``None`` until an optimal
solve. A variable that appears in no expression is not sent to the solver.

After an optimal LP solve, ``constraint.pi`` is d(objective)/d(rhs) and
``variable.dj`` is d(objective)/d(variable), both in the objective's own sense.
That is PuLP's convention with its default solver, CBC; PuLP's HiGHS interface
flips both signs for a maximisation. A MIP leaves both ``None``.

Not supported: solver selection, elastic constraints, file output
(``writeLP``, ``writeMPS``) and quadratic terms. PuLP 4 is a different API
(no ``LpVariable.dicts``); this subset follows PuLP 2 and 3.
"""

from __future__ import annotations

import itertools
import math
import numbers
from collections.abc import Iterable
from typing import Any

from . import _opt as _ext  # type: ignore[attr-defined]  # nanobind extension

__all__ = [
    "LpAffineExpression",
    "LpBinary",
    "LpConstraint",
    "LpConstraintEQ",
    "LpConstraintGE",
    "LpConstraintLE",
    "LpContinuous",
    "LpInteger",
    "LpMaximize",
    "LpMinimize",
    "LpProblem",
    "LpStatus",
    "LpStatusInfeasible",
    "LpStatusNotSolved",
    "LpStatusOptimal",
    "LpStatusUnbounded",
    "LpStatusUndefined",
    "LpVariable",
    "PulpError",
    "lpSum",
    "value",
]

LpMinimize = 1
LpMaximize = -1

LpContinuous = "Continuous"
LpInteger = "Integer"
LpBinary = "Binary"

LpConstraintLE = -1
LpConstraintEQ = 0
LpConstraintGE = 1

LpStatusNotSolved = 0
LpStatusOptimal = 1
LpStatusInfeasible = -1
LpStatusUnbounded = -2
LpStatusUndefined = -3
LpStatus = {
    LpStatusNotSolved: "Not Solved",
    LpStatusOptimal: "Optimal",
    LpStatusInfeasible: "Infeasible",
    LpStatusUnbounded: "Unbounded",
    LpStatusUndefined: "Undefined",
}

_SENSE_EXT = {LpConstraintLE: _ext.LE, LpConstraintGE: _ext.GE, LpConstraintEQ: _ext.EQ}
_SENSE_TEXT = {LpConstraintLE: "<=", LpConstraintGE: ">=", LpConstraintEQ: "="}


class PulpError(Exception):
    """A model error, or a PuLP feature outside the subset."""


class _Subset:
    """Names a missing attribute as outside the subset, not as a typo."""

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        raise PulpError(f"{type(self).__name__}.{attr} is not in gridcalc's PuLP subset")


def _number(x: Any) -> float:
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        raise PulpError(f"{x!r} is not a number")
    return float(x)


Pair = tuple["LpVariable", "LpVariable"]


def _pair(a: LpVariable, b: LpVariable) -> Pair:
    """``(a, b)`` in a fixed order, so `x*y` and `y*x` are one term."""
    return (a, b) if id(a) <= id(b) else (b, a)


class LpAffineExpression(_Subset):
    """``sum(coef * var) + constant``, plus ``sum(coef * var * var)`` for a QP objective.

    The quadratic part is gridcalc's: PuLP itself refuses a product of variables.
    """

    def __init__(
        self,
        terms: dict[LpVariable, float] | None = None,
        constant: float = 0.0,
        qterms: dict[Pair, float] | None = None,
    ) -> None:
        self.terms: dict[LpVariable, float] = dict(terms or {})
        self.constant = constant
        self.qterms: dict[Pair, float] = dict(qterms or {})

    @staticmethod
    def of(x: Any) -> LpAffineExpression:
        if isinstance(x, LpAffineExpression):
            return x
        if isinstance(x, LpVariable):
            return LpAffineExpression({x: 1.0})
        if x is None:
            return LpAffineExpression()
        return LpAffineExpression(constant=_number(x))

    def copy(self) -> LpAffineExpression:
        return LpAffineExpression(self.terms, self.constant, self.qterms)

    def _add(self, other: Any, sign: float) -> LpAffineExpression:
        return self.copy()._add_in_place(other, sign)

    def _scale(self, k: Any) -> LpAffineExpression:
        if isinstance(k, (LpAffineExpression, LpVariable)):
            return self._product(LpAffineExpression.of(k))
        f = _number(k)
        return LpAffineExpression(
            {v: a * f for v, a in self.terms.items()},
            self.constant * f,
            {p: a * f for p, a in self.qterms.items()},
        )

    def _product(self, other: LpAffineExpression) -> LpAffineExpression:
        """``self * other``: quadratic at most, as HiGHS solves."""
        if not other.terms and not other.qterms:
            return self._scale(other.constant)
        if not self.terms and not self.qterms:
            return other._scale(self.constant)
        if self.qterms or other.qterms:
            raise PulpError("a product past degree 2 is not supported; HiGHS solves quadratics")
        out = self._scale(other.constant)._add(other._scale(self.constant), 1.0)
        out.constant -= self.constant * other.constant  # counted in both scales
        for v, a in self.terms.items():
            for w, b in other.terms.items():
                p = _pair(v, w)
                out.qterms[p] = out.qterms.get(p, 0.0) + a * b
        return out

    def __add__(self, o: Any) -> LpAffineExpression:
        return self._add(o, 1.0)

    def __radd__(self, o: Any) -> LpAffineExpression:
        return self._add(o, 1.0)

    def __sub__(self, o: Any) -> LpAffineExpression:
        return self._add(o, -1.0)

    def _add_in_place(self, other: Any, sign: float) -> LpAffineExpression:
        o = LpAffineExpression.of(other)
        for v, a in o.terms.items():
            self.terms[v] = self.terms.get(v, 0.0) + sign * a
        for p, a in o.qterms.items():
            self.qterms[p] = self.qterms.get(p, 0.0) + sign * a
        self.constant += sign * o.constant
        return self

    def __pow__(self, n: Any) -> LpAffineExpression:
        if n != 2:
            raise PulpError("only a square (** 2) is supported")
        return self._product(self)

    # In place, as in PuLP, so `e += x` in a loop is linear, not quadratic.
    def __iadd__(self, o: Any) -> LpAffineExpression:
        return self._add_in_place(o, 1.0)

    def __isub__(self, o: Any) -> LpAffineExpression:
        return self._add_in_place(o, -1.0)

    def __rsub__(self, o: Any) -> LpAffineExpression:
        return LpAffineExpression.of(o)._add(self, -1.0)

    def __neg__(self) -> LpAffineExpression:
        return self._scale(-1.0)

    def __pos__(self) -> LpAffineExpression:
        return self

    def __mul__(self, k: Any) -> LpAffineExpression:
        return self._scale(k)

    def __rmul__(self, k: Any) -> LpAffineExpression:
        return self._scale(k)

    def __truediv__(self, k: Any) -> LpAffineExpression:
        if isinstance(k, (LpAffineExpression, LpVariable)):
            raise PulpError("dividing by a variable is not linear")
        return self._scale(1.0 / _number(k))

    def _constraint(self, o: Any, sense: int) -> LpConstraint:
        e = self - o
        if e.qterms:
            raise PulpError("a constraint must be linear; only the objective may be quadratic")
        return LpConstraint(e, sense)

    def __le__(self, o: Any) -> LpConstraint:
        return self._constraint(o, LpConstraintLE)

    def __ge__(self, o: Any) -> LpConstraint:
        return self._constraint(o, LpConstraintGE)

    def __eq__(self, o: Any) -> LpConstraint:  # type: ignore[override]
        return self._constraint(o, LpConstraintEQ)

    __hash__ = object.__hash__

    def value(self) -> float | None:
        total = self.constant
        for v, a in self.terms.items():
            if v.varValue is None:
                return None
            total += a * v.varValue
        for (v, w), a in self.qterms.items():
            if v.varValue is None or w.varValue is None:
                return None
            total += a * v.varValue * w.varValue
        return total

    def __repr__(self) -> str:
        parts = [f"{a:g}*{v.name}*{w.name}" for (v, w), a in self.qterms.items()]
        parts += [f"{a:g}*{v.name}" for v, a in self.terms.items()]
        if self.constant or not parts:
            parts.append(f"{self.constant:g}")
        return " + ".join(parts)


class LpVariable(LpAffineExpression):
    """A decision variable. Hashed by identity, so it can key a dict."""

    def __init__(
        self,
        name: str,
        lowBound: float | None = None,  # noqa: N803  (PuLP's spelling)
        upBound: float | None = None,  # noqa: N803
        cat: str = LpContinuous,
        e: Any = None,
    ) -> None:
        if e is not None:
            raise PulpError("LpVariable(e=...) column modelling is not in gridcalc's PuLP subset")
        if cat not in (LpContinuous, LpInteger, LpBinary):
            raise PulpError(f"unknown category {cat!r}")
        self.name = str(name)
        self.cat = cat
        lo = -math.inf if lowBound is None else _number(lowBound)
        hi = math.inf if upBound is None else _number(upBound)
        if cat == LpBinary:
            lo, hi = max(lo, 0.0), min(hi, 1.0)
        self.lowBound = lo
        self.upBound = hi
        self.varValue: float | None = None
        self.dj: float | None = None

    # An LpVariable is its own one-term expression.
    @property
    def terms(self) -> dict[LpVariable, float]:
        return {self: 1.0}

    @terms.setter
    def terms(self, _: Any) -> None:
        pass

    @property
    def constant(self) -> float:
        return 0.0

    @constant.setter
    def constant(self, _: Any) -> None:
        pass

    @property
    def qterms(self) -> dict[Pair, float]:
        return {}

    @qterms.setter
    def qterms(self, _: Any) -> None:
        pass

    def copy(self) -> LpAffineExpression:
        return LpAffineExpression({self: 1.0})

    # A variable is never changed by `+=`; `v += 1` makes a new expression.
    def __iadd__(self, o: Any) -> LpAffineExpression:
        return self._add(o, 1.0)

    def __isub__(self, o: Any) -> LpAffineExpression:
        return self._add(o, -1.0)

    def value(self) -> float | None:
        return self.varValue

    def __repr__(self) -> str:
        return self.name

    @classmethod
    def dicts(
        cls,
        name: str,
        indices: Any,
        lowBound: float | None = None,  # noqa: N803
        upBound: float | None = None,  # noqa: N803
        cat: str = LpContinuous,
        indexStart: list[Any] | None = None,  # noqa: N803
    ) -> dict[Any, Any]:
        """One variable per index; a tuple of index lists gives nested dicts, as in PuLP."""
        start = list(indexStart or [])
        if isinstance(indices, tuple):
            if len(indices) == 0:
                raise PulpError("LpVariable.dicts: empty index tuple")
            head, rest = indices[0], indices[1:]
            if not rest:
                return cls.dicts(name, head, lowBound, upBound, cat, start)
            return {
                i: cls.dicts(name, rest, lowBound, upBound, cat, [*start, i]) for i in list(head)
            }
        return {i: cls(_var_name(name, [*start, i]), lowBound, upBound, cat) for i in list(indices)}


def _var_name(name: str, index: list[Any]) -> str:
    return "_".join([name, *(str(i) for i in index)]).replace(" ", "_")


def _hessian(qterms: dict[Pair, float], pos: dict[LpVariable, int]) -> list[list[float]]:
    """The lower triangle of Q, ragged, for HiGHS's ``c'x + 0.5 x'Qx``.

    ``a * x_i * x_j`` puts ``a`` at ``Q[i][j]`` and ``Q[j][i]``; a square
    ``a * x_i**2`` puts ``2a`` at ``Q[i][i]``.
    """
    rows: list[list[float]] = [[] for _ in pos]
    for (v, w), a in qterms.items():
        i, j = pos[v], pos[w]
        i, j = max(i, j), min(i, j)
        row = rows[i]
        if len(row) <= j:
            row.extend([0.0] * (j + 1 - len(row)))
        row[j] += 2 * a if i == j else a
    return rows


class LpConstraint(_Subset):
    """``expr sense 0``, from a comparison of expressions."""

    def __init__(self, expr: LpAffineExpression, sense: int, name: str | None = None) -> None:
        self.expr = expr
        self.sense = sense
        self.name = name
        self.pi: float | None = None

    def __bool__(self) -> bool:
        raise PulpError("a constraint has no truth value; add it to a problem with +=")

    def __repr__(self) -> str:
        e = self.expr
        return f"{LpAffineExpression(e.terms)!r} {_SENSE_TEXT[self.sense]} {-e.constant:g}"


def lpSum(vector: Iterable[Any]) -> LpAffineExpression:  # noqa: N802  (PuLP's spelling)
    """The sum of numbers, variables and expressions."""
    out = LpAffineExpression()
    for x in vector:  # in place: `out = out + x` copies the dict each time
        out._add_in_place(x, 1.0)
    return out


def value(x: Any) -> Any:
    """A number as itself; a variable or expression at the last solution, or None."""
    if isinstance(x, LpAffineExpression):
        return x.value()
    return x


class LpProblem(_Subset):
    """An objective and named constraints. ``prob += expr`` sets the objective."""

    def __init__(self, name: str = "NoName", sense: int = LpMinimize) -> None:
        if sense not in (LpMinimize, LpMaximize):
            raise PulpError("sense must be LpMinimize or LpMaximize")
        self.name = name
        self.sense = sense
        self.objective: LpAffineExpression | None = None
        self.constraints: dict[str, LpConstraint] = {}
        self.status = LpStatusNotSolved
        self._unnamed = itertools.count(1)

    def __iadd__(self, other: Any) -> LpProblem:
        name = None
        if isinstance(other, tuple):
            if len(other) != 2:
                raise PulpError("prob += takes (expression, name)")
            other, name = other
        if isinstance(other, LpConstraint):
            self.addConstraint(other, name)
        elif isinstance(other, bool):
            raise PulpError("prob += got a bool; comparing plain numbers makes no constraint")
        else:
            self.setObjective(LpAffineExpression.of(other))
        return self

    def setObjective(self, obj: Any) -> None:  # noqa: N802
        self.objective = LpAffineExpression.of(obj)

    def addConstraint(self, c: LpConstraint, name: str | None = None) -> None:  # noqa: N802
        name = name or c.name
        if name is None:
            name = f"_C{next(self._unnamed)}"
            while name in self.constraints:
                name = f"_C{next(self._unnamed)}"
        name = str(name).replace(" ", "_")
        if name in self.constraints:
            raise PulpError(f"overlapping constraint names: {name}")
        c.name = name
        self.constraints[name] = c

    def variables(self) -> list[LpVariable]:
        """The variables that appear in the objective or a constraint, by name."""
        return sorted(self._columns(), key=lambda v: v.name)

    def _columns(self) -> list[LpVariable]:
        """Every variable in the model; those in quadratic terms first, so the
        Hessian's lower-triangle rows stay as short as the quadratic part."""
        seen: dict[LpVariable, None] = {}
        exprs = [c.expr for c in self.constraints.values()]
        if self.objective is not None:
            for v, w in self.objective.qterms:
                seen.setdefault(v)
                seen.setdefault(w)
            exprs.insert(0, self.objective)
        for e in exprs:
            for v in e.terms:
                seen.setdefault(v)
        return list(seen)

    def solve(self, solver: Any = None, **kwargs: Any) -> int:
        """Solve with HiGHS. Returns ``self.status``. ``time_limit`` in seconds."""
        if solver is not None:
            raise PulpError("solver selection is not in gridcalc's PuLP subset; call solve()")
        time_limit = kwargs.pop("time_limit", None)
        if kwargs:
            raise PulpError(f"solve() does not take {', '.join(kwargs)}")
        cols = self._columns()
        for v in cols:
            v.varValue = None
            v.dj = None
        for c in self.constraints.values():
            c.pi = None
        pos = {v: j for j, v in enumerate(cols)}
        obj = self.objective or LpAffineExpression()

        # Row-wise CSR: a generated model is sparse, and its dense matrix may not fit.
        a_start: list[int] = []
        a_index: list[int] = []
        a_value: list[float] = []
        senses: list[int] = []
        rhs: list[float] = []
        sent: list[LpConstraint] = []
        for c in self.constraints.values():
            if not c.expr.terms:
                k = c.expr.constant  # `0 <= 3` style: decide it here
                ok = {LpConstraintLE: k <= 0, LpConstraintGE: k >= 0, LpConstraintEQ: k == 0}
                if not ok[c.sense]:
                    self.status = LpStatusInfeasible
                    return self.status
                continue
            a_start.append(len(a_index))
            for v, a in c.expr.terms.items():
                a_index.append(pos[v])
                a_value.append(a)
            sent.append(c)
            senses.append(_SENSE_EXT[c.sense])
            rhs.append(-c.expr.constant)

        if not cols:
            self.status = LpStatusOptimal
            return self.status

        c_vec = [0.0] * len(cols)
        for v, a in obj.terms.items():
            c_vec[pos[v]] = a
        args: dict[str, Any] = {
            "maximize": self.sense == LpMaximize,
            "integer_vars": [j for j, v in enumerate(cols) if v.cat == LpInteger],
            "binary_vars": [j for j, v in enumerate(cols) if v.cat == LpBinary],
        }
        # Duals exist for an LP only; HiGHS ignores the flag for a MIP or QP.
        args["sensitivity"] = not (args["integer_vars"] or args["binary_vars"])
        quadratic = {p: a for p, a in obj.qterms.items() if a != 0.0}
        if quadratic:
            if args["integer_vars"] or args["binary_vars"]:
                raise PulpError(
                    "a quadratic objective with integer variables (MIQP) is not supported"
                )
            args["hessian"] = _hessian(quadratic, pos)
            args["sensitivity"] = False
        if time_limit is not None:
            args["time_limit"] = _number(time_limit)
        try:
            sol = _ext.solve_lp_sparse(
                c_vec,
                a_start,
                a_index,
                a_value,
                senses,
                rhs,
                [v.lowBound for v in cols],
                [v.upBound for v in cols],
                **args,
            )
        except (RuntimeError, ValueError) as exc:
            if quadratic:
                raise PulpError(
                    f"solver failed: {exc}; a quadratic objective must be convex when"
                    " minimising and concave when maximising"
                ) from exc
            raise PulpError(f"solver failed: {exc}") from exc
        self.status = {
            _ext.OPTIMAL: LpStatusOptimal,
            _ext.INFEASIBLE: LpStatusInfeasible,
            _ext.UNBOUNDED: LpStatusUnbounded,
        }.get(sol.status, LpStatusUndefined)
        if self.status == LpStatusOptimal:
            for v, x in zip(cols, sol.x, strict=True):
                v.varValue = x
            if sol.sensitivity_valid:
                # The binding's signs already match CBC's (docs/dev/crosstab-model.md).
                for c, d in zip(sent, sol.duals, strict=True):
                    c.pi = d + 0.0  # + 0.0 turns -0.0 into 0.0
                for v, d in zip(cols, sol.reduced_costs, strict=True):
                    v.dj = d + 0.0
        return self.status
