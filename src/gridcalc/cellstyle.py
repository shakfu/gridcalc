"""Cell styles beyond bold, italic, underline and number format.

`XStyle` holds what an xlsx cell format carries and gridcalc has no other
field for: font face, size, colour and strikethrough, a solid fill, borders,
alignment other than plain left or right, wrapping, indent and rotation.
It is immutable, so cells share one instance and a copy is a reference.
Colours are ``RRGGBB`` hex; theme colours are resolved on import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from typing import Any

BORDER_STYLES = frozenset(
    {
        "thin",
        "medium",
        "thick",
        "dashed",
        "dotted",
        "double",
        "hair",
        "mediumDashed",
        "dashDot",
        "mediumDashDot",
        "dashDotDot",
        "mediumDashDotDot",
        "slantDashDot",
    }
)
HALIGN = frozenset(
    {"left", "right", "center", "centerContinuous", "justify", "fill", "distributed"}
)
VALIGN = frozenset({"top", "center", "justify", "distributed"})
SIDES = ("left", "right", "top", "bottom")

_HEX = re.compile(r"[0-9A-F]{6}")


@dataclass(frozen=True, slots=True)
class Side:
    style: str
    color: str | None = None


@dataclass(frozen=True, slots=True)
class XStyle:
    font: str | None = None
    size: float | None = None
    color: str | None = None
    strike: bool = False
    fill: str | None = None
    left: Side | None = None
    right: Side | None = None
    top: Side | None = None
    bottom: Side | None = None
    halign: str | None = None
    valign: str | None = None  # None is Excel's default, bottom
    wrap: bool = False
    indent: int = 0
    rotation: int = 0  # degrees, 0-180, or 255 for stacked text

    def __bool__(self) -> bool:
        return self != _EMPTY

    def with_(self, **changes: Any) -> XStyle:
        return replace(self, **changes)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if v == f.default:
                continue
            out[f.name] = {"style": v.style, "color": v.color} if isinstance(v, Side) else v
        return out

    @classmethod
    def from_json(cls, d: Any) -> XStyle | None:
        """An `XStyle` from ``d``, or None when ``d`` is not a valid one.

        ``d`` comes from a file, so every field is checked; an invalid field
        is dropped rather than failing the load.
        """
        if not isinstance(d, dict):
            return None
        kw: dict[str, Any] = {}
        for name in ("font",):
            if isinstance(d.get(name), str) and 0 < len(d[name]) <= 31:
                kw[name] = d[name]
        size = d.get("size")
        if isinstance(size, (int, float)) and not isinstance(size, bool) and 1 <= size <= 409:
            kw["size"] = float(size)
        for name in ("color", "fill"):
            c = color(d.get(name))
            if c:
                kw[name] = c
        for name in ("strike", "wrap"):
            if d.get(name) is True:
                kw[name] = True
        for name in SIDES:
            s = d.get(name)
            if isinstance(s, dict) and s.get("style") in BORDER_STYLES:
                kw[name] = Side(s["style"], color(s.get("color")))
        if d.get("halign") in HALIGN:
            kw["halign"] = d["halign"]
        if d.get("valign") in VALIGN:
            kw["valign"] = d["valign"]
        for name, hi in (("indent", 250), ("rotation", 255)):
            v = d.get(name)
            if isinstance(v, int) and not isinstance(v, bool) and 0 < v <= hi:
                kw[name] = v
        style = cls(**kw)
        return style or None


_EMPTY = XStyle()


def color(v: Any) -> str | None:
    """``v`` as ``RRGGBB`` upper-case hex, or None. Accepts ``AARRGGBB``."""
    if not isinstance(v, str):
        return None
    v = v.strip().lstrip("#").upper()
    if len(v) == 8:
        v = v[2:]
    return v if _HEX.fullmatch(v) else None
