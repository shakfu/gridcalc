"""xlsx mode -- Excel-compatible function names for formula evaluation.

Provides IF, AND, OR, VLOOKUP, SUMIF, AVERAGE, text functions, etc.
All functions accept the same argument patterns as their Excel counterparts.
"""

from __future__ import annotations

import datetime as _dt
import math
import operator
import re
import statistics
from typing import Any

from ..engine import Vec
from ..formula.errors import ExcelError

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
    if type(value).__name__ == "ExcelError":
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


def FIND(find_text: str, within: str, start: int = 1) -> int | ExcelError:
    """=FIND("o", "hello") -> 5. 1-indexed, case-sensitive."""
    idx = str(within).find(str(find_text), max(int(start) - 1, 0))
    return idx + 1 if idx >= 0 else ExcelError.VALUE


def SEARCH(find_text: str, within: str, start: int = 1) -> int | ExcelError:
    """=SEARCH("O", "hello") -> 5. 1-indexed, case-insensitive."""
    idx = str(within).lower().find(str(find_text).lower(), max(int(start) - 1, 0))
    return idx + 1 if idx >= 0 else ExcelError.VALUE


def REPLACE(text: str, start: int, n: int, new: str) -> str:
    """=REPLACE("abcdef", 2, 3, "X") -> "aXef" """
    s = str(text)
    i = max(int(start) - 1, 0)
    return s[:i] + str(new) + s[i + max(int(n), 0) :]


def TEXTJOIN(sep: str, ignore_empty: Any, *args: Any) -> str:
    """=TEXTJOIN(",", TRUE, "a", "", "b") -> "a,b" """
    skip = bool(ignore_empty)
    parts: list[str] = []
    for a in args:
        if isinstance(a, Vec):
            for v in a.data:
                s = "" if v is None else str(v)
                if skip and s == "":
                    continue
                parts.append(s)
        else:
            s = "" if a is None else str(a)
            if skip and s == "":
                continue
            parts.append(s)
    return str(sep).join(parts)


def CHAR(n: int) -> str:
    """=CHAR(65) -> 'A'"""
    return chr(int(n))


def CODE(text: str) -> int:
    """=CODE("A") -> 65"""
    s = str(text)
    return ord(s[0]) if s else 0


def VALUE(text: Any) -> float | ExcelError:
    """=VALUE("3.14") -> 3.14"""
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).strip().replace(",", ""))
    except (TypeError, ValueError):
        return ExcelError.VALUE


def TEXT(value: Any, fmt: str) -> str:
    """=TEXT(1234.5, "0.00") -> "1234.50". Subset of Excel format strings."""
    f = str(fmt)
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    # Decimal precision derived from trailing zeros after a "."
    decimals = len(f.split(".", 1)[1].rstrip("%")) if "." in f else 0
    if "%" in f:
        return f"{n * 100:.{decimals}f}%"
    if "," in f:
        return f"{n:,.{decimals}f}"
    return f"{n:.{decimals}f}"


# -- Date and time --
#
# Excel stores dates as serial numbers since 1899-12-30 (the offset that
# matches Excel's 1900-leap-year bug for serials > 60). Time is the
# fractional part. We use Python's datetime.date / datetime as the
# in-memory representation and convert to/from serials at the boundary.

_EXCEL_EPOCH = _dt.date(1899, 12, 30)


def _to_serial(d: _dt.date | _dt.datetime) -> float:
    if isinstance(d, _dt.datetime):
        days = (d.date() - _EXCEL_EPOCH).days
        secs = d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
        return days + secs / 86400.0
    return float((d - _EXCEL_EPOCH).days)


def _from_serial(s: float) -> _dt.datetime:
    days = int(s)
    frac = s - days
    base = _EXCEL_EPOCH + _dt.timedelta(days=days)
    return _dt.datetime(base.year, base.month, base.day) + _dt.timedelta(seconds=frac * 86400)


def NOW() -> float:
    """=NOW() -> current date+time as Excel serial."""
    return _to_serial(_dt.datetime.now())


def TODAY() -> float:
    """=TODAY() -> current date as Excel serial."""
    return _to_serial(_dt.date.today())


def DATE(year: int, month: int, day: int) -> float | ExcelError:
    """=DATE(2026, 5, 5) -> serial."""
    try:
        return _to_serial(_dt.date(int(year), int(month), int(day)))
    except (TypeError, ValueError):
        return ExcelError.VALUE


def TIME(hour: int, minute: int, second: int) -> float:
    """=TIME(14, 30, 0) -> 0.604166... (fractional day)."""
    return (int(hour) * 3600 + int(minute) * 60 + int(second)) / 86400.0


def DATEVALUE(text: str) -> float | ExcelError:
    """=DATEVALUE("2026-05-05") -> serial. Tries common ISO formats."""
    s = str(text).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return _to_serial(_dt.datetime.strptime(s, fmt).date())
        except ValueError:
            continue
    return ExcelError.VALUE


def TIMEVALUE(text: str) -> float | ExcelError:
    """=TIMEVALUE("14:30:00") -> 0.604166..."""
    s = str(text).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
        try:
            t = _dt.datetime.strptime(s, fmt).time()
            return (t.hour * 3600 + t.minute * 60 + t.second) / 86400.0
        except ValueError:
            continue
    return ExcelError.VALUE


def YEAR(serial: float) -> int:
    """=YEAR(DATE(2026,5,5)) -> 2026"""
    return _from_serial(float(serial)).year


def MONTH(serial: float) -> int:
    return _from_serial(float(serial)).month


def DAY(serial: float) -> int:
    return _from_serial(float(serial)).day


def HOUR(serial: float) -> int:
    return _from_serial(float(serial)).hour


def MINUTE(serial: float) -> int:
    return _from_serial(float(serial)).minute


def SECOND(serial: float) -> int:
    return _from_serial(float(serial)).second


def WEEKDAY(serial: float, return_type: int = 1) -> int:
    """=WEEKDAY(serial[, type]). Default: Sun=1..Sat=7."""
    py_dow = _from_serial(float(serial)).weekday()  # Mon=0..Sun=6
    rt = int(return_type)
    if rt == 1:
        return ((py_dow + 1) % 7) + 1  # Sun=1..Sat=7
    if rt == 2:
        return py_dow + 1  # Mon=1..Sun=7
    if rt == 3:
        return py_dow  # Mon=0..Sun=6
    return ((py_dow + 1) % 7) + 1


def EDATE(serial: float, months: int) -> float:
    """=EDATE(serial, n) -> serial of date n months later."""
    d = _from_serial(float(serial)).date()
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    last = _last_day(y, m)
    return _to_serial(_dt.date(y, m, min(d.day, last)))


def EOMONTH(serial: float, months: int) -> float:
    """=EOMONTH(serial, n) -> last day of month n months from serial."""
    d = _from_serial(float(serial)).date()
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    return _to_serial(_dt.date(y, m, _last_day(y, m)))


def _last_day(y: int, m: int) -> int:
    nxt = _dt.date(y + 1, 1, 1) if m == 12 else _dt.date(y, m + 1, 1)
    return (nxt - _dt.timedelta(days=1)).day


def DATEDIF(start: float, end: float, unit: str) -> int | ExcelError:
    """=DATEDIF(start, end, "Y"|"M"|"D"). Returns whole units."""
    s = _from_serial(float(start)).date()
    e = _from_serial(float(end)).date()
    if e < s:
        return ExcelError.NUM
    u = str(unit).upper()
    if u == "D":
        return (e - s).days
    if u == "M":
        months = (e.year - s.year) * 12 + (e.month - s.month)
        if e.day < s.day:
            months -= 1
        return months
    if u == "Y":
        years = e.year - s.year
        if (e.month, e.day) < (s.month, s.day):
            years -= 1
        return years
    return ExcelError.VALUE


def NETWORKDAYS(start: float, end: float) -> int:
    """=NETWORKDAYS(start, end) -> weekdays between, inclusive."""
    s = _from_serial(float(start)).date()
    e = _from_serial(float(end)).date()
    if e < s:
        s, e = e, s
    n = 0
    cur = s
    while cur <= e:
        if cur.weekday() < 5:
            n += 1
        cur += _dt.timedelta(days=1)
    return n


def WORKDAY(start: float, days: int) -> float:
    """=WORKDAY(start, n) -> serial n weekdays after start."""
    cur = _from_serial(float(start)).date()
    remaining = int(days)
    step = 1 if remaining >= 0 else -1
    while remaining != 0:
        cur += _dt.timedelta(days=step)
        if cur.weekday() < 5:
            remaining -= step
    return _to_serial(cur)


# -- Information --


def ISNUMBER(x: Any) -> bool:
    """Excel's ISNUMBER: True for int/float, False for bool, strings, etc."""
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and not (isinstance(x, float) and math.isnan(x))
    )


def ISTEXT(x: Any) -> bool:
    return isinstance(x, str)


def ISBLANK(x: Any) -> bool:
    return x is None or x == ""


def ISERROR(x: Any) -> bool:
    if isinstance(x, ExcelError):
        return True
    return isinstance(x, float) and math.isnan(x)


def ISNA(x: Any) -> bool:
    return x is ExcelError.NA


def ISERR(x: Any) -> bool:
    return ISERROR(x) and not ISNA(x)


def ISLOGICAL(x: Any) -> bool:
    return isinstance(x, bool)


def ISEVEN(x: float) -> bool:
    return int(x) % 2 == 0


def ISODD(x: float) -> bool:
    return int(x) % 2 != 0


def NA() -> ExcelError:
    return ExcelError.NA


def N(x: Any) -> float:
    """=N(value) -> numeric coercion; non-numerics return 0."""
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    return 0.0


# -- Multi-criteria aggregates --


def _multi_criteria(
    sum_rng: Vec | None,
    count_only: bool,
    args: tuple[Any, ...],
) -> tuple[list[float], int]:
    """Shared driver for SUMIFS/COUNTIFS/AVERAGEIFS/MAXIFS/MINIFS.

    Returns (matched_values, match_count). For COUNTIFS the values list
    is just 1.0 per match.
    """
    if len(args) % 2 != 0:
        raise ValueError("criteria args must come in (range, criteria) pairs")
    pairs: list[tuple[Vec, Any]] = [
        (args[i], _parse_criteria(str(args[i + 1]))) for i in range(0, len(args), 2)
    ]
    ranges = [p[0].data for p in pairs]
    if count_only:
        n = min(len(r) for r in ranges)
        matched = [
            1.0 for i in range(n) if all(p[1](r[i]) for p, r in zip(pairs, ranges, strict=False))
        ]
        return matched, len(matched)
    if sum_rng is None:
        return [], 0
    target = sum_rng.data
    n = min(len(target), *[len(r) for r in ranges])
    matched = [
        target[i] for i in range(n) if all(p[1](r[i]) for p, r in zip(pairs, ranges, strict=False))
    ]
    return matched, len(matched)


def SUMIFS(sum_rng: Vec, *args: Any) -> float:
    """=SUMIFS(sum_rng, crit_rng1, crit1, [crit_rng2, crit2, ...])"""
    matched, _ = _multi_criteria(sum_rng, False, args)
    return sum(matched)


def COUNTIFS(*args: Any) -> int:
    """=COUNTIFS(crit_rng1, crit1, [crit_rng2, crit2, ...])"""
    _, n = _multi_criteria(None, True, args)
    return n


def AVERAGEIFS(avg_rng: Vec, *args: Any) -> float | ExcelError:
    matched, n = _multi_criteria(avg_rng, False, args)
    if n == 0:
        return ExcelError.DIV0
    return sum(matched) / n


def MAXIFS(max_rng: Vec, *args: Any) -> float:
    matched, _ = _multi_criteria(max_rng, False, args)
    return max(matched) if matched else 0.0


def MINIFS(min_rng: Vec, *args: Any) -> float:
    matched, _ = _multi_criteria(min_rng, False, args)
    return min(matched) if matched else 0.0


# -- Statistical --


def _vec_data(x: Vec | float) -> list[float]:
    if isinstance(x, Vec):
        return list(x.data)
    return [float(x)]


def STDEV(x: Vec | float) -> float | ExcelError:
    """Sample stdev (n-1 divisor)."""
    data = _vec_data(x)
    if len(data) < 2:
        return ExcelError.DIV0
    return statistics.stdev(data)


def STDEVP(x: Vec | float) -> float | ExcelError:
    """Population stdev (n divisor)."""
    data = _vec_data(x)
    if not data:
        return ExcelError.DIV0
    return statistics.pstdev(data)


def VAR(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    if len(data) < 2:
        return ExcelError.DIV0
    return statistics.variance(data)


def VARP(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    if not data:
        return ExcelError.DIV0
    return statistics.pvariance(data)


def CORREL(x: Vec, y: Vec) -> float | ExcelError:
    a = list(x.data)
    b = list(y.data)
    n = min(len(a), len(b))
    if n < 2:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    var_a = sum((a[i] - ma) ** 2 for i in range(n))
    var_b = sum((b[i] - mb) ** 2 for i in range(n))
    if var_a == 0 or var_b == 0:
        return ExcelError.DIV0
    return cov / math.sqrt(var_a * var_b)


def COVAR(x: Vec, y: Vec) -> float | ExcelError:
    """Population covariance."""
    a = list(x.data)
    b = list(y.data)
    n = min(len(a), len(b))
    if n == 0:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n


def RANK(value: float, rng: Vec, order: int = 0) -> int:
    """=RANK(v, rng[, order]). order=0 (default) descending; non-zero ascending."""
    data = list(rng.data)
    sorted_data = sorted(data, reverse=int(order) == 0)
    return sorted_data.index(float(value)) + 1


def PERCENTILE(rng: Vec, p: float) -> float | ExcelError:
    """Linear-interpolation percentile (Excel PERCENTILE / PERCENTILE.INC)."""
    data = sorted(rng.data)
    if not data or not 0 <= float(p) <= 1:
        return ExcelError.NUM
    if len(data) == 1:
        return data[0]
    pos = float(p) * (len(data) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(data):
        return data[lo]
    return data[lo] + frac * (data[lo + 1] - data[lo])


def QUARTILE(rng: Vec, q: int) -> float | ExcelError:
    return PERCENTILE(rng, int(q) / 4)


def MODE(x: Vec | float) -> float | ExcelError:
    """Most frequent value. Returns #N/A if no value repeats."""
    data = _vec_data(x)
    counts: dict[float, int] = {}
    for v in data:
        counts[v] = counts.get(v, 0) + 1
    if not counts or max(counts.values()) == 1:
        return ExcelError.NA
    return max(counts, key=lambda k: (counts[k], -data.index(k)))


def GEOMEAN(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    if not data or any(v <= 0 for v in data):
        return ExcelError.NUM
    return math.exp(sum(math.log(v) for v in data) / len(data))


def HARMEAN(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    if not data or any(v <= 0 for v in data):
        return ExcelError.NUM
    return len(data) / sum(1 / v for v in data)


# -- Financial --


def PV(rate: float, nper: int, pmt: float, fv: float = 0.0, when: int = 0) -> float:
    """Present value. when=0 (end of period, default), 1 (beginning)."""
    r = float(rate)
    n = int(nper)
    if r == 0:
        return -(float(pmt) * n + float(fv))
    factor = (1 + r) ** n
    pmt_factor = 1 + r * (1 if when else 0)
    return -(float(fv) + float(pmt) * pmt_factor * (factor - 1) / r) / factor


def FV(rate: float, nper: int, pmt: float, pv: float = 0.0, when: int = 0) -> float:
    r = float(rate)
    n = int(nper)
    if r == 0:
        return -(float(pv) + float(pmt) * n)
    factor = (1 + r) ** n
    pmt_factor = 1 + r * (1 if when else 0)
    return -(float(pv) * factor + float(pmt) * pmt_factor * (factor - 1) / r)


def PMT(rate: float, nper: int, pv: float, fv: float = 0.0, when: int = 0) -> float:
    r = float(rate)
    n = int(nper)
    if r == 0:
        return -(float(pv) + float(fv)) / n
    factor = (1 + r) ** n
    pmt_factor = 1 + r * (1 if when else 0)
    return -(float(pv) * factor + float(fv)) * r / (pmt_factor * (factor - 1))


def NPER(rate: float, pmt: float, pv: float, fv: float = 0.0, when: int = 0) -> float | ExcelError:
    r = float(rate)
    if r == 0:
        if float(pmt) == 0:
            return ExcelError.NUM
        return -(float(pv) + float(fv)) / float(pmt)
    pmt_factor = float(pmt) * (1 + r * (1 if when else 0))
    try:
        num = pmt_factor - float(fv) * r
        den = float(pv) * r + pmt_factor
        if num / den <= 0:
            return ExcelError.NUM
        return math.log(num / den) / math.log(1 + r)
    except (ValueError, ZeroDivisionError):
        return ExcelError.NUM


def RATE(
    nper: int, pmt: float, pv: float, fv: float = 0.0, when: int = 0, guess: float = 0.1
) -> float | ExcelError:
    """Newton's method on the periodic-cashflow equation."""
    n = int(nper)
    r = float(guess)
    for _ in range(100):
        if r <= -1:
            return ExcelError.NUM
        factor = (1 + r) ** n
        pmt_factor = 1 + r * (1 if when else 0)
        r_safe = r if r else 1e-12
        f = float(pv) * factor + float(pmt) * pmt_factor * (factor - 1) / r_safe + float(fv)
        # Numerical derivative.
        dr = max(abs(r) * 1e-6, 1e-9)
        factor2 = (1 + r + dr) ** n
        pmt_factor2 = 1 + (r + dr) * (1 if when else 0)
        r2_safe = (r + dr) if (r + dr) else 1e-12
        f2 = float(pv) * factor2 + float(pmt) * pmt_factor2 * (factor2 - 1) / r2_safe + float(fv)
        deriv = (f2 - f) / dr
        if deriv == 0:
            return ExcelError.NUM
        new_r = r - f / deriv
        if abs(new_r - r) < 1e-10:
            return new_r
        r = new_r
    return ExcelError.NUM


def NPV(rate: float, *cashflows: Any) -> float:
    flows: list[float] = []
    for c in cashflows:
        if isinstance(c, Vec):
            flows.extend(c.data)
        else:
            flows.append(float(c))
    r = float(rate)
    return sum(cf / (1 + r) ** (i + 1) for i, cf in enumerate(flows))


def IRR(values: Vec, guess: float = 0.1) -> float | ExcelError:
    """Newton's method on NPV-equation. Cashflows include time 0."""
    flows = list(values.data)
    if not flows:
        return ExcelError.NUM
    r = float(guess)
    for _ in range(100):
        if r <= -1:
            return ExcelError.NUM
        npv = sum(cf / (1 + r) ** i for i, cf in enumerate(flows))
        deriv = sum(-i * cf / (1 + r) ** (i + 1) for i, cf in enumerate(flows))
        if deriv == 0:
            return ExcelError.NUM
        new_r = r - npv / deriv
        if abs(new_r - r) < 1e-10:
            return new_r
        r = new_r
    return ExcelError.NUM


def IPMT(rate: float, period: int, nper: int, pv: float, fv: float = 0.0, when: int = 0) -> float:
    """Interest portion of period n's payment."""
    p = PMT(rate, nper, pv, fv, when)
    # Remaining balance at start of `period`.
    fv_at = FV(rate, int(period) - 1, p, pv, when)
    if when == 1 and int(period) == 1:
        return 0.0
    interest = -fv_at * float(rate)
    return interest


def PPMT(rate: float, period: int, nper: int, pv: float, fv: float = 0.0, when: int = 0) -> float:
    """Principal portion of period n's payment."""
    return PMT(rate, nper, pv, fv, when) - IPMT(rate, period, nper, pv, fv, when)


# -- Math (Tier 2) --


def CEILING(x: float, significance: float = 1.0) -> float:
    sig = float(significance)
    if sig == 0:
        return 0.0
    return math.ceil(float(x) / sig) * sig


def FLOOR(x: float, significance: float = 1.0) -> float:
    sig = float(significance)
    if sig == 0:
        return 0.0
    return math.floor(float(x) / sig) * sig


def MROUND(x: float, multiple: float) -> float:
    m = float(multiple)
    if m == 0:
        return 0.0
    return round(float(x) / m) * m


def ODD(x: float) -> int:
    """Round away from zero to nearest odd integer."""
    n = int(math.ceil(abs(float(x))))
    if n % 2 == 0:
        n += 1
    return n if x >= 0 else -n


def EVEN(x: float) -> int:
    """Round away from zero to nearest even integer."""
    n = int(math.ceil(abs(float(x))))
    if n % 2 != 0:
        n += 1
    return n if x >= 0 else -n


def FACT(n: int) -> int | ExcelError:
    n = int(n)
    if n < 0:
        return ExcelError.NUM
    return math.factorial(n)


def GCD(*args: Any) -> int:
    nums: list[int] = []
    for a in args:
        if isinstance(a, Vec):
            nums.extend(int(v) for v in a.data)
        else:
            nums.append(int(a))
    return math.gcd(*nums) if nums else 0


def LCM(*args: Any) -> int:
    nums: list[int] = []
    for a in args:
        if isinstance(a, Vec):
            nums.extend(int(v) for v in a.data)
        else:
            nums.append(int(a))
    return math.lcm(*nums) if nums else 0


def TRUNC(x: float, n: int = 0) -> float:
    """Truncate toward zero to n decimal places."""
    factor: float = float(10 ** int(n))
    return math.trunc(float(x) * factor) / factor


# -- Logical (Tier 2) --


def IFS(*args: Any) -> Any:
    """=IFS(cond1, val1, cond2, val2, ...). Returns first matching value."""
    if len(args) % 2 != 0:
        return ExcelError.NA
    for i in range(0, len(args), 2):
        if args[i]:
            return args[i + 1]
    return ExcelError.NA


def SWITCH(value: Any, *args: Any) -> Any:
    """=SWITCH(value, match1, result1, ..., [default])."""
    pairs = len(args) // 2
    for i in range(pairs):
        if value == args[2 * i]:
            return args[2 * i + 1]
    if len(args) % 2 == 1:
        return args[-1]
    return ExcelError.NA


def IFNA(value: Any, fallback: Any) -> Any:
    if value is ExcelError.NA:
        return fallback
    return value


def XOR(*args: Any) -> bool:
    """Logical XOR: True iff an odd number of inputs are truthy."""
    truthy = 0
    for a in args:
        if isinstance(a, Vec):
            truthy += sum(1 for v in a.data if v)
        elif a:
            truthy += 1
    return truthy % 2 == 1


# -- Reference (Tier 2 subset) --


def CHOOSE(index: int, *args: Any) -> Any:
    """=CHOOSE(2, "a", "b", "c") -> "b". 1-indexed."""
    i = int(index) - 1
    if 0 <= i < len(args):
        return args[i]
    return ExcelError.VALUE


# Raw-args functions: receive Env + raw AST nodes from the evaluator.
# Names must be listed in `formula.evaluator.RAW_ARG_FUNCS`.


def ROW(env: Any, *args: Any) -> int | ExcelError:
    """=ROW() -> current cell's 1-based row.
    =ROW(A5) -> 5. =ROW(B2:B7) -> 2 (top row of range)."""
    from ..formula.ast_nodes import CellRef as _CellRef
    from ..formula.ast_nodes import RangeRef as _RangeRef

    if not args:
        if env.current_cell is None:
            return ExcelError.VALUE
        return int(env.current_cell[1]) + 1
    a = args[0]
    if isinstance(a, _CellRef):
        return a.row + 1
    if isinstance(a, _RangeRef):
        return min(a.start.row, a.end.row) + 1
    return ExcelError.VALUE


def COLUMN(env: Any, *args: Any) -> int | ExcelError:
    """=COLUMN() -> current cell's 1-based column.
    =COLUMN(A5) -> 1. =COLUMN(B2:D7) -> 2 (leftmost col of range)."""
    from ..formula.ast_nodes import CellRef as _CellRef
    from ..formula.ast_nodes import RangeRef as _RangeRef

    if not args:
        if env.current_cell is None:
            return ExcelError.VALUE
        return int(env.current_cell[0]) + 1
    a = args[0]
    if isinstance(a, _CellRef):
        return a.col + 1
    if isinstance(a, _RangeRef):
        return min(a.start.col, a.end.col) + 1
    return ExcelError.VALUE


def ROWS(env: Any, *args: Any) -> int | ExcelError:
    """=ROWS(A1:B10) -> 10. =ROWS(A1) -> 1."""
    from ..formula.ast_nodes import CellRef as _CellRef
    from ..formula.ast_nodes import RangeRef as _RangeRef

    if len(args) != 1:
        return ExcelError.VALUE
    a = args[0]
    if isinstance(a, _CellRef):
        return 1
    if isinstance(a, _RangeRef):
        return abs(a.end.row - a.start.row) + 1
    return ExcelError.VALUE


def COLUMNS(env: Any, *args: Any) -> int | ExcelError:
    """=COLUMNS(A1:C10) -> 3. =COLUMNS(A1) -> 1."""
    from ..formula.ast_nodes import CellRef as _CellRef
    from ..formula.ast_nodes import RangeRef as _RangeRef

    if len(args) != 1:
        return ExcelError.VALUE
    a = args[0]
    if isinstance(a, _CellRef):
        return 1
    if isinstance(a, _RangeRef):
        return abs(a.end.col - a.start.col) + 1
    return ExcelError.VALUE


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
    "FIND": FIND,
    "SEARCH": SEARCH,
    "REPLACE": REPLACE,
    "TEXTJOIN": TEXTJOIN,
    "CHAR": CHAR,
    "CODE": CODE,
    "VALUE": VALUE,
    "TEXT": TEXT,
    # Date and time
    "NOW": NOW,
    "TODAY": TODAY,
    "DATE": DATE,
    "TIME": TIME,
    "DATEVALUE": DATEVALUE,
    "TIMEVALUE": TIMEVALUE,
    "YEAR": YEAR,
    "MONTH": MONTH,
    "DAY": DAY,
    "HOUR": HOUR,
    "MINUTE": MINUTE,
    "SECOND": SECOND,
    "WEEKDAY": WEEKDAY,
    "EDATE": EDATE,
    "EOMONTH": EOMONTH,
    "DATEDIF": DATEDIF,
    "NETWORKDAYS": NETWORKDAYS,
    "WORKDAY": WORKDAY,
    # Information
    "ISNUMBER": ISNUMBER,
    "ISTEXT": ISTEXT,
    "ISBLANK": ISBLANK,
    "ISERROR": ISERROR,
    "ISNA": ISNA,
    "ISERR": ISERR,
    "ISLOGICAL": ISLOGICAL,
    "ISEVEN": ISEVEN,
    "ISODD": ISODD,
    "NA": NA,
    "N": N,
    # Multi-criteria aggregates
    "SUMIFS": SUMIFS,
    "COUNTIFS": COUNTIFS,
    "AVERAGEIFS": AVERAGEIFS,
    "MAXIFS": MAXIFS,
    "MINIFS": MINIFS,
    # Statistical
    "STDEV": STDEV,
    "STDEVP": STDEVP,
    "VAR": VAR,
    "VARP": VARP,
    "CORREL": CORREL,
    "COVAR": COVAR,
    "RANK": RANK,
    "PERCENTILE": PERCENTILE,
    "QUARTILE": QUARTILE,
    "MODE": MODE,
    "GEOMEAN": GEOMEAN,
    "HARMEAN": HARMEAN,
    # Financial
    "PV": PV,
    "FV": FV,
    "PMT": PMT,
    "NPER": NPER,
    "RATE": RATE,
    "NPV": NPV,
    "IRR": IRR,
    "IPMT": IPMT,
    "PPMT": PPMT,
    # Math (Tier 2)
    "CEILING": CEILING,
    "FLOOR": FLOOR,
    "MROUND": MROUND,
    "ODD": ODD,
    "EVEN": EVEN,
    "FACT": FACT,
    "GCD": GCD,
    "LCM": LCM,
    "TRUNC": TRUNC,
    # Logical (Tier 2)
    "IFS": IFS,
    "SWITCH": SWITCH,
    "IFNA": IFNA,
    "XOR": XOR,
    # Reference (Tier 2 subset)
    "CHOOSE": CHOOSE,
    # Raw-args (receive AST nodes via evaluator's RAW_ARG_FUNCS path)
    "ROW": ROW,
    "COLUMN": COLUMN,
    "ROWS": ROWS,
    "COLUMNS": COLUMNS,
}
