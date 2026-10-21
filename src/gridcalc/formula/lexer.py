from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .errors import FormulaError, parse_error_literal

# Token kinds
NUMBER = "NUMBER"
STRING = "STRING"
BOOL = "BOOL"
IDENT = "IDENT"
CELLREF = "CELLREF"
ERROR_LIT = "ERROR_LIT"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
COMMA = "COMMA"
COLON = "COLON"
DOT = "DOT"
PLUS = "PLUS"
MINUS = "MINUS"
STAR = "STAR"
SLASH = "SLASH"
CARET = "CARET"
AMP = "AMP"
PERCENT = "PERCENT"
EQ = "EQ"
NE = "NE"
LT = "LT"
GT = "GT"
LE = "LE"
GE = "GE"
BANG = "BANG"
HASH = "HASH"
LBRACE = "LBRACE"
RBRACE = "RBRACE"
SEMI = "SEMI"
# Whole columns (`B:B`) and whole rows (`1:1`): value is (first, last, abs first, abs last).
COLRANGE = "COLRANGE"
# A 3D reference's sheets with the `!`: `Jan:Mar!`, value (first, last).
SHEETSPAN = "SHEETSPAN"
ROWRANGE = "ROWRANGE"
EOF = "EOF"

_SINGLE = {
    "(": LPAREN,
    ")": RPAREN,
    ",": COMMA,
    ":": COLON,
    ".": DOT,
    "+": PLUS,
    "-": MINUS,
    "*": STAR,
    "/": SLASH,
    "^": CARET,
    "&": AMP,
    "%": PERCENT,
    "=": EQ,
    "<": LT,
    ">": GT,
    "!": BANG,
    "#": HASH,  # spill-range operator (A1#); error literals matched above
    "{": LBRACE,
    "}": RBRACE,
    ";": SEMI,
}


@dataclass
class Token:
    kind: str
    value: Any
    pos: int


_CELLREF_RE = re.compile(r"(\$?)([A-Za-z]+)(\$?)(\d+)")
_COLRANGE_RE = re.compile(r"(\$?)([A-Za-z]{1,3}):(\$?)([A-Za-z]{1,3})(?![A-Za-z0-9_.(!])")
_SHEETSPAN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_.]*)!")
_ROWRANGE_RE = re.compile(r"(\$?)(\d+):(\$?)(\d+)(?![A-Za-z0-9_.(])")
_NUMBER_RE = re.compile(r"\d+(\.\d*)?([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?", re.ASCII)
_SIGNED_NUMBER_RE = re.compile(r"[+-]?(?:" + _NUMBER_RE.pattern + ")", re.ASCII)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_]+")
_ERROR_LIT_RE = re.compile(r"#(?:DIV/0!|N/A|NAME\?|REF!|VALUE!|NUM!|NULL!)", re.IGNORECASE)


def parse_number(text: str) -> float | None:
    """The number ``text`` spells, or None. Accepts only decimal notation:
    ``float`` alone also takes ``nan``, ``inf`` and ``1_000``. A value past
    the float range (``1e400``) is None: Excel keeps such an entry as text."""
    if not _SIGNED_NUMBER_RE.fullmatch(text):
        return None
    v = float(text)
    return None if math.isinf(v) else v


def _digits15(text: str) -> str | None:
    """Number ``text`` cut to 15 significant digits, or None if it has no more.

    Excel reads a typed number this way: `12345678901234567` is
    `12345678901234500` (`num-1` in docs/dev/excel-check.md).
    """
    if sum(ch.isdigit() for ch in text) <= 15:
        return None
    sign, digits, exp = Decimal(text).as_tuple()
    if not isinstance(exp, int) or len(digits) <= 15:
        return None
    d = Decimal((sign, digits[:15], exp + len(digits) - 15))
    return str(d) if "e" in text.lower() else format(d, "f")


def float15(text: str) -> float:
    """A number literal as Excel reads it: 15 significant digits."""
    return float(_digits15(text) or text)


def entry_text(text: str) -> str:
    """A typed cell entry as Excel keeps it: a number to 15 significant digits."""
    t = text.strip()
    if parse_number(t) is None:
        return text
    return _digits15(t) or text


def _parse_cellref(text: str, start: int) -> tuple[int, int, int, bool, bool] | None:
    """The cell reference at ``start``, as (end index, col, row, abs col, abs row)."""
    m = _CELLREF_RE.match(text, start)
    if not m:
        return None
    abs_c = m.group(1) == "$"
    letters = m.group(2).upper()
    abs_r = m.group(3) == "$"
    rownum = int(m.group(4))
    if rownum <= 0:
        return None
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    col -= 1
    row = rownum - 1
    return (m.end(), col, row, abs_c, abs_r)


def bare_span_ok(first: str, last: str) -> bool:
    """Whether unquoted `first:last!` is a 3D qualifier, not a range such as
    `A1:Sheet2!B5`. Excel quotes a sheet name that reads as a cell (`'Q1'`)."""
    return not any(_EXCEL_CELL_RE.fullmatch(name) for name in (first, last))


_EXCEL_CELL_RE = re.compile(r"(?i)(?:[A-Z]{1,2}|[A-W][A-Z]{2}|X[A-E][A-Z]|XF[A-D])0*[1-9]\d{0,6}")


def _col_index(letters: str) -> int:
    col = 0
    for ch in letters.upper():
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return col - 1


def whole_range(text: str, start: int) -> tuple[str, tuple[int, int, bool, bool], int] | None:
    """The `B:B` or `1:1` reference at ``start``, as (kind, value, end index)."""
    m = _COLRANGE_RE.match(text, start)
    if m:
        a, b = _col_index(m.group(2)), _col_index(m.group(4))
        return COLRANGE, (a, b, m.group(1) == "$", m.group(3) == "$"), m.end()
    m = _ROWRANGE_RE.match(text, start)
    if m and int(m.group(2)) > 0 and int(m.group(4)) > 0:
        a, b = int(m.group(2)) - 1, int(m.group(4)) - 1
        return ROWRANGE, (a, b, m.group(1) == "$", m.group(3) == "$"), m.end()
    return None


def tokenize(text: str) -> list[Token]:
    s = text.lstrip()
    if s.startswith("="):
        s = s[1:]
    offset = len(text) - len(s)
    tokens: list[Token] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        pos = i + offset
        # error literal
        m = _ERROR_LIT_RE.match(s, i) if ch == "#" else None
        if m:
            err = parse_error_literal(m.group(0))
            if err is None:
                raise FormulaError(f"unknown error literal {m.group(0)!r} at {pos}")
            tokens.append(Token(ERROR_LIT, err, pos))
            i = m.end()
            continue
        # `Jan:Mar!`, before cellref takes `Sheet1` as a cell.
        m = _SHEETSPAN_RE.match(s, i) if ch.isalpha() or ch == "_" else None
        if m and bare_span_ok(m.group(1), m.group(2)):
            tokens.append(Token(SHEETSPAN, (m.group(1), m.group(2)), pos))
            i = m.end()
            continue
        # Whole columns and rows, before cellref, IDENT and NUMBER take a part.
        if ch == "$" or ch.isalnum():
            whole = whole_range(s, i)
            if whole is not None:
                whole_kind, value, i = whole
                tokens.append(Token(whole_kind, value, pos))
                continue
        # cellref (must come before IDENT and NUMBER; handles $A$1 etc.)
        if ch == "$" or ch.isalpha():
            cr = _parse_cellref(s, i)
            if cr is not None:
                next_idx, col, row, ac, ar = cr
                # Validate it's not followed by an alpha/digit that would extend it
                # (e.g., A1B should NOT be a cellref). Already guaranteed because we
                # match greedy letters then digits; what follows must not be alnum
                # for the cellref to be standalone. Also: a cellref-shaped token
                # followed by `!` is actually a sheet name (e.g. `Sheet1!A1`),
                # so emit an IDENT instead and let the parser handle the prefix.
                if next_idx < n and (s[next_idx].isalnum() or s[next_idx] == "_"):
                    cr = None  # fall through to IDENT
                elif next_idx < n and s[next_idx] in "!(":
                    # `Sheet1!A1` is a sheet prefix; `LOG10(` a function name.
                    cr = None
                else:
                    tokens.append(Token(CELLREF, (col, row, ac, ar), pos))
                    i = next_idx
                    continue
        # identifier (function name, named range, bool, py keyword). A segment
        # straight after `name.` may start with a digit: `T.DIST.2T`.
        dotted = s[i - 1 : i] == "." and bool(tokens) and tokens[-1].kind == DOT
        if ch.isalpha() or ch == "_" or (dotted and ch.isdigit()):
            m2 = (_SEGMENT_RE if dotted else _IDENT_RE).match(s, i)
            if m2 is None:
                raise FormulaError(f"unexpected character {ch!r} at {pos}")
            ident = m2.group(0)
            up = ident.upper()
            if up == "TRUE":
                tokens.append(Token(BOOL, True, pos))
            elif up == "FALSE":
                tokens.append(Token(BOOL, False, pos))
            else:
                tokens.append(Token(IDENT, ident, pos))
            i = m2.end()
            continue
        # number
        after_ident = bool(tokens) and tokens[-1].kind == IDENT and s[i - 1 : i].isalnum()
        if ch.isdigit() or (ch == "." and i + 1 < n and s[i + 1].isdigit() and not after_ident):
            m3 = _NUMBER_RE.match(s, i)
            if m3 is None:
                raise FormulaError(f"invalid number at {pos}")
            tokens.append(Token(NUMBER, float15(m3.group(0)), pos))
            i = m3.end()
            continue
        # string "..." with "" escape
        if ch == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                if s[j] == '"':
                    if j + 1 < n and s[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(s[j])
                j += 1
            else:
                raise FormulaError(f"unterminated string at {pos}")
            tokens.append(Token(STRING, "".join(buf), pos))
            i = j + 1
            continue
        # 'Sheet Name'!A1 -- a quoted sheet name, with '' for a literal
        # apostrophe. Emitted as IDENT so the parser's existing
        # `IDENT BANG CELLREF` path handles it: quoting is a lexical device for
        # names that are not identifiers (spaces, punctuation, a leading
        # digit), not a different kind of reference. A single quote means
        # nothing else in this grammar -- Excel strings use double quotes --
        # so there is no ambiguity to resolve here.
        if ch == "'":
            j = i + 1
            name: list[str] = []
            while j < n:
                if s[j] == "'":
                    if j + 1 < n and s[j + 1] == "'":
                        name.append("'")
                        j += 2
                        continue
                    break
                name.append(s[j])
                j += 1
            else:
                raise FormulaError(f"unterminated sheet name at {pos}")
            quoted = "".join(name)
            # `'Jan a:Mar b'!` -- a sheet name cannot hold a colon, so this is a span.
            if ":" in quoted and j + 1 < n and s[j + 1] == "!":
                first, _, last = quoted.partition(":")
                tokens.append(Token(SHEETSPAN, (first, last), pos))
                i = j + 2
                continue
            tokens.append(Token(IDENT, quoted, pos))
            i = j + 1
            continue
        # multi-char operators
        if ch == "<" and i + 1 < n and s[i + 1] == "=":
            tokens.append(Token(LE, "<=", pos))
            i += 2
            continue
        if ch == ">" and i + 1 < n and s[i + 1] == "=":
            tokens.append(Token(GE, ">=", pos))
            i += 2
            continue
        if ch == "<" and i + 1 < n and s[i + 1] == ">":
            tokens.append(Token(NE, "<>", pos))
            i += 2
            continue
        # single-char
        kind = _SINGLE.get(ch)
        if kind is not None:
            tokens.append(Token(kind, ch, pos))
            i += 1
            continue
        raise FormulaError(f"unexpected character {ch!r} at {pos}")

    tokens.append(Token(EOF, None, len(text)))
    return tokens
