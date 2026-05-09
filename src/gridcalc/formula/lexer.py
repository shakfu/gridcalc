from __future__ import annotations

import re
from dataclasses import dataclass
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
EOF = "EOF"


@dataclass
class Token:
    kind: str
    value: Any
    pos: int


_CELLREF_RE = re.compile(r"\$?([A-Za-z]+)\$?(\d+)")
_NUMBER_RE = re.compile(r"\d+(\.\d*)?([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ERROR_LIT_RE = re.compile(r"#(?:DIV/0!|N/A|NAME\?|REF!|VALUE!|NUM!|NULL!)", re.IGNORECASE)


def _parse_cellref(text: str) -> tuple[int, int, int, bool, bool] | None:
    m = re.match(r"(\$?)([A-Za-z]+)(\$?)(\d+)", text)
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
        m = _ERROR_LIT_RE.match(s, i)
        if m:
            err = parse_error_literal(m.group(0))
            if err is None:
                raise FormulaError(f"unknown error literal {m.group(0)!r} at {pos}")
            tokens.append(Token(ERROR_LIT, err, pos))
            i = m.end()
            continue
        # cellref (must come before IDENT and NUMBER; handles $A$1 etc.)
        if ch == "$" or ch.isalpha():
            cr = _parse_cellref(s[i:])
            if cr is not None:
                end, col, row, ac, ar = cr
                # Validate it's not followed by an alpha/digit that would extend it
                # (e.g., A1B should NOT be a cellref). Already guaranteed because we
                # match greedy letters then digits; what follows must not be alnum
                # for the cellref to be standalone. Also: a cellref-shaped token
                # followed by `!` is actually a sheet name (e.g. `Sheet1!A1`),
                # so emit an IDENT instead and let the parser handle the prefix.
                next_idx = i + end
                if next_idx < n and (s[next_idx].isalnum() or s[next_idx] == "_"):
                    cr = None  # fall through to IDENT
                elif next_idx < n and s[next_idx] == "!":
                    cr = None  # sheet prefix; let IDENT branch consume it
                else:
                    tokens.append(Token(CELLREF, (col, row, ac, ar), pos))
                    i += end
                    continue
        # identifier (function name, named range, bool, py keyword)
        if ch.isalpha() or ch == "_":
            m2 = _IDENT_RE.match(s, i)
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
        if ch.isdigit() or (ch == "." and i + 1 < n and s[i + 1].isdigit()):
            m3 = _NUMBER_RE.match(s, i)
            if m3 is None:
                raise FormulaError(f"invalid number at {pos}")
            tokens.append(Token(NUMBER, float(m3.group(0)), pos))
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
        single = {
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
        }
        kind = single.get(ch)
        if kind is not None:
            tokens.append(Token(kind, ch, pos))
            i += 1
            continue
        raise FormulaError(f"unexpected character {ch!r} at {pos}")

    tokens.append(Token(EOF, None, len(text)))
    return tokens
