"""Math, engineering and statistics fixes from the Excel-saved corpus workbooks.

Expected values are Excel's saved results, from the IronCalc `calc_tests`
workbooks (GCD_LCM, NUMBER_SYSTEMS, BASE_DECIMAL, MROUND_TRUNC_INT, CONVERT,
COMPLEXs, T_DIST, BETADIST_BETAINV, GAMMA) and pycel `stats.xlsx`.
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


def _check(got, value) -> None:
    if isinstance(value, ExcelError):
        assert got is value
    elif isinstance(value, float):
        assert got == pytest.approx(value, rel=1e-9)
    else:
        assert got == value


A1, B1, C1 = (0, 0), (1, 0), (2, 0)


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        ('=LCM({4,"8",12})', None, 24.0),
        ('=LCM({4,"2024-01-10",12})', None, 543612.0),
        ('=GCD({4,"eight",12})', None, ExcelError.VALUE),
        ("=LCM({4,TRUE,12})", None, ExcelError.VALUE),
        ("=LCM(A1,B1)", {A1: '="8"', B1: "2"}, 8.0),
        ("=GCD(A1,B1)", {A1: '=""', B1: "10"}, ExcelError.VALUE),
        ("=GCD(A1,B1)", {A1: "TRUE", B1: "2"}, ExcelError.VALUE),
        ("=GCD(,5)", None, ExcelError.NA),
        # A blank direct reference is skipped; a blank in a range is 0.
        ("=LCM(A1,B1)", {B1: "5"}, 5.0),
        ("=LCM(A1:B1)", {B1: "5"}, 0.0),
        ("=LCM(A1,B1,C1)", {}, ExcelError.VALUE),
        ("=GCD(A1:B1)", {}, 0.0),
        ("=LCM(2^31-1,2^30-1)", None, ExcelError.NUM),
    ],
)
def test_gcd_lcm(formula, cells, value) -> None:
    _check(_ev(formula, cells), value)


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        ("=BIN2DEC(A1)", {A1: "TRUE"}, ExcelError.VALUE),
        ("=DEC2BIN(A1)", {A1: "TRUE"}, ExcelError.VALUE),
        ("=DEC2BIN(A1,B1)", {A1: "12"}, ExcelError.NUM),  # blank places is 0
        ("=DEC2BIN(12)", None, "1100"),
        ("=BIN2HEX(1100011011,-2)", None, ExcelError.NUM),
        ("=BIN2HEX(1100011011,1)", None, "FFFFFFFF1B"),
        ("=BIN2HEX(1100011011,A1)", {A1: "TRUE"}, ExcelError.VALUE),
        ("=BIN2OCT(A1)", {}, "0"),
        ("=DEC2OCT(536870911)", None, "3777777777"),
        ("=DEC2OCT(536870912)", None, ExcelError.NUM),
        ("=DEC2HEX(549755813887)", None, "7FFFFFFFFF"),
        ('=HEX2OCT("01fffffff")', None, "3777777777"),
        ("=BASE(-0.5,2)", None, ExcelError.NUM),
        ("=BASE(5,2,-0.5)", None, ExcelError.NUM),
        ('=DECIMAL(" 10",2)', None, 2.0),
        ('=DECIMAL(" 10  ",2)', None, ExcelError.NUM),
        ('=DECIMAL(REPT("0",255)&"1",2)', None, ExcelError.VALUE),
    ],
)
def test_number_bases(formula, cells, value) -> None:
    _check(_ev(formula, cells), value)


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        ("=MROUND(,5)", None, ExcelError.NA),
        ("=MROUND(5,)", None, ExcelError.NA),
        ("=MROUND(A1,2)", {A1: "TRUE"}, ExcelError.VALUE),
        ("=MROUND(A1,2)", {}, 0.0),
        ("=INT(A1)", {A1: '="8"'}, 8.0),
        ("=INT(A1)", {A1: '="2024-01-10"'}, 45301.0),
        ("=INT(A1)", {A1: "TRUE"}, 1.0),
        ("=INT(A1)", {A1: '=""'}, ExcelError.VALUE),
    ],
)
def test_mround_int(formula, cells, value) -> None:
    _check(_ev(formula, cells), value)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=CONVERT(1,"Mly","m")', 9.4607304725808e21),
        ('=CONVERT(1,"ft^2","m2")', 0.09290304),
        ('=CONVERT(1,"Pica2","m2")', 1.2445216049382715e-07),
        ('=CONVERT(0.05,"Mm2","m2")', 5e10),  # the prefix is squared
        ('=CONVERT(0.05,"Mang^2","m2")', 5e-10),
        ('=CONVERT(0.05,"Mar","m2")', 5e6),
        ('=CONVERT(0.05,"Mft2","m2")', ExcelError.NA),
        ('=CONVERT(1,"ly3","m3")', 8.467866646237152e47),
        ('=CONVERT(0.0002,"Mm^3","m3")', 2e14),
        ('=CONVERT(0.0002,"Muk_pt","m3")', 0.11365225000000002),
        ('=CONVERT(1,"m/hr","m/s")', 0.0002777777777777778),
        ('=CONVERT(0.004,"Mmph","m/s")', 1788.16),
        ('=CONVERT(12,"Mkel","K")', 12000000.0),
        ('=CONVERT(12,"MC","K")', ExcelError.NA),
        ('=CONVERT(1,"mmHg","Pa")', 133.322),
    ],
)
def test_convert(formula, value) -> None:
    _check(_ev(formula), value)


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        ('=IMCONJUGATE("1-2j")', None, "1+2j"),
        ('=IMCONJUGATE("j")', None, "-j"),
        ('=IMCOT("0")', None, ExcelError.NUM),
        ('=IMCSC("0")', None, ExcelError.NUM),
        ('=IMCSCH("0")', None, ExcelError.NUM),
        ("=IMSUM(A1,B1)", {A1: "7"}, "7"),
        ("=IMPRODUCT(A1,B1)", {A1: "7"}, "0"),
        ("=IMSUB(A1,B1)", {}, "0"),
    ],
)
def test_complex(formula, cells, value) -> None:
    _check(_ev(formula, cells), value)


_Y = "{1,2.1,3.1,4.1,5.1}"
_X = "{-2,-4,-7,-9,-11}"


@pytest.mark.parametrize(
    ("formula", "cells", "value"),
    [
        # A single-row y takes its regressors from the rows of x.
        (f"=INDEX(LINEST({_Y},{_X}),1,1)", None, -0.4409774436090227),
        (f"=INDEX(TREND({_Y},{_X},{{2.5,3.5}}),1,1)", None, -0.9328947368421063),
        (f"=INDEX(LINEST({_Y},{{-2,-4,-7,-9,-11;1,3,6,9,12}}),1,1)", None, 0.14374999999999988),
        (f"=INDEX(LINEST({_Y},{{-2,-4,-7,-9,-11;1,3,6,9,12}}),1,2)", None, -0.2669642857142858),
        (f"=INDEX(LINEST({_Y},{{-2,-4,-7,-9,-11;1,3,6,9,12}}),1,3)", None, 0.42678571428571443),
        # A constant regressor is dropped: slope 0, intercept the mean.
        ("=INDEX(LINEST({1,3,6,9,12},{1,1,1,1,1}),1,1)", None, 0.0),
        ("=INDEX(LINEST({1,3,6,9,12},{1,1,1,1,1}),1,2)", None, 6.2),
        ("=INDEX(TREND({1;2;3},{2,3;2,3;2,3}),1,1)", None, 2.0),
        ("=INDEX(LINEST({1;2;3},{2,3;2,3;2,3},,TRUE),1,3)", None, 2.0),
        ("=LINEST({1,2,3,4,5},{1,2,3,4})", None, ExcelError.REF),
        ("=TREND({1,2,3,4,5},{1,2,3,4},2.5)", None, ExcelError.REF),
        (
            "=LINEST(A1:A3,B1:B3)",
            {(0, 0): "1", (0, 1): "2", (1, 0): "1", (1, 1): "2", (1, 2): "3"},
            ExcelError.VALUE,
        ),
        ("=SLOPE({1,2,3},{1,2})", None, ExcelError.NA),
        ("=INTERCEPT({1,2,3},{1,2,3,4})", None, ExcelError.NA),
        ("=FORECAST(2.5,{1,2,3},{1,2})", None, ExcelError.NA),
    ],
)
def test_regression(formula, cells, value) -> None:
    _check(_ev(formula, cells), value)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # Degrees of freedom are truncated.
        ("=T.DIST(3,5.2,TRUE)", 0.9849503760512687),
        ("=T.DIST(-2,5.2,FALSE)", 0.0650903103262165),
        ("=T.DIST.RT(1,10.999999)", 0.17044656615102993),
        ("=T.DIST(1,1.000001,TRUE)", 0.75),
        ("=T.DIST(1,0.999999,TRUE)", ExcelError.NUM),
        ("=T.DIST.2T(3,5.2)", 0.030099247897462586),
        ('=T.DIST(1,10,"true")', 0.8295534338489701),
        ('=T.DIST(1,10,"abc")', ExcelError.VALUE),
        ("=T.INV(1.230468749943611E-56,10)", -1000000.0000000001),
        ("=T.INV(1E-07,10)", -12.492209687558763),
        ("=T.INV(0.500000389989757,11)", 9.999999999666944e-07),
        ("=GAMMA.INV(1,9,2)", ExcelError.NUM),
        ("=GAMMA.INV(2.755707120924027E-51,9,1000000)", 9.999999999999998),
        ("=GAMMA.INV(1E-07,9,2)", 1.4902187371078093),
        ("=GAMMA.DIST(0,0.5,1,FALSE)", ExcelError.NUM),
        ('=GAMMA.DIST(10,9,2,"abc")', ExcelError.VALUE),
        ("=BETA.INV(0,1,2,1,10)", ExcelError.NUM),
        ("=BETA.INV(1,1,2,0,1)", ExcelError.NUM),
        ("=BETA.INV(2.3817091316180232E-30,100,1,0.1,1)", 0.555),
        ("=BETA.INV(4.688385940594357E-12,2,2.5,0.234,1.2)", 0.234001),
        ('=BETA.DIST(0.234,2,2.5,"abc",0.15,1.2)', ExcelError.VALUE),
    ],
)
def test_distributions(formula, value) -> None:
    _check(_ev(formula), value)
