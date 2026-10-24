"""Excel number-format codes: `"$"#,##0.00`, `0.00_);[Red](0.00)`, `# ?/?`.

Renders a value through a code as Excel's cell display and `TEXT` do. Up to
four `;` sections apply to positive, negative, zero and text values, or to
values meeting a `[>=1000]` condition. A section's colour (`[Red]`) is
returned beside the text, not inside it. Date and time sections go to
`dates.format_serial`.

Not modelled: locale codes beyond the currency symbol of `[$€-2]`, and the
column width a `*` fill would pad to (it is dropped).
"""

from __future__ import annotations

import math
import operator
import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import NamedTuple

from .dates import format_serial, is_date_format

COLORS = frozenset({"black", "blue", "cyan", "green", "magenta", "red", "white", "yellow"})

_CONDITION_RE = re.compile(r"\[(<=|>=|<>|<|>|=)\s*(-?[\d.]+(?:[eE][+-]?\d+)?)\]")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "=": operator.eq,
    "<>": operator.ne,
}


class Formatted(NamedTuple):
    text: str | None  # None: the value cannot be shown so (TEXT gives #VALUE!)
    color: str | None  # a name from COLORS, `colorN`, or None


class _Section(NamedTuple):
    body: str  # the code without its brackets
    color: str | None
    condition: tuple[str, float] | None


def split_sections(code: str) -> list[str]:
    """``code`` split on `;` outside quotes, brackets and escapes."""
    out: list[str] = []
    cur: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch == '"':
            j = code.find('"', i + 1)
            j = n - 1 if j < 0 else j
            cur.append(code[i : j + 1])
            i = j + 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(code[i : i + 2])
            i += 2
            continue
        if ch == "[":
            j = code.find("]", i + 1)
            j = n - 1 if j < 0 else j
            cur.append(code[i : j + 1])
            i = j + 1
            continue
        if ch == ";":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _section(raw: str) -> _Section:
    color: str | None = None
    condition: tuple[str, float] | None = None
    keep: list[str] = []
    pos = 0
    for m in _BRACKET_RE.finditer(raw):
        keep.append(raw[pos : m.start()])
        pos = m.end()
        inner = m.group()[1:-1]
        low = inner.lower()
        cond = _CONDITION_RE.fullmatch(m.group())
        if cond:
            condition = (cond.group(1), float(cond.group(2)))
        elif low in COLORS or re.fullmatch(r"color\d{1,2}", low):
            color = low
        elif inner.startswith("$"):
            # `[$€-2]`: a currency symbol and a locale; keep the symbol.
            sym = inner[1:].split("-")[0]
            keep.append('"' + sym.replace('"', "") + '"' if sym else "")
        else:
            keep.append(m.group())  # `[h]` elapsed time stays for the date path
    keep.append(raw[pos:])
    return _Section("".join(keep), color, condition)


def _pick(sections: list[_Section], v: float) -> tuple[_Section, bool]:
    """The section for number ``v``, and whether it shows its own sign."""
    numeric = sections[:3]
    if any(s.condition for s in numeric):
        for s in numeric:
            if s.condition and _OPS[s.condition[0]](v, s.condition[1]):
                return s, False
        rest = [s for s in numeric if s.condition is None]
        return (rest[0] if rest else numeric[-1]), False
    if v < 0 and len(numeric) >= 2:
        return numeric[1], True
    if v == 0 and len(numeric) >= 3:
        return numeric[2], False
    return numeric[0], False


def format_value(
    value: float | str, code: str, general: Callable[[float], str] = repr
) -> Formatted:
    """``value`` rendered through Excel number-format ``code``.

    ``general`` renders a number for the `General` format, by the caller's
    own number-to-text rule.
    """
    sections = [_section(s) for s in split_sections(code)]
    if isinstance(value, str):
        if len(sections) >= 4:
            sec = sections[3]
        elif "@" in sections[0].body:
            sec = sections[0]
        else:
            return Formatted(value, None)
        return Formatted(_literal_render(sec.body, value), sec.color)
    sec, own_sign = _pick(sections, value)
    body = sec.body
    v = abs(value) if own_sign else value
    if body.strip().lower() in ("", "general"):
        text = general(v)
        if body.strip() == "" and len(sections) > 1:
            text = ""  # an empty section hides the value
        return Formatted(text, sec.color)
    if _ELAPSED_RE.search(body):
        return Formatted(_render_elapsed(v, body), sec.color)
    if is_date_format(body):
        if _DIGIT_IN_DATE_RE.search(_NOISE_RE.sub("", body)):
            return Formatted(None, sec.color)  # `mm###` mixes date and digit codes
        return Formatted(format_serial(v, body), sec.color)
    if _DATE_LETTER_RE.search(_NOISE_RE.sub("", body)):
        return Formatted(None, sec.color)
    return Formatted(_render_number(v, body), sec.color)


_NOISE_RE = re.compile(r'"[^"]*"|\\.|_.|\*.')
_ELAPSED_RE = re.compile(r"\[(h+|m+|s+)\]", re.IGNORECASE)
# A digit placeholder in a date code, except the `.000` of fractional seconds.
_DIGIT_IN_DATE_RE = re.compile(r"[#?]|(?<![.0])0")
# A date or time letter in a numeric code: `mm###` is not a format Excel takes.
_DATE_LETTER_RE = re.compile(r"[ymdhsYMDHS]")


def _render_elapsed(v: float, body: str) -> str | None:
    """`[h]:mm:ss`, `[m]:ss.00`, `[s]`: elapsed time, the bracketed unit
    unbounded. A negative value is allowed only for a code of one bracket."""
    toks = re.findall(r'\[(?:h+|m+|s+)\]|"[^"]*"|\\.|\.0+|h+|m+|s+|.', body, re.IGNORECASE)
    units = [t for t in toks if t[0] in "[hHmMsS"]
    if v < 0 and len(units) > 1:
        return None
    dec = next((len(t) - 1 for t in toks if t.startswith(".0")), 0)
    sign = "-" if v < 0 else ""
    total = round(abs(v) * 86400 * 10**dec) / 10**dec  # seconds, rounded as shown
    whole = int(total)
    out: list[str] = []
    seen_big = None
    for t in toks:
        low = t.lower()
        if low.startswith("["):
            unit, width = low[1], len(low) - 2
            n = whole // {"h": 3600, "m": 60, "s": 1}[unit]
            seen_big = unit
            out.append(f"{n:0{width}d}")
        elif low[0] in "hms" and t[0].isalpha():
            if low[0] == "h":
                n = whole // 3600 % 24
            elif low[0] == "m":
                n = whole // 60 % 60 if seen_big != "m" else whole // 60
            else:
                n = whole % 60
            out.append(f"{n:0{len(low)}d}" if len(low) > 1 else str(n))
        elif t.startswith(".0"):
            frac = round(total - whole, dec)
            out.append("." + f"{frac:.{dec}f}".split(".")[1])
        elif t.startswith('"'):
            out.append(t[1:-1])
        elif t.startswith("\\"):
            out.append(t[1:])
        else:
            out.append(t)
    return sign + "".join(out)


# -- tokenising a numeric section --------------------------------------------


def _tokens(body: str) -> list[tuple[str, str]]:
    """``(kind, text)``: `d` a digit placeholder, `.`, `,`, `%`, `E` an
    exponent marker with its sign, `/`, `@`, or `lit` literal text."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch == '"':
            j = body.find('"', i + 1)
            j = n if j < 0 else j
            out.append(("lit", body[i + 1 : j]))
            i = j + 1
        elif ch == "\\" and i + 1 < n:
            out.append(("lit", body[i + 1]))
            i += 2
        elif ch == "_" and i + 1 < n:
            out.append(("lit", " "))  # space as wide as the next character
            i += 2
        elif ch == "*" and i + 1 < n:
            i += 2  # repeat-fill to the column width: not modelled
        elif ch in "0#?":
            out.append(("d", ch))
            i += 1
        elif ch in "eE" and i + 1 < n and body[i + 1] in "+-":
            out.append(("E", body[i + 1]))
            i += 2
        elif ch in ".,%/@":
            out.append((ch, ch))
            i += 1
        else:
            out.append(("lit", ch))
            i += 1
    return out


def _round(x: float, places: int) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _int_digits(placeholders: list[str], digits: str, group: bool) -> list[str]:
    """Integer placeholders filled right to left; extra digits go in front.
    Returns one string per placeholder, so literals can sit between them."""
    out = [""] * len(placeholders)
    count = 0  # digits emitted, for grouping

    def emit(ch: str) -> str:
        nonlocal count
        sep = "," if group and count and count % 3 == 0 and ch.isdigit() else ""
        if ch.isdigit():
            count += 1
        return ch + sep

    k = len(digits)
    for idx in range(len(placeholders) - 1, -1, -1):
        p = placeholders[idx]
        if k > 0:
            k -= 1
            out[idx] = emit(digits[k])
        else:
            out[idx] = emit("0") if p == "0" else (" " if p == "?" else "")
    if k > 0:
        lead = ""
        for ch in reversed(digits[:k]):
            lead = emit(ch) + lead
        if out:
            out[0] = lead + out[0]
        else:
            out = [lead]  # `.00`: the integer digits still show
    return out


def _frac_digits(placeholders: list[str], digits: str) -> list[str]:
    out = list(digits)
    for idx in range(len(placeholders) - 1, -1, -1):
        if out[idx] != "0" or placeholders[idx] == "0":
            break
        out[idx] = " " if placeholders[idx] == "?" else ""
    return out


def _render_number(v: float, body: str) -> str:
    toks = _tokens(body)
    neg = v < 0
    if not any(k == "d" for k, _ in toks):
        # No digit placeholder: the code is all literal, `TEXT(3,1)` is "1".
        return ("" if v == 0 else "-" if neg else "") + _literal_render(body, "")
    v = abs(v)
    if any(k == "/" for k, _ in toks) and any(k == "d" for k, _ in toks):
        return ("-" if neg else "") + _render_fraction(v, toks)
    # Commas right after the last digit placeholder scale by 1000 each; one
    # between integer placeholders groups thousands.
    first_point = next((i for i, (k, _) in enumerate(toks) if k in (".", "E")), len(toks))
    int_end = max((i for i, (k, _) in enumerate(toks[:first_point]) if k == "d"), default=-1)
    mant = next((i for i, (k, _) in enumerate(toks) if k == "E"), len(toks))
    last_d = max((i for i, (k, _) in enumerate(toks[:mant]) if k == "d"), default=-1)
    scale = 0
    j = last_d + 1
    while j < len(toks) and toks[j][0] == ",":
        scale += 1
        j += 1
    group = int_end >= 0 and any(k == "," for k, _ in toks[:int_end])
    v = v * 100 ** sum(k == "%" for k, _ in toks) / 1000**scale
    scaling = set(range(last_d + 1, j))

    def comma(i: int) -> tuple[str, str] | None:
        if i < int_end and group:
            return None  # grouping, applied to the integer digits
        if i in scaling or i < first_point:
            return None
        return ("lit", ",")  # in the fraction: a literal comma

    kept = [t if t[0] != "," else comma(i) for i, t in enumerate(toks)]
    toks = [t for t in kept if t is not None]

    exp_at = next((i for i, (k, _) in enumerate(toks) if k == "E"), None)
    point_at = next((i for i, (k, _) in enumerate(toks) if k == "."), None)
    mant_end = exp_at if exp_at is not None else len(toks)
    int_end_at = mant_end if point_at is None else point_at
    int_ph = [t for i, (k, t) in enumerate(toks) if k == "d" and i < int_end_at]
    frac_ph = (
        [t for i, (k, t) in enumerate(toks) if k == "d" and point_at < i < mant_end]
        if point_at is not None
        else []
    )
    exponent = 0
    if exp_at is not None and v != 0:
        step = len(int_ph) if int_ph and int_ph[0] == "#" and len(int_ph) > 1 else 1
        lead = max(1, sum(p == "0" for p in int_ph)) if step == 1 else 1
        exponent = math.floor(math.log10(v)) - (lead - 1)
        exponent -= exponent % step
        v = v / 10**exponent
        if _round(v, len(frac_ph)) >= 10 ** (lead if step == 1 else step):
            exponent += step
            v /= 10**step
    q = _round(v, len(frac_ph))
    whole, _, frac = f"{q:f}".partition(".")
    whole = "" if whole == "0" else whole
    ints = _int_digits(int_ph, whole, group)
    fracs = _frac_digits(frac_ph, frac.ljust(len(frac_ph), "0")[: len(frac_ph)])

    out: list[str] = ["-"] if neg and q != 0 else []
    ii = fi = 0
    for i, (k, t) in enumerate(toks[:mant_end]):
        if k == "d":
            if point_at is None or i < point_at:
                out.append(ints[ii])
                ii += 1
            else:
                out.append(fracs[fi])
                fi += 1
        elif k == "." and not int_ph:
            out.append(ints[0] + t if ints else t)
        elif k in ("lit", ".", "%", "@", "/"):
            out.append(t)
    if exp_at is not None:
        sign = "-" if exponent < 0 else ("+" if toks[exp_at][1] == "+" else "")
        exp_ph = [t for k, t in toks[exp_at + 1 :] if k == "d"]
        out.append("E" + sign + "".join(_int_digits(exp_ph, str(abs(exponent)), False)))
        out.extend(t for k, t in toks[exp_at + 1 :] if k == "lit")
    return "".join(out)


def _render_fraction(v: float, toks: list[tuple[str, str]]) -> str:
    """`# ?/?`, `?/4`, `# ??/100`: an optional whole part, then a fraction."""
    slash = next(i for i, (k, _) in enumerate(toks) if k == "/")
    # The numerator is the run of placeholders just before the slash.
    num_start = slash
    while num_start > 0 and toks[num_start - 1][0] == "d":
        num_start -= 1
    whole_ph = [t for k, t in toks[:num_start] if k == "d"]
    num_ph = [t for _, t in toks[num_start:slash]]
    den_toks = toks[slash + 1 :]
    # A denominator starting with 1-9 is a fixed number (`/100`); else placeholders.
    fixed = bool(den_toks) and den_toks[0][0] == "lit" and den_toks[0][1] in "123456789"
    den_text = ""
    for k, t in den_toks:
        if not (t.isdigit() and (fixed or k == "d")):
            break
        den_text += t
    den_ph = [] if fixed else [t for k, t in den_toks if k == "d"]
    whole = int(v) if whole_ph else 0
    rest = v - whole
    if fixed:
        den = int(den_text)
        num = int(_round(rest * den, 0))
    else:
        f = Fraction(rest).limit_denominator(10 ** max(1, len(den_ph)) - 1)
        num, den = f.numerator, f.denominator
    if whole_ph and num == den:
        whole, num = whole + 1, 0
    out: list[str] = []
    for k, t in toks[:num_start]:
        if k == "lit":
            out.append(t)
    if whole_ph:
        w = "".join(_int_digits(whole_ph, str(whole) if whole else "", False))
        out.insert(0, w)
    if num == 0 and whole_ph:
        width = len(num_ph) + 1 + (len(den_ph) or len(den_text))
        return "".join(out).rstrip() + " " * (width + 1) if whole else "0"
    out.append("".join(_int_digits(num_ph, str(num), False)).strip() or "0")
    out.append("/")
    out.append(str(den) if fixed else str(den).ljust(len(den_ph)))
    return "".join(out)


def _literal_render(body: str, text: str) -> str:
    out: list[str] = []
    for k, t in _tokens(body):
        if k == "@":
            out.append(text)
        elif k in ("lit", ".", ",", "%", "/"):
            out.append(t)
    return "".join(out)
