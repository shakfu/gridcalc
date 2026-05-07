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
    a = list(x.data)
    b = list(y.data)
    n = min(len(a), len(b))
    divisor = n - 1 if sample else n
    if divisor <= 0:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
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
    data = sorted(rng.data)
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
    data = list(rng.data)
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
    a = list(y.data)
    b = list(x.data)
    n = min(len(a), len(b))
    if n < 2:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
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
    a = list(known_y.data)
    b = list(known_x.data)
    n = min(len(a), len(b))
    if n < 2:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
    my, mx = sum(a) / n, sum(b) / n
    syy = sum((a[i] - my) ** 2 for i in range(n))
    sxx = sum((b[i] - mx) ** 2 for i in range(n))
    sxy = sum((b[i] - mx) * (a[i] - my) for i in range(n))
    if sxx == 0 or syy == 0:
        return ExcelError.DIV0
    return (sxy * sxy) / (sxx * syy)


def STEYX(known_y: Vec, known_x: Vec) -> float | ExcelError:
    """Standard error of predicted y."""
    a = list(known_y.data)
    b = list(known_x.data)
    n = min(len(a), len(b))
    if n < 3:
        return ExcelError.DIV0
    a, b = a[:n], b[:n]
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
    data = sorted(rng.data)
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
            nums.extend(int(v) for v in a.data)
        else:
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
    a = list(x.data)
    b = list(y.data)
    n = min(len(a), len(b))
    return a[:n], b[:n]


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
}
