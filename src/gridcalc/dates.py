"""Excel date serials: conversion, format classification, and rendering.

A date in a spreadsheet is a number wearing a number format. `2026-05-05` is
`46147.0`, and the only thing that makes it a date rather than forty-six
thousand is the format code attached to the cell. That is Excel's model, and
copying it is what lets date arithmetic (`=B2-A2` is a day count) work without
a date type in the value system.

So gridcalc stores the serial and remembers the format. This module owns both
halves:

* **Serial arithmetic** (:func:`to_serial`, :func:`from_serial`) -- previously
  private in ``libs/xlsx.py``, where `DATE`, `YEAR` and friends already used
  it. The display layer and the criteria parser need the same epoch, and three
  copies of the 1900-leap-year offset is three chances to get it wrong.
* **Format classification** (:func:`is_date_format`, :func:`normalise_format`)
  -- deciding whether a format code from an xlsx file means "this is a date",
  which is what turns a column of floats back into dates on import.

The epoch is 1899-12-30 rather than 1900-01-01 because Excel believes 1900 was
a leap year. Serial 60 is Excel's non-existent 1900-02-29; this offset makes
every serial above it agree with Excel, which is the range every real workbook
lives in. Below 60 the two disagree by a day, and matching the bug exactly
would mean reproducing a phantom date no Python `date` can hold.
"""

from __future__ import annotations

import datetime as _dt
import re

EXCEL_EPOCH = _dt.date(1899, 12, 30)

# The built-in numFmtIds that mean "date" or "time". xlsx files omit the format
# code for these entirely -- the ids are defined by the spec, so a file that
# uses one carries only the number. 14-22 are the date and time formats, 45-47
# the elapsed-time ones.
BUILTIN_DATE_FORMAT_IDS = frozenset({14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47})

# What each built-in id renders as, near enough. Excel's 14 is locale-dependent
# ("the short date format"); ISO is the defensible choice for a tool whose
# output gets diffed and grepped, and it is unambiguous, which `3/4/2026` is
# not.
_BUILTIN_FORMAT_CODES = {
    14: "yyyy-mm-dd",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "yyyy-mm-dd h:mm",
    45: "mm:ss",
    46: "h:mm:ss",
    47: "mm:ss.0",
}

# gridcalc's own default when a date arrives with no usable code.
DEFAULT_DATE_FORMAT = "yyyy-mm-dd"

# Tokens that can only appear in a date/time format. A bare `m` is deliberately
# absent: it means minutes as often as months, and alone it says nothing --
# `mmm` (a month name) is unambiguous, so that one counts.
_DATE_TOKENS = re.compile(r"[ydhs]|mmm", re.IGNORECASE)

# Everything inside a format code that is not a token: literal text in quotes,
# escaped characters, colour and condition sections, and padding directives.
_FORMAT_NOISE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.', re.DOTALL)


def to_serial(d: _dt.date | _dt.datetime) -> float:
    """Python date/datetime -> Excel serial."""
    if isinstance(d, _dt.datetime):
        days = (d.date() - EXCEL_EPOCH).days
        secs = d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
        return days + secs / 86400.0
    return float((d - EXCEL_EPOCH).days)


def from_serial(s: float) -> _dt.datetime:
    """Excel serial -> Python datetime."""
    days = int(s)
    frac = s - days
    base = EXCEL_EPOCH + _dt.timedelta(days=days)
    return _dt.datetime(base.year, base.month, base.day) + _dt.timedelta(seconds=frac * 86400)


def is_date_format(code: str) -> bool:
    """Whether an xlsx number-format code renders its number as a date or time.

    Excel has no flag for this: a format is a date format if its tokens say so.
    The check strips the parts of the code that are not tokens first -- a
    literal ``"day"`` in quotes, an escaped character, a ``[Red]`` colour
    section -- because otherwise any currency format mentioning a `d` in its
    literal text would classify as a date.

    Deliberately conservative: a code with no date token is not a date, so a
    misread leaves a number looking like a number rather than turning a price
    into 1974.
    """
    if not code:
        return False
    # Sections are separated by `;` (positive;negative;zero;text). The first
    # is the one a date would use.
    first = code.split(";")[0]
    stripped = _FORMAT_NOISE.sub("", first)
    if not stripped:
        return False
    # A general or purely numeric format is not a date however many `d`s the
    # stripped remainder appears to hold.
    if stripped.strip().lower() in ("general", ""):
        return False
    return bool(_DATE_TOKENS.search(stripped))


def normalise_format(code: str, fmt_id: int | None = None) -> str:
    """The format code to store for a cell, or ``""`` if it is not a date.

    ``fmt_id`` is the built-in numFmtId when the file carried one; those have
    no code in the file at all, so the id is the only evidence.
    """
    if code and is_date_format(code):
        return code.split(";")[0].strip()
    if fmt_id is not None and fmt_id in BUILTIN_DATE_FORMAT_IDS:
        return _BUILTIN_FORMAT_CODES.get(fmt_id, DEFAULT_DATE_FORMAT)
    return ""


def has_time(code: str) -> bool:
    """Whether the code renders a time component as well as (or instead of) a date."""
    stripped = _FORMAT_NOISE.sub("", code.split(";")[0])
    return bool(re.search(r"(h|s)", stripped, re.IGNORECASE))


def format_serial(value: float, code: str) -> str | None:
    """Render ``value`` through an xlsx date format code.

    Returns ``None`` when the code is not a date format or the serial cannot
    be a date, so the caller falls through to numeric formatting rather than
    printing something misleading. A negative serial has no date, and Excel
    shows ``#####`` for one; here it stays a number, which is more informative
    than a row of hashes.

    Supports the subset of the format language that actually appears on date
    cells -- `yyyy`/`yy`, `mmmm`/`mmm`/`mm`/`m`, `dddd`/`ddd`/`dd`/`d`,
    `hh`/`h`, `ss`/`s`, `AM/PM`, and quoted literals. Anything else in the code
    is emitted as-is.
    """
    if not code or value < 0 or value > 2_958_465:  # 9999-12-31
        return None
    try:
        dt = from_serial(value)
    except (OverflowError, ValueError):
        return None

    time_mode = False  # `m` means minutes once an hour token has been seen
    out: list[str] = []
    i = 0
    low = code
    n = len(low)
    while i < n:
        ch = low[i]
        # Quoted literal.
        if ch == '"':
            j = low.find('"', i + 1)
            if j < 0:
                out.append(low[i + 1 :])
                break
            out.append(low[i + 1 : j])
            i = j + 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(low[i + 1])
            i += 2
            continue
        # AM/PM marker: also switches `h` to 12-hour.
        rest = low[i:].lower()
        if rest.startswith("am/pm") or rest.startswith("a/p"):
            width = 5 if rest.startswith("am/pm") else 3
            out.append("AM" if dt.hour < 12 else "PM")
            i += width
            continue
        run = _run_of(low, i)
        token = run.lower()
        if token.startswith("y"):
            out.append(f"{dt.year:04d}" if len(run) > 2 else f"{dt.year % 100:02d}")
        elif token.startswith("h"):
            time_mode = True
            hour = dt.hour
            if _uses_ampm(low):
                hour = hour % 12 or 12
            out.append(f"{hour:02d}" if len(run) > 1 else str(hour))
        elif token.startswith("s"):
            out.append(f"{dt.second:02d}" if len(run) > 1 else str(dt.second))
        elif token.startswith("m"):
            # `m` after an hour token is minutes; otherwise it is a month.
            if time_mode and len(run) <= 2:
                out.append(f"{dt.minute:02d}" if len(run) > 1 else str(dt.minute))
            elif len(run) >= 4:
                out.append(dt.strftime("%B"))
            elif len(run) == 3:
                out.append(dt.strftime("%b"))
            elif len(run) == 2:
                out.append(f"{dt.month:02d}")
            else:
                out.append(str(dt.month))
        elif token.startswith("d"):
            if len(run) >= 4:
                out.append(dt.strftime("%A"))
            elif len(run) == 3:
                out.append(dt.strftime("%a"))
            elif len(run) == 2:
                out.append(f"{dt.day:02d}")
            else:
                out.append(str(dt.day))
        else:
            out.append(run)
        i += len(run)
    return "".join(out)


def _run_of(s: str, i: int) -> str:
    """The maximal run of the character at ``i`` (case-insensitively)."""
    ch = s[i].lower()
    j = i
    while j < len(s) and s[j].lower() == ch:
        j += 1
    return s[i:j]


def _uses_ampm(code: str) -> bool:
    low = code.lower()
    return "am/pm" in low or "a/p" in low


# Formats accepted when a criteria string or a typed cell should become a date.
# ISO first: it is unambiguous, and `03/04/2026` is not, so a file that uses it
# is read the American way Excel would read it rather than silently the other.
_PARSE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d, %Y",
    "%d %B %Y",
)


def parse_date(text: str) -> float | None:
    """Parse a date string to an Excel serial, or ``None`` if it is not one.

    Used by the criteria parser so `COUNTIF(range, ">1/1/2020")` compares
    dates rather than failing to coerce a string to a float. Returning
    ``None`` rather than raising keeps the caller's "is this a number?"
    cascade readable.
    """
    s = (text or "").strip()
    if not s:
        return None
    for fmt in _PARSE_FORMATS:
        try:
            return to_serial(_dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None
