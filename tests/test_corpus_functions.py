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


# -- syntax found in real workbooks (`scripts/xlsx_survey.py`) ----------------


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=SUM(A1:INDEX(A:A,4))", 10.0),  # the range operator over INDEX
        ("=SUM(INDEX(A:A,2):INDEX(A:A,5))", 14.0),
        ("=SUM(INDEX(A:A,3):A1)", 6.0),
        ("=ROWS(A2:OFFSET(A1,6,0))", 6.0),
        ("=SUM(A1:A3:A5)", 15.0),
        ("=ROWS(INDEX(A1:B10,0,2))", 10.0),  # INDEX gives a reference
        ("=SUM(INDEX(A1:B10,3,0))", 33.0),
        ("=SUM(CHOOSE(1,A1,A2):CHOOSE(2,A3,A5))", 15.0),  # CHOOSE and IF give references
        ("=SUM(CHOOSE(2,A1:A5,B1:B5))", 150.0),
        ("=ROWS(IF(TRUE,A1:A3,B1:B5))", 3.0),
        ("=SUM(IF(FALSE,A1,B1):B3)", 60.0),
        ("=SUM(CHOOSE(9,A1,A2):A3)", ExcelError.VALUE),
        ("=SUM(IF(A1:A5>2,A1:A5,B1:B5))", 42.0),
        ("=SUM(Data!#REF!)", ExcelError.REF),  # a deleted reference, still qualified
        ("=COUNTIFS('District I'!#REF!,\"0\")", ExcelError.REF),
    ],
)
def test_reference_syntax(formula, value) -> None:
    cells = {(0, r): str(r + 1) for r in range(10)} | {(1, r): str(10 * (r + 1)) for r in range(10)}
    got = _ev(formula, cells)
    assert got is value if isinstance(value, ExcelError) else got == value


def test_a_range_needs_a_reference_on_each_side() -> None:
    from gridcalc.formula.parser import ParseError, parse

    for text in ("A1:5", '"a":A1', "1:A1+1"):
        with pytest.raises(ParseError):
            parse(text)


def test_poisson_cdf_at_a_large_mean_matches_excel() -> None:
    """IronCalc `POISSON.xlsx` POISSON.DIST!D31, saved by Excel."""
    from gridcalc.libs.xlsx import POISSON_DIST

    assert POISSON_DIST(1_000_000, 1_000_000, True) == pytest.approx(0.5002659614862837, rel=1e-12)


# -- AGGREGATE, and ROW/COLUMN as arrays -------------------------------------

_AGG_CELLS = {
    (0, 0): "5",
    (0, 1): "=1/0",
    (0, 2): "3",
    (0, 3): "8",
    (0, 4): "1",
    (0, 5): "=SUBTOTAL(9,A3:A5)",
    (1, 0): "x",
    (1, 2): "x",
    (1, 3): "x",
}


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=AGGREGATE(9,6,A1:A6)", 29.0),  # skip errors, keep the nested total
        ("=AGGREGATE(9,2,A1:A6)", 17.0),  # skip errors and nested totals
        ("=AGGREGATE(9,4,A1:A6)", ExcelError.DIV0),  # skip nothing
        ("=AGGREGATE(2,4,A1:A6)", 5.0),  # COUNT takes errors as values
        ("=AGGREGATE(4,6,A1:A5)", 8.0),
        ("=AGGREGATE(12,6,A1:A5)", 4.0),
        ("=AGGREGATE(15,6,A1:A5,2)", 3.0),
        ('=AGGREGATE(14,6,A1:A5/(B1:B5="x"),1)', 8.0),
        ('=AGGREGATE(15,6,ROW(A1:A5)/(B1:B5="x"),2)', 3.0),
        ("=AGGREGATE(9,6,A1:A5*2)", ExcelError.VALUE),  # 1-13 take references only
        ("=AGGREGATE(20,6,A1:A5)", ExcelError.VALUE),
        ("=AGGREGATE(9,8,A1:A5)", ExcelError.VALUE),
        ("=SUBTOTAL(9,A1:A5)", ExcelError.DIV0),
        ("=SUMPRODUCT(ROW(A2:A4))", 9.0),
        ("=SUM(COLUMN(B1:D1))", 9.0),
        ("=ROWS(ROW(A1:A9))", 9.0),
    ],
)
def test_aggregate(formula, value) -> None:
    got = _ev(formula, _AGG_CELLS)
    assert got is value if isinstance(value, ExcelError) else got == value


# IronCalc `BINOM.xlsx` and `POISSON.xlsx`, values saved by Excel.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=BINOM.DIST(7,8,0.7,"abc")', ExcelError.VALUE),
        ("=BINOM.DIST(2,10,1,TRUE)", 0.0),
        ("=BINOM.INV(10,0.7,0)", ExcelError.NUM),
        ("=BINOM.INV(10,0.7,1)", ExcelError.NUM),
        ("=BINOM.INV(10,1,0.8)", ExcelError.NUM),
        ("=NEGBINOM.DIST(2,10,1,TRUE)", ExcelError.NUM),
        ('=NEGBINOM.DIST(7,8,0.7,"abc")', ExcelError.VALUE),
        ("=POISSON.DIST(-0.000001,5,TRUE)", ExcelError.NUM),
        ('=POISSON.DIST(2,5,"abc")', ExcelError.VALUE),
    ],
)
def test_distribution_arguments(formula, value) -> None:
    got = _ev(formula, {})
    assert got is value if isinstance(value, ExcelError) else got == value


def _spill(formula: str, cells: dict[tuple[int, int], str], rows: int, cols: int) -> list[list]:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(c, r, t) for (c, r), t in cells.items()])
    g.setcell(9, 9, formula)
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            cl = g.cell(9 + c, 9 + r)
            row.append(cl.err if cl.err is not None else cl.val)
        out.append(row)
    return out


_NA = ExcelError.NA


@pytest.mark.parametrize(
    ("formula", "rows", "cols", "want"),
    [
        # Exceljet's broadcasting example: https://exceljet.net/glossary/broadcasting
        ("={2;4;6;8}*{2;2}", 4, 1, [[4.0], [8.0], [_NA], [_NA]]),
        ("={1;2;3}*{2,3}", 3, 2, [[2.0, 3.0], [4.0, 6.0], [6.0, 9.0]]),
        ("=A1:A3+{10}", 3, 1, [[11.0], [12.0], [12.0]]),
        ("={1,2;3,4}+{1,2,3}", 2, 3, [[2.0, 4.0, _NA], [4.0, 6.0, _NA]]),
        ("=COUNTIFS(A1:A3,{1;2})", 2, 1, [[1.0], [2.0]]),  # one count per criterion
        ("=BYROW({1;2},LAMBDA(z,COUNTIFS(A1:A3,z)))", 2, 1, [[1.0], [2.0]]),
        ("=MAP({1;2},LAMBDA(x,{5}))", 2, 1, [[5.0], [5.0]]),  # a 1x1 result is its value
        ("=BYROW({1;2},LAMBDA(z,{1,2}))", 2, 1, [[ExcelError.CALC], [ExcelError.CALC]]),
        ("=ROW(B2:B4)", 3, 1, [[2.0], [3.0], [4.0]]),
        ("=COLUMN(B2:D2)", 1, 3, [[2.0, 3.0, 4.0]]),
        ("=INDEX({1,2;3,4},2,0)", 1, 2, [[3.0, 4.0]]),  # a whole row spills across
        ("=INDEX({1,2,3,4},,)", 1, 4, [[1.0, 2.0, 3.0, 4.0]]),
        ("=INDEX({1,2;3,4},0,2)", 2, 1, [[2.0], [4.0]]),
    ],
)
def test_array_shapes(formula, rows, cols, want) -> None:
    got = _spill(formula, {(0, 0): "1", (0, 1): "2", (0, 2): "2"}, rows, cols)
    assert got == want


def test_a_range_in_a_scalar_parameter_saves_as_a_dynamic_array(tmp_path) -> None:
    """`SUM(IF(WEEKDAY(A1:A7)=2,1))` lifts WEEKDAY over a range; saved
    without the dynamic-array flag, Excel would intersect it instead."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, r, str(45000 + r)) for r in range(7)])
    g.setcell(2, 0, "=SUM(IF(WEEKDAY(A1:A7)=2,1,0))")
    g.setcell(2, 1, "=SUM(A1:A7)")
    path = tmp_path / "w.xlsx"
    assert g.xlsxsave(str(path)) == 0
    g2 = Grid()
    assert g2.xlsxload(str(path)) == 0
    assert not g2.cell(2, 0).legacy and g2.cell(2, 0).val == 1.0
    assert g2.cell(2, 1).legacy  # a range passed whole needs no flag


def test_index_is_not_volatile_and_still_follows_its_range() -> None:
    """A volatile cell recalculates on every edit; `INDEX` reads inside its
    first argument, so static dependencies keep it current."""
    from gridcalc.formula.deps import has_dynamic_refs
    from gridcalc.formula.parser import parse

    assert not has_dynamic_refs(parse("=INDEX(A1:A3,2)"))
    assert has_dynamic_refs(parse("=SUM(A1:INDEX(A:A,3))"))  # the `:` widens a rectangle
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, 0, "1"), (0, 1, "2"), (0, 2, "3"), (1, 0, "2")])
    g.setcell(2, 0, "=INDEX(A1:A3,B1)")
    g.setcell(3, 0, "=SUM(A1:INDEX(A:A,B1))")
    assert (g.cell(2, 0).val, g.cell(3, 0).val) == (2.0, 3.0)
    g.setcell(0, 1, "20")
    assert (g.cell(2, 0).val, g.cell(3, 0).val) == (20.0, 21.0)
    g.setcell(1, 0, "3")
    assert (g.cell(2, 0).val, g.cell(3, 0).val) == (3.0, 24.0)


# -- found by the 2026-11-05 run against a second engine (`scripts/engine_diff.py`)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # A blank or empty suffix is "i" (IronCalc `COMPLEXs.xlsx`).
        ("=COMPLEX(1.23,9.5121,Z99)", "1.23+9.5121i"),
        ('=COMPLEX(1,2,"")', "1+2i"),
        ("=COMPLEX(1,2,0)", ExcelError.VALUE),
        ("=IMREAL(COMPLEX(1.23,9.5121,Z99))", 1.23),
        # IronCalc `ENCODEURL.xlsx`.
        (
            '=ENCODEURL("http://contoso.sharepoint.com/Finance")',
            "http%3A%2F%2Fcontoso.sharepoint.com%2FFinance",
        ),
        ('=ENCODEURL("!*\'()")', "%21%2A%27%28%29"),
        ('=ENCODEURL("-_.~az09")', "-_.~az09"),
        ('=ENCODEURL("über €")', "%C3%BCber%20%E2%82%AC"),
        ("=ENCODEURL(1E+20)", "1E%2B20"),
        ("=ENCODEURL(TRUE)", "TRUE"),
        ("=ENCODEURL(1/0)", ExcelError.DIV0),
        ('=LEN(ENCODEURL(REPT(" ",10922)))', 32766.0),
        ('=ENCODEURL(REPT(" ",10923))', ExcelError.VALUE),  # past Excel's text limit
        ('=LEN(ENCODEURL(REPT("a",32767)))', ExcelError.VALUE),
        # IronCalc `INDEX.xlsx` and pycel `lookup.xlsx`.
        ("=INDEX({1,2,3;4,5,6},-1,1)", ExcelError.VALUE),
        ("=INDEX(A1:A3,-2)", ExcelError.VALUE),
        ("=INDEX({1,2;3,4},2,1,1)", 3.0),
        ("=INDEX({1,2;3,4},2,1,2)", ExcelError.REF),
    ],
)
def test_second_engine_findings(formula, value) -> None:
    got = _ev(formula, {(0, 0): "1", (0, 1): "2", (0, 2): "3"})
    if isinstance(value, ExcelError):
        assert got is value
    else:
        assert got == (pytest.approx(value) if isinstance(value, float) else value)


# Probed against Excel 16.114 (2026-11-16). A1:A3 hold 1, 2, 3; Z1 holds 5,
# Y1 `=5`, W1 `=SEQUENCE(2)`.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # Number text: grouping, currency, parentheses, percent.
        ('="1,600"*1', 1600.0),
        ('="1,600.5%"*1', 16.005),
        ('="$1,600.50"*1', 1600.5),
        ('="-$5"*1', -5.0),
        ('="$-5"*1', -5.0),
        ('="($5)"*1', -5.0),
        ('="$(5)"*1', -5.0),
        ('="(5%)"*1', -0.05),
        ('="(5)%"*1', -0.05),
        ('="%5"*1', 0.05),
        ('="50 %"*1', 0.5),
        ('="5e2%"*1', 5.0),
        ('="1600%"*1', 16.0),
        ('="5%%"*1', ExcelError.VALUE),
        ('="$5%"*1', ExcelError.VALUE),
        ('="(-5)"*1', ExcelError.VALUE),
        ('="1,6"*1', ExcelError.VALUE),
        ('="5$"*1', ExcelError.VALUE),
        ('=VALUE("(5)")', -5.0),
        ('=VALUE("24:00")', 1.0),
        ('=VALUE("1E400")', ExcelError.VALUE),
        # Hours past 23.
        ('="25:00"+0', 25 / 24),
        ('="9999:00"+0', 9999 / 24),
        ('="10000:00"+0', ExcelError.VALUE),
        ('="24:59"+0', (24 * 60 + 59) / 1440),
        ('="23:99"+0', (23 * 60 + 99) / 1440),
        ('="24:99"+0', ExcelError.VALUE),
        ('="0:30 AM"+0', 30 / 1440),
        ('="13:00 PM"+0', ExcelError.VALUE),
        ('=TIMEVALUE("24:00")', 0.0),
        ('=TIMEVALUE("48:30")', 30 / 1440),
        ('=TIMEVALUE("1/1/2020 25:00")', pytest.approx(1 / 24, abs=1e-9)),
        ('=TIMEVALUE("1/1/2020")', 0.0),
        ('=TIMEVALUE("1600%")', ExcelError.VALUE),
        ('=DATEVALUE("1/1/2020 25:00")', 43832.0),
        ('=DATEVALUE("10:30")', 0.0),
        ('="4 : 35"+0', 275 / 1440),  # spaces around a separator are ignored
        ('="2026 - 01 - 01"+0', 46023.0),
        ('="10 :30 PM"+0', 0.9375),
        ('="26-01-01"+0', ExcelError.VALUE),
        # A year-less date whose second number cannot be the day is a year.
        ('="1/40"+0', 14611.0),
        ('="Jan-40"+0', 14611.0),
        ('="Jan 40"+0', 14611.0),
        ('="1/32"+0', 11689.0),
        ('="4/31"+0', 11414.0),
        ('="12/99"+0', 36495.0),
        ('="1/0"+0', 36526.0),
        ('="1/2026"+0', 46023.0),
        ('="Jan 2, 26"+0', 46024.0),
        ('="13/2"+0', ExcelError.VALUE),
        ('="0/5"+0', ExcelError.VALUE),
        ('="1/100"+0', ExcelError.VALUE),
        ('="1 2"+0', ExcelError.VALUE),
        ('="40 Jan"+0', ExcelError.VALUE),
        ('="30-Feb"+0', ExcelError.VALUE),
        # INDEX: a fraction that truncates to 0.
        ("=INDEX(A1:A3,0.4)", ExcelError.VALUE),
        ("=INDEX(A1:A3,-0.4)", ExcelError.VALUE),
        ("=INDEX(A1:A3,1.9)", 1.0),
        ("=INDEX(A1:A3,1,0.4)", 1.0),
        ("=INDEX(A1:C1,0.4)", ExcelError.VALUE),
        ("=INDEX(A1:C1,1,0.4)", ExcelError.VALUE),
        ("=ROWS(INDEX(A1:B3,0,0.4))", 3.0),
        # `X#` needs a formula at X.
        ("=ROWS(Z1#)", ExcelError.REF),
        ("=ROWS(Y1#)", 1.0),
        ("=ROWS(W1#)", 2.0),
        ("=ROWS(W2#)", ExcelError.REF),
        ("=ROWS(U1#)", ExcelError.REF),
        # Binomial: Excel refuses 2^31-1 trials; large n stays accurate.
        ("=BINOM.DIST(1,2147483646,1E-9,FALSE)", 0.250778076933),
        ("=BINOM.DIST(1,2147483647,0.5,FALSE)", ExcelError.NUM),
        ("=BINOM.DIST(1,1E30,1E-30,FALSE)", ExcelError.NUM),
        ("=BINOM.DIST.RANGE(2147483647,0.5,1)", ExcelError.NUM),
        ("=BINOM.INV(2147483647,0.5,0.5)", ExcelError.NUM),
        ("=BINOM.INV(2147483646,0.5,0.5)", 1073741823.0),
        ("=BINOM.DIST(5E8,1E9,0.5,TRUE)", 0.500012615663),
        ("=BINOM.DIST(5E8,1E9,0.5,FALSE)", 2.523132521389e-5),
        ("=BINOM.DIST(1,1E9,1E-9,FALSE)", 0.367879441355),
        ("=BINOM.DIST(3,2^30,1E-9,TRUE)", 0.97615328355),
    ],
)
def test_excel_probed(formula, value) -> None:
    cells = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (2, 0): "x"}
    cells |= {(25, 0): "5", (24, 0): "=5", (22, 0): "=SEQUENCE(2)"}
    got = _ev(formula, cells)
    if isinstance(value, ExcelError):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-11)
    else:
        assert got == value


@pytest.mark.parametrize(
    ("text", "month", "day"),
    [
        ("1/2", 1, 2),
        ("1-2", 1, 2),
        ("01/02", 1, 2),
        ("Jan 2", 1, 2),
        ("2-Jan", 1, 2),
        ("2 January", 1, 2),
        ("Sept 2", 9, 2),
        ("12/31", 12, 31),
    ],
)
def test_yearless_date_is_this_year(text, month, day) -> None:
    import datetime as dt

    from gridcalc.dates import to_serial

    assert _ev(f'="{text}"+0') == to_serial(dt.date(dt.date.today().year, month, day))


def test_yearless_feb_29() -> None:
    """Excel 16.114 in 2026 reads `2/29` as 2029-02-01: no Feb 29, so 29 is the year."""
    import calendar
    import datetime as dt

    from gridcalc.dates import to_serial

    y = dt.date.today().year
    want = dt.date(y, 2, 29) if calendar.isleap(y) else dt.date(2029, 2, 1)
    assert _ev('="2/29"+0') == to_serial(want)


def test_binom_cdf_is_accurate_at_large_n() -> None:
    """At p = 1/2 and k = n/2 the CDF is exactly 1/2 + pmf/2. The continued
    fraction this replaced gave 0.49998 at n = 2e6 and -1.79 at n = 1e9."""
    from gridcalc.libs.xlsx import _binom_cdf, _binom_pmf

    for n in (2_000, 2_000_000, 1_000_000_000):
        k = n // 2
        assert _binom_cdf(k, n, 0.5) == pytest.approx(0.5 + _binom_pmf(k, n, 0.5) / 2, rel=1e-13)


# Argument rules probed against Excel 16.114 (2026-11-16), and the IronCalc
# corpus files named. B1 holds `=TRUE`, B2 `="25"`, B3 `=DATE(2024,1,31)`.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # The Analysis ToolPak refuses a logical; the other functions read it as 1.
        ("=ERF(B1)", ExcelError.VALUE),
        ("=ERF(TRUE)", ExcelError.VALUE),
        ("=GESTEP(TRUE)", ExcelError.VALUE),
        ("=ISODD(TRUE)", ExcelError.VALUE),
        ("=QUOTIENT(TRUE,1)", ExcelError.VALUE),
        ("=GCD({TRUE,2})", ExcelError.VALUE),
        ("=EDATE(B3,B1)", ExcelError.VALUE),
        ("=WEEKNUM(1,TRUE)", ExcelError.VALUE),
        ("=WEEKNUM(-1,TRUE)", ExcelError.NUM),  # the date's range comes first
        ("=YEARFRAC(-1,TRUE)", ExcelError.NUM),
        ("=YEARFRAC(-1,200,TRUE)", ExcelError.VALUE),  # YEARFRAC checks basis first
        ("=NETWORKDAYS.INTL(B3,B3+5,B1)", 4.0),
        ("=ERF(B2)", math.erf(25)),
        ('=EDATE(B3,"1")', 45351.0),
        ("=ABS(B1)", 1.0),
        ("=SQRT(B2)", 5.0),
        ("=COMBIN(B1,1)", 1.0),
        ("=ISNONTEXT(1/0)", True),
        ('=NORM.DIST(42,40,1.5,"abc")', ExcelError.VALUE),
        ('=EXPON.DIST(0.2,10,"abc")', ExcelError.VALUE),
        # Times round to the second; arguments have Excel's limits.
        ("=MINUTE(12.5/24-0.0004/86400)", 30.0),
        ("=SECOND(PI())", 54.0),
        ("=HOUR(1-0.1/86400)", 0.0),
        ("=TIME(32768,0,0)", ExcelError.NUM),
        ("=TIME(32767,0,0)", pytest.approx((32767 % 24) / 24)),
        ("=EDATE(2958465,0)", 2958465.0),
        ("=EOMONTH(2958465,0)", 2958465.0),
        ("=EDATE(2958465,1)", ExcelError.NUM),
        ("=EDATE(1,-1)", ExcelError.NUM),
        # Degrees of freedom truncate.
        ("=CHISQ.DIST(8,3.34,TRUE)", pytest.approx(0.9539882943107687, rel=1e-9)),
        ("=CHISQ.INV(0.5,3.5)", pytest.approx(2.365973884375, rel=1e-9)),
        ("=F.DIST(0.8,2.4,3,TRUE)", pytest.approx(0.4733220523344033, rel=1e-9)),
        ("=F.INV(0.5,2.9,3)", pytest.approx(0.881101577952, rel=1e-9)),
        ("=CONFIDENCE.T(0.05,1,1.9)", ExcelError.DIV0),
        ("=RANK.EQ(4,A1:A3)", ExcelError.NA),
        ("=PROB({1,2,3},{0.5,0.5},1)", ExcelError.NA),
        ("=PROB({1,2},{0.5,0.5},2,1)", 0.0),
        ("=COVARIANCE.P({1,2,3},{1,2})", ExcelError.NA),
        ("=COTH(9999999999999)", 1.0),
        ("=SECH(9999999999999)", 0.0),
        ("=ROUND(7.123,-10000000)", 0.0),
        ("=ROUNDUP(7.123,-10000000)", ExcelError.NUM),
        # Comparison and lookup.
        ('=SWITCH(Z9,0,"m","n")', "m"),
        ('=SWITCH(Z9,"","m","n")', "n"),
        ('=SWITCH(Z9,FALSE,"m","n")', "n"),
        ('=SWITCH(1,TRUE,"m","n")', "n"),
        ('=SWITCH("a","A","m","n")', "m"),
        ('=SWITCH("1",1,"m","n")', "n"),
        ("=INDEX(SWITCH({FALSE,TRUE},FALSE,0,TRUE,1),2)", 1.0),
        ('=MATCH(FALSE,{"FALSE",0},0)', ExcelError.NA),
        ('=MATCH(FALSE,{"FALSE",0,FALSE},0)', 3.0),
        ("=MATCH(0,{FALSE,0},0)", 2.0),
        ('=SUMIF(E1:E2,"12*",F1:F2)', 3.0),  # a number is not text: E2's error is skipped
        ('=COUNTIF(A1:A3,"*")', 0.0),
        # Powers, COMBINA, SMALL, SUBSTITUTE.
        ("=(-8)^(1/3)", -2.0),
        ("=(-8)^(1/5)", pytest.approx(-1.51571656651)),
        ("=(-8)^(2/3)", ExcelError.NUM),
        ("=POWER(-2,0.5)", ExcelError.NUM),
        ("=POWER(0,-1)", ExcelError.DIV0),
        ("=COMBINA(0,5)", ExcelError.NUM),
        ("=COMBINA(0,0)", 1.0),
        ('=SMALL("3.4",1)', 3.4),
        ("=SMALL(TRUE,1)", 1.0),
        ('=SMALL("x",1)', ExcelError.VALUE),
        ('=SUBSTITUTE("aaa","a","b",0)', ExcelError.VALUE),
        ('=SUBSTITUTE("aaa","a","b",1.5)', "baa"),
    ],
)
def test_excel_argument_rules(formula, value) -> None:
    cells = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (1, 0): "=TRUE", (1, 1): '="25"'}
    cells |= {(1, 2): "=DATE(2024,1,31)", (4, 0): '"1213', (4, 1): "1213"}
    cells |= {(5, 0): "3", (5, 1): "=1/0"}
    got = _ev(formula, cells)
    if isinstance(value, (ExcelError, bool)):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-12)
    else:
        assert got == value


# Probed against Excel 16.114 (2026-11-16) or read from IronCalc's saved values.
# A1:A3 hold 1, 2, 3; K1 holds the text "text".
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=MAX(,-1)", 0.0),  # an omitted argument is 0
        ("=MIN(5,)", 0.0),
        ("=AVERAGE(,2)", 1.0),
        ("=COUNT(,1)", 2.0),
        ('=MAX(NA(),"abc")', ExcelError.NA),  # left to right
        ('=MAX("abc",NA())', ExcelError.VALUE),
        ("=+TRUE", True),
        ('=TYPE(+"3")', 2.0),
        ('=NOT(" TRUE ")', ExcelError.VALUE),
        ('=ADDRESS(1,1,1,1,"A Wird One$")', "'A Wird One$'!$A$1"),
        ('=ADDRESS(1,1,1,1,"A1")', "'A1'!$A$1"),
        ('=ADDRESS(1,1,1,1,"a.b")', "a.b!$A$1"),
        ("=XMATCH(2,{1,2;3,4})", ExcelError.VALUE),
        ("=SEQUENCE(-1)", ExcelError.VALUE),
        ("=INDEX(SEQUENCE(,12,,2.5),1,2)", 3.5),
        ('=NUMBERVALUE(" 3 000 ")', 3000.0),
        ('=NUMBERVALUE("3"&CHAR(160)&"000")', ExcelError.VALUE),
        ('=NUMBERVALUE("1.234,5",",;",".;")', 1234.5),
        ('=NUMBERVALUE("1.000,5")', ExcelError.VALUE),
        ('=NUMBERVALUE("1,5",",",",")', ExcelError.VALUE),
        ('=NUMBERVALUE("%")', 0.0),
        ('=NUMBERVALUE("inf")', ExcelError.VALUE),
        ('=TEXTAFTER("a-b-c","")', "a-b-c"),
        ('=TEXTAFTER("a-b-c","",-1)', ""),
        ('=TEXTBEFORE("a-b-c","")', ""),
        ('=TEXTBEFORE("a-b-c","",-100)', "a-b-c"),
        ('=TEXTSPLIT("Hello","")', ExcelError.VALUE),
        ('=INDEX(TEXTSPLIT("1,2.3-4",{",",".","-"}),1,3)', "3"),
        ("=INDEX(WRAPROWS(A1:A3,2,NA()),1,1)", 1.0),
        ('=INDEX(SORT({1;"a";#N/A;#DIV/0!},1,-1),1)', ExcelError.NA),  # errors by code
        ("=LAMBDA(x,ISREF(x))(K1)", True),
        ("=LET(x,A1:A2,ISREF(x))", True),
        ("=LET(x,5,ISREF(x))", False),
        ("=LAMBDA(x,MAX(x))(K1)", 0.0),  # text in a reference is skipped
        ("=LET(x,A2,ROW(x))", 2.0),
    ],
)
def test_excel_batch3(formula, value) -> None:
    got = _ev(formula, {(0, 0): "1", (0, 1): "2", (0, 2): "3", (10, 0): "text"})
    if isinstance(value, (ExcelError, bool)):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-12)
    else:
        assert got == value


# Probed against Excel 16.114 (2026-11-16); IronCalc's T_TEST.xlsx and XMATCH.xlsx.
# A1:B7 pair numbers with logicals and text; D2:D9 hold country names.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=T.TEST(A1:A7,B1:B7,1,1)", 0.15855028798217946),  # pairs with a non-number drop
        ("=T.TEST(A1:A7,B1:B7,2,1)", 0.3171005759643589),
        ("=T.TEST(A1:A7,B1:B6,2,1)", ExcelError.NA),
        ("=DATE(2025,1,32767)", 78424.0),
        ("=DATE(2025,1,1E15)", 78424.0),  # a day past 16 bits reads as 32767
        ("=DATE(2025,1,-40000)", 78424.0),
        ("=DATE(2025,1,-32768)", 12889.0),
        ("=DATE(2025,32766,1)", 1042920.0),
        ("=DATE(2025,32767,1)", ExcelError.NUM),
        ("=DATE(2025,-32768,1)", ExcelError.NUM),
        ("=ERF(7,Z99)", -1.0),  # a blank upper limit is 0
        ("=ERF(7,)", ExcelError.NA),
        ('=XMATCH("[A-Z][a-z]+y",D2:D9,3,1)', 4.0),
        ('=XMATCH("[A-Z][a-z]+y",D2:D9,3,-1)', 8.0),
        ('=XMATCH("[A-Z][a-z]+y",D2:D9,3,2)', ExcelError.VALUE),
        ("=XMATCH(42,D2:D3,3)", ExcelError.NA),
        ('=XLOOKUP("^Ind",D2:D9,D2:D9,,3)', "Indonesia"),
    ],
)
def test_excel_batch4(formula, value) -> None:
    pairs = [
        ("1", "2"),
        ("2", "-3.3"),
        ("3", "0"),
        ("4", "TRUE"),
        ("-3", '"no'),
        ("TRUE", "2"),
        ('"hello', "2"),
    ]
    cells = {(c, r): v for r, row in enumerate(pairs) for c, v in enumerate(row)}
    countries = [
        "Albania",
        "Indonesia",
        "India",
        "Germany",
        "Spain",
        "Venezuela",
        "Italy",
        "Francialy",
    ]
    cells |= {(3, r + 1): name for r, name in enumerate(countries)}
    got = _ev(formula, cells)
    if isinstance(value, ExcelError):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-12)
    else:
        assert got == value


# Probed against Excel 16.114 (2026-11-16). A1:A3 = 1, 2, 3; B1 is ="" and
# B2 FALSE; A4:A5 and Q99 are blank.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=MULTINOMIAL(TRUE,1,2)", ExcelError.VALUE),
        ("=MULTINOMIAL(B1:B2,1)", ExcelError.VALUE),  # a logical or text in a range too
        ('=MULTINOMIAL("2",1)', 3.0),
        ("=MULTINOMIAL(Q99,1)", 1.0),
        ("=MULTINOMIAL(,1)", ExcelError.NA),
        ("=SMALL(TRUE,1)", 1.0),  # typed: converts
        ("=SMALL(B2,1)", ExcelError.NUM),  # read from a cell: no number
        ("=LARGE(B1,1)", ExcelError.NUM),
        ('=SMALL(A1,"1")', 1.0),
        ('=SEARCH("~","Hi ~Bang!")', 1.0),  # a trailing tilde is dropped
        ('=SEARCH("a~","a~b")', 1.0),
        ('=MATCH("~",{"a","~","b"},0)', ExcelError.NA),
        ('=VLOOKUP("a","a",1)', ExcelError.VALUE),  # a scalar table
        ("=VLOOKUP(3,3,0)", ExcelError.NA),
        ('=HLOOKUP("a",TRUE,1)', ExcelError.NA),
        ("=BASE(0,2,0)", ""),
        ("=LEN(BASE(0,2,))", 1.0),  # an omitted length
        ("=LEN(BASE(0,2,Q99))", 0.0),  # a blank length is 0
        ('=ISBLANK("")', False),
        ("=ISBLANK(B1)", False),
        ("=YEARFRAC(1/0,200,5)", ExcelError.NUM),  # basis before the dates
        ('=YEARFRAC(1/0,200,"x")', ExcelError.VALUE),
        ("=YEARFRAC(1/0,200,0)", ExcelError.DIV0),
        ("=DISC(NA(),100,1,1,9)", ExcelError.NUM),
        ("=DURATION(NA(),100,0.05,0.05,2,9)", ExcelError.NA),  # no basis first here
        ("=WEEKNUM(-1,1/0)", ExcelError.NUM),  # a bad first date before a later error
        ('=EDATE(-1,"x")', ExcelError.NUM),
        ("=COUPDAYS(-1,100,2,NA())", ExcelError.NUM),
        ("=WEEKNUM(1,1/0)", ExcelError.DIV0),
        ("=NETWORKDAYS.INTL(DATE(2025,1,1),DATE(2026,1,1),Q99)", ExcelError.NUM),
        ("=NETWORKDAYS.INTL(DATE(2025,1,1),DATE(2026,1,1),)", 262.0),
        ("=WORKDAY.INTL(DATE(2025,1,10),10,)", 45681.0),
        ("=WORKDAY.INTL(DATE(2025,1,10),10,,DATE(2025,1,13))", 45684.0),
        ("=RATE(48,-200,8000,0,0,-1)", ExcelError.VALUE),
        ("=RATE(48,-200,8000,0,0,-0.5)", ExcelError.NUM),
        ('=TEXT(0,"#;-#;m")', "1"),  # a date code in one section
        ('=TEXT(45000,"m")', "3"),
        ('=TEXT(-1,"[s].000")', ExcelError.VALUE),
        ('=TEXT(-1,"[s]")', "-86400"),
        ('=VALUE("23:59.")', 1439 / 1440),  # h:mm, the dot with no digits
        ('=VALUE("23:59.0")', 1439 / 86400),  # m:ss.0
        ("=DROP(A1:A3,3)", ExcelError.CALC),
        ("=TAKE(A1:A3,0)", ExcelError.CALC),
        ("=CHAR(128)", "€"),  # Windows Excel's cp1252
        ("=CHAR(129)", "\x81"),
        ('=CODE("€")', 128.0),
        ("=MATCH(2,{5,4,0,3,1},-1)", 2.0),  # -1 scans: the first smaller value stops it
        ("=MATCH(0,{0,1,2,3,4},-1)", 1.0),
        ("=MATCH(Q99,{4,3,2,1,0},-1)", 5.0),
        ("=MATCH(,A1:A3,-1)", 3.0),
        ("=XLOOKUP(,A1:A5,{10;20;30;40;50})", 40.0),  # a blank finds a blank
        ("=XLOOKUP(5,A1:A5,{10;20;30;40;50},,1)", 40.0),  # a blank ranks above a number
        ('=XLOOKUP("z",A1:A5,{10;20;30;40;50},,1,2)', 40.0),
        ("=XLOOKUP(5,A1:A5,{10;20;30;40;50},,-1,2)", 30.0),
        ("=XLOOKUP(,A1:A5,{10;20;30;40;50},,1,-2)", ExcelError.NA),
        ("=XLOOKUP(Q99,A1:A3,{10;20;30},,-1)", 30.0),
        ("=XLOOKUP(Q99,A1:A3,{10;20;30},,1)", ExcelError.NA),
        ("=XLOOKUP(Q99,A1:A5,{10;20;30;40;50},,0,-1)", 50.0),
        ("=XLOOKUP(Q99,A1:A5,{10;20;30;40;50},,0,-2)", ExcelError.NA),
        ("=XMATCH(,A1:A5,1,2)", 4.0),
        ("=COLUMNS(LOGEST(A1:A3))", 2.0),  # one row, as LINEST
        ("=COUPDAYS(DATE(2024,4,1),DATE(2026,8,31),2,1)", 182.0),
        ("=COUPDAYS(DATE(2024,1,15),DATE(2026,8,30),2,1)", 184.0),
        ("=DURATION(DATE(2024,1,15),DATE(2026,8,30),0.05,0.06,2,0)", 2.445002592587616),
        (
            "=ODDLPRICE(DATE(2024,3,15),DATE(2024,8,30),DATE(2024,2,29),0.05,0.06,100,2,0)",
            99.56214263670627,
        ),
    ],
)
def test_excel_batch5(formula, value) -> None:
    cells = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (1, 0): '=""', (1, 1): "=FALSE"}
    got = _ev(formula, cells)
    if isinstance(value, float) and not isinstance(value, bool):
        assert got == pytest.approx(value, rel=1e-12)
    elif isinstance(value, (bool, ExcelError)):
        assert got is value or got == ("TRUE" if value is True else "FALSE")
    else:
        assert got == value


# Array formulas over whole columns, probed against Excel 16.114 with A1:A3 =
# 1, 2, 3, Z1 = 5, B1 `=""` and B2 `=FALSE`. gridcalc reads `A:A` over the used
# rows only; the rows it leaves out must still count where the function sees them.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=SUMPRODUCT((A:A="")*1)', 1048573.0),
        ('=SUM((A:A="")*1)', 1048573.0),
        ('=COUNT((A:A="")*1)', 1048576.0),
        ("=ROWS(A:A*1)", 1048576.0),
        ('=MAX((A:A<>"")*ROW(A:A))', 3.0),  # the last used row
        ('=ROWS((A:A<>"")*ROW(A:A))', 1048576.0),
        ("=SUM(ISBLANK(A:A)*1)", 1048573.0),  # a lifted function's trimmed rows
        ("=AVERAGE(A:A*1)", 6 / 1048576),
        ('=COUNTA(A:A&"")', 1048576.0),
        ('=ROWS(FILTER(A:A,A:A=""))', 1048573.0),
        ('=ROWS(FILTER(A:A,A:A<>""))', 3.0),
        ("=MIN(A:A+5)", 5.0),
        ('=AND(A:A="")', False),
        ("=PRODUCT(A:A+1)", 24.0),
        ("=SUM(A:A*1)", 6.0),
        # Two whole columns: two million cells, counted rather than padded.
        ('=COUNT((A:B="")*1)', 2097152.0),
        ('=SUM((A:B="")*1)', 2097148.0),
        ('=COUNTA(A:B&"")', 2097152.0),
        ("=SUMSQ(Y:Z+1)", 2097187.0),
        ("=VAR.P(A:A+1)", 1.335140768788e-5),
        ("=VAR.S(A:A+1)", 1.335142042078e-5),
        ("=STDEV.S((A:A>1)*1)", 0.001381067273),
        ("=DEVSQ(A:A+1)", 13.999965667725),
        ("=MEDIAN(A:A+1)", 1.0),
        ("=GEOMEAN(A:A+1)", 1.000003030833),
        ("=HARMEAN(A:A+1)", 1.000001827879),
        ("=MODE(A:A+1)", 1.0),
        ("=LARGE(A:A+1,4)", 1.0),
        ("=LARGE(A:A+1,2)", 3.0),
        ("=SKEW(Y:Z+1)", 1448.154687870378),
        ("=KURT(Y:Z+1)", 2097152.0),
        ("=AVEDEV(Y:Z+1)", 4.768369308294e-6),
        ("=SKEW.P(Y:Z+1)", 1448.153652069224),
        ("=SKEW(A:A+1)", 703.735927553369),
        ("=KURT(A:A+1)", 524285.6632591),
        ("=AVEDEV(A:A+1)", 1.144405905507e-5),
        # Two arrays whose unused rows differ: a split median, a tied mode.
        ("=MEDIAN((A:A>9)*1,Z:Z*0+1)", 0.5),
        ("=MEDIAN(A:A*0+1,Z:Z*2)", 1.0),
        ("=MODE(A:A*0+1,Z:Z*0)", 1.0),
        ("=MODE(Z:Z*0,A:A*0+1)", 0.0),
        ("=MODE.SNGL(A:A+1,Z:Z+3)", 3.0),
        ("=MEDIAN(Y:Z+1,7)", 1.0),
        ("=SKEW(A:A*0)", ExcelError.DIV0),
        ('=AVERAGEA((A:B="")*1)', 0.999998092651),
        ('=SUMPRODUCT((Y:Z="")*1,(Y:Z="")*2)', 4194302.0),
        ("=AVEDEV(A:A*0+1,TRUE)", 0.0),
        ('=SKEW(A:A+1,"5")', 623.185365679472),
        ("=MEDIAN(A:A+1,TRUE)", 1.0),
        # Lookups: the trimmed rows matter only where they hold the value sought.
        ("=XLOOKUP(0,(A:A=2)*1,Z:Z)", 5.0),
        ("=XLOOKUP(1,(A:A=2)*1,Z:Z)", 0.0),
        ("=MATCH(0,(A:A=1)*1,0)", 2.0),
        # IF, IFERROR and SWITCH keep the value of the trimmed rows.
        ("=SUM(IF(ISBLANK(A:A),1,0))", 1048573.0),
        ("=SUM(IFERROR(1/(A:A*1),7))", 7340012.833333333),
        ('=SUM(IF(A:A="",ROW(A:A),0))', 549756338170.0),
        ("=SUM(SWITCH(A:A,1,1,2))", 2097151.0),
        # Text: "" adds nothing; anything else passes the 32767-character limit.
        ('=TEXTJOIN(",",TRUE,A:B&"")', "1,2,FALSE,3"),
        ('=CONCAT(A:B&"")', "12FALSE3"),
        ('=TEXTJOIN(",",FALSE,A:A&"")', ExcelError.CALC),
        ('=CONCAT(A1:A40000&"x")', ExcelError.CALC),
        # An error in the unused rows propagates; only COUNT skips it.
        ("=SUM(1/A:A)", ExcelError.DIV0),
        ("=AVERAGE(1/A:A)", ExcelError.DIV0),
        ("=SUMPRODUCT(1/A:A)", ExcelError.DIV0),
        ("=SUMPRODUCT(A:A,1/Y:Y)", ExcelError.DIV0),
        ("=MAX(1/A:A)", ExcelError.DIV0),
        ("=CONCAT(1/A:A)", ExcelError.DIV0),
        ("=COUNT(1/A:A)", 3.0),
        # Past one column a function with no shortcut reads the used rows.
        ("=INDEX(A:B*2,1,1)", 2.0),
    ],
)
def test_whole_column_array_counts_its_unused_rows(formula, value) -> None:
    cells = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (25, 0): "5", (1, 0): '=""', (1, 1): "=FALSE"}
    got = _ev(formula, cells)
    if isinstance(value, float):
        assert got == pytest.approx(value)
    else:
        assert got == value if isinstance(value, str) else got is value


# Probed against Excel 16.114 with B1:B5 = 1..5: a trimmed array beside a
# full-height one, such as `ROW(B:B)`, lines up with it.
@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=SUMPRODUCT(--(B:B<>""),ROW(B:B))', 15.0),
        ('=ROWS(FILTER(ROW(B:B),B:B<>""))', 5.0),
        ("=XLOOKUP(3,B:B*1,ROW(B:B))", 3.0),
        ("=XLOOKUP(3,B:B,ROW(B:B))", 3.0),
        ('=XLOOKUP("",B:B,ROW(B:B))', ExcelError.NA),
        ("=SUMPRODUCT(B:B,ROW(B:B))", 55.0),
        ("=SUM(IF(ROW(B:B)>2,B:B*2,0))", 24.0),
        ("=SUM(IFERROR(ROW(B:B)/(B:B>0),B:B*0+1))", 1048586.0),
        ('=TEXTJOIN(",",FALSE,B:B)', ExcelError.CALC),
        ('=LEN(TEXTJOIN(",",TRUE,B:B))', 9.0),
    ],
)
def test_a_trimmed_array_lines_up_with_a_full_height_one(formula, value) -> None:
    got = _ev(formula, {(1, r): str(r + 1) for r in range(5)})
    assert got == pytest.approx(value) if isinstance(value, float) else got is value
