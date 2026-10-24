"""Read and write `cellstyle.XStyle` through an xlsx package.

OpenXLSX reads and writes only bold, italic, underline, left/right alignment
and number formats. The rest of a cell format is read here from
``xl/styles.xml``, and written by appending fonts, fills, borders and cell
formats to the styles part OpenXLSX produced, then pointing each cell's
``s`` attribute at them.
"""

from __future__ import annotations

import colorsys
import contextlib
import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import quoteattr

from .cellstyle import BORDER_STYLES, HALIGN, SIDES, VALIGN, Side, XStyle, color

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

# The legacy palette `indexed` colours refer to (ECMA-376 18.8.27).
INDEXED = [
    "000000",
    "FFFFFF",
    "FF0000",
    "00FF00",
    "0000FF",
    "FFFF00",
    "FF00FF",
    "00FFFF",
    "000000",
    "FFFFFF",
    "FF0000",
    "00FF00",
    "0000FF",
    "FFFF00",
    "FF00FF",
    "00FFFF",
    "800000",
    "008000",
    "000080",
    "808000",
    "800080",
    "008080",
    "C0C0C0",
    "808080",
    "9999FF",
    "993366",
    "FFFFCC",
    "CCFFFF",
    "660066",
    "FF8080",
    "0066CC",
    "CCCCFF",
    "000080",
    "FF00FF",
    "FFFF00",
    "00FFFF",
    "800080",
    "800000",
    "008080",
    "0000FF",
    "00CCFF",
    "CCFFFF",
    "CCFFCC",
    "FFFF99",
    "99CCFF",
    "FF99CC",
    "CC99FF",
    "FFCC99",
    "3366FF",
    "33CCCC",
    "99CC00",
    "FFCC00",
    "FF9900",
    "FF6600",
    "666699",
    "969696",
    "003366",
    "339966",
    "003300",
    "333300",
    "993300",
    "993366",
    "333399",
    "333333",
]


# -- reading ------------------------------------------------------------------


def theme_colors(theme_xml: bytes | None) -> list[str]:
    """The theme palette in the order `theme="n"` indexes it.

    The scheme lists dk1, lt1, dk2, lt2, ...; SpreadsheetML swaps each dark
    and light pair, so index 0 is lt1.
    """
    if not theme_xml:
        return []
    try:
        root = ET.fromstring(theme_xml)  # noqa: S314 -- no external entities
    except ET.ParseError:
        return []
    scheme = root.find(f".//{_A}clrScheme")
    if scheme is None:
        return []
    out: list[str] = []
    for el in scheme:
        rgb = el.find(f"{_A}srgbClr")
        sys_ = el.find(f"{_A}sysClr")
        val = (
            rgb.get("val")
            if rgb is not None
            else (sys_.get("lastClr") if sys_ is not None else None)
        )
        out.append(color(val) or "000000")
    if len(out) >= 4:
        out[0], out[1], out[2], out[3] = out[1], out[0], out[3], out[2]
    return out


def _tint(rgb: str, tint: float) -> str:
    r, g, b = (int(rgb[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, min(max(lum, 0.0), 1.0), s)
    return "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def _color(el: ET.Element | None, theme: list[str]) -> str | None:
    if el is None or el.get("auto") in ("1", "true"):
        return None
    out: str | None = None
    if el.get("rgb"):
        out = color(el.get("rgb"))
    elif el.get("theme", "").isdigit() and int(el.get("theme", "")) < len(theme):
        out = theme[int(el.get("theme", ""))]
    elif el.get("indexed", "").isdigit() and int(el.get("indexed", "")) < len(INDEXED):
        out = INDEXED[int(el.get("indexed", ""))]
    tint = el.get("tint")
    if out and tint:
        with contextlib.suppress(ValueError):
            out = _tint(out, float(tint))
    return out


def _font(el: ET.Element, theme: list[str]) -> tuple[str | None, float | None, str | None, bool]:
    name = el.find(f"{NS}name")
    sz = el.find(f"{NS}sz")
    strike = el.find(f"{NS}strike")
    try:
        size = float(sz.get("val", "")) if sz is not None else None
    except ValueError:
        size = None
    return (
        name.get("val") if name is not None else None,
        size,
        _color(el.find(f"{NS}color"), theme),
        strike is not None and strike.get("val", "1") not in ("0", "false"),
    )


def read_styles(styles_xml: bytes | None, theme_xml: bytes | None) -> list[XStyle | None]:
    """One entry per cell format (`cellXfs`), None where it has nothing extra.

    Font face, size and colour count only where they differ from font 0, the
    workbook's default. Never raises.
    """
    if not styles_xml:
        return []
    try:
        root = ET.fromstring(styles_xml)  # noqa: S314 -- no external entities
    except ET.ParseError:
        return []
    theme = theme_colors(theme_xml)
    fonts = [_font(f, theme) for f in root.findall(f"{NS}fonts/{NS}font")]
    base = fonts[0] if fonts else (None, None, None, False)
    fills: list[str | None] = []
    for f in root.findall(f"{NS}fills/{NS}fill"):
        p = f.find(f"{NS}patternFill")
        solid = p is not None and p.get("patternType") == "solid"
        fills.append(_color(p.find(f"{NS}fgColor"), theme) if solid and p is not None else None)
    borders: list[dict[str, Side]] = []
    for b in root.findall(f"{NS}borders/{NS}border"):
        sides: dict[str, Side] = {}
        for name in SIDES:
            el = b.find(f"{NS}{name}")
            if el is None:  # Excel 2007 writes `start` and `end` in some files
                el = b.find(f"{NS}{ {'left': 'start', 'right': 'end'}.get(name, name) }")
            if el is not None and el.get("style") in BORDER_STYLES:
                sides[name] = Side(el.get("style", ""), _color(el.find(f"{NS}color"), theme))
        borders.append(sides)
    out: list[XStyle | None] = []
    for xf in root.findall(f"{NS}cellXfs/{NS}xf"):
        kw: dict[str, Any] = {}
        fi = _index(xf.get("fontId"))
        if fi is not None and fi < len(fonts):
            face, size, col, strike = fonts[fi]
            if face and face != base[0]:
                kw["font"] = face[:31]
            if size and size != base[1] and 1 <= size <= 409:
                kw["size"] = size
            # No colour on the default font is automatic: black.
            if col and col != (base[2] or "000000"):
                kw["color"] = col
            kw["strike"] = strike
        li = _index(xf.get("fillId"))
        if li is not None and li < len(fills) and fills[li]:
            kw["fill"] = fills[li]
        bi = _index(xf.get("borderId"))
        if bi is not None and bi < len(borders):
            kw.update(borders[bi])
        al = xf.find(f"{NS}alignment")
        if al is not None:
            if al.get("horizontal") in HALIGN:
                kw["halign"] = al.get("horizontal")
            if al.get("vertical") in VALIGN:
                kw["valign"] = al.get("vertical")
            kw["wrap"] = al.get("wrapText") in ("1", "true")
            for attr, key, hi in (("indent", "indent", 250), ("textRotation", "rotation", 255)):
                n = _index(al.get(attr))
                if n is not None and 0 < n <= hi:
                    kw[key] = n
        style = XStyle(**kw)
        out.append(style or None)
    return out


def default_font(styles_xml: bytes) -> tuple[str, float] | None:
    """Face and size of font 0, or None when the part has none."""
    try:
        root = ET.fromstring(styles_xml)  # noqa: S314 -- no external entities
    except ET.ParseError:
        return None
    font = root.find(f"{NS}fonts/{NS}font")
    if font is None:
        return None
    name, size, _, _ = _font(font, [])
    if not name or not size or not 0 < len(name) <= 31 or not 1 <= size <= 409:
        return None
    return name, size


def set_default_font(styles_xml: bytes, name: str, size: float) -> bytes:
    """``styles_xml`` with font 0, and every font copied from it, set to
    ``name`` at ``size``. OpenXLSX builds each font from font 0, so its
    other fonts carry the same face and size."""
    root = ET.fromstring(styles_xml)  # noqa: S314 -- OpenXLSX's own output
    base = root.find(f"{NS}fonts/{NS}font")
    if base is None:
        return styles_xml
    old_name, old_size, _, _ = _font(base, [])
    data = styles_xml
    if old_name:
        data = data.replace(
            b"<name val=" + quoteattr(old_name).encode() + b"/>",
            b"<name val=" + quoteattr(name).encode() + b"/>",
        )
        if old_name != name:  # the theme font scheme names Calibri, not ours
            data = re.sub(rb'<scheme val="[^"]*"/>', b"", data)
    if old_size:
        data = data.replace(
            b'<sz val="%s"/>' % f"{old_size:g}".encode(), b'<sz val="%s"/>' % f"{size:g}".encode()
        )
    return data


def _index(v: str | None) -> int | None:
    return int(v) if v is not None and v.isdigit() else None


_CELL_TAG = re.compile(rb'<c r="([A-Z]{1,3})(\d{1,7})"((?: [\w:]+="[^"]*")*)\s*(/?)>')
_S_ATTR = re.compile(rb' s="(\d+)"')


def read_cell_xfs(sheet_xml: bytes) -> dict[tuple[int, int], int]:
    """``(col, row) -> cellXfs index`` for every cell carrying an ``s``."""
    out: dict[tuple[int, int], int] = {}
    for m in _CELL_TAG.finditer(sheet_xml):
        s = _S_ATTR.search(m.group(3))
        if s:
            out[(_col(m.group(1)), int(m.group(2)) - 1)] = int(s.group(1))
    return out


def _col(letters: bytes) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ch - 64
    return n - 1


def _letters(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


# -- writing ------------------------------------------------------------------

_FONT_DROP = ("name", "sz", "color", "strike", "family", "scheme", "charset")


def patch_styles(
    styles_xml: bytes, wanted: set[tuple[int, XStyle]]
) -> tuple[bytes, dict[tuple[int, XStyle], int]]:
    """Add a cell format for each ``(existing xf index, XStyle)`` pair.

    Each new format copies the existing one -- its number format and the
    bold, italic and underline OpenXLSX set -- and adds the style's font,
    fill, border and alignment. Returns the new part and the index of each
    new format.
    """
    root = ET.fromstring(styles_xml)  # noqa: S314 -- OpenXLSX's own output
    fonts = root.findall(f"{NS}fonts/{NS}font")
    xfs = root.findall(f"{NS}cellXfs/{NS}xf")
    n_fonts, n_fills, n_borders, n_xfs = (
        len(fonts),
        len(root.findall(f"{NS}fills/{NS}fill")),
        len(root.findall(f"{NS}borders/{NS}border")),
        len(xfs),
    )
    new_fonts: list[str] = []
    new_fills: list[str] = []
    new_borders: list[str] = []
    new_xfs: list[str] = []
    font_ids: dict[tuple[int, XStyle], int] = {}
    fill_ids: dict[str, int] = {}
    border_ids: dict[tuple[Side | None, ...], int] = {}
    out: dict[tuple[int, XStyle], int] = {}
    for xi, st in sorted(wanted, key=lambda p: (p[0], repr(p[1]))):
        xf = xfs[xi] if xi < len(xfs) else xfs[0]
        attrs = dict(xf.attrib)
        fi = _index(attrs.get("fontId")) or 0
        if st.font or st.size or st.color or st.strike:
            key = (fi, XStyle(font=st.font, size=st.size, color=st.color, strike=st.strike))
            if key not in font_ids:
                font_ids[key] = n_fonts + len(new_fonts)
                new_fonts.append(_font_xml(fonts[fi] if fi < len(fonts) else fonts[0], st))
            attrs["fontId"] = str(font_ids[key])
            attrs["applyFont"] = "1"
        if st.fill:
            if st.fill not in fill_ids:
                fill_ids[st.fill] = n_fills + len(new_fills)
                new_fills.append(
                    f'<fill><patternFill patternType="solid"><fgColor rgb="FF{st.fill}"/>'
                    '<bgColor indexed="64"/></patternFill></fill>'
                )
            attrs["fillId"] = str(fill_ids[st.fill])
            attrs["applyFill"] = "1"
        sides = (st.left, st.right, st.top, st.bottom)
        if any(sides):
            if sides not in border_ids:
                border_ids[sides] = n_borders + len(new_borders)
                new_borders.append(_border_xml(sides))
            attrs["borderId"] = str(border_ids[sides])
            attrs["applyBorder"] = "1"
        align = _align_attrs(xf.find(f"{NS}alignment"), st)
        if align:
            attrs["applyAlignment"] = "1"
        head = "<xf" + "".join(f" {k}={quoteattr(v)}" for k, v in attrs.items()) + ">"
        body = f"<alignment{align}/>" if align else ""
        new_xfs.append(head + body + "</xf>")
        out[(xi, st)] = n_xfs + len(new_xfs) - 1

    data = styles_xml
    for tag, items, count in (
        (b"fonts", new_fonts, n_fonts),
        (b"fills", new_fills, n_fills),
        (b"borders", new_borders, n_borders),
        (b"cellXfs", new_xfs, n_xfs),
    ):
        if items:
            data = _append(data, tag, "".join(items).encode(), count + len(items))
    return data, out


def _append(data: bytes, tag: bytes, items: bytes, count: int) -> bytes:
    close = b"</" + tag + b">"
    if data.count(close) != 1:
        raise ValueError(f"unexpected styles layout at {tag!r}; styles not written")
    data = data.replace(close, items + close)
    pat = rb"<" + tag + rb' count="\d+"'
    return re.sub(pat, b"<" + tag + b' count="%d"' % count, data, count=1)


def _font_xml(base: ET.Element, st: XStyle) -> str:
    keep = []
    for child in base:
        name = child.tag.removeprefix(NS)
        if name in _FONT_DROP and (
            (name == "name" and st.font)
            or (name == "sz" and st.size)
            or (name == "color" and st.color)
            or (name in ("family", "scheme", "charset") and st.font)
            or name == "strike"
        ):
            continue
        attrs = "".join(f" {k}={quoteattr(v)}" for k, v in child.attrib.items())
        keep.append(f"<{name}{attrs}/>")
    if st.strike:
        keep.append("<strike/>")
    if st.size:
        keep.append(f'<sz val="{st.size:g}"/>')
    if st.color:
        keep.append(f'<color rgb="FF{st.color}"/>')
    if st.font:
        keep.append(f"<name val={quoteattr(st.font)}/>")
    return "<font>" + "".join(keep) + "</font>"


def _border_xml(sides: tuple[Side | None, ...]) -> str:
    parts = []
    for name, side in zip(SIDES, sides, strict=True):
        if side is None:
            parts.append(f"<{name}/>")
        else:
            col = f'<color rgb="FF{side.color}"/>' if side.color else '<color indexed="64"/>'
            parts.append(f'<{name} style="{side.style}">{col}</{name}>')
    return "<border>" + "".join(parts) + "<diagonal/></border>"


def _align_attrs(existing: ET.Element | None, st: XStyle) -> str:
    attrs: dict[str, str] = dict(existing.attrib) if existing is not None else {}
    if st.halign:
        attrs["horizontal"] = st.halign
    if st.valign:
        attrs["vertical"] = st.valign
    if st.wrap:
        attrs["wrapText"] = "1"
    if st.indent:
        attrs["indent"] = str(st.indent)
        attrs.setdefault("horizontal", "left")  # Excel ignores an indent without one
    if st.rotation:
        attrs["textRotation"] = str(st.rotation)
    return "".join(f" {k}={quoteattr(v)}" for k, v in attrs.items())


def patch_sheet(sheet_xml: bytes, styles: dict[tuple[int, int], XStyle], xf_of: Any) -> bytes:
    """Point each styled cell in one worksheet part at its new cell format.

    ``xf_of(old_index, style)`` gives the new index. A styled cell the part
    does not hold -- a blank one -- is added to its row, creating the row
    when needed.
    """
    seen: set[tuple[int, int]] = set()

    def restyle(m: re.Match[bytes]) -> bytes:
        pos = (_col(m.group(1)), int(m.group(2)) - 1)
        st = styles.get(pos)
        if st is None:
            return m.group(0)
        seen.add(pos)
        attrs = m.group(3)
        old = _S_ATTR.search(attrs)
        new = xf_of(int(old.group(1)) if old else 0, st)
        attrs = _S_ATTR.sub(b"", attrs) + b' s="%d"' % new
        return b'<c r="' + m.group(1) + m.group(2) + b'"' + attrs + m.group(4) + b">"

    data = _CELL_TAG.sub(restyle, sheet_xml)
    blanks = sorted((p for p in styles if p not in seen), key=lambda p: (p[1], p[0]))
    if not blanks:
        return data
    by_row: dict[int, list[int]] = {}
    for c, r in blanks:
        by_row.setdefault(r, []).append(c)
    return _add_blank_cells(data, by_row, lambda c, r: xf_of(0, styles[(c, r)]))


def _add_blank_cells(data: bytes, by_row: dict[int, list[int]], xf: Any) -> bytes:
    """Insert ``<c r=".." s=".."/>`` cells in column order, adding rows."""
    start = data.find(b"<sheetData")
    end = data.find(b"</sheetData>")
    if start < 0:
        raise ValueError("unexpected worksheet layout; styled blank cells not written")
    if end < 0:  # `<sheetData/>`
        selfclose = data.find(b"/>", start)
        data = data[:selfclose] + b"></sheetData>" + data[selfclose + 2 :]
        end = data.find(b"</sheetData>")
    open_end = data.find(b">", start) + 1
    body = data[open_end:end]
    rows: dict[int, bytes] = {}
    order: list[int] = []
    for m in re.finditer(rb'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', body, re.S):
        r = int(m.group(1)) - 1
        rows[r] = m.group(0)
        order.append(r)
    for r, cols in by_row.items():
        if not cols and r in rows:
            continue  # the row exists; nothing to add
        cells = b"".join(
            b'<c r="%s%d" s="%d"/>' % (_letters(c).encode(), r + 1, xf(c, r)) for c in cols
        )
        if r not in rows:
            rows[r] = b'<row r="%d">' % (r + 1) + cells + b"</row>"
            order.append(r)
            continue
        row = re.sub(rb' spans="[^"]*"', b"", rows[r], count=1)
        if row.endswith(b"/>"):
            row = row[:-2] + b"></row>"
        # Merge by column: split the row's cells, add ours, rejoin in order.
        head_end = row.find(b">") + 1
        existing = re.findall(rb'<c r="[A-Z]+\d+".*?(?:/>|</c>)', row[head_end:-6], re.S)
        new = re.findall(rb"<c [^>]*/>", cells)

        def col_of(cell: bytes) -> int:
            m = re.match(rb'<c r="([A-Z]+)', cell)
            return _col(m.group(1)) if m else 0

        merged = sorted(existing + new, key=col_of)
        rows[r] = row[:head_end] + b"".join(merged) + b"</row>"
    body = b"".join(rows[r] for r in sorted(order))
    return data[:open_end] + body + data[end:]


# -- merged cells and row heights ---------------------------------------------

_MERGE = re.compile(rb'<mergeCell ref="([A-Z]{1,3})(\d{1,7}):([A-Z]{1,3})(\d{1,7})"\s*/>')
_ROW_HEAD = re.compile(rb"<row\b([^>]*?)(/?)>")
_ATTR = re.compile(rb'([\w:]+)="([^"]*)"')


def read_layout(sheet_xml: bytes) -> tuple[list[tuple[int, int, int, int]], dict[int, float]]:
    """A worksheet part's merged ranges and custom row heights (points)."""
    merges = []
    for m in _MERGE.finditer(sheet_xml):
        c1, r1 = _col(m.group(1)), int(m.group(2)) - 1
        c2, r2 = _col(m.group(3)), int(m.group(4)) - 1
        merges.append((min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)))
    heights: dict[int, float] = {}
    for m in _ROW_HEAD.finditer(sheet_xml):
        attrs = dict(_ATTR.findall(m.group(1)))
        if attrs.get(b"customHeight") not in (b"1", b"true") or b"r" not in attrs:
            continue
        try:
            r, ht = int(attrs[b"r"]) - 1, float(attrs.get(b"ht", b""))
        except ValueError:
            continue
        if 0 <= ht <= 409:
            heights[r] = ht
    return merges, heights


def patch_layout(
    sheet_xml: bytes, merges: list[tuple[int, int, int, int]], heights: dict[int, float]
) -> bytes:
    """Write merged ranges and custom row heights into one worksheet part."""
    data = sheet_xml
    if heights:
        data = _add_blank_cells(data, {r: [] for r in heights}, lambda c, r: 0)

        def height(m: re.Match[bytes]) -> bytes:
            attrs = m.group(1)
            rm = re.search(rb' r="(\d+)"', attrs)
            row = int(rm.group(1)) - 1 if rm else -1
            if row not in heights:
                return m.group(0)
            attrs = re.sub(rb' (?:ht|customHeight)="[^"]*"', b"", attrs)
            ht = f' ht="{heights[row]:g}" customHeight="1"'.encode()
            return b"<row" + attrs + ht + m.group(2) + b">"

        data = _ROW_HEAD.sub(height, data)
    if merges:
        if data.count(b"</sheetData>") != 1 or b"<mergeCells" in data:
            raise ValueError("unexpected worksheet layout; merged cells not written")
        refs = "".join(
            f'<mergeCell ref="{_letters(c1)}{r1 + 1}:{_letters(c2)}{r2 + 1}"/>'
            for c1, r1, c2, r2 in merges
        )
        xml = f'<mergeCells count="{len(merges)}">{refs}</mergeCells>'.encode()
        data = data.replace(b"</sheetData>", b"</sheetData>" + xml)
    return data
