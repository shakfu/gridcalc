"""Functions the 2026-10-24 corpus run found missing (`docs/dev/excel-corpus.md`).

Expected values are Excel's, from the IronCalc and pycel test workbooks, or
follow from the function's definition.
"""

import math

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


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=COT(1)", 1 / math.tan(1)),
        ("=COT(0)", ExcelError.DIV0),
        ("=CSC(2^27)", ExcelError.NUM),
        ("=SEC(0)", 1.0),
        ("=COTH(1)", 1 / math.tanh(1)),
        ("=CSCH(1000)", 0.0),
        ("=SECH(0)", 1.0),
        ("=ACOT(1)", math.pi / 4),
        ("=ACOTH(0.5)", ExcelError.NUM),
        ("=SQRTPI(1)", math.sqrt(math.pi)),
        ("=FACTDOUBLE(7)", 105.0),
        ("=FACTDOUBLE(-1)", 1.0),
        ("=SERIESSUM(2,1,1,{1,1})", 6.0),
        ("=SERIESSUM(0,0,2,{1,2,3})", ExcelError.NUM),
        ("=GAUSS(0)", 0.0),
        ("=ERF.PRECISE(1)", math.erf(1)),
        ("=CEILING.PRECISE(-4.3,-2)", -4.0),
        ("=ISO.CEILING(4.3,2)", 6.0),
        ("=FLOOR.PRECISE(-4.3,2)", -6.0),
        ("=FLOOR.PRECISE(4.3,0)", 0.0),
    ],
)
def test_math(formula, value) -> None:
    got = _ev(formula)
    assert got == pytest.approx(value) if isinstance(value, float) else got is value


def test_matrices() -> None:
    assert _ev("=INDEX(MMULT({1,2;3,4},{5;6}),2,1)") == 39.0
    assert _ev("=MMULT({1,2},{1,2})") is ExcelError.VALUE
    assert _ev("=MDETERM({1,2;3,4})") == pytest.approx(-2.0)
    assert _ev("=INDEX(MINVERSE({4,7;2,6}),1,1)") == pytest.approx(0.6)
    assert _ev("=MINVERSE({1,2;2,4})") is ExcelError.NUM
    assert _ev("=SUM(MUNIT(3))") == 3.0


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=BINOM.DIST.RANGE(60,0.75,48)", 0.083974967429),  # Microsoft's example
        ("=BINOM.DIST.RANGE(60,0.75,45,50)", 0.523629793),  # Microsoft's example
        ("=PERCENTRANK.INC({1,2,3,4},3)", 0.666),
        ("=PERCENTRANK.EXC({1,2,3,4},3)", 0.6),
        ("=VARA(2,4,TRUE)", 7 / 3),
        ("=STDEVPA(1,3)", 1.0),
        ("=FVSCHEDULE(1,{0.09,0.11,0.1})", 1.33089),  # Microsoft's example
    ],
)
def test_statistics_and_finance(formula, value) -> None:
    assert _ev(formula) == pytest.approx(value, rel=1e-9)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=BESSELJ(0,0)", 1.00000000283141),  # Excel's own approximation error
        ("=BESSELJ(0.2,1)", 0.09950083265193917),
        ("=BESSELJ(1,-1)", ExcelError.NUM),
        ("=BESSELY(0,1)", ExcelError.NUM),
        ("=BESSELI(1.5,1)", 0.981666428),  # Microsoft's example
        ("=BESSELK(1.5,1)", 0.277387804),  # Microsoft's example
    ],
)
def test_bessel(formula, value) -> None:
    got = _ev(formula)
    assert got == pytest.approx(value, rel=1e-8) if isinstance(value, float) else got is value


def test_odd_period_prices_match_microsofts_examples() -> None:
    oddf = (
        "=ODDFPRICE(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),"
        "0.0785,0.0625,100,2,1)"
    )
    assert _ev(oddf) == pytest.approx(113.597717474079, rel=1e-9)
    oddl = "=ODDLPRICE(DATE(2008,2,7),DATE(2008,6,15),DATE(2007,10,15),0.0375,0.0405,100,2,0)"
    assert _ev(oddl) == pytest.approx(99.8782860147213, rel=1e-9)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=REGEXTEST("ABCDE","^[A-Z]{5}$")', True),
        ('=REGEXTEST("abc","B")', False),
        ('=REGEXTEST("abc","B",1)', True),
        ('=REGEXEXTRACT("tel 555-1234","\\d+-\\d+")', "555-1234"),
        ('=ROWS(REGEXEXTRACT("a1b22c333","\\d+",1))', 3.0),
        ('=REGEXEXTRACT("x","\\d")', ExcelError.NA),
        ('=REGEXREPLACE("a1b2","(\\d)","<$1>")', "a<1>b<2>"),
        ('=REGEXREPLACE("a1b2","\\d","#",-1)', "a1b#"),
        ('=VALUETOTEXT("x",1)', '"x"'),
        ("=ARRAYTOTEXT({1,2;3,4})", "1, 2, 3, 4"),
        ('=ARRAYTOTEXT({1,"a"},1)', '{1,"a"}'),
        ('=HYPERLINK("http://x","site")', "site"),
    ],
)
def test_text(formula, value) -> None:
    got = _ev(formula)
    assert got == value if not isinstance(value, ExcelError) else got is value


def test_sortby_sorts_by_keys() -> None:
    cells = {(0, 0): "a", (0, 1): "b", (0, 2): "c", (1, 0): "2", (1, 1): "1", (1, 2): "2"}
    assert _ev('=TEXTJOIN(",",,SORTBY(A1:A3,B1:B3))', cells) == "b,a,c"
    assert _ev('=TEXTJOIN(",",,SORTBY(A1:A3,B1:B3,-1,A1:A3,-1))', cells) == "c,a,b"


def test_reference_functions() -> None:
    cells = {(0, 0): "1", (0, 1): "=SUBTOTAL(9,A1)", (0, 2): "5", (2, 9): "7"}
    assert _ev("=SUBTOTAL(9,A1:A3)", cells) == 6.0  # skips the nested SUBTOTAL
    assert _ev("=SUBTOTAL(101,A1:A3)", cells) == 3.0
    assert _ev('=CELL("address",B3)') == "$B$3"
    assert _ev('=CELL("type",A1)', cells) == "v"
    assert _ev('=CELL("type",Z1)') == "b"
    assert _ev("=SINGLE(C1:C20)", cells) == 7.0  # the cell on the formula's row
    assert _ev("=ROWS(TRIMRANGE(A1:A100))", cells) == 3.0
    assert _ev("=ANCHORARRAY(OFFSET(A1,0,0))", {(0, 0): "=SEQUENCE(3)"}) == 1.0


def test_isomitted_and_short_lambda_calls() -> None:
    f = '=LAMBDA(x,y,IF(ISOMITTED(y),"missing",x+y))'
    assert _ev(f + "(1)") == "missing"
    assert _ev(f + "(1,)") == "missing"
    assert _ev(f + "(1,2)") == 3.0
    assert _ev("=LAMBDA(x,x)(1,2)") is ExcelError.VALUE


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('="2024-01-10"+1', 45302.0),
        ('=SIN("2024-01-10")', math.sin(45301)),
        ('="10:30"*24', 10.5),
        ('="2:30 PM"*24', 14.5),
        ('="abc"+1', ExcelError.VALUE),
    ],
)
def test_date_text_reads_as_a_number(formula, value) -> None:
    got = _ev(formula)
    assert got == pytest.approx(value) if isinstance(value, float) else got is value


# -- wrong answers the corpus found (Excel's saved values) --------------------


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=ROMAN(499,0)", "CDXCIX"),  # Microsoft's examples, every form
        ("=ROMAN(499,1)", "LDVLIV"),
        ("=ROMAN(499,2)", "XDIX"),
        ("=ROMAN(499,3)", "VDIV"),
        ("=ROMAN(499,4)", "ID"),
        ("=ROMAN(99,TRUE)", "XCIX"),
        ("=ROMAN(99,FALSE)", "IC"),
        ("=ROMAN(1,5)", ExcelError.VALUE),
        ('=ROMAN(1,"a")', ExcelError.VALUE),
        ("=FLOOR(10,0)", ExcelError.DIV0),
        ("=FLOOR(0,0)", 0.0),
        ("=CEILING(10,0)", 0.0),
        ("=CEILING(10,1E-307)", 10.0),
        ("=CEILING(709,1E-307)", ExcelError.NUM),
        ("=FLOOR.MATH(7.1,0.1)", 7.1000000000000005),
        ("=FLOOR.MATH(-10,0.21,0.01)", -9.87),
        ('=FLOOR("",1/0)', ExcelError.VALUE),  # arguments fail left to right
        ('=TEXT(1/3,"General")', "0.333333333"),
        ('=TEXT(123456789012,"General")', "1.23457E+11"),
        ('=TEXT(-2.5E-9,"General")', "-2.5E-09"),
        ('=TEXT(41181,"ddddd/mmmmm/yyyyy")', "Saturday/S/2012"),
        ('=TEXT(2958466,"m/d/y")', ExcelError.VALUE),
        ('=TEXT(41181,"mm###")', ExcelError.VALUE),
        ('=TEXT(-1,"[h]")', "-24"),
        ('=TEXT(-1,"[m]:s")', ExcelError.VALUE),
        ('=TEXT(0.5,"[h]:mm:ss")', "12:00:00"),
        ('=TEXT("23:99","#.#####")', "1.02708"),
        ('=TEXT("24:99","#.#####")', "24:99"),
        ('=TEXT(890123.456789,"#.###x,##")', "890123.456x,79"),
        ('=TEXT(Z99,"#.###")', "."),
        ("=VALUE(TRUE)", ExcelError.VALUE),
        ("=VALUE(Z99)", 0.0),
    ],
)
def test_excel_answers(formula, value) -> None:
    got = _ev(formula)
    if isinstance(value, ExcelError):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-15)
    else:
        assert got == value


@pytest.mark.parametrize(
    ("criteria", "count"),
    [
        ("NA()", 1),  # the error, not the text "#N/A"
        ('"<>#N/A"', 7),  # blanks count: they are not the error
        ('"TRUE"', 1),  # the logical, not the text "TRUE"
        ('"<>"', 7),  # every cell that is not empty, `=""` included
        ('">"', 0),
        ("Z99", 1),  # a blank criterion cell is 0
    ],
)
def test_countif_criteria_follow_excel(criteria, count) -> None:
    cells = {
        (0, 0): "=NA()",
        (0, 1): '"#N/A',
        (0, 2): "TRUE",
        (0, 3): '"TRUE',
        (0, 4): "0",
        (0, 5): '=""',
        (0, 6): "5",
    }
    assert _ev(f"=COUNTIF(A1:A8,{criteria})", cells) == count
