"""Lookup, reference and text cases where gridcalc disagreed with Excel.

Expected values are Excel's saved results from the IronCalc and pycel test
workbooks (XLOOKUP, INDIRECT, ROW_COLUM, TEXTBEFORE_TEXTAFTER, lookup, text).
"""

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError


def _ev(formula: str, cells: dict[tuple[int, int], str] | None = None):
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(c, r, t) for (c, r), t in (cells or {}).items()])
    g.setcell(9, 9, formula)
    cl = g.cell(9, 9)
    if cl.err is not None:
        return cl.err
    return cl.sval if cl.sval is not None and not isinstance(cl.val, bool) else cl.val


# A1:A7 = 2,5,4,5,3,TRUE,"ala"; B1:B7 = a..g (XLOOKUP.xlsx ReturnSmaller).
_MIXED = {(0, i): v for i, v in enumerate(["2", "5", "4", "5", "3", "TRUE", "ala"])}
_MIXED.update({(1, i): ch for i, ch in enumerate("abcdefg")})
# A1:A5 = 2..6 ascending; B1:B5 = a..e.
_SORTED = {(0, i): str(i + 2) for i in range(5)}
_SORTED.update({(1, i): ch for i, ch in enumerate("abcde")})
# A1:A13 = 1,2,3,4,5,5,5,6,7,7,7,8,9; B = a..l with "aa" first.
_DUPS = {(0, i): str(v) for i, v in enumerate([1, 2, 3, 4, 5, 5, 5, 6, 7, 7, 7, 8, 9])}
_DUPS.update({(1, i): v for i, v in enumerate(["aa", *"abcdefghijkl"])})
_DESC = {(0, i): str(v) for i, v in enumerate([9, 8, 7, 7, 7, 6, 5, 5, 5, 4, 3, 2, 1])}
_DESC.update({(1, i): v for i, v in enumerate(["aa", *"abcdefghijkl"])})


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        # Approximate modes order numbers < text < FALSE < TRUE.
        ("=XLOOKUP(TRUE,A1:A7,B1:B7,,-1)", _MIXED, "f"),
        ("=XLOOKUP(FALSE,A1:A7,B1:B7,,-1)", _MIXED, "g"),
        ("=XLOOKUP(10,A1:A7,B1:B7,,1)", _MIXED, "g"),
        ('=XLOOKUP("qwerty",A1:A7,B1:B7,,1)', _MIXED, "f"),
        ("=XLOOKUP(FALSE,A1:A7,B1:B7,,1,-1)", _MIXED, "f"),
        ('=XLOOKUP("a",A1:A5,B1:B5,,-1,2)', _SORTED, "e"),
        ("=XLOOKUP(TRUE,B1:B5,A1:A5,,-1,2)", _SORTED, 6.0),
        ("=XLOOKUP(12,B1:B5,A1:A5,,1,2)", _SORTED, 2.0),
        # Binary search: next smaller is the last of a run, exact the first.
        ("=XLOOKUP(7.1,A1:A13,B1:B13,,-1,2)", _DUPS, "j"),
        ("=XLOOKUP(7,A1:A13,B1:B13,,-1,2)", _DUPS, "h"),
        ("=XLOOKUP(6.8,A1:A13,B1:B13,,1,2)", _DUPS, "h"),
        # Descending binary search mirrors the ascending one.
        ("=XLOOKUP(7.1,A1:A13,B1:B13,,-1,-2)", _DESC, "b"),
        ("=XLOOKUP(5,A1:A13,B1:B13,,-1,-2)", _DESC, "h"),
        ("=XLOOKUP(6.8,A1:A13,B1:B13,,1,-2)", _DESC, "d"),
        # Wildcards do not work with binary search.
        ('=XLOOKUP("Abra",B1:B5,A1:A5,,2,2)', _SORTED, ExcelError.VALUE),
    ],
)
def test_xlookup_approximate(formula, cells, value):
    assert _ev(formula, cells) == value


# lookup.xlsx Table1: A1:A5 = 0..4, B1:B5 = a,e,i,o,u, C1:C5 = 0,"plugh",TRUE.
_TABLE = {(0, i): str(i) for i in range(5)}
_TABLE.update({(1, i): ch for i, ch in enumerate("aeiou")})
_TABLE.update({(2, 1): "plugh", (2, 2): "TRUE"})


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # A blank lookup value matches as 0.
        ("=VLOOKUP(Z1,A1:B5,2)", "a"),
        ('=HLOOKUP(Z1,{0,1,2;"a","e","i"},2)', "a"),
        ("=LOOKUP(Z1,A1:B5)", "a"),
        # A 2D lookup_vector searches its first column even with result_vector.
        ("=LOOKUP(2,A1:B5,B1:B5)", "i"),
        ("=LOOKUP(2,A1:B5,C1:C5)", True),
        # result_vector must be one row or column.
        ("=LOOKUP(2,A1:B5,B1:C5)", ExcelError.NA),
    ],
)
def test_legacy_lookup(formula, value):
    assert _ev(formula, _TABLE) == value


def test_indirect_r1c1_relative_wraps_around():
    # J10 is (9, 9); R[-6]C from row 10 is J4, RC[-5] is E10.
    cells = {(9, 3): "42", (4, 9): "7"}
    assert _ev('=INDIRECT("R[-6]C",FALSE)', cells) == 42
    assert _ev('=INDIRECT("RC[-5]",FALSE)', cells) == 7
    # R[-20] from row 10 wraps to row 1048566: blank.
    assert _ev('=INDIRECT("R[-20]C",FALSE)', cells) == 0
    assert _ev('=INDIRECT("R[-1048576]C",FALSE)', cells) == ExcelError.REF
    assert _ev('=INDIRECT("RC[16384]",FALSE)', cells) == ExcelError.REF


def test_indirect_r1c1_whole_rows_and_columns():
    cells = {(1, 0): "3", (1, 1): "4", (2, 1): "9", (0, 1): "2"}
    assert _ev('=SUM(INDIRECT("C2",FALSE))') == 0
    assert _ev('=SUM(INDIRECT("C2",FALSE))', cells) == 7
    assert _ev('=SUM(INDIRECT("R2",FALSE))', cells) == 15
    assert _ev('=SUM(INDIRECT("C2:C3",FALSE))', cells) == 16
    assert _ev('=SUM(INDIRECT("R1:R2",FALSE))', cells) == 18


def test_indirect_a1_argument_must_be_logical():
    assert _ev('=INDIRECT("R1C1","no")') == ExcelError.VALUE


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=ROW(INDIRECT("h"))', ExcelError.REF),
        ('=COLUMN(INDIRECT(""))', ExcelError.REF),
        ('=ROW(INDIRECT("XFE:XFE"))', ExcelError.REF),
        ('=COLUMN(OFFSET(INDIRECT("A1"),-2,1))', ExcelError.REF),
        ("=OFFSET(A1,2,2,-10,1)", ExcelError.VALUE),
        ("=OFFSET(A1,2,2,2,-2)", ExcelError.VALUE),
        ("=SUM(OFFSET(A1,0,0,1,0.9))", 5),
    ],
)
def test_reference_errors(formula, value):
    assert _ev(formula, {(0, 0): "5", (1, 0): "6"}) == value


def test_indirect_unknown_sheet_is_ref():
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.add_sheet("Other")
    g.setcell(0, 0, '=ROW(INDIRECT("NonExist!W3"))')
    assert g.cell(0, 0).err == ExcelError.REF


_T = "123 the 456 the 891"


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # if_not_found is only evaluated for its value when nothing matches.
        (f'=TEXTAFTER("{_T}","THE",2,1,0,1/0)', " 891"),
        (f'=TEXTBEFORE("{_T}","THE",2,1,0,1/0)', "123 the 456 "),
        ('=TEXTBEFORE("A day in the woods","the",-2,1,0,"Not here")', "Not here"),
        (f'=TEXTBEFORE("{_T}","the",5,1,0,"Not found")', "Not found"),
        # instance_num rounds down.
        (f'=TEXTAFTER("{_T}","the",-1.6,1,0,"x")', " 456 the 891"),
        (f'=TEXTBEFORE("{_T}","the",-1.2,1,0,"x")', "123 "),
        # A delimiter longer than the text is #VALUE! once instance_num is given.
        ('=TEXTAFTER("del","deli",1,1,0,"q")', ExcelError.VALUE),
        ('=TEXTAFTER("del","deli",1)', ExcelError.VALUE),
        ('=TEXTAFTER("del","deli")', ExcelError.NA),
        # match_end: the end of the text (its start, searching back) is a delimiter.
        (f'=TEXTAFTER("{_T}","the",1,1,1,"Failed")', " 456 the 891"),
        (f'=TEXTBEFORE("{_T}","Hello",2,1,1,"Failed")', "Failed"),
        (f'=TEXTAFTER("{_T}","Hello",-1,1,1,"Failed")', _T),
        ('=TEXTBEFORE("Email - me@example.com","- ",-1,,1)', "Email "),
        (f'=TEXTAFTER("{_T}","Hello",-1,1,2,"Failed")', ExcelError.VALUE),
    ],
)
def test_textbefore_textafter(formula, value):
    assert _ev(formula) == value


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # A short code's last section holding `@` is its text section.
        ('=TEXT(0,"w;x;z@")', "w"),
        ('=TEXT(-1,"w;x@")', "-w"),
        ('=TEXT("X",";-  ##.0;""ZERO""@;""X""")', ExcelError.VALUE),
        ('=TEXT(0,"#,#""ZZ""#.0""YY""00@")', ExcelError.VALUE),
        ('=TEXT(-1,"")', "-"),
        # A comma after a placeholder is dropped; elsewhere it is literal.
        ('=TEXT(890123.456789,"#,#.##.##,#")', "890,123.45.679"),
        ('=TEXT(890123.456789,"0,x#.00.0")', "89012x3.45.7"),
        ('=TEXT(890123.456789,"#x,0x#.00.0")', "8901x,2x3.45.7"),
        ('=TEXT(890123.456789,"#x,0,#.00.0")', "890,1x,23.45.7"),
        ('=TEXT(890123.456789,",#.00.0")', ",890123.45.7"),
        ('=TEXT(890123.456789,"#.###,x,##")', "890123.456x,79"),
    ],
)
def test_text_format(formula, value):
    assert _ev(formula) == value
