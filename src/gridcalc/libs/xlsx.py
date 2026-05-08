"""xlsx mode -- Excel-compatible function names for formula evaluation.

Provides IF, AND, OR, VLOOKUP, SUMIF, AVERAGE, text functions, etc.
All functions accept the same argument patterns as their Excel counterparts.
"""

from __future__ import annotations

import datetime as _dt
import math
import operator
import random as _random
import re
import statistics
from collections.abc import Callable
from typing import Any

from ..engine import Vec
from ..formula.errors import ExcelError

# -- Criteria parsing --


def _wildcard_regex(pattern: str) -> re.Pattern[str]:
    """Compile an Excel wildcard pattern. ``*`` -> ``.*``, ``?`` -> ``.``,
    ``~*`` / ``~?`` / ``~~`` escape the next char literally."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile(f"^{''.join(out)}$", re.IGNORECASE | re.DOTALL)


def _parse_criteria(criteria: Any) -> Any:
    """Parse an Excel-style criterion into a predicate.

    Accepts numeric, bool, and string criteria. For strings: ``">5"``,
    ``">=10"``, ``"<3"``, ``"<=0"``, ``"<>0"``, ``"=5"``, ``"5"`` (equals),
    plus wildcard text patterns with ``*``, ``?``, and ``~`` escapes.
    Empty-string criteria matches blanks (None / "").
    """
    # Non-string criteria: direct equality.
    if isinstance(criteria, bool):
        cb = criteria
        return lambda x, v=cb: isinstance(x, bool) and x == v
    if isinstance(criteria, (int, float)):
        cn = float(criteria)
        return lambda x, v=cn: _crit_eq_number(x, v)

    s = str(criteria).strip()
    if s == "":
        return lambda x: x is None or x == ""

    ops: list[tuple[str, Any]] = [
        (">=", operator.ge),
        ("<=", operator.le),
        ("<>", operator.ne),
        (">", operator.gt),
        ("<", operator.lt),
        ("=", operator.eq),
    ]

    for prefix, op in ops:
        if s.startswith(prefix):
            raw = s[len(prefix) :]
            cmp_val: float | str
            try:
                cmp_val = float(raw)
                is_numeric = True
            except ValueError:
                cmp_val = raw
                is_numeric = False
            if op is operator.eq and not is_numeric:
                regex = _wildcard_regex(raw)
                return lambda x, r=regex: bool(r.match(str(x))) if x is not None else False
            if op is operator.ne and not is_numeric:
                regex = _wildcard_regex(raw)
                return lambda x, r=regex: not bool(r.match(str(x))) if x is not None else True
            return lambda x, o=op, v=cmp_val, num=is_numeric: _crit_compare(o, x, v, num)

    # No operator prefix -- equality with wildcards if non-numeric.
    try:
        val = float(s)
        return lambda x, v=val: _crit_eq_number(x, v)
    except ValueError:
        regex = _wildcard_regex(s)
        return lambda x, r=regex: bool(r.match(str(x))) if x is not None else False


def _crit_eq_number(x: Any, v: float) -> bool:
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return float(x) == v
    return False


def _crit_compare(op: Any, x: Any, v: Any, numeric: bool) -> bool:
    """Apply numeric or string comparison, skipping mismatched types like Excel."""
    if numeric:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return False
        try:
            return bool(op(float(x), float(v)))
        except (TypeError, ValueError):
            return False
    if not isinstance(x, str):
        return False
    try:
        return bool(op(x.lower(), str(v).lower()))
    except TypeError:
        return False


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
    nums = _vec_data(x)
    return sum(nums) / len(nums) if nums else 0.0


def MEDIAN(x: Vec | float) -> float:
    """=MEDIAN(A1:A10)"""
    s = sorted(_vec_data(x))
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def SUMPRODUCT(a: Vec, b: Vec) -> float:
    """=SUMPRODUCT(A1:A10, B1:B10). Non-numeric pairs contribute 0 (Excel rule)."""
    total = 0.0
    for x, y in zip(a.data, b.data, strict=False):
        if (
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and isinstance(y, (int, float))
            and not isinstance(y, bool)
        ):
            total += float(x) * float(y)
    return total


def LARGE(x: Vec, k: int) -> float:
    """=LARGE(A1:A10, 2) -- kth largest value."""
    s = sorted(_vec_data(x), reverse=True)
    return s[int(k) - 1]


def SMALL(x: Vec, k: int) -> float:
    """=SMALL(A1:A10, 2) -- kth smallest value."""
    s = sorted(_vec_data(x))
    return s[int(k) - 1]


# -- Conditional aggregates --


def SUMIF(rng: Vec, criteria: str, sum_rng: Vec | None = None) -> float:
    """=SUMIF(A1:A10, ">5") or =SUMIF(A1:A10, ">5", B1:B10)"""
    pred = _parse_criteria(criteria)
    values = sum_rng.data if sum_rng is not None else rng.data
    total = 0.0
    for c, v in zip(rng.data, values, strict=False):
        if pred(c) and isinstance(v, (int, float)) and not isinstance(v, bool):
            total += float(v)
    return total


def COUNTIF(rng: Vec, criteria: str) -> int:
    """=COUNTIF(A1:A10, ">5")"""
    pred = _parse_criteria(criteria)
    return sum(1 for x in rng.data if pred(x))


def AVERAGEIF(rng: Vec, criteria: str, avg_rng: Vec | None = None) -> float:
    """=AVERAGEIF(A1:A10, ">5") or =AVERAGEIF(A1:A10, ">5", B1:B10)"""
    pred = _parse_criteria(criteria)
    values = avg_rng.data if avg_rng is not None else rng.data
    matches = [
        float(v)
        for c, v in zip(rng.data, values, strict=False)
        if pred(c) and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    return sum(matches) / len(matches) if matches else 0.0


# -- Lookup functions --


def _safe_le(a: Any, b: Any) -> bool:
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    try:
        return bool(a <= b)
    except TypeError:
        return False


def _safe_ge(a: Any, b: Any) -> bool:
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    try:
        return bool(a >= b)
    except TypeError:
        return False


def _exact_match(target: Any, candidate: Any) -> bool:
    """Exact match with Excel wildcard support when target is a string."""
    if isinstance(target, str) and any(c in target for c in "*?~"):
        return bool(_wildcard_regex(target).match(str(candidate)))
    if isinstance(target, str) and isinstance(candidate, str):
        return target.lower() == candidate.lower()
    return bool(target == candidate)


def VLOOKUP(lookup: Any, table: Vec, col_idx: int, approx: Any = True) -> Any:
    """=VLOOKUP(value, A1:C10, 3, 0)

    Searches the first column of `table` for `lookup`. col_idx is 1-based
    into the row. ``approx=TRUE`` (default) does nearest-not-exceeding match
    on a sorted first column; ``approx=FALSE`` does exact match (with Excel
    wildcards when lookup is a string).
    """
    ci = int(col_idx)
    data = table.data
    n = len(data)
    if n == 0 or ci <= 0:
        return ExcelError.VALUE
    cols = table.cols if table.cols else ci
    if cols <= 0 or ci > cols:
        return ExcelError.REF
    n_rows = n // cols
    if n_rows == 0:
        return ExcelError.NA

    use_approx = bool(approx) if not isinstance(approx, str) else approx != "0"
    best = -1
    if use_approx:
        for i in range(n_rows):
            v = data[i * cols]
            if _safe_le(v, lookup):
                best = i
            else:
                break
    else:
        for i in range(n_rows):
            if _exact_match(lookup, data[i * cols]):
                best = i
                break

    if best < 0:
        return ExcelError.NA
    return data[best * cols + (ci - 1)]


def HLOOKUP(lookup: Any, table: Vec, row_idx: int, approx: Any = True) -> Any:
    """=HLOOKUP(value, A1:J3, 3, 0). Like VLOOKUP but searches the first row."""
    ri = int(row_idx)
    data = table.data
    n = len(data)
    if n == 0 or ri <= 0:
        return ExcelError.VALUE
    # Use shape if available; otherwise fall back to assuming row_idx rows.
    n_cols = table.cols if (table.cols and table.cols > 0) else (n // ri)
    if n_cols == 0:
        return ExcelError.NA
    n_rows = n // n_cols
    if ri > n_rows:
        return ExcelError.REF

    use_approx = bool(approx) if not isinstance(approx, str) else approx != "0"
    best = -1
    if use_approx:
        for j in range(n_cols):
            if _safe_le(data[j], lookup):
                best = j
            else:
                break
    else:
        for j in range(n_cols):
            if _exact_match(lookup, data[j]):
                best = j
                break

    if best < 0:
        return ExcelError.NA
    return data[(ri - 1) * n_cols + best]


def INDEX(rng: Vec, row: int, col: int = 0) -> Any:
    """=INDEX(rng, row, [col]). 1-based row/col into a range.

    Uses ``rng.cols`` (set by the evaluator on RangeRef materialization)
    to interpret 2D shape. With cols set, ``row=0`` means whole column,
    ``col=0`` means whole row.
    """
    r = int(row)
    c = int(col)
    data = rng.data
    n = len(data)
    cols = rng.cols
    if cols is None or cols <= 0:
        # Treat as 1D: single positional index.
        idx = r if r > 0 else c
        if idx <= 0 or idx > n:
            return ExcelError.REF
        return data[idx - 1]
    n_rows = n // cols if cols else 0
    if r < 0 or r > n_rows or c < 0 or c > cols:
        return ExcelError.REF
    if r == 0 and c == 0:
        return ExcelError.VALUE
    if r == 0:
        # Return entire column c as a 1D Vec.
        return Vec([data[i * cols + (c - 1)] for i in range(n_rows)])
    if c == 0:
        # Return entire row r as a 1D Vec.
        if cols == 1:
            return data[r - 1]
        return Vec(data[(r - 1) * cols : (r - 1) * cols + cols])
    return data[(r - 1) * cols + (c - 1)]


def MATCH(lookup: Any, rng: Vec, match_type: int = 1) -> int | ExcelError:
    """=MATCH(value, rng, [match_type]). Returns 1-based position, or #N/A.

    match_type: 0 = exact (with wildcards if lookup is text);
    1 = largest <= lookup (range sorted ascending);
    -1 = smallest >= lookup (range sorted descending).
    """
    mt = int(match_type)
    data = rng.data
    if mt == 0:
        for i, v in enumerate(data):
            if _exact_match(lookup, v):
                return i + 1
        return ExcelError.NA
    if mt == 1:
        best = -1
        for i, v in enumerate(data):
            if _safe_le(v, lookup):
                best = i
            else:
                break
        return best + 1 if best >= 0 else ExcelError.NA
    if mt == -1:
        best = -1
        for i, v in enumerate(data):
            if _safe_ge(v, lookup):
                best = i
            else:
                break
        return best + 1 if best >= 0 else ExcelError.NA
    return ExcelError.VALUE


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
        float(target[i])
        for i in range(n)
        if all(p[1](r[i]) for p, r in zip(pairs, ranges, strict=False))
        and isinstance(target[i], (int, float))
        and not isinstance(target[i], bool)
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
    """Numeric-only view of a Vec or scalar. Skips text and bools (Excel rule)."""
    if isinstance(x, Vec):
        return [float(v) for v in x.data if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return []
    return [float(x)]


def _pair_numeric(x: Vec, y: Vec) -> tuple[list[float], list[float]]:
    """Index-aligned numeric-only pairs from two Vecs. Skips a pair if
    either side is non-numeric (Excel rule for paired stats)."""
    a = list(x.data)
    b = list(y.data)
    n = min(len(a), len(b))
    out_a: list[float] = []
    out_b: list[float] = []
    for i in range(n):
        av, bv = a[i], b[i]
        if (
            isinstance(av, (int, float))
            and not isinstance(av, bool)
            and isinstance(bv, (int, float))
            and not isinstance(bv, bool)
        ):
            out_a.append(float(av))
            out_b.append(float(bv))
    return out_a, out_b


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
    a, b = _pair_numeric(x, y)
    n = len(a)
    if n < 2:
        return ExcelError.DIV0
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    var_a = sum((a[i] - ma) ** 2 for i in range(n))
    var_b = sum((b[i] - mb) ** 2 for i in range(n))
    if var_a == 0 or var_b == 0:
        return ExcelError.DIV0
    return cov / math.sqrt(var_a * var_b)


def COVAR(x: Vec, y: Vec) -> float | ExcelError:
    """Population covariance."""
    a, b = _pair_numeric(x, y)
    n = len(a)
    if n == 0:
        return ExcelError.DIV0
    ma, mb = sum(a) / n, sum(b) / n
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n


def RANK(value: float, rng: Vec, order: int = 0) -> int:
    """=RANK(v, rng[, order]). order=0 (default) descending; non-zero ascending."""
    data = _vec_data(rng)
    sorted_data = sorted(data, reverse=int(order) == 0)
    return sorted_data.index(float(value)) + 1


def PERCENTILE(rng: Vec, p: float) -> float | ExcelError:
    """Linear-interpolation percentile (Excel PERCENTILE / PERCENTILE.INC)."""
    data = sorted(_vec_data(rng))
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
            flows.extend(_vec_data(c))
        elif isinstance(c, (int, float)) and not isinstance(c, bool):
            flows.append(float(c))
    r = float(rate)
    return sum(cf / (1 + r) ** (i + 1) for i, cf in enumerate(flows))


def IRR(values: Vec, guess: float = 0.1) -> float | ExcelError:
    """Newton's method on NPV-equation. Cashflows include time 0."""
    flows = _vec_data(values)
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
    """Interest portion of period n's payment.

    Excel sign convention: the result is negative when paying interest
    on a positive ``pv`` (a loan).
    """
    p = PMT(rate, nper, pv, fv, when)
    # Remaining balance at start of `period` (negative in Excel convention
    # when pv is positive).
    fv_at = FV(rate, int(period) - 1, p, pv, when)
    if when == 1 and int(period) == 1:
        return 0.0
    interest = fv_at * float(rate)
    if when == 1:
        # When payments are at the start, the previous period's interest is
        # paid one period earlier, so discount.
        interest = interest / (1 + float(rate))
    return interest


def PPMT(rate: float, period: int, nper: int, pv: float, fv: float = 0.0, when: int = 0) -> float:
    """Principal portion of period n's payment."""
    return PMT(rate, nper, pv, fv, when) - IPMT(rate, period, nper, pv, fv, when)


# -- Financial (Tier 4) --


def SLN(cost: float, salvage: float, life: float) -> float | ExcelError:
    """=SLN(cost, salvage, life). Straight-line depreciation per period."""
    n = float(life)
    if n == 0:
        return ExcelError.NUM
    return (float(cost) - float(salvage)) / n


def SYD(cost: float, salvage: float, life: float, period: float) -> float | ExcelError:
    """=SYD(cost, salvage, life, period). Sum-of-years-digits for one period."""
    c, s, n, p = float(cost), float(salvage), float(life), float(period)
    if n <= 0 or p <= 0 or p > n:
        return ExcelError.NUM
    return (c - s) * (n - p + 1) * 2 / (n * (n + 1))


def DB(cost: float, salvage: float, life: int, period: int, month: int = 12) -> float | ExcelError:
    """=DB(cost, salvage, life, period, [month]).

    Fixed-declining-balance for a single period. Excel rounds the rate
    to 3 decimals. ``month`` (default 12) prorates the first and final
    partial periods.
    """
    c, s = float(cost), float(salvage)
    n, p, m = int(life), int(period), int(month)
    if c <= 0 or s < 0 or n <= 0 or p <= 0 or p > n + 1 or m < 1 or m > 12:
        return ExcelError.NUM
    rate = 1.0 if s == 0 else round(1 - (s / c) ** (1 / n), 3)
    if p == 1:
        return c * rate * m / 12
    accum = c * rate * m / 12
    for _ in range(2, p):
        accum += (c - accum) * rate
    if p == n + 1:
        return (c - accum) * rate * (12 - m) / 12
    return (c - accum) * rate


def DDB(
    cost: float, salvage: float, life: float, period: float, factor: float = 2.0
) -> float | ExcelError:
    """=DDB(cost, salvage, life, period, [factor]).

    Double-declining-balance for one period. Default factor is 2.
    Never depreciates below salvage.
    """
    c, s, n = float(cost), float(salvage), float(life)
    p, f = int(period), float(factor)
    if c < 0 or s < 0 or n <= 0 or p < 1 or p > n or f <= 0:
        return ExcelError.NUM
    accum = 0.0
    for i in range(1, p + 1):
        book = c - accum
        d = min(book * f / n, max(book - s, 0.0))
        if i == p:
            return d
        accum += d
    return 0.0


def VDB(
    cost: float,
    salvage: float,
    life: float,
    start_period: float,
    end_period: float,
    factor: float = 2.0,
    no_switch: Any = False,
) -> float | ExcelError:
    """=VDB(cost, salvage, life, start, end, [factor], [no_switch]).

    Total depreciation between integer ``start`` and ``end`` periods.
    Switches to straight-line when SL exceeds DDB unless ``no_switch``.
    Fractional start/end periods are not supported (returns #NUM!).
    """
    c, s, n = float(cost), float(salvage), float(life)
    a, b, f = float(start_period), float(end_period), float(factor)
    if c < 0 or s < 0 or n <= 0 or a < 0 or b > n or a > b or f <= 0:
        return ExcelError.NUM
    if a != int(a) or b != int(b):
        return ExcelError.NUM
    ai, bi = int(a), int(b)
    book = c
    total = 0.0
    use_sl = False
    sl_d = 0.0
    for i in range(1, int(math.ceil(n)) + 1):
        if use_sl:
            d = sl_d
        else:
            ddb_d = book * f / n
            remaining = n - i + 1
            sl_d = (book - s) / remaining if remaining > 0 else 0.0
            if not bool(no_switch) and sl_d > ddb_d:
                use_sl = True
                d = sl_d
            else:
                d = min(ddb_d, max(book - s, 0.0))
        if ai < i <= bi:
            total += d
        book -= d
        if book <= s:
            break
    return total


def EFFECT(nominal_rate: float, npery: int) -> float | ExcelError:
    """=EFFECT(nominal_rate, npery). Effective annual rate."""
    n = int(npery)
    nr = float(nominal_rate)
    if n < 1 or nr <= -1:
        return ExcelError.NUM
    return (1 + nr / n) ** n - 1


def NOMINAL(effect_rate: float, npery: int) -> float | ExcelError:
    """=NOMINAL(effect_rate, npery). Nominal annual rate from effective."""
    n = int(npery)
    e = float(effect_rate)
    if n < 1 or e <= -1:
        return ExcelError.NUM
    return float(n * ((1 + e) ** (1 / n) - 1))


def CUMIPMT(
    rate: float, nper: int, pv: float, start_period: int, end_period: int, when: int = 0
) -> float | ExcelError:
    """=CUMIPMT(rate, nper, pv, start, end, type). Sum of IPMT over [start, end]."""
    n = int(nper)
    s, e = int(start_period), int(end_period)
    if float(rate) <= 0 or n <= 0 or float(pv) <= 0 or s < 1 or e < s or e > n:
        return ExcelError.NUM
    return sum(IPMT(rate, p, n, pv, 0.0, when) for p in range(s, e + 1))


def CUMPRINC(
    rate: float, nper: int, pv: float, start_period: int, end_period: int, when: int = 0
) -> float | ExcelError:
    """=CUMPRINC(rate, nper, pv, start, end, type). Sum of PPMT over [start, end]."""
    n = int(nper)
    s, e = int(start_period), int(end_period)
    if float(rate) <= 0 or n <= 0 or float(pv) <= 0 or s < 1 or e < s or e > n:
        return ExcelError.NUM
    return sum(PPMT(rate, p, n, pv, 0.0, when) for p in range(s, e + 1))


def MIRR(values: Vec, finance_rate: float, reinvest_rate: float) -> float | ExcelError:
    """=MIRR(values, finance_rate, reinvest_rate).

    Modified internal rate of return: borrowing cost on negative flows,
    reinvestment rate on positive flows.
    """
    flows = _vec_data(values)
    n = len(flows)
    if n < 2:
        return ExcelError.DIV0
    fr, rr = float(finance_rate), float(reinvest_rate)
    if fr <= -1 or rr <= -1:
        return ExcelError.NUM
    pv_neg = sum(cf / (1 + fr) ** i for i, cf in enumerate(flows) if cf < 0)
    fv_pos = sum(cf * (1 + rr) ** (n - 1 - i) for i, cf in enumerate(flows) if cf > 0)
    if pv_neg == 0 or fv_pos == 0:
        return ExcelError.DIV0
    try:
        return float((-fv_pos / pv_neg) ** (1 / (n - 1)) - 1)
    except (ValueError, ZeroDivisionError):
        return ExcelError.NUM


def XNPV(rate: float, values: Vec, dates: Vec) -> float | ExcelError:
    """=XNPV(rate, values, dates). Net present value with arbitrary dates.

    Dates are Excel date serials. Year fraction uses a 365-day basis.
    """
    cfs = _vec_data(values)
    ds = _vec_data(dates)
    r = float(rate)
    if not cfs or len(cfs) != len(ds) or r <= -1:
        return ExcelError.NUM
    d0 = ds[0]
    return float(sum(cf / (1 + r) ** ((d - d0) / 365.0) for cf, d in zip(cfs, ds, strict=True)))


def XIRR(values: Vec, dates: Vec, guess: float = 0.1) -> float | ExcelError:
    """=XIRR(values, dates, [guess]). IRR for irregularly-spaced cashflows.

    Newton's method on XNPV; date basis matches XNPV (365-day year).
    """
    cfs = _vec_data(values)
    ds = _vec_data(dates)
    if len(cfs) < 2 or len(cfs) != len(ds):
        return ExcelError.NUM
    has_pos = any(cf > 0 for cf in cfs)
    has_neg = any(cf < 0 for cf in cfs)
    if not (has_pos and has_neg):
        return ExcelError.NUM
    d0 = ds[0]
    deltas = [(d - d0) / 365.0 for d in ds]
    r = float(guess)
    for _ in range(100):
        if r <= -1:
            return ExcelError.NUM
        try:
            f = sum(cf / (1 + r) ** t for cf, t in zip(cfs, deltas, strict=True))
            df = sum(-t * cf / (1 + r) ** (t + 1) for cf, t in zip(cfs, deltas, strict=True))
        except (ValueError, OverflowError):
            return ExcelError.NUM
        if df == 0:
            return ExcelError.NUM
        new_r = r - f / df
        if abs(new_r - r) < 1e-10:
            return float(new_r)
        r = new_r
    return ExcelError.NUM


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
            nums.extend(
                int(v) for v in a.data if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            nums.append(int(a))
    return math.gcd(*nums) if nums else 0


def LCM(*args: Any) -> int:
    nums: list[int] = []
    for a in args:
        if isinstance(a, Vec):
            nums.extend(
                int(v) for v in a.data if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
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


# -- Tier 3: aggregates --


def _flatten(args: tuple[Any, ...]) -> list[Any]:
    out: list[Any] = []
    for a in args:
        if isinstance(a, Vec):
            out.extend(a.data)
        else:
            out.append(a)
    return out


def _flatten_numeric(args: tuple[Any, ...]) -> list[float]:
    out: list[float] = []
    for v in _flatten(args):
        if isinstance(v, bool):
            continue  # AVERAGE/SUM ignore bools when given as values
        if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
            out.append(float(v))
    return out


def COUNTA(*args: Any) -> int:
    """Count non-empty values."""
    n = 0
    for v in _flatten(args):
        if v is None:
            continue
        if isinstance(v, str) and v == "":
            continue
        n += 1
    return n


def COUNTBLANK(*args: Any) -> int:
    n = 0
    for v in _flatten(args):
        if v is None or (isinstance(v, str) and v == ""):
            n += 1
    return n


def PRODUCT(*args: Any) -> float:
    nums = _flatten_numeric(args)
    p = 1.0
    for v in nums:
        p *= v
    return p


def _coerce_a(v: Any) -> float:
    """AVERAGEA/MAXA/MINA coercion: text -> 0, bool -> 0/1, num -> num."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return 0.0
    return 0.0  # text counts as 0


def AVERAGEA(*args: Any) -> float | ExcelError:
    vals: list[float] = []
    for v in _flatten(args):
        if v is None:
            continue
        vals.append(_coerce_a(v))
    if not vals:
        return ExcelError.DIV0
    return sum(vals) / len(vals)


def MAXA(*args: Any) -> float:
    vals = [_coerce_a(v) for v in _flatten(args) if v is not None]
    return max(vals) if vals else 0.0


def MINA(*args: Any) -> float:
    vals = [_coerce_a(v) for v in _flatten(args) if v is not None]
    return min(vals) if vals else 0.0


# -- Tier 3: stats (modern aliases for existing impls) --

# STDEV.S = STDEV (sample), STDEV.P = STDEVP (population), VAR.S/VAR.P, etc.
# Aliases registered in BUILTINS below. They reuse the existing functions.


def _covariance(x: Vec, y: Vec, sample: bool) -> float | ExcelError:
    a, b = _pair_numeric(x, y)
    n = len(a)
    divisor = n - 1 if sample else n
    if divisor <= 0:
        return ExcelError.DIV0
    ma, mb = sum(a) / n, sum(b) / n
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / divisor


def COVARIANCE_P(x: Vec, y: Vec) -> float | ExcelError:
    return _covariance(x, y, sample=False)


def COVARIANCE_S(x: Vec, y: Vec) -> float | ExcelError:
    return _covariance(x, y, sample=True)


def MODE_MULT(x: Vec | float) -> Vec | ExcelError:
    """Return all values that share the maximum frequency (>= 2)."""
    data = _vec_data(x)
    counts: dict[float, int] = {}
    for v in data:
        counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ExcelError.NA
    top = max(counts.values())
    if top < 2:
        return ExcelError.NA
    seen: list[float] = []
    for v in data:
        if counts[v] == top and v not in seen:
            seen.append(v)
    return Vec(seen)


def PERCENTILE_EXC(rng: Vec, p: float) -> float | ExcelError:
    """Exclusive percentile: requires 1/(n+1) <= p <= n/(n+1)."""
    data = sorted(_vec_data(rng))
    n = len(data)
    if n == 0:
        return ExcelError.NUM
    pp = float(p)
    if pp < 1 / (n + 1) or pp > n / (n + 1):
        return ExcelError.NUM
    pos = pp * (n + 1) - 1  # 0-based interpolation index
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= n:
        return data[lo]
    return data[lo] + frac * (data[lo + 1] - data[lo])


def QUARTILE_EXC(rng: Vec, q: int) -> float | ExcelError:
    qi = int(q)
    if qi <= 0 or qi >= 4:
        return ExcelError.NUM
    return PERCENTILE_EXC(rng, qi / 4)


def RANK_AVG(value: float, rng: Vec, order: int = 0) -> float | ExcelError:
    data = _vec_data(rng)
    v = float(value)
    if v not in data:
        return ExcelError.NA
    sorted_data = sorted(data, reverse=int(order) == 0)
    # Average of all 1-based positions where value occurs.
    positions = [i + 1 for i, x in enumerate(sorted_data) if x == v]
    return sum(positions) / len(positions)


# -- Tier 3: stats (additional) --


def AVEDEV(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    if not data:
        return ExcelError.NUM
    m = sum(data) / len(data)
    return sum(abs(v - m) for v in data) / len(data)


def DEVSQ(x: Vec | float) -> float:
    data = _vec_data(x)
    if not data:
        return 0.0
    m = sum(data) / len(data)
    return sum((v - m) ** 2 for v in data)


def _linreg(y: Vec, x: Vec) -> tuple[float, float, int, float, float, float] | ExcelError:
    """Return (slope, intercept, n, mx, my, sxx). NB y first matches Excel."""
    a, b = _pair_numeric(y, x)
    n = len(a)
    if n < 2:
        return ExcelError.DIV0
    my = sum(a) / n
    mx = sum(b) / n
    sxx = sum((b[i] - mx) ** 2 for i in range(n))
    if sxx == 0:
        return ExcelError.DIV0
    sxy = sum((b[i] - mx) * (a[i] - my) for i in range(n))
    slope = sxy / sxx
    intercept = my - slope * mx
    return (slope, intercept, n, mx, my, sxx)


def SLOPE(known_y: Vec, known_x: Vec) -> float | ExcelError:
    r = _linreg(known_y, known_x)
    if isinstance(r, ExcelError):
        return r
    return r[0]


def INTERCEPT(known_y: Vec, known_x: Vec) -> float | ExcelError:
    r = _linreg(known_y, known_x)
    if isinstance(r, ExcelError):
        return r
    return r[1]


def RSQ(known_y: Vec, known_x: Vec) -> float | ExcelError:
    a, b = _pair_numeric(known_y, known_x)
    n = len(a)
    if n < 2:
        return ExcelError.DIV0
    my, mx = sum(a) / n, sum(b) / n
    syy = sum((a[i] - my) ** 2 for i in range(n))
    sxx = sum((b[i] - mx) ** 2 for i in range(n))
    sxy = sum((b[i] - mx) * (a[i] - my) for i in range(n))
    if sxx == 0 or syy == 0:
        return ExcelError.DIV0
    return (sxy * sxy) / (sxx * syy)


def STEYX(known_y: Vec, known_x: Vec) -> float | ExcelError:
    """Standard error of predicted y."""
    a, b = _pair_numeric(known_y, known_x)
    n = len(a)
    if n < 3:
        return ExcelError.DIV0
    my, mx = sum(a) / n, sum(b) / n
    sxx = sum((b[i] - mx) ** 2 for i in range(n))
    syy = sum((a[i] - my) ** 2 for i in range(n))
    sxy = sum((b[i] - mx) * (a[i] - my) for i in range(n))
    if sxx == 0:
        return ExcelError.DIV0
    return math.sqrt((syy - (sxy * sxy) / sxx) / (n - 2))


def SKEW(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    n = len(data)
    if n < 3:
        return ExcelError.DIV0
    m = sum(data) / n
    s = statistics.stdev(data)
    if s == 0:
        return ExcelError.DIV0
    factor = n / ((n - 1) * (n - 2))
    return factor * sum(((v - m) / s) ** 3 for v in data)


def KURT(x: Vec | float) -> float | ExcelError:
    data = _vec_data(x)
    n = len(data)
    if n < 4:
        return ExcelError.DIV0
    m = sum(data) / n
    s = statistics.stdev(data)
    if s == 0:
        return ExcelError.DIV0
    factor = (n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))
    correction = (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))
    return factor * sum(((v - m) / s) ** 4 for v in data) - correction


def PERCENTRANK(rng: Vec, x: float, significance: int = 3) -> float | ExcelError:
    data = sorted(_vec_data(rng))
    n = len(data)
    if n == 0:
        return ExcelError.NA
    xv = float(x)
    if xv < data[0] or xv > data[-1]:
        return ExcelError.NA
    # Find lo index where data[lo] <= xv
    lo = 0
    for i, v in enumerate(data):
        if v <= xv:
            lo = i
        else:
            break
    if data[lo] == xv:
        rank = lo / (n - 1) if n > 1 else 1.0
    else:
        # Linear interpolation between lo and lo+1
        a, b = data[lo], data[lo + 1]
        frac = (xv - a) / (b - a) if b != a else 0.0
        rank = (lo + frac) / (n - 1) if n > 1 else 1.0
    sig = max(int(significance), 1)
    factor: float = float(10**sig)
    return math.floor(rank * factor) / factor


# -- Tier 3: dates --


def DAYS(end: float, start: float) -> int:
    return int(float(end) - float(start))


def DAYS360(start: float, end: float, method: bool = False) -> int:
    """360-day calendar day count. method=False (US/NASD), True (European)."""
    s = _from_serial(float(start)).date()
    e = _from_serial(float(end)).date()
    sy, sm, sd = s.year, s.month, s.day
    ey, em, ed = e.year, e.month, e.day
    if method:  # European
        if sd == 31:
            sd = 30
        if ed == 31:
            ed = 30
    else:  # US/NASD
        if sd == 31:
            sd = 30
        if ed == 31 and sd >= 30:
            ed = 30
    return (ey - sy) * 360 + (em - sm) * 30 + (ed - sd)


def WEEKNUM(serial: float, return_type: int = 1) -> int:
    """Excel week number. type 1 (default): week starts Sun, week 1 contains Jan 1.
    type 2: week starts Mon. type 21: ISO 8601."""
    rt = int(return_type)
    d = _from_serial(float(serial)).date()
    if rt == 21:
        return d.isocalendar()[1]
    jan1 = _dt.date(d.year, 1, 1)
    # Day-of-week shift: type 1 -> Sun=0, Mon=1, ..., Sat=6
    # type 2 -> Mon=0, ..., Sun=6
    if rt == 2:
        shift = jan1.weekday()  # Mon=0
        offset = (d - jan1).days + shift
    else:  # default 1
        shift = (jan1.weekday() + 1) % 7  # Sun=0
        offset = (d - jan1).days + shift
    return offset // 7 + 1


def ISOWEEKNUM(serial: float) -> int:
    return _from_serial(float(serial)).date().isocalendar()[1]


def YEARFRAC(start: float, end: float, basis: int = 0) -> float | ExcelError:
    """Year fraction between two dates. basis: 0=US 30/360, 1=actual/actual,
    2=actual/360, 3=actual/365, 4=European 30/360."""
    b = int(basis)
    s = _from_serial(float(start)).date()
    e = _from_serial(float(end)).date()
    if e < s:
        s, e = e, s
    if b == 0:
        return DAYS360(_to_serial(s), _to_serial(e), method=False) / 360.0
    if b == 4:
        return DAYS360(_to_serial(s), _to_serial(e), method=True) / 360.0
    days = (e - s).days
    if b == 2:
        return days / 360.0
    if b == 3:
        return days / 365.0
    if b == 1:
        # Actual/actual: average year length over the spanned years
        if s.year == e.year:
            yl = 366 if _is_leap(s.year) else 365
            return days / yl
        years = e.year - s.year + 1
        total = sum(366 if _is_leap(y) else 365 for y in range(s.year, e.year + 1))
        return days / (total / years)
    return ExcelError.NUM


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


# -- Tier 3: information --


_ERROR_TYPE_MAP: dict[ExcelError, int] = {
    ExcelError.NULL: 1,
    ExcelError.DIV0: 2,
    ExcelError.VALUE: 3,
    ExcelError.REF: 4,
    ExcelError.NAME: 5,
    ExcelError.NUM: 6,
    ExcelError.NA: 7,
}


def ERROR_TYPE(x: Any) -> int | ExcelError:
    if isinstance(x, ExcelError):
        return _ERROR_TYPE_MAP.get(x, ExcelError.NA)
    return ExcelError.NA


def TYPE(x: Any) -> int:
    """1=number, 2=text, 4=bool, 16=error, 64=array."""
    if isinstance(x, bool):
        return 4
    if isinstance(x, ExcelError):
        return 16
    if isinstance(x, Vec):
        return 64
    if isinstance(x, (int, float)):
        return 1
    if isinstance(x, str):
        return 2
    return 1


def ISNONTEXT(x: Any) -> bool:
    return not isinstance(x, str)


def ISFORMULA(env: Any, *args: Any) -> bool | ExcelError:
    """Raw-args. True if the referenced cell holds a formula."""
    from ..formula.ast_nodes import CellRef as _CellRef

    if len(args) != 1:
        return ExcelError.VALUE
    a = args[0]
    if isinstance(a, _CellRef):
        return bool(env.cell_is_formula(a.col, a.row))
    return ExcelError.VALUE


def ISREF(env: Any, *args: Any) -> bool:
    """Raw-args. True if argument is a cell or range reference."""
    from ..formula.ast_nodes import CellRef as _CellRef
    from ..formula.ast_nodes import RangeRef as _RangeRef

    if len(args) != 1:
        return False
    return isinstance(args[0], (_CellRef, _RangeRef))


# -- Tier 3: text --


def CLEAN(text: Any) -> str:
    """Strip non-printable ASCII control characters (codes 0-31)."""
    return "".join(c for c in str(text) if ord(c) >= 32)


def NUMBERVALUE(text: Any, decimal_sep: str = ".", group_sep: str = ",") -> float | ExcelError:
    s = str(text).strip()
    if not s:
        return 0.0
    s = s.replace(str(group_sep), "")
    if str(decimal_sep) != ".":
        s = s.replace(str(decimal_sep), ".")
    pct = 0
    while s.endswith("%"):
        pct += 1
        s = s[:-1]
    try:
        v = float(s)
    except ValueError:
        return ExcelError.VALUE
    return v / (100**pct) if pct else v


def FIXED(num: float, decimals: int = 2, no_commas: bool = False) -> str:
    d = max(int(decimals), 0)
    n = float(num)
    if no_commas:
        return f"{n:.{d}f}"
    return f"{n:,.{d}f}"


def DOLLAR(num: float, decimals: int = 2) -> str:
    d = int(decimals)
    n = float(num)
    if d >= 0:
        return f"${n:,.{d}f}"
    # Negative decimals: round to nearest 10^|d|
    factor = 10 ** (-d)
    rounded = round(n / factor) * factor
    return f"${rounded:,.0f}"


def T(value: Any) -> str:
    return value if isinstance(value, str) else ""


def UNICHAR(n: int) -> str | ExcelError:
    try:
        return chr(int(n))
    except (ValueError, OverflowError):
        return ExcelError.VALUE


def UNICODE(text: Any) -> int | ExcelError:
    s = str(text)
    if not s:
        return ExcelError.VALUE
    return ord(s[0])


# -- Tier 3: math --


def COMBIN(n: int, k: int) -> int | ExcelError:
    nn, kk = int(n), int(k)
    if nn < 0 or kk < 0 or kk > nn:
        return ExcelError.NUM
    return math.comb(nn, kk)


def COMBINA(n: int, k: int) -> int | ExcelError:
    """Combinations with repetition."""
    nn, kk = int(n), int(k)
    if nn < 0 or kk < 0:
        return ExcelError.NUM
    if nn == 0 and kk == 0:
        return 1
    return math.comb(nn + kk - 1, kk)


def PERMUT(n: int, k: int) -> int | ExcelError:
    nn, kk = int(n), int(k)
    if nn < 0 or kk < 0 or kk > nn:
        return ExcelError.NUM
    return math.perm(nn, kk)


def PERMUTATIONA(n: int, k: int) -> int | ExcelError:
    nn, kk = int(n), int(k)
    if nn < 0 or kk < 0:
        return ExcelError.NUM
    return int(nn**kk)


def MULTINOMIAL(*args: Any) -> int | ExcelError:
    nums: list[int] = []
    for a in args:
        if isinstance(a, Vec):
            nums.extend(
                int(v) for v in a.data if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
        elif isinstance(a, (int, float)) and not isinstance(a, bool):
            nums.append(int(a))
    if any(n < 0 for n in nums):
        return ExcelError.NUM
    total = sum(nums)
    num = math.factorial(total)
    den = 1
    for n in nums:
        den *= math.factorial(n)
    return num // den


def QUOTIENT(numerator: float, denominator: float) -> int | ExcelError:
    d = float(denominator)
    if d == 0:
        return ExcelError.DIV0
    return int(float(numerator) / d)


def CEILING_MATH(x: float, significance: float = 1.0, mode: int = 0) -> float:
    """mode=0: round toward +inf; mode!=0: round away from zero (negatives down)."""
    sig = abs(float(significance))
    if sig == 0:
        return 0.0
    n = float(x)
    if int(mode) == 0 or n >= 0:
        return math.ceil(n / sig) * sig
    return math.floor(n / sig) * sig


def FLOOR_MATH(x: float, significance: float = 1.0, mode: int = 0) -> float:
    sig = abs(float(significance))
    if sig == 0:
        return 0.0
    n = float(x)
    if int(mode) == 0 or n >= 0:
        return math.floor(n / sig) * sig
    return math.ceil(n / sig) * sig


def RADIANS(x: float) -> float:
    return math.radians(float(x))


def DEGREES(x: float) -> float:
    return math.degrees(float(x))


# -- Tier 3: paired sums --


def _paired_data(x: Vec, y: Vec) -> tuple[list[float], list[float]]:
    return _pair_numeric(x, y)


def SUMSQ(*args: Any) -> float:
    return sum(v * v for v in _flatten_numeric(args))


def SUMX2MY2(x: Vec, y: Vec) -> float:
    a, b = _paired_data(x, y)
    return sum(ai * ai - bi * bi for ai, bi in zip(a, b, strict=False))


def SUMX2PY2(x: Vec, y: Vec) -> float:
    a, b = _paired_data(x, y)
    return sum(ai * ai + bi * bi for ai, bi in zip(a, b, strict=False))


def SUMXMY2(x: Vec, y: Vec) -> float:
    a, b = _paired_data(x, y)
    return sum((ai - bi) ** 2 for ai, bi in zip(a, b, strict=False))


# -- Tier 3: hyperbolic --


def SINH(x: float) -> float:
    return math.sinh(float(x))


def COSH(x: float) -> float:
    return math.cosh(float(x))


def TANH(x: float) -> float:
    return math.tanh(float(x))


def ASINH(x: float) -> float:
    return math.asinh(float(x))


def ACOSH(x: float) -> float | ExcelError:
    n = float(x)
    if n < 1:
        return ExcelError.NUM
    return math.acosh(n)


def ATANH(x: float) -> float | ExcelError:
    n = float(x)
    if n <= -1 or n >= 1:
        return ExcelError.NUM
    return math.atanh(n)


# -- Tier 3: bitwise --


def _bit_arg(x: Any) -> int | ExcelError:
    n = int(x)
    if n < 0 or n >= (1 << 48):
        return ExcelError.NUM
    return n


def BITAND(a: Any, b: Any) -> int | ExcelError:
    aa = _bit_arg(a)
    if isinstance(aa, ExcelError):
        return aa
    bb = _bit_arg(b)
    if isinstance(bb, ExcelError):
        return bb
    return aa & bb


def BITOR(a: Any, b: Any) -> int | ExcelError:
    aa = _bit_arg(a)
    if isinstance(aa, ExcelError):
        return aa
    bb = _bit_arg(b)
    if isinstance(bb, ExcelError):
        return bb
    return aa | bb


def BITXOR(a: Any, b: Any) -> int | ExcelError:
    aa = _bit_arg(a)
    if isinstance(aa, ExcelError):
        return aa
    bb = _bit_arg(b)
    if isinstance(bb, ExcelError):
        return bb
    return aa ^ bb


def BITLSHIFT(value: Any, shift: int) -> int | ExcelError:
    v = _bit_arg(value)
    if isinstance(v, ExcelError):
        return v
    s = int(shift)
    if abs(s) > 53:
        return ExcelError.NUM
    r = v << s if s >= 0 else v >> -s
    if r >= (1 << 48):
        return ExcelError.NUM
    return r


def BITRSHIFT(value: Any, shift: int) -> int | ExcelError:
    return BITLSHIFT(value, -int(shift))


# -- Tier 3: random (volatile) --


def RAND() -> float:
    return _random.random()  # noqa: S311 -- spreadsheet RNG, not cryptographic


def RANDBETWEEN(low: int, high: int) -> int:
    lo, hi = int(low), int(high)
    if lo > hi:
        lo, hi = hi, lo
    return _random.randint(lo, hi)  # noqa: S311 -- spreadsheet RNG, not cryptographic


# -- Reference / address --


def _col_letters(n: int) -> str:
    """1-based column number -> Excel letters (1->A, 27->AA)."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def ADDRESS(
    row: int,
    col: int,
    abs_num: int = 1,
    a1: Any = True,
    sheet: str | None = None,
) -> str | ExcelError:
    """=ADDRESS(row, col, [abs_num], [a1], [sheet])

    abs_num: 1=$A$1, 2=A$1, 3=$A1, 4=A1. a1 truthy = A1 style (default);
    falsy = R1C1 style.
    """
    r = int(row)
    c = int(col)
    an = int(abs_num)
    if r <= 0 or c <= 0 or an < 1 or an > 4:
        return ExcelError.VALUE
    use_a1 = bool(a1) if not isinstance(a1, str) else a1.upper() not in ("FALSE", "0")
    if use_a1:
        col_part = ("$" if an in (1, 3) else "") + _col_letters(c)
        row_part = ("$" if an in (1, 2) else "") + str(r)
        addr = col_part + row_part
    else:
        # R1C1 style. abs_num: 1=R1C1, 2=R1C[1], 3=R[1]C1, 4=R[1]C[1].
        row_part = f"R{r}" if an in (1, 2) else f"R[{r}]"
        col_part = f"C{c}" if an in (1, 3) else f"C[{c}]"
        addr = row_part + col_part
    if sheet is not None and str(sheet) != "":
        return f"{sheet}!{addr}"
    return addr


# -- Excel 365 array functions (1D, scalar return only -- no spilling) --


def XLOOKUP(
    lookup: Any,
    lookup_array: Vec,
    return_array: Vec,
    if_not_found: Any = None,
    match_mode: int = 0,
    search_mode: int = 1,
) -> Any:
    """=XLOOKUP(value, lookup_array, return_array, [if_not_found],
    [match_mode], [search_mode])

    match_mode: 0=exact (default), -1=exact-or-next-smaller,
                1=exact-or-next-larger, 2=wildcard.
    search_mode: 1=first-to-last (default), -1=last-to-first.
    Scalar-return only: ``return_array`` is treated as 1D parallel to
    ``lookup_array``.
    """
    la = lookup_array.data
    ra = return_array.data
    n = min(len(la), len(ra))
    mm = int(match_mode)
    sm = int(search_mode)
    indices = range(n - 1, -1, -1) if sm == -1 else range(n)

    found = -1
    if mm == 0 or mm == 2:
        target = lookup
        if mm == 2 and isinstance(lookup, str):
            regex = _wildcard_regex(lookup)
            for i in indices:
                if regex.match(str(la[i])):
                    found = i
                    break
        else:
            for i in indices:
                if _exact_match(target, la[i]):
                    found = i
                    break
    elif mm == -1:
        # exact, or next smaller
        best = -1
        for i in range(n):
            if _exact_match(lookup, la[i]):
                best = i
                break
            if _safe_le(la[i], lookup) and (best == -1 or _safe_le(la[best], la[i])):
                best = i
        found = best
    elif mm == 1:
        # exact, or next larger
        best = -1
        for i in range(n):
            if _exact_match(lookup, la[i]):
                best = i
                break
            if _safe_ge(la[i], lookup) and (best == -1 or _safe_ge(la[best], la[i])):
                best = i
        found = best
    else:
        return ExcelError.VALUE

    if found < 0:
        return if_not_found if if_not_found is not None else ExcelError.NA
    return ra[found]


def XMATCH(
    lookup: Any,
    lookup_array: Vec,
    match_mode: int = 0,
    search_mode: int = 1,
) -> int | ExcelError:
    """=XMATCH(value, lookup_array, [match_mode], [search_mode]) -> 1-based pos.

    match_mode: 0=exact, -1=exact-or-next-smaller, 1=exact-or-next-larger,
                2=wildcard. search_mode: 1=first-to-last, -1=last-to-first.
    """
    la = lookup_array.data
    n = len(la)
    mm = int(match_mode)
    sm = int(search_mode)
    indices = range(n - 1, -1, -1) if sm == -1 else range(n)

    if mm == 0 or mm == 2:
        if mm == 2 and isinstance(lookup, str):
            regex = _wildcard_regex(lookup)
            for i in indices:
                if regex.match(str(la[i])):
                    return i + 1
        else:
            for i in indices:
                if _exact_match(lookup, la[i]):
                    return i + 1
        return ExcelError.NA
    if mm == -1:
        best = -1
        for i in range(n):
            if _exact_match(lookup, la[i]):
                return i + 1
            if _safe_le(la[i], lookup) and (best == -1 or _safe_le(la[best], la[i])):
                best = i
        return best + 1 if best >= 0 else ExcelError.NA
    if mm == 1:
        best = -1
        for i in range(n):
            if _exact_match(lookup, la[i]):
                return i + 1
            if _safe_ge(la[i], lookup) and (best == -1 or _safe_ge(la[best], la[i])):
                best = i
        return best + 1 if best >= 0 else ExcelError.NA
    return ExcelError.VALUE


def FILTER(rng: Vec, include: Vec, if_empty: Any = None) -> Vec | Any:
    """=FILTER(rng, include_vec, [if_empty])

    Returns a Vec of values from ``rng`` where the parallel ``include`` value
    is truthy. With no matches, returns ``if_empty`` (or #N/A).
    """
    a = rng.data
    b = include.data
    n = min(len(a), len(b))
    out = [a[i] for i in range(n) if b[i]]
    if not out:
        return if_empty if if_empty is not None else ExcelError.NA
    return Vec(out)


def SORT(rng: Vec, sort_index: int = 1, sort_order: int = 1, by_col: bool = False) -> Vec:
    """=SORT(rng, [sort_index], [sort_order], [by_col])

    1D sort over ``rng.data``; ``sort_index`` is reserved for 2D and ignored
    here. ``sort_order``: 1 ascending (default), -1 descending.
    ``by_col`` is ignored in the 1D path.
    """
    _ = sort_index, by_col
    return Vec(sorted(rng.data, reverse=int(sort_order) == -1))


def UNIQUE(rng: Vec, by_col: bool = False, exactly_once: bool = False) -> Vec:
    """=UNIQUE(rng, [by_col], [exactly_once])

    Preserves first-seen order. If ``exactly_once`` is truthy, returns only
    values appearing exactly once.
    """
    _ = by_col
    counts: dict[Any, int] = {}
    order: list[Any] = []
    for v in rng.data:
        if v not in counts:
            counts[v] = 0
            order.append(v)
        counts[v] += 1
    if exactly_once:
        return Vec([v for v in order if counts[v] == 1])
    return Vec(order)


def SEQUENCE(rows: int, columns: int = 1, start: float = 1.0, step: float = 1.0) -> Vec:
    """=SEQUENCE(rows, [columns], [start], [step])

    Generates ``rows*columns`` numbers row-major. ``cols`` field is set so
    INDEX can re-shape the result.
    """
    n_rows = max(int(rows), 0)
    n_cols = max(int(columns), 1)
    s = float(start)
    st = float(step)
    total = n_rows * n_cols
    return Vec([s + i * st for i in range(total)], cols=n_cols)


def RANDARRAY(
    rows: int = 1,
    columns: int = 1,
    minimum: float = 0.0,
    maximum: float = 1.0,
    integer: bool = False,
) -> Vec:
    """=RANDARRAY([rows], [cols], [min], [max], [integer]). 1D Vec, cols set."""
    n_rows = max(int(rows), 1)
    n_cols = max(int(columns), 1)
    lo = float(minimum)
    hi = float(maximum)
    total = n_rows * n_cols
    if integer:
        ilo, ihi = int(lo), int(hi)
        if ilo > ihi:
            ilo, ihi = ihi, ilo
        data: list[float] = [
            float(_random.randint(ilo, ihi))  # noqa: S311
            for _ in range(total)
        ]
    else:
        if lo > hi:
            lo, hi = hi, lo
        span = hi - lo
        data = [lo + _random.random() * span for _ in range(total)]  # noqa: S311
    return Vec(data, cols=n_cols)


# -- Statistical distributions (Tier 4) --
#
# Stdlib-only implementations. Accuracy targets: full double precision
# for normal (closed-form via math.erf and Acklam's rational inverse);
# ~1e-12 for Student-t / regularised incomplete beta (Lentz continued
# fraction with 200-iter cap); inverses by bisection to 1e-10 in p.
# Excel reference values match to >= 5 significant figures across the
# test set.


def _norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# Acklam's rational approximation to the inverse standard normal CDF.
# Max relative error ~1.15e-9; one Halley step would tighten further but
# this is already well past Excel's reported precision.
_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def _norm_s_inv(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        c, d = _ACKLAM_C, _ACKLAM_D
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        a, b = _ACKLAM_A, _ACKLAM_B
        num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        den = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        return num / den
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    c, d = _ACKLAM_C, _ACKLAM_D
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def _betacf(a: float, b: float, x: float) -> float:
    """Lentz's modified continued fraction for the incomplete beta tail."""
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            return h
    return h


def _incbeta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_cdf(t: float, v: float) -> float:
    """Student-t CDF: Pr(T <= t) for v degrees of freedom."""
    x = v / (v + t * t)
    half = 0.5 * _incbeta(v / 2.0, 0.5, x)
    return 1.0 - half if t >= 0 else half


def _t_inv_2tail(p: float, v: float) -> float:
    """Inverse two-tailed Student-t: returns x with Pr(|T| > x) = p."""
    # Bisect on g(x) = Pr(|T|>x) - p, monotone decreasing in x in (0, +inf).
    lo, hi = 0.0, 1e6
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        # 2 * (1 - cdf(mid))
        tail = 2.0 * (1.0 - _t_cdf(mid, v))
        if abs(tail - p) < 1e-12:
            return mid
        if tail > p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            return mid
    return 0.5 * (lo + hi)


def _t_inv(p: float, v: float) -> float:
    """Inverse Student-t left-tail: returns x with Pr(T <= x) = p."""
    if p <= 0 or p >= 1:
        raise ValueError("p must be in (0,1)")
    if p == 0.5:
        return 0.0
    # Symmetric: T.INV(p, v) = -T.INV(1-p, v).
    if p < 0.5:
        return -_t_inv_2tail(2.0 * p, v)
    return _t_inv_2tail(2.0 * (1.0 - p), v)


def _binom_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    if p == 0.0:
        return 1.0 if k == 0 else 0.0
    if p == 1.0:
        return 1.0 if k == n else 0.0
    log_pmf = (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log(1.0 - p)
    )
    return math.exp(log_pmf)


def _pois_pmf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def NORM_DIST(x: float, mean: float, sd: float, cumulative: Any = True) -> float | ExcelError:
    """=NORM.DIST(x, mean, sd, cumulative)."""
    s = float(sd)
    if s <= 0:
        return ExcelError.NUM
    z = (float(x) - float(mean)) / s
    if bool(cumulative):
        return _norm_cdf(z)
    return _norm_pdf(z) / s


def NORM_INV(p: float, mean: float = 0.0, sd: float = 1.0) -> float | ExcelError:
    pp = float(p)
    s = float(sd)
    if not 0.0 < pp < 1.0 or s <= 0:
        return ExcelError.NUM
    return float(mean) + s * _norm_s_inv(pp)


def NORM_S_DIST(z: float, cumulative: Any = True) -> float:
    """=NORM.S.DIST(z, cumulative). Excel 2010+ requires cumulative; legacy
    NORMSDIST is one-arg and always cumulative."""
    if bool(cumulative):
        return _norm_cdf(float(z))
    return _norm_pdf(float(z))


def NORM_S_INV(p: float) -> float | ExcelError:
    pp = float(p)
    if not 0.0 < pp < 1.0:
        return ExcelError.NUM
    return _norm_s_inv(pp)


def T_DIST(x: float, df: int, cumulative: Any = True) -> float | ExcelError:
    """=T.DIST(x, df, cumulative). Left-tail CDF or PDF."""
    v = float(df)
    if v < 1:
        return ExcelError.NUM
    xv = float(x)
    if bool(cumulative):
        return _t_cdf(xv, v)
    # PDF: gamma((v+1)/2) / (sqrt(v*pi)*gamma(v/2)) * (1 + x^2/v)^(-(v+1)/2)
    log_coef = math.lgamma((v + 1) / 2) - 0.5 * math.log(v * math.pi) - math.lgamma(v / 2)
    return float(math.exp(log_coef) * (1.0 + xv * xv / v) ** (-(v + 1) / 2))


def T_DIST_2T(x: float, df: int) -> float | ExcelError:
    """=T.DIST.2T(x, df). Two-tailed: Pr(|T| > |x|). x must be >= 0."""
    v = float(df)
    xv = float(x)
    if v < 1 or xv < 0:
        return ExcelError.NUM
    return 2.0 * (1.0 - _t_cdf(xv, v))


def T_DIST_RT(x: float, df: int) -> float | ExcelError:
    """=T.DIST.RT(x, df). Right-tail: Pr(T > x)."""
    v = float(df)
    if v < 1:
        return ExcelError.NUM
    return 1.0 - _t_cdf(float(x), v)


def T_INV(p: float, df: int) -> float | ExcelError:
    """=T.INV(p, df). Inverse left-tail."""
    v = float(df)
    pp = float(p)
    if v < 1 or not 0.0 < pp < 1.0:
        return ExcelError.NUM
    return _t_inv(pp, v)


def T_INV_2T(p: float, df: int) -> float | ExcelError:
    """=T.INV.2T(p, df). Inverse two-tailed: returns x s.t. Pr(|T|>x)=p."""
    v = float(df)
    pp = float(p)
    if v < 1 or not 0.0 < pp <= 1.0:
        return ExcelError.NUM
    return _t_inv_2tail(pp, v)


def BINOM_DIST(num_s: int, trials: int, prob_s: float, cumulative: Any) -> float | ExcelError:
    """=BINOM.DIST(num_s, trials, prob_s, cumulative)."""
    k, n = int(num_s), int(trials)
    p = float(prob_s)
    if n < 0 or k < 0 or k > n or not 0.0 <= p <= 1.0:
        return ExcelError.NUM
    if bool(cumulative):
        return sum(_binom_pmf(i, n, p) for i in range(k + 1))
    return _binom_pmf(k, n, p)


def POISSON_DIST(x: int, mean: float, cumulative: Any) -> float | ExcelError:
    k = int(x)
    lam = float(mean)
    if k < 0 or lam < 0:
        return ExcelError.NUM
    if bool(cumulative):
        return sum(_pois_pmf(i, lam) for i in range(k + 1))
    return _pois_pmf(k, lam)


def EXPON_DIST(x: float, lam: float, cumulative: Any) -> float | ExcelError:
    xv = float(x)
    lv = float(lam)
    if xv < 0 or lv <= 0:
        return ExcelError.NUM
    if bool(cumulative):
        return 1.0 - math.exp(-lv * xv)
    return lv * math.exp(-lv * xv)


def CONFIDENCE_NORM(alpha: float, sd: float, n: int) -> float | ExcelError:
    """=CONFIDENCE.NORM(alpha, sd, size). Half-width of confidence interval."""
    a = float(alpha)
    s = float(sd)
    nn = int(n)
    if not 0.0 < a < 1.0 or s <= 0 or nn < 1:
        return ExcelError.NUM
    return _norm_s_inv(1.0 - a / 2.0) * s / math.sqrt(nn)


def TDIST_LEGACY(x: float, df: int, tails: int) -> float | ExcelError:
    """Legacy TDIST(x, df, tails). x must be non-negative.
    tails=1 -> right-tail; tails=2 -> two-tailed."""
    v = float(df)
    xv = float(x)
    t = int(tails)
    if v < 1 or xv < 0 or t not in (1, 2):
        return ExcelError.NUM
    rt = 1.0 - _t_cdf(xv, v)
    return rt if t == 1 else 2.0 * rt


# -- Statistical distributions (Tier 4 heavier) --
#
# These chain off `_incbeta`/`math.lgamma` (already in this module) plus
# a regularised incomplete gamma `_incgamma` defined here. Inverses
# default to bisection on the CDF (200 iterations, 1e-12 tolerance in
# probability) — adequate for ~10 decimal digits, matching Excel's
# documented precision.


def _gser(a: float, x: float) -> float:
    """Series for regularised lower incomplete gamma P(a, x). Use when x < a+1."""
    if x <= 0:
        return 0.0
    ap = a
    s = 1.0 / a
    delta = s
    for _ in range(1000):
        ap += 1.0
        delta *= x / ap
        s += delta
        if abs(delta) < abs(s) * 1e-15:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Lentz CF for regularised upper incomplete gamma Q(a, x). Use when x >= a+1."""
    fpmin = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b
    h = d
    for i in range(1, 201):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _incgamma(a: float, x: float) -> float:
    """Regularised lower incomplete gamma P(a, x) = γ(a, x) / Γ(a)."""
    if x <= 0 or a <= 0:
        return 0.0
    if x < a + 1:
        return _gser(a, x)
    return 1.0 - _gcf(a, x)


def _bisect_inv(
    cdf: Callable[[float], float], p: float, lo: float, hi: float, tol: float = 1e-12
) -> float:
    """Bisect for x with cdf(x) = p, assuming cdf is monotone non-decreasing."""
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        v = cdf(mid)
        if abs(v - p) < tol or hi - lo < 1e-14:
            return mid
        if v < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _hypgeom_pmf(k: int, n: int, K: int, N: int) -> float:
    """P(X=k) for hypergeometric: k successes in sample of n drawn
    from population N containing K total successes."""
    if k < max(0, n - (N - K)) or k > min(n, K):
        return 0.0
    log_p = (
        math.lgamma(K + 1)
        - math.lgamma(k + 1)
        - math.lgamma(K - k + 1)
        + math.lgamma(N - K + 1)
        - math.lgamma(n - k + 1)
        - math.lgamma(N - K - n + k + 1)
        - math.lgamma(N + 1)
        + math.lgamma(n + 1)
        + math.lgamma(N - n + 1)
    )
    return math.exp(log_p)


def _negbinom_pmf(k: int, r: int, p: float) -> float:
    """P(X=k) negative binomial: k failures before r-th success, success prob p."""
    if k < 0 or r < 1 or not 0 < p <= 1:
        return 0.0
    log_p = (
        math.lgamma(k + r)
        - math.lgamma(k + 1)
        - math.lgamma(r)
        + r * math.log(p)
        + k * math.log1p(-p)
        if p < 1
        else 0.0
    )
    if p == 1:
        return 1.0 if k == 0 else 0.0
    return math.exp(log_p)


# -- F distribution --


def _f_cdf(x: float, d1: float, d2: float) -> float:
    if x <= 0:
        return 0.0
    return _incbeta(d1 / 2.0, d2 / 2.0, (d1 * x) / (d1 * x + d2))


def F_DIST(x: float, df1: int, df2: int, cumulative: Any = True) -> float | ExcelError:
    """=F.DIST(x, df1, df2, cumulative). Left-tail."""
    xv = float(x)
    v1, v2 = float(df1), float(df2)
    if xv < 0 or v1 < 1 or v2 < 1:
        return ExcelError.NUM
    if bool(cumulative):
        return _f_cdf(xv, v1, v2)
    if xv == 0:
        return 0.0
    log_pdf = (
        math.lgamma((v1 + v2) / 2)
        - math.lgamma(v1 / 2)
        - math.lgamma(v2 / 2)
        + (v1 / 2) * math.log(v1)
        + (v2 / 2) * math.log(v2)
        + (v1 / 2 - 1) * math.log(xv)
        - ((v1 + v2) / 2) * math.log(v2 + v1 * xv)
    )
    return math.exp(log_pdf)


def F_DIST_RT(x: float, df1: int, df2: int) -> float | ExcelError:
    """=F.DIST.RT(x, df1, df2). Right-tail; legacy FDIST signature."""
    xv = float(x)
    v1, v2 = float(df1), float(df2)
    if xv < 0 or v1 < 1 or v2 < 1:
        return ExcelError.NUM
    return 1.0 - _f_cdf(xv, v1, v2)


def F_INV(p: float, df1: int, df2: int) -> float | ExcelError:
    pp = float(p)
    v1, v2 = float(df1), float(df2)
    if not 0.0 <= pp <= 1.0 or v1 < 1 or v2 < 1:
        return ExcelError.NUM
    if pp == 0:
        return 0.0
    return _bisect_inv(lambda x: _f_cdf(x, v1, v2), pp, 0.0, 1e8)


def F_INV_RT(p: float, df1: int, df2: int) -> float | ExcelError:
    pp = float(p)
    if not 0.0 < pp <= 1.0:
        return ExcelError.NUM
    return F_INV(1.0 - pp, df1, df2)


# -- Chi-square distribution --


def _chi2_cdf(x: float, df: float) -> float:
    if x <= 0:
        return 0.0
    return _incgamma(df / 2.0, x / 2.0)


def CHISQ_DIST(x: float, df: int, cumulative: Any = True) -> float | ExcelError:
    """=CHISQ.DIST(x, df, cumulative). Left-tail."""
    xv = float(x)
    v = float(df)
    if xv < 0 or v < 1:
        return ExcelError.NUM
    if bool(cumulative):
        return _chi2_cdf(xv, v)
    if xv == 0:
        return 0.0 if v != 2 else 0.5
    log_pdf = (v / 2 - 1) * math.log(xv) - xv / 2 - (v / 2) * math.log(2) - math.lgamma(v / 2)
    return math.exp(log_pdf)


def CHISQ_DIST_RT(x: float, df: int) -> float | ExcelError:
    """=CHISQ.DIST.RT(x, df). Right-tail; legacy CHIDIST."""
    xv = float(x)
    v = float(df)
    if xv < 0 or v < 1:
        return ExcelError.NUM
    return 1.0 - _chi2_cdf(xv, v)


def CHISQ_INV(p: float, df: int) -> float | ExcelError:
    pp = float(p)
    v = float(df)
    if not 0.0 <= pp <= 1.0 or v < 1:
        return ExcelError.NUM
    if pp == 0:
        return 0.0
    return _bisect_inv(lambda x: _chi2_cdf(x, v), pp, 0.0, 1e8)


def CHISQ_INV_RT(p: float, df: int) -> float | ExcelError:
    pp = float(p)
    if not 0.0 < pp <= 1.0:
        return ExcelError.NUM
    return CHISQ_INV(1.0 - pp, df)


def CHISQ_TEST(actual: Vec, expected: Vec) -> float | ExcelError:
    """=CHISQ.TEST(actual, expected). 1D arrays: df = n - 1.

    Returns the right-tail p-value for the chi-square statistic.
    """
    a = _vec_data(actual)
    e = _vec_data(expected)
    if len(a) != len(e) or len(a) < 2:
        return ExcelError.NUM
    if any(ev <= 0 for ev in e):
        return ExcelError.NUM
    chi2 = sum((ai - ei) ** 2 / ei for ai, ei in zip(a, e, strict=True))
    return 1.0 - _chi2_cdf(chi2, len(a) - 1)


# -- Gamma distribution --


def _gamma_cdf(x: float, alpha: float, beta: float) -> float:
    if x <= 0:
        return 0.0
    return _incgamma(alpha, x / beta)


def GAMMA(x: float) -> float | ExcelError:
    """=GAMMA(x). Returns Γ(x)."""
    xv = float(x)
    if xv == int(xv) and xv <= 0:
        return ExcelError.NUM  # poles at non-positive integers
    try:
        return math.gamma(xv)
    except (ValueError, OverflowError):
        return ExcelError.NUM


def GAMMALN(x: float) -> float | ExcelError:
    """=GAMMALN(x). Returns ln(Γ(x)). Domain x > 0."""
    xv = float(x)
    if xv <= 0:
        return ExcelError.NUM
    return math.lgamma(xv)


def GAMMA_DIST(x: float, alpha: float, beta: float, cumulative: Any = True) -> float | ExcelError:
    """=GAMMA.DIST(x, alpha, beta, cumulative)."""
    xv, av, bv = float(x), float(alpha), float(beta)
    if xv < 0 or av <= 0 or bv <= 0:
        return ExcelError.NUM
    if bool(cumulative):
        return _gamma_cdf(xv, av, bv)
    if xv == 0:
        return 0.0 if av != 1 else 1.0 / bv
    log_pdf = (av - 1) * math.log(xv) - xv / bv - av * math.log(bv) - math.lgamma(av)
    return math.exp(log_pdf)


def GAMMA_INV(p: float, alpha: float, beta: float) -> float | ExcelError:
    pp, av, bv = float(p), float(alpha), float(beta)
    if not 0.0 <= pp <= 1.0 or av <= 0 or bv <= 0:
        return ExcelError.NUM
    if pp == 0:
        return 0.0
    # Mode-anchored upper bound: 100 * mean = 100 * alpha * beta is generous.
    hi = max(100.0 * av * bv, 1e3)
    return _bisect_inv(lambda x: _gamma_cdf(x, av, bv), pp, 0.0, hi)


# -- Beta distribution --


def BETA_DIST(
    x: float,
    alpha: float,
    beta: float,
    cumulative: Any = True,
    a: float = 0.0,
    b: float = 1.0,
) -> float | ExcelError:
    """=BETA.DIST(x, alpha, beta, cumulative, [A], [B]). Defaults to [0,1]."""
    xv, av, bv = float(x), float(alpha), float(beta)
    lo, hi = float(a), float(b)
    if av <= 0 or bv <= 0 or hi <= lo or xv < lo or xv > hi:
        return ExcelError.NUM
    z = (xv - lo) / (hi - lo)
    if bool(cumulative):
        return _incbeta(av, bv, z)
    if z == 0 or z == 1:
        return 0.0
    log_pdf = (
        math.lgamma(av + bv)
        - math.lgamma(av)
        - math.lgamma(bv)
        + (av - 1) * math.log(z)
        + (bv - 1) * math.log1p(-z)
    )
    return math.exp(log_pdf) / (hi - lo)


def BETA_INV(
    p: float, alpha: float, beta: float, a: float = 0.0, b: float = 1.0
) -> float | ExcelError:
    pp, av, bv = float(p), float(alpha), float(beta)
    lo, hi = float(a), float(b)
    if not 0.0 <= pp <= 1.0 or av <= 0 or bv <= 0 or hi <= lo:
        return ExcelError.NUM
    z = _bisect_inv(lambda x: _incbeta(av, bv, x), pp, 0.0, 1.0)
    return lo + z * (hi - lo)


# -- Lognormal --


def LOGNORM_DIST(x: float, mean: float, sd: float, cumulative: Any = True) -> float | ExcelError:
    """=LOGNORM.DIST(x, mean, sd, cumulative). Lognormal of underlying N(mean, sd)."""
    xv, mu, sigma = float(x), float(mean), float(sd)
    if xv <= 0 or sigma <= 0:
        return ExcelError.NUM
    z = (math.log(xv) - mu) / sigma
    if bool(cumulative):
        return _norm_cdf(z)
    return _norm_pdf(z) / (xv * sigma)


def LOGNORM_INV(p: float, mean: float, sd: float) -> float | ExcelError:
    pp, mu, sigma = float(p), float(mean), float(sd)
    if not 0.0 < pp < 1.0 or sigma <= 0:
        return ExcelError.NUM
    return math.exp(mu + sigma * _norm_s_inv(pp))


# -- Weibull --


def WEIBULL_DIST(x: float, alpha: float, beta: float, cumulative: Any = True) -> float | ExcelError:
    """=WEIBULL.DIST(x, shape, scale, cumulative)."""
    xv, av, bv = float(x), float(alpha), float(beta)
    if xv < 0 or av <= 0 or bv <= 0:
        return ExcelError.NUM
    if bool(cumulative):
        return 1.0 - math.exp(-((xv / bv) ** av))
    return float((av / bv) * (xv / bv) ** (av - 1) * math.exp(-((xv / bv) ** av)))


# -- Hypergeometric --


def HYPGEOM_DIST(
    sample_s: int, num_sample: int, pop_s: int, num_pop: int, cumulative: Any = False
) -> float | ExcelError:
    """=HYPGEOM.DIST(sample_s, number_sample, population_s, number_pop, cumulative)."""
    k, n, K, N = int(sample_s), int(num_sample), int(pop_s), int(num_pop)
    if k < 0 or n < 0 or K < 0 or N < 0 or n > N or K > N or k > n or k > K:
        return ExcelError.NUM
    if bool(cumulative):
        return sum(_hypgeom_pmf(i, n, K, N) for i in range(k + 1))
    return _hypgeom_pmf(k, n, K, N)


# -- Negative binomial --


def NEGBINOM_DIST(
    num_f: int, num_s: int, prob_s: float, cumulative: Any = False
) -> float | ExcelError:
    """=NEGBINOM.DIST(num_failures, num_success, prob_success, cumulative)."""
    f, r = int(num_f), int(num_s)
    p = float(prob_s)
    if f < 0 or r < 1 or not 0 < p <= 1:
        return ExcelError.NUM
    if bool(cumulative):
        return sum(_negbinom_pmf(i, r, p) for i in range(f + 1))
    return _negbinom_pmf(f, r, p)


# -- Inverse binomial CDF (CRITBINOM) --


def BINOM_INV(trials: int, prob_s: float, alpha: float) -> int | ExcelError:
    """=BINOM.INV(trials, prob_s, alpha). Smallest k with binomial CDF >= alpha."""
    n = int(trials)
    p = float(prob_s)
    a = float(alpha)
    if n < 0 or not 0.0 <= p <= 1.0 or not 0.0 <= a <= 1.0:
        return ExcelError.NUM
    cum = 0.0
    for k in range(n + 1):
        cum += _binom_pmf(k, n, p)
        if cum >= a:
            return k
    return n


# -- Hypothesis tests --


def T_TEST(array1: Vec, array2: Vec, tails: int, ttype: int) -> float | ExcelError:
    """=T.TEST(array1, array2, tails, type).

    type: 1 = paired, 2 = two-sample equal variance, 3 = two-sample
    unequal variance (Welch). tails: 1 or 2.
    """
    a = _vec_data(array1)
    b = _vec_data(array2)
    tt = int(ttype)
    tl = int(tails)
    if tt not in (1, 2, 3) or tl not in (1, 2):
        return ExcelError.NUM
    if tt == 1:
        if len(a) != len(b) or len(a) < 2:
            return ExcelError.NUM
        diffs = [ai - bi for ai, bi in zip(a, b, strict=True)]
        n = len(diffs)
        m = sum(diffs) / n
        var = sum((d - m) ** 2 for d in diffs) / (n - 1)
        if var == 0:
            return ExcelError.DIV0
        t = m / math.sqrt(var / n)
        df = float(n - 1)
    else:
        n1, n2 = len(a), len(b)
        if n1 < 2 or n2 < 2:
            return ExcelError.NUM
        m1, m2 = sum(a) / n1, sum(b) / n2
        v1 = sum((x - m1) ** 2 for x in a) / (n1 - 1)
        v2 = sum((x - m2) ** 2 for x in b) / (n2 - 1)
        if tt == 2:
            sp2 = ((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)
            if sp2 == 0:
                return ExcelError.DIV0
            t = (m1 - m2) / math.sqrt(sp2 * (1 / n1 + 1 / n2))
            df = float(n1 + n2 - 2)
        else:  # Welch
            denom = v1 / n1 + v2 / n2
            if denom == 0:
                return ExcelError.DIV0
            t = (m1 - m2) / math.sqrt(denom)
            df = denom**2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    rt = 1.0 - _t_cdf(abs(t), df)
    return rt if tl == 1 else 2.0 * rt


def Z_TEST(array: Vec, x: float, sigma: float | None = None) -> float | ExcelError:
    """=Z.TEST(array, x, [sigma]). One-tailed P(Z > z) where
    z = (mean(array) - x) / (sigma / sqrt(n)). Sample stdev used when
    sigma is omitted.
    """
    data = _vec_data(array)
    n = len(data)
    if n < 1:
        return ExcelError.NUM
    m = sum(data) / n
    if sigma is None:
        if n < 2:
            return ExcelError.DIV0
        s = statistics.stdev(data)
    else:
        s = float(sigma)
    if s <= 0:
        return ExcelError.NUM
    z = (m - float(x)) / (s / math.sqrt(n))
    return 1.0 - _norm_cdf(z)


def CONFIDENCE_T(alpha: float, sd: float, n: int) -> float | ExcelError:
    """=CONFIDENCE.T(alpha, sd, size). Half-width using Student-t critical."""
    a = float(alpha)
    s = float(sd)
    nn = int(n)
    if not 0.0 < a < 1.0 or s <= 0 or nn < 2:
        return ExcelError.NUM
    return _t_inv_2tail(a, nn - 1) * s / math.sqrt(nn)


def STANDARDIZE(x: float, mean: float, sd: float) -> float | ExcelError:
    """=STANDARDIZE(x, mean, sd). z = (x - mean) / sd."""
    s = float(sd)
    if s <= 0:
        return ExcelError.NUM
    return (float(x) - float(mean)) / s


def PHI(x: float) -> float:
    """=PHI(x). Standard normal density at x."""
    return _norm_pdf(float(x))


def PROB(
    x_range: Vec, prob_range: Vec, lower_limit: float, upper_limit: float | None = None
) -> float | ExcelError:
    """=PROB(x_range, prob_range, lower, [upper]).

    Sums prob_range[i] for x_range[i] in [lower, upper]. With no
    upper, returns the probability at lower exactly.
    """
    xs = _vec_data(x_range)
    ps = _vec_data(prob_range)
    if len(xs) != len(ps) or not xs:
        return ExcelError.NUM
    if any(p < 0 for p in ps) or not math.isclose(sum(ps), 1.0, abs_tol=1e-9):
        return ExcelError.NUM
    lo = float(lower_limit)
    hi = lo if upper_limit is None else float(upper_limit)
    if hi < lo:
        lo, hi = hi, lo
    return sum(p for x, p in zip(xs, ps, strict=True) if lo <= x <= hi)


# -- Math: error function --


def ERF(lower: float, upper: float | None = None) -> float | ExcelError:
    """=ERF(lower, [upper]). One-arg form returns erf(lower); two-arg
    returns erf(upper) - erf(lower)."""
    a = float(lower)
    if upper is None:
        return math.erf(a)
    return math.erf(float(upper)) - math.erf(a)


def ERFC(x: float) -> float:
    """=ERFC(x). Complementary error function: 1 - erf(x)."""
    return math.erfc(float(x))


# -- Tier 4: text parsing --


def TEXTBEFORE(
    text: str,
    delimiter: Any,
    instance: int = 1,
    match_mode: int = 0,
    match_end: int = 0,
    if_not_found: Any = None,
) -> Any:
    """=TEXTBEFORE(text, delimiter, [instance], [match_mode], [match_end], [if_not_found]).

    Returns the substring before the n-th occurrence of ``delimiter``.
    ``match_mode``: 0 = case-sensitive (default), 1 = case-insensitive.
    Negative ``instance`` searches from the end. ``match_end=1`` treats
    end-of-string as a match. Tuple/list delimiters: any element matches.
    """
    s = str(text)
    delims: list[str] = (
        list(delimiter) if isinstance(delimiter, (list, tuple)) else [str(delimiter)]
    )
    inst = int(instance)
    if inst == 0:
        return ExcelError.VALUE
    case_fold = bool(int(match_mode))
    haystack = s.lower() if case_fold else s
    delims_cmp = [d.lower() if case_fold else d for d in delims]
    matches: list[tuple[int, int]] = []  # (start, len) sorted by start
    for d, dc in zip(delims, delims_cmp, strict=True):
        if not d:
            continue
        i = 0
        while True:
            idx = haystack.find(dc, i)
            if idx < 0:
                break
            matches.append((idx, len(d)))
            i = idx + 1
    matches.sort()
    if int(match_end):
        matches.append((len(s), 0))
    if not matches:
        return if_not_found if if_not_found is not None else ExcelError.NA
    pick = matches[inst - 1] if inst > 0 else matches[inst]  # negative -> from end
    if not 0 <= (matches.index(pick) if pick in matches else -1) < len(matches):
        return if_not_found if if_not_found is not None else ExcelError.NA
    return s[: pick[0]]


def TEXTAFTER(
    text: str,
    delimiter: Any,
    instance: int = 1,
    match_mode: int = 0,
    match_end: int = 0,
    if_not_found: Any = None,
) -> Any:
    """=TEXTAFTER(text, delimiter, [instance], [match_mode], [match_end], [if_not_found])."""
    s = str(text)
    delims: list[str] = (
        list(delimiter) if isinstance(delimiter, (list, tuple)) else [str(delimiter)]
    )
    inst = int(instance)
    if inst == 0:
        return ExcelError.VALUE
    case_fold = bool(int(match_mode))
    haystack = s.lower() if case_fold else s
    delims_cmp = [d.lower() if case_fold else d for d in delims]
    matches: list[tuple[int, int]] = []
    for d, dc in zip(delims, delims_cmp, strict=True):
        if not d:
            continue
        i = 0
        while True:
            idx = haystack.find(dc, i)
            if idx < 0:
                break
            matches.append((idx, len(d)))
            i = idx + 1
    matches.sort()
    if int(match_end):
        matches.insert(0, (0, 0))
    if not matches:
        return if_not_found if if_not_found is not None else ExcelError.NA
    try:
        pick = matches[inst - 1] if inst > 0 else matches[inst]
    except IndexError:
        return if_not_found if if_not_found is not None else ExcelError.NA
    return s[pick[0] + pick[1] :]


def TEXTSPLIT(
    text: str,
    col_delimiter: Any,
    row_delimiter: Any = None,
    ignore_empty: int = 0,
    match_mode: int = 0,
    pad_with: Any = None,
) -> Vec | ExcelError:
    """=TEXTSPLIT(text, col_delim, [row_delim], [ignore_empty], [match_mode], [pad_with]).

    Returns a 1D ``Vec`` (rows flattened with ``cols`` set) of the split
    parts. Multiple delimiters are supported as list/tuple.
    """
    _ = pad_with  # 2D padding not relevant for 1D-flattened output.
    s = str(text)
    case_fold = bool(int(match_mode))

    def _splitall(t: str, dlm: Any) -> list[str]:
        delims = list(dlm) if isinstance(dlm, (list, tuple)) else [str(dlm)]
        delims = [d for d in delims if d]
        if not delims:
            return [t]
        # Case-insensitive split via regex.
        pattern = "|".join(re.escape(d) for d in delims)
        flags = re.IGNORECASE if case_fold else 0
        return re.split(pattern, t, flags=flags)

    if row_delimiter is None or (isinstance(row_delimiter, str) and row_delimiter == ""):
        parts = _splitall(s, col_delimiter)
        if int(ignore_empty):
            parts = [p for p in parts if p != ""]
        if not parts:
            return ExcelError.NA
        return Vec(list(parts), cols=len(parts))
    rows = _splitall(s, row_delimiter)
    grid: list[list[str]] = [_splitall(r, col_delimiter) for r in rows]
    if int(ignore_empty):
        grid = [[c for c in row if c != ""] for row in grid]
        grid = [r for r in grid if r]
    if not grid:
        return ExcelError.NA
    n_cols = max(len(r) for r in grid)
    pad = "" if pad_with is None else str(pad_with)
    flat: list[Any] = []
    for r in grid:
        flat.extend(r + [pad] * (n_cols - len(r)))
    return Vec(flat, cols=n_cols)


# -- Tier 4: number-base conversion --
#
# Excel uses 10-digit two's-complement for negative inputs/outputs in the
# DEC2BIN/DEC2OCT/DEC2HEX family: the high bit of a 10-digit string in
# the source base indicates a negative number.


def _dec_to_base(n: int, base: int, places: int | None) -> str | ExcelError:
    if n < 0:
        # Two's complement in the base's 10-digit representation.
        n = base**10 + n
        if n < 0:
            return ExcelError.NUM
        s = ""
        while n:
            d = n % base
            s = (chr(ord("0") + d) if d < 10 else chr(ord("A") + d - 10)) + s
            n //= base
        s = s.rjust(10, "0")
        return s
    digits = ""
    if n == 0:
        digits = "0"
    while n:
        d = n % base
        digits = (chr(ord("0") + d) if d < 10 else chr(ord("A") + d - 10)) + digits
        n //= base
    if places is None:
        return digits
    p = int(places)
    if p < 1 or p > 10 or len(digits) > p:
        return ExcelError.NUM
    return digits.rjust(p, "0")


def _base_to_dec(s: str, base: int) -> int | ExcelError:
    text = str(s).strip().upper()
    if not text:
        return ExcelError.NUM
    if len(text) > 10:
        return ExcelError.NUM
    try:
        n = int(text, base)
    except ValueError:
        return ExcelError.NUM
    # 10-digit two's-complement: if leading digit makes value >= base^9 * (base/2),
    # interpret as negative. Easiest: if length == 10 and n >= base**10 / 2.
    if len(text) == 10 and n >= base**10 // 2:
        n -= base**10
    return n


def DEC2BIN(number: int, places: int | None = None) -> str | ExcelError:
    n = int(number)
    if n < -(2**9) or n >= 2**9:
        return ExcelError.NUM
    return _dec_to_base(n, 2, places)


def DEC2OCT(number: int, places: int | None = None) -> str | ExcelError:
    n = int(number)
    if n < -(8**9) or n >= 8**9:
        return ExcelError.NUM
    return _dec_to_base(n, 8, places)


def DEC2HEX(number: int, places: int | None = None) -> str | ExcelError:
    n = int(number)
    if n < -(16**9) or n >= 16**9:
        return ExcelError.NUM
    return _dec_to_base(n, 16, places)


def BIN2DEC(text: str) -> int | ExcelError:
    return _base_to_dec(str(text), 2)


def OCT2DEC(text: str) -> int | ExcelError:
    return _base_to_dec(str(text), 8)


def HEX2DEC(text: str) -> int | ExcelError:
    return _base_to_dec(str(text), 16)


def BIN2OCT(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 2)
    if isinstance(n, ExcelError):
        return n
    return _dec_to_base(n, 8, places)


def BIN2HEX(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 2)
    if isinstance(n, ExcelError):
        return n
    return _dec_to_base(n, 16, places)


def OCT2BIN(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 8)
    if isinstance(n, ExcelError):
        return n
    if n < -(2**9) or n >= 2**9:
        return ExcelError.NUM
    return _dec_to_base(n, 2, places)


def OCT2HEX(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 8)
    if isinstance(n, ExcelError):
        return n
    return _dec_to_base(n, 16, places)


def HEX2BIN(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 16)
    if isinstance(n, ExcelError):
        return n
    if n < -(2**9) or n >= 2**9:
        return ExcelError.NUM
    return _dec_to_base(n, 2, places)


def HEX2OCT(text: str, places: int | None = None) -> str | ExcelError:
    n = _base_to_dec(str(text), 16)
    if isinstance(n, ExcelError):
        return n
    if n < -(8**9) or n >= 8**9:
        return ExcelError.NUM
    return _dec_to_base(n, 8, places)


# -- Tier 4: scalar forecasting --


def FORECAST(x: float, known_y: Vec, known_x: Vec) -> float | ExcelError:
    """=FORECAST(x, known_y, known_x). Single-point linear forecast."""
    r = _linreg(known_y, known_x)
    if isinstance(r, ExcelError):
        return r
    slope, intercept, *_ = r
    return intercept + slope * float(x)


def FORECAST_LINEAR(x: float, known_y: Vec, known_x: Vec) -> float | ExcelError:
    """=FORECAST.LINEAR. Identical to FORECAST in Excel 2016+."""
    return FORECAST(x, known_y, known_x)


def TREND_SCALAR(known_y: Vec, known_x: Vec | None = None, new_x: Any = None) -> Any:
    """=TREND(known_y, [known_x], [new_x]).

    Scalar form only: when ``new_x`` is a single number or a 1D ``Vec``
    of new x-values, returns one prediction per x. Multi-column array
    form (multiple regressors with 2D inputs) requires 2D-aware Vecs and
    is not yet supported.
    """
    if known_x is None:
        known_x = Vec([float(i + 1) for i in range(len(known_y.data))])
    r = _linreg(known_y, known_x)
    if isinstance(r, ExcelError):
        return r
    slope, intercept, *_ = r
    if new_x is None:
        new_x = known_x
    if isinstance(new_x, Vec):
        return Vec([intercept + slope * float(x) for x in _vec_data(new_x)])
    if isinstance(new_x, (int, float)) and not isinstance(new_x, bool):
        return float(intercept + slope * float(new_x))
    return ExcelError.VALUE


# -- Tier 4: D-functions (database queries) --
#
# Database is a 2D Vec (cells row-major; cols carries the width). The
# first row is the header. ``field`` may be a column name (case-insensitive)
# or a 1-based column index. ``criteria`` is a 2D Vec where the first
# row names the column to filter; subsequent rows are clauses. Within a
# row, predicates are ANDed; across rows, ORed -- standard Excel
# semantics.


def _vec_table(v: Vec) -> tuple[list[str], list[list[Any]]] | ExcelError:
    """Split a 2D Vec into (header, rows)."""
    cols = v.cols
    data = list(v.data)
    if not cols or cols <= 0 or len(data) < cols:
        return ExcelError.VALUE
    header = [str(h) for h in data[:cols]]
    body: list[list[Any]] = []
    for i in range(cols, len(data), cols):
        body.append(data[i : i + cols])
    return header, body


def _resolve_field(header: list[str], field: Any) -> int | ExcelError:
    if isinstance(field, (int, float)) and not isinstance(field, bool):
        idx = int(field) - 1
        if 0 <= idx < len(header):
            return idx
        return ExcelError.VALUE
    name = str(field).strip().lower()
    for i, h in enumerate(header):
        if h.strip().lower() == name:
            return i
    return ExcelError.VALUE


def _row_matches_criteria(
    row: list[Any], db_header: list[str], crit_header: list[str], crit_rows: list[list[Any]]
) -> bool:
    """OR over criteria rows; AND across populated cells within a row."""
    if not crit_rows:
        return True
    for clause in crit_rows:
        ok = True
        for j, cval in enumerate(clause):
            if cval is None or (isinstance(cval, str) and cval == ""):
                continue
            col_name = crit_header[j]
            try:
                db_idx = _resolve_field(db_header, col_name)
            except Exception:  # noqa: BLE001 -- defensive against malformed criteria
                ok = False
                break
            if isinstance(db_idx, ExcelError):
                ok = False
                break
            pred = _parse_criteria(cval)
            if not pred(row[db_idx]):
                ok = False
                break
        if ok:
            return True
    return False


def _d_collect(database: Vec, field: Any, criteria: Vec) -> list[Any] | ExcelError:
    """Return the field values from rows passing the criteria."""
    db = _vec_table(database)
    if isinstance(db, ExcelError):
        return db
    db_header, db_body = db
    cr = _vec_table(criteria)
    if isinstance(cr, ExcelError):
        return cr
    crit_header, crit_body = cr
    field_idx = _resolve_field(db_header, field)
    if isinstance(field_idx, ExcelError):
        return field_idx
    return [
        row[field_idx]
        for row in db_body
        if _row_matches_criteria(row, db_header, crit_header, crit_body)
    ]


def _d_numerics(database: Vec, field: Any, criteria: Vec) -> list[float] | ExcelError:
    vals = _d_collect(database, field, criteria)
    if isinstance(vals, ExcelError):
        return vals
    return [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]


def DSUM(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    return sum(nums)


def DAVERAGE(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    if not nums:
        return ExcelError.DIV0
    return sum(nums) / len(nums)


def DCOUNT(database: Vec, field: Any, criteria: Vec) -> int | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    return len(nums)


def DCOUNTA(database: Vec, field: Any, criteria: Vec) -> int | ExcelError:
    vals = _d_collect(database, field, criteria)
    if isinstance(vals, ExcelError):
        return vals
    return sum(1 for v in vals if v is not None and not (isinstance(v, str) and v == ""))


def DGET(database: Vec, field: Any, criteria: Vec) -> Any:
    vals = _d_collect(database, field, criteria)
    if isinstance(vals, ExcelError):
        return vals
    if len(vals) == 0:
        return ExcelError.VALUE
    if len(vals) > 1:
        return ExcelError.NUM
    return vals[0]


def DMAX(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    return max(nums) if nums else 0.0


def DMIN(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    return min(nums) if nums else 0.0


def DPRODUCT(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    p = 1.0
    for v in nums:
        p *= v
    return p


def DSTDEV(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    if len(nums) < 2:
        return ExcelError.DIV0
    return statistics.stdev(nums)


def DSTDEVP(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    if not nums:
        return ExcelError.DIV0
    return statistics.pstdev(nums)


def DVAR(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    if len(nums) < 2:
        return ExcelError.DIV0
    return statistics.variance(nums)


def DVARP(database: Vec, field: Any, criteria: Vec) -> float | ExcelError:
    nums = _d_numerics(database, field, criteria)
    if isinstance(nums, ExcelError):
        return nums
    if not nums:
        return ExcelError.DIV0
    return statistics.pvariance(nums)


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
    # Tier 3 -- aggregates
    "COUNTA": COUNTA,
    "COUNTBLANK": COUNTBLANK,
    "PRODUCT": PRODUCT,
    "AVERAGEA": AVERAGEA,
    "MAXA": MAXA,
    "MINA": MINA,
    # Tier 3 -- modern stat name aliases
    "STDEV.S": STDEV,
    "STDEV.P": STDEVP,
    "VAR.S": VAR,
    "VAR.P": VARP,
    "MODE.SNGL": MODE,
    "MODE.MULT": MODE_MULT,
    "COVARIANCE.P": COVARIANCE_P,
    "COVARIANCE.S": COVARIANCE_S,
    "PERCENTILE.INC": PERCENTILE,
    "PERCENTILE.EXC": PERCENTILE_EXC,
    "QUARTILE.INC": QUARTILE,
    "QUARTILE.EXC": QUARTILE_EXC,
    "RANK.EQ": RANK,
    "RANK.AVG": RANK_AVG,
    # Tier 3 -- additional stats
    "AVEDEV": AVEDEV,
    "DEVSQ": DEVSQ,
    "SLOPE": SLOPE,
    "INTERCEPT": INTERCEPT,
    "RSQ": RSQ,
    "STEYX": STEYX,
    "SKEW": SKEW,
    "KURT": KURT,
    "PERCENTRANK": PERCENTRANK,
    # Tier 3 -- dates
    "DAYS": DAYS,
    "DAYS360": DAYS360,
    "WEEKNUM": WEEKNUM,
    "ISOWEEKNUM": ISOWEEKNUM,
    "YEARFRAC": YEARFRAC,
    # Tier 3 -- information
    "ERROR.TYPE": ERROR_TYPE,
    "TYPE": TYPE,
    "ISFORMULA": ISFORMULA,
    "ISREF": ISREF,
    "ISNONTEXT": ISNONTEXT,
    # Tier 3 -- text
    "CLEAN": CLEAN,
    "NUMBERVALUE": NUMBERVALUE,
    "FIXED": FIXED,
    "DOLLAR": DOLLAR,
    "T": T,
    "UNICHAR": UNICHAR,
    "UNICODE": UNICODE,
    # Tier 3 -- math
    "COMBIN": COMBIN,
    "COMBINA": COMBINA,
    "PERMUT": PERMUT,
    "PERMUTATIONA": PERMUTATIONA,
    "MULTINOMIAL": MULTINOMIAL,
    "QUOTIENT": QUOTIENT,
    "CEILING.MATH": CEILING_MATH,
    "FLOOR.MATH": FLOOR_MATH,
    "RADIANS": RADIANS,
    "DEGREES": DEGREES,
    # Tier 3 -- paired sums
    "SUMSQ": SUMSQ,
    "SUMX2MY2": SUMX2MY2,
    "SUMX2PY2": SUMX2PY2,
    "SUMXMY2": SUMXMY2,
    # Tier 3 -- hyperbolic
    "SINH": SINH,
    "COSH": COSH,
    "TANH": TANH,
    "ASINH": ASINH,
    "ACOSH": ACOSH,
    "ATANH": ATANH,
    # Tier 3 -- bitwise
    "BITAND": BITAND,
    "BITOR": BITOR,
    "BITXOR": BITXOR,
    "BITLSHIFT": BITLSHIFT,
    "BITRSHIFT": BITRSHIFT,
    # Tier 3 -- random (volatile)
    "RAND": RAND,
    "RANDBETWEEN": RANDBETWEEN,
    # Reference
    "ADDRESS": ADDRESS,
    # Excel 365 array functions (1D / scalar return)
    "XLOOKUP": XLOOKUP,
    "XMATCH": XMATCH,
    "FILTER": FILTER,
    "SORT": SORT,
    "UNIQUE": UNIQUE,
    "SEQUENCE": SEQUENCE,
    "RANDARRAY": RANDARRAY,
    # Tier 4 -- financial
    "SLN": SLN,
    "SYD": SYD,
    "DB": DB,
    "DDB": DDB,
    "VDB": VDB,
    "EFFECT": EFFECT,
    "NOMINAL": NOMINAL,
    "CUMIPMT": CUMIPMT,
    "CUMPRINC": CUMPRINC,
    "MIRR": MIRR,
    "XNPV": XNPV,
    "XIRR": XIRR,
    # Tier 4 -- statistical distributions
    "NORM.DIST": NORM_DIST,
    "NORM.INV": NORM_INV,
    "NORM.S.DIST": NORM_S_DIST,
    "NORM.S.INV": NORM_S_INV,
    "T.DIST": T_DIST,
    "T.DIST.2T": T_DIST_2T,
    "T.DIST.RT": T_DIST_RT,
    "T.INV": T_INV,
    "T.INV.2T": T_INV_2T,
    "BINOM.DIST": BINOM_DIST,
    "POISSON.DIST": POISSON_DIST,
    "EXPON.DIST": EXPON_DIST,
    "CONFIDENCE.NORM": CONFIDENCE_NORM,
    # Legacy (pre-2010) aliases
    "NORMDIST": NORM_DIST,
    "NORMINV": NORM_INV,
    "NORMSDIST": lambda z: _norm_cdf(float(z)),
    "NORMSINV": NORM_S_INV,
    "TDIST": TDIST_LEGACY,
    "TINV": T_INV_2T,
    "BINOMDIST": BINOM_DIST,
    "POISSON": POISSON_DIST,
    "EXPONDIST": EXPON_DIST,
    "CONFIDENCE": CONFIDENCE_NORM,
    # Tier 4 -- math
    "ERF": ERF,
    "ERFC": ERFC,
    "GAMMA": GAMMA,
    "GAMMALN": GAMMALN,
    "GAMMALN.PRECISE": GAMMALN,
    "PHI": PHI,
    "STANDARDIZE": STANDARDIZE,
    # Tier 4 -- distributions (heavier)
    "F.DIST": F_DIST,
    "F.DIST.RT": F_DIST_RT,
    "F.INV": F_INV,
    "F.INV.RT": F_INV_RT,
    "CHISQ.DIST": CHISQ_DIST,
    "CHISQ.DIST.RT": CHISQ_DIST_RT,
    "CHISQ.INV": CHISQ_INV,
    "CHISQ.INV.RT": CHISQ_INV_RT,
    "CHISQ.TEST": CHISQ_TEST,
    "GAMMA.DIST": GAMMA_DIST,
    "GAMMA.INV": GAMMA_INV,
    "BETA.DIST": BETA_DIST,
    "BETA.INV": BETA_INV,
    "LOGNORM.DIST": LOGNORM_DIST,
    "LOGNORM.INV": LOGNORM_INV,
    "WEIBULL.DIST": WEIBULL_DIST,
    "HYPGEOM.DIST": HYPGEOM_DIST,
    "NEGBINOM.DIST": NEGBINOM_DIST,
    "BINOM.INV": BINOM_INV,
    "T.TEST": T_TEST,
    "Z.TEST": Z_TEST,
    "CONFIDENCE.T": CONFIDENCE_T,
    "PROB": PROB,
    # Pre-2010 legacy aliases
    "FDIST": F_DIST_RT,
    "FINV": F_INV_RT,
    "CHIDIST": CHISQ_DIST_RT,
    "CHIINV": CHISQ_INV_RT,
    "CHITEST": CHISQ_TEST,
    "GAMMADIST": GAMMA_DIST,
    "GAMMAINV": GAMMA_INV,
    "BETADIST": BETA_DIST,
    "BETAINV": BETA_INV,
    "LOGNORMDIST": LOGNORM_DIST,
    "LOGINV": LOGNORM_INV,
    "WEIBULL": WEIBULL_DIST,
    "HYPGEOMDIST": HYPGEOM_DIST,
    "NEGBINOMDIST": NEGBINOM_DIST,
    "CRITBINOM": BINOM_INV,
    "TTEST": T_TEST,
    "ZTEST": Z_TEST,
    # Tier 4 -- text parsing
    "TEXTSPLIT": TEXTSPLIT,
    "TEXTBEFORE": TEXTBEFORE,
    "TEXTAFTER": TEXTAFTER,
    # Tier 4 -- number-base conversion
    "DEC2BIN": DEC2BIN,
    "DEC2OCT": DEC2OCT,
    "DEC2HEX": DEC2HEX,
    "BIN2DEC": BIN2DEC,
    "OCT2DEC": OCT2DEC,
    "HEX2DEC": HEX2DEC,
    "BIN2OCT": BIN2OCT,
    "BIN2HEX": BIN2HEX,
    "OCT2BIN": OCT2BIN,
    "OCT2HEX": OCT2HEX,
    "HEX2BIN": HEX2BIN,
    "HEX2OCT": HEX2OCT,
    # Tier 4 -- scalar forecasting
    "FORECAST": FORECAST,
    "FORECAST.LINEAR": FORECAST_LINEAR,
    "TREND": TREND_SCALAR,
    # Tier 4 -- D-functions
    "DSUM": DSUM,
    "DAVERAGE": DAVERAGE,
    "DCOUNT": DCOUNT,
    "DCOUNTA": DCOUNTA,
    "DGET": DGET,
    "DMAX": DMAX,
    "DMIN": DMIN,
    "DPRODUCT": DPRODUCT,
    "DSTDEV": DSTDEV,
    "DSTDEVP": DSTDEVP,
    "DVAR": DVAR,
    "DVARP": DVARP,
}
