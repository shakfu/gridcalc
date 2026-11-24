"""Data items and sheet models in an xlsx, as a custom XML part.

SolverStudio keeps its models the same way. Excel keeps a custom XML part it
does not understand when it saves the workbook, so the models survive a round
trip through Excel. The part holds one JSON document:

    {"data_items": {name: DataItem JSON}, "models": {sheet: {"lang", "text"}}}

Design: ``docs/dev/crosstab-model.md``.
"""

from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

NS = "urn:gridcalc:models:1"
_TAG = f"{{{NS}}}gridcalc"
_REL_CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
_REL_PROPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
_PROPS_TYPE = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/customXml"


def payload(data_items: dict[str, Any], models: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    """The JSON the part holds, or None when there is nothing to keep."""
    if not data_items and not models:
        return None
    return {
        "data_items": {n: it.to_json() for n, it in data_items.items()},
        "models": models,
    }


def _part_xml(doc: dict[str, Any]) -> bytes:
    root = ET.Element(_TAG)
    root.text = json.dumps(doc)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(root)


def _props_xml() -> bytes:
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<ds:datastoreItem ds:itemID="{guid}" xmlns:ds="{_DS_NS}">'
        f'<ds:schemaRefs><ds:schemaRef ds:uri="{NS}"/></ds:schemaRefs>'
        "</ds:datastoreItem>"
    ).encode()


def add_part(members: list[tuple[Any, bytes]], doc: dict[str, Any]) -> list[tuple[Any, bytes]]:
    """``members`` (an xlsx's parts) with the custom XML part for ``doc`` added."""
    out = list(members)
    names = {info.filename for info, _ in out}
    n = 1
    while f"customXml/item{n}.xml" in names:
        n += 1
    by_name = {info.filename: i for i, (info, _) in enumerate(out)}
    rels_at, types_at = by_name["xl/_rels/workbook.xml.rels"], by_name["[Content_Types].xml"]
    rels, types = out[rels_at][1], out[types_at][1]
    rid = max((int(m) for m in re.findall(rb'Id="rId(\d+)"', rels)), default=0) + 1
    rel = f'<Relationship Id="rId{rid}" Type="{_REL_CUSTOM}" Target="../customXml/item{n}.xml"/>'
    rels = rels.replace(b"</Relationships>", rel.encode() + b"</Relationships>", 1)
    override = f'<Override PartName="/customXml/itemProps{n}.xml" ContentType="{_PROPS_TYPE}"/>'
    types = types.replace(b"</Types>", override.encode() + b"</Types>", 1)
    if b'Extension="xml"' not in types:
        default = b'<Default Extension="xml" ContentType="application/xml"/>'
        types = types.replace(b"</Types>", default + b"</Types>", 1)
    out[rels_at] = (out[rels_at][0], rels)
    out[types_at] = (out[types_at][0], types)
    item_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_PKG_REL_NS[1:-1]}">'
        f'<Relationship Id="rId1" Type="{_REL_PROPS}" Target="itemProps{n}.xml"/>'
        "</Relationships>"
    ).encode()
    out.append((zipfile.ZipInfo(f"customXml/item{n}.xml"), _part_xml(doc)))
    out.append((zipfile.ZipInfo(f"customXml/itemProps{n}.xml"), _props_xml()))
    out.append((zipfile.ZipInfo(f"customXml/_rels/item{n}.xml.rels"), item_rels))
    return out


def read(z: zipfile.ZipFile) -> dict[str, Any] | None:
    """The gridcalc part's JSON from an open xlsx, or None. Never raises.

    Untrusted input: the caller checks each field before use.
    """
    try:
        for name in z.namelist():
            if not re.fullmatch(r"customXml/item\d+\.xml", name):
                continue
            data = z.read(name)
            if NS.encode() not in data:
                continue
            root = ET.fromstring(data)  # noqa: S314  (ElementTree resolves no external entities)
            if root.tag != _TAG or not root.text:
                continue
            doc = json.loads(root.text)
            return doc if isinstance(doc, dict) else None
    except (KeyError, OSError, ValueError, ET.ParseError, zipfile.BadZipFile, RecursionError):
        return None
    return None


def read_file(path: str) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path) as z:
            return read(z)
    except (OSError, zipfile.BadZipFile):
        return None


def model_texts(doc: dict[str, Any] | None) -> dict[str, tuple[str, str]]:
    """Each sheet's ``(lang, text)`` from a read part, skipping malformed entries.

    For the trust prompt; loading reads the full entry with `Sheet.load_model`."""
    models = doc.get("models") if isinstance(doc, dict) else None
    out: dict[str, tuple[str, str]] = {}
    if not isinstance(models, dict):
        return out
    for sheet, m in models.items():
        if isinstance(sheet, str) and isinstance(m, dict) and isinstance(m.get("text"), str):
            lang = m.get("lang", "pulp")
            out[sheet] = (lang if isinstance(lang, str) else "pulp", m["text"])
    return out
