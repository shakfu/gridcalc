"""Formulas that read another workbook through the values the xlsx cached for it."""

import json
import re
import zipfile

import pytest

openpyxl = pytest.importorskip("openpyxl")

from gridcalc.engine import Grid, Mode, NamedRange  # noqa: E402
from gridcalc.formula.errors import ExcelError  # noqa: E402
from gridcalc.loader import save_losses  # noqa: E402

_LINK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<externalBook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' r:id="rId1"><sheetNames><sheetName val="Data"/><sheetName val="Empty"/>'
    '<sheetName val="My Sheet"/></sheetNames><sheetDataSet>'
    '<sheetData sheetId="0"><row r="1"><cell r="A1"><v>21</v></cell>'
    '<cell r="B1" t="str"><v>"quoted"</v></cell></row>'
    '<row r="2"><cell r="A2"><v>4</v></cell><cell r="B2" t="e"><v>#N/A</v></cell></row>'
    '<row r="3"><cell r="A3" t="b"><v>1</v></cell></row></sheetData>'
    '<sheetData sheetId="1" refreshError="1"/>'
    '<sheetData sheetId="2"><row r="5"><cell r="C5"><v>7</v></cell></row></sheetData>'
    "</sheetDataSet></externalBook></externalLink>"
)
_LINK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/externalLinkPath" Target="other.xlsx" TargetMode="External"/></Relationships>'
)


def _linked_book(tmp_path, formulas, saved, inputs=None, link=_LINK, links=1):
    """An xlsx whose formulas link to `[1]`, with Excel's saved values and a link cache."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for a, v in {**(inputs or {}), **formulas}.items():
        ws[a] = v
    src = tmp_path / "linked.xlsx"
    wb.save(str(src))
    with zipfile.ZipFile(src) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    sheet = "xl/worksheets/sheet1.xml"
    for a, v in saved.items():
        parts[sheet] = re.sub(
            rf'(<c r="{a}"[^>]*>\s*<f>[^<]*</f>)\s*(<v\s*/>|<v></v>)?'.encode(),
            rf"\1<v>{v}</v>".encode(),
            parts[sheet],
        )
    if link is not None:
        refs = b""
        for n in range(1, links + 1):
            target = f"externalLinks/externalLink{n}.xml"
            parts[f"xl/{target}"] = link.encode()
            parts[f"xl/externalLinks/_rels/externalLink{n}.xml.rels"] = _LINK_RELS.encode()
            rels = "xl/_rels/workbook.xml.rels"
            parts[rels] = parts[rels].replace(
                b"</Relationships>",
                f'<Relationship Id="rId9{n}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/externalLink" Target="{target}"/>'
                f"</Relationships>".encode(),
            )
            ct = "[Content_Types].xml"
            parts[ct] = parts[ct].replace(
                b"</Types>",
                f'<Override PartName="/xl/{target}" ContentType="application/vnd.openxmlformats-'
                f'officedocument.spreadsheetml.externalLink+xml"/></Types>'.encode(),
            )
            refs += f'<externalReference r:id="rId9{n}"/>'.encode()
        book = "xl/workbook.xml"
        parts[book] = parts[book].replace(
            b"</sheets>",
            b'</sheets><externalReferences xmlns:r="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships">' + refs + b"</externalReferences>",
        )
    with zipfile.ZipFile(src, "w") as z:
        for k, v in parts.items():
            z.writestr(k, v)
    g = Grid()
    assert g.xlsxload(str(src)) == 0
    return g, src


def test_a_link_formula_recalculates_from_the_cache(tmp_path):
    g, _ = _linked_book(tmp_path, {"B1": "=[1]Data!A1*A1"}, {"B1": 42}, {"A1": 2})
    assert (g.cell(1, 0).val, g.cell(1, 0).err) == (42.0, None)
    g.setcell(0, 0, "3")
    assert g.cell(1, 0).val == 63.0  # frozen, it stayed 42


def test_cached_values_keep_their_type(tmp_path):
    formulas = {
        "A1": "=[1]Data!B1",
        "A2": "=ISNA([1]Data!B2)",
        "A3": "=[1]Data!A3",
        "A4": "=SUM([1]Data!A:A)",
        "A5": "=ISBLANK([1]Data!D9)",
        "A6": "='[1]My Sheet'!C5+1",
    }
    saved = {"A1": '"quoted"', "A2": 1, "A3": 1, "A4": 25, "A5": 1, "A6": 8}
    g, _ = _linked_book(tmp_path, formulas, saved)
    assert g.cell(0, 0).sval == '"quoted"'
    assert [g.cell(0, r).val for r in range(1, 6)] == [True, True, 25.0, True, 8.0]
    assert all(g.cell(0, r).cached is None for r in range(6))  # all live


def test_a_cached_error_reads_as_that_error(tmp_path):
    g, _ = _linked_book(tmp_path, {"A1": "=[1]Data!B2"}, {"A1": "#N/A"})
    assert g.cell(0, 0).err is ExcelError.NA


@pytest.mark.parametrize(
    "formula",
    [
        "=[1]Empty!A1+1",  # Excel cached nothing for that sheet
        "=[1]Gone!A1+1",  # not a sheet of the link
        "=[2]Data!A1+1",  # no second link
        "=SUM(OFFSET([1]Data!A1,0,0,2,1))+1",  # can reach past the cache
    ],
)
def test_a_link_the_cache_cannot_answer_keeps_excels_value(tmp_path, formula):
    g, _ = _linked_book(tmp_path, {"A1": formula, "B1": "=A1*2"}, {"A1": 99})
    cl = g.cell(0, 0)
    assert (cl.val, cl.err, cl.cached) == (99.0, None, 99.0)
    assert g.cell(1, 0).val == 198.0


def test_no_link_part_keeps_excels_value(tmp_path):
    g, _ = _linked_book(tmp_path, {"A1": "=[1]Data!A1+1"}, {"A1": 5}, link=None)
    assert (g.cell(0, 0).val, g.cell(0, 0).cached) == (5.0, 5.0)


def test_link_sheets_stay_out_of_the_workbook(tmp_path):
    g, _ = _linked_book(tmp_path, {"A1": "=[1]Data!A1"}, {"A1": 21})
    assert [s.name for s in g.sheets] == ["Sheet"]
    assert sorted(g.links) == ["[1]data", "[1]my sheet"]  # `Empty` cached nothing


def test_json_keeps_the_cache_so_links_stay_live(tmp_path):
    g, _ = _linked_book(tmp_path, {"B1": "=[1]Data!A1*A1"}, {"B1": 42}, {"A1": 2})
    j = tmp_path / "linked.json"
    assert g.jsonsave(str(j)) == 0
    h = Grid()
    assert h.jsonload(str(j)) == 0
    assert h.cell(1, 0).val == 42.0
    h.setcell(0, 0, "3")
    assert h.cell(1, 0).val == 63.0


def test_json_drops_malformed_link_entries(tmp_path):
    j = tmp_path / "bad.json"
    links = {
        "[1]Data": {"A1": 5, "nope": 1, "B1": {"x": 1}},
        "Data": {"A1": 1},  # not a link sheet name
        "[2]X": [1, 2],
    }
    doc = {"version": 2, "mode": "EXCEL", "sheets": [{"name": "S", "cells": []}], "links": links}
    j.write_text(json.dumps(doc))
    g = Grid()
    assert g.jsonload(str(j)) == 0
    assert list(g.links) == ["[1]data"]
    assert list(g.links["[1]data"]._cells) == [(0, 0)]


def test_an_xlsx_save_keeps_the_links(tmp_path):
    g, src = _linked_book(tmp_path, {"B1": "=[1]Data!A1*A1"}, {"B1": 42}, {"A1": 2})
    g.names.append(NamedRange(name="Rate", sheet="Sheet", c1=0, r1=0, c2=0, r2=0))
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        for part in (
            "xl/externalLinks/externalLink1.xml",
            "xl/externalLinks/_rels/externalLink1.xml.rels",
        ):
            assert b.read(part) == a.read(part)
        book = b.read("xl/workbook.xml")
        assert book.index(b"<externalReferences>") < book.index(b"<definedNames>")
        assert b"externalLink1.xml" in b.read("xl/_rels/workbook.xml.rels")
        assert b"externalLink+xml" in b.read("[Content_Types].xml")
        assert b"absPath" not in book  # OpenXLSX's template folder would resolve the link
    h = Grid()
    assert h.xlsxload(str(out)) == 0
    assert h.cell(1, 0).val == 42.0 and h.cell(1, 0).cached is None
    h.setcell(0, 0, "3")
    assert h.cell(1, 0).val == 63.0
    wb = openpyxl.load_workbook(str(out))  # a reader that resolves the parts
    assert len(wb._external_links) == 1


def test_a_second_link_keeps_its_number(tmp_path):
    second = _LINK.replace('<sheetName val="Data"/>', '<sheetName val="Other"/>').replace(
        "<v>21</v>", "<v>5</v>"
    )
    g, _ = _linked_book(tmp_path, {"A1": "=[1]Data!A1+[2]Other!A1"}, {"A1": 26}, links=2)
    g.link_parts[1] = (second.encode(), g.link_parts[1][1])
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    h = Grid()
    assert h.xlsxload(str(out)) == 0
    assert sorted(h.links) == ["[1]data", "[1]my sheet", "[2]my sheet", "[2]other"]
    assert h.cell(0, 0).val == 26.0


def test_saving_over_a_linked_file_reports_links_only_when_lost(tmp_path):
    g, src = _linked_book(tmp_path, {"A1": "=[1]Data!A1"}, {"A1": 21})
    assert "links to other workbooks" not in save_losses(g, src)
    g.mode = Mode.HYBRID  # values only: no formula names a link
    assert "links to other workbooks" in save_losses(g, src)
    assert "links to other workbooks" in save_losses(Grid(), src)


@pytest.mark.parametrize("live", [True, False])
def test_an_xlsx_save_from_json_reports_the_lost_links(tmp_path, live):
    link = _LINK if live else None  # without a cache the formula keeps Excel's value
    g, _ = _linked_book(tmp_path, {"A1": "=[1]Data!A1+1"}, {"A1": 22}, link=link)
    j = tmp_path / "linked.json"
    assert g.jsonsave(str(j)) == 0
    h = Grid()
    assert h.jsonload(str(j)) == 0
    assert "links to other workbooks" in save_losses(h, tmp_path / "new.xlsx")
    assert save_losses(Grid(), tmp_path / "new.xlsx") == []
