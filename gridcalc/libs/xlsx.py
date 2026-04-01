"""xlsx mode -- Excel-compatible function names for formula evaluation.

Provides IF, AND, OR, VLOOKUP, SUMIF, AVERAGE, text functions, etc.
All functions accept the same argument patterns as their Excel counterparts.
"""

from __future__ import annotations

import math
import operator
import re
from typing import Any

from ..engine import Vec

# -- Criteria parsing --


def _parse_criteria(criteria: str) -> Any:
    """Parse an Excel-style criteria string into a predicate function.

    Supports: ">5", ">=10", "<3", "<=0", "<>0", "=5", "5" (equals),
    and wildcard text patterns with * and ?.
    """
    criteria = criteria.strip()

    ops: list[tuple[str, Any]] = [
        (">=", operator.ge),
        ("<=", operator.le),
        ("<>", operator.ne),
        (">", operator.gt),
        ("<", operator.lt),
        ("=", operator.eq),
    ]

    for prefix, op in ops:
        if criteria.startswith(prefix):
            raw = criteria[len(prefix) :]
            try:
                cmp_val: float | str = float(raw)
            except ValueError:
                cmp_val = raw
            return lambda x, o=op, v=cmp_val: o(x, v)

    # No operator prefix -- treat as equality
    try:
        val = float(criteria)
        return lambda x, v=val: x == v
    except ValueError:
        # Wildcard text match: * matches any chars, ? matches one char
        pattern = re.escape(criteria).replace(r"\*", ".*").replace(r"\?", ".")
        regex = re.compile(f"^{pattern}$", re.IGNORECASE)
        return lambda x, r=regex: bool(r.match(str(x)))


# -- Logical functions --


def IF(condition: Any, true_val: Any, false_val: Any = 0) -> Any:
    """=IF(A1>0, A1, 0)"""
    return true_val if condition else false_val


def AND(*args: Any) -> bool:
    """=AND(A1>0, B1>0, C1>0)"""
    return all(args)


def OR(*args: Any) -> bool:
    """=OR(A1>0, B1>0)"""
    return any(args)


def NOT(x: Any) -> bool:
    """=NOT(A1>0)"""
    return not x


def IFERROR(value: Any, fallback: Any) -> Any:
    """=IFERROR(A1/B1, 0)"""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return fallback
    return value


# -- Math functions --


def ROUND(x: float, n: int = 0) -> float:
    """=ROUND(A1, 2)"""
    return round(x, n)


def ROUNDUP(x: float, n: int = 0) -> float:
    """=ROUNDUP(2.123, 2) -> 2.13"""
    factor: float = 10.0**n
    return math.ceil(x * factor) / factor


def ROUNDDOWN(x: float, n: int = 0) -> float:
    """=ROUNDDOWN(2.129, 2) -> 2.12"""
    factor: float = 10.0**n
    return math.floor(x * factor) / factor


def MOD(x: float, y: float) -> float:
    """=MOD(10, 3) -> 1"""
    return x % y


def POWER(x: float, y: float) -> float:
    """=POWER(2, 10) -> 1024"""
    return float(x**y)


def SIGN(x: float) -> int:
    """=SIGN(-5) -> -1"""
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


# -- Aggregate functions --


def AVERAGE(x: Vec | float) -> float:
    """=AVERAGE(A1:A10) -- alias for AVG."""
    if isinstance(x, Vec):
        return sum(x.data) / len(x.data) if x.data else 0.0
    return float(x)


def MEDIAN(x: Vec | float) -> float:
    """=MEDIAN(A1:A10)"""
    if isinstance(x, Vec):
        s = sorted(x.data)
        n = len(s)
        if n == 0:
            return 0.0
        mid = n // 2
        if n % 2 == 0:
            return (s[mid - 1] + s[mid]) / 2
        return s[mid]
    return float(x)


def SUMPRODUCT(a: Vec, b: Vec) -> float:
    """=SUMPRODUCT(A1:A10, B1:B10)"""
    return sum(x * y for x, y in zip(a.data, b.data, strict=False))


def LARGE(x: Vec, k: int) -> float:
    """=LARGE(A1:A10, 2) -- kth largest value."""
    s = sorted(x.data, reverse=True)
    return s[int(k) - 1]


def SMALL(x: Vec, k: int) -> float:
    """=SMALL(A1:A10, 2) -- kth smallest value."""
    s = sorted(x.data)
    return s[int(k) - 1]


# -- Conditional aggregates --


def SUMIF(rng: Vec, criteria: str, sum_rng: Vec | None = None) -> float:
    """=SUMIF(A1:A10, ">5") or =SUMIF(A1:A10, ">5", B1:B10)"""
    pred = _parse_criteria(criteria)
    values = sum_rng.data if sum_rng is not None else rng.data
    return sum(v for c, v in zip(rng.data, values, strict=False) if pred(c))


def COUNTIF(rng: Vec, criteria: str) -> int:
    """=COUNTIF(A1:A10, ">5")"""
    pred = _parse_criteria(criteria)
    return sum(1 for x in rng.data if pred(x))


def AVERAGEIF(rng: Vec, criteria: str, avg_rng: Vec | None = None) -> float:
    """=AVERAGEIF(A1:A10, ">5") or =AVERAGEIF(A1:A10, ">5", B1:B10)"""
    pred = _parse_criteria(criteria)
    values = avg_rng.data if avg_rng is not None else rng.data
    matches = [v for c, v in zip(rng.data, values, strict=False) if pred(c)]
    return sum(matches) / len(matches) if matches else 0.0


# -- Lookup functions --


def VLOOKUP(lookup: float, table: Vec, col_idx: int, approx: int = 1) -> float:
    """=VLOOKUP(value, A1:C10, 3, 0)

    Simplified: table is a flat Vec, col_idx selects which "column" to return.
    Requires the table range to span multiple columns (e.g. A1:C10 gives a
    Vec of 30 values for 10 rows x 3 cols). col_idx is 1-based.

    approx=0: exact match, approx=1: nearest match (assumes sorted first col).
    """
    cols = int(col_idx)
    data = table.data
    if cols <= 0 or len(data) == 0:
        return float("nan")
    n_rows = len(data) // cols
    if n_rows == 0:
        return float("nan")

    best_row = -1
    if approx:
        for i in range(n_rows):
            val = data[i * cols]
            if val <= lookup:
                best_row = i
            else:
                break
    else:
        for i in range(n_rows):
            if data[i * cols] == lookup:
                best_row = i
                break

    if best_row < 0:
        return float("nan")
    return data[best_row * cols + (cols - 1)]


def HLOOKUP(lookup: float, table: Vec, row_idx: int, approx: int = 1) -> float:
    """=HLOOKUP(value, A1:J3, 3, 0)

    Like VLOOKUP but searches the first row and returns from row_idx.
    """
    rows = int(row_idx)
    data = table.data
    if rows <= 0 or len(data) == 0:
        return float("nan")
    n_cols = len(data) // rows
    if n_cols == 0:
        return float("nan")

    best_col = -1
    if approx:
        for j in range(n_cols):
            if data[j] <= lookup:
                best_col = j
            else:
                break
    else:
        for j in range(n_cols):
            if data[j] == lookup:
                best_col = j
                break

    if best_col < 0:
        return float("nan")
    return data[(rows - 1) * n_cols + best_col]


def INDEX(rng: Vec, row: int, col: int = 1) -> float:
    """=INDEX(A1:C10, 3, 2) -- 1-based row and column index into a range."""
    return rng.data[int(row) - 1]


def MATCH(lookup: float, rng: Vec, match_type: int = 1) -> int:
    """=MATCH(value, A1:A10, 0) -- returns 1-based position.

    match_type: 0=exact, 1=largest<=lookup (sorted asc), -1=smallest>=lookup.
    """
    if match_type == 0:
        for i, v in enumerate(rng.data):
            if v == lookup:
                return i + 1
    elif match_type == 1:
        best = -1
        for i, v in enumerate(rng.data):
            if v <= lookup:
                best = i
            else:
                break
        if best >= 0:
            return best + 1
    elif match_type == -1:
        best = -1
        for i, v in enumerate(rng.data):
            if v >= lookup:
                best = i
            else:
                break
        if best >= 0:
            return best + 1
    return 0


# -- Text functions --


def CONCATENATE(*args: Any) -> str:
    """=CONCATENATE(A1, " ", B1)"""
    return "".join(str(a) for a in args)


def CONCAT(*args: Any) -> str:
    """=CONCAT(A1, B1) -- same as CONCATENATE."""
    return "".join(str(a) for a in args)


def LEFT(text: str, n: int = 1) -> str:
    """=LEFT("hello", 3) -> "hel" """
    return str(text)[: int(n)]


def RIGHT(text: str, n: int = 1) -> str:
    """=RIGHT("hello", 3) -> "llo" """
    s = str(text)
    return s[len(s) - int(n) :]


def MID(text: str, start: int, n: int) -> str:
    """=MID("hello", 2, 3) -> "ell" (1-based start)"""
    s = str(text)
    st = int(start) - 1
    return s[st : st + int(n)]


def LEN(text: Any) -> int:
    """=LEN("hello") -> 5"""
    return len(str(text))


def TRIM(text: str) -> str:
    """=TRIM("  hello  ") -> "hello" """
    return str(text).strip()


def UPPER(text: str) -> str:
    """=UPPER("hello") -> "HELLO" """
    return str(text).upper()


def LOWER(text: str) -> str:
    """=LOWER("HELLO") -> "hello" """
    return str(text).lower()


def PROPER(text: str) -> str:
    """=PROPER("hello world") -> "Hello World" """
    return str(text).title()


def SUBSTITUTE(text: str, old: str, new: str, instance: int = 0) -> str:
    """=SUBSTITUTE("abab", "a", "x") -> "xbxb"
    =SUBSTITUTE("abab", "a", "x", 1) -> "xbab" (1-based instance)
    """
    s = str(text)
    if instance <= 0:
        return s.replace(str(old), str(new))
    count = 0
    result = []
    i = 0
    old_s = str(old)
    new_s = str(new)
    while i < len(s):
        if s[i : i + len(old_s)] == old_s:
            count += 1
            if count == instance:
                result.append(new_s)
                i += len(old_s)
                continue
        result.append(s[i])
        i += 1
    return "".join(result)


def REPT(text: str, n: int) -> str:
    """=REPT("*", 5) -> "*****" """
    return str(text) * int(n)


def EXACT(a: str, b: str) -> bool:
    """=EXACT("hello", "Hello") -> False (case-sensitive compare)"""
    return str(a) == str(b)


# -- Builtins dict for registration --

BUILTINS: dict[str, Any] = {
    # Logical
    "IF": IF,
    "AND": AND,
    "OR": OR,
    "NOT": NOT,
    "IFERROR": IFERROR,
    # Math
    "ROUND": ROUND,
    "ROUNDUP": ROUNDUP,
    "ROUNDDOWN": ROUNDDOWN,
    "MOD": MOD,
    "POWER": POWER,
    "SIGN": SIGN,
    # Aggregates
    "AVERAGE": AVERAGE,
    "MEDIAN": MEDIAN,
    "SUMPRODUCT": SUMPRODUCT,
    "LARGE": LARGE,
    "SMALL": SMALL,
    # Conditional aggregates
    "SUMIF": SUMIF,
    "COUNTIF": COUNTIF,
    "AVERAGEIF": AVERAGEIF,
    # Lookup
    "VLOOKUP": VLOOKUP,
    "HLOOKUP": HLOOKUP,
    "INDEX": INDEX,
    "MATCH": MATCH,
    # Text
    "CONCATENATE": CONCATENATE,
    "CONCAT": CONCAT,
    "LEFT": LEFT,
    "RIGHT": RIGHT,
    "MID": MID,
    "LEN": LEN,
    "TRIM": TRIM,
    "UPPER": UPPER,
    "LOWER": LOWER,
    "PROPER": PROPER,
    "SUBSTITUTE": SUBSTITUTE,
    "REPT": REPT,
    "EXACT": EXACT,
}
