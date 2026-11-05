"""Financial functions against Excel's saved results.

Expected values come from the IronCalc FINANCIAL test workbooks
(`docs/dev/excel-corpus.md`), which Excel saved.
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


def _check(formula: str, value, cells=None, rel: float = 1e-9) -> None:
    got = _ev(formula, cells)
    if isinstance(value, ExcelError):
        assert got is value
    else:
        assert got == pytest.approx(value, rel=rel, abs=1e-12)


_ODDF = "DATE(2020,3,1),DATE(2030,3,1),DATE(2020,1,15),DATE(2021,3,1)"
_ODDL = "DATE(2020,3,1),DATE(2030,3,1),DATE(2020,1,15)"
_PRICE = "DATE(2020,3,1),DATE(2030,3,1)"


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # rate <= -1 and nper == 0 are #NUM!
        ("=PMT(-3,5,100,300,1)", ExcelError.NUM),
        ("=PMT(-1,1,-100)", ExcelError.NUM),
        ("=PMT(0.02,0,100,300,1)", ExcelError.NUM),
        ("=PMT(0,0,-150,10,1)", ExcelError.NUM),
        ("=FV(-1,-2,1)", ExcelError.DIV0),
        ("=RATE(10,-1200,2000,0,1)", ExcelError.NUM),
        # per outside [1, nper+1) is #NUM!; a fractional per is not truncated
        ("=IPMT(0.1,-3,36,8000)", ExcelError.NUM),
        ("=IPMT(0.1,3,2,8000,0,1)", ExcelError.NUM),
        ("=IPMT(0.01,0.99999,36,8000)", ExcelError.NUM),
        ("=IPMT(0.1,3.3,30,8000,10,1)", -716.4227794432131),
        ("=IPMT(0.01,1.0001,36,8000,0,1)", -79.2077378295619),
        ("=PPMT(0.1,3.9,3,8000,10,1)", -2900.351432640776),
        ("=PPMT(0.1,2.8,30,8000,100,0)", -58.45770089045371),
        # start rounds up, end truncates, nper may be fractional, type is 0 or 1
        ("=CUMPRINC(0.01,36,8000,1.2,8.53,1)", -1339.6579298169904),
        ("=CUMIPMT(0.8,36,18000,2.7,9.667,1)", -55999.99877582575),
        ("=CUMIPMT(0.1,29.9,8000,3,10,1)", -5557.470043410287),
        ("=CUMIPMT(0.3,12,8000,5.1,5,1)", ExcelError.NUM),
        ("=CUMPRINC(0.01,36,8000,3,10,1.2)", ExcelError.NUM),
        ("=CUMPRINC(0.01,36,8000,3,10,0.7)", ExcelError.NUM),
    ],
)
def test_annuities(formula, value) -> None:
    _check(formula, value)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # PRICE discounts by (E - A) / E for bases 2 and 3
        (f"=PRICE({_PRICE},0.04,0.05,155,1,2)", 126.04349401555694),
        (f"=PRICE({_PRICE},0.06,0.07,23,2,3)", 54.196225247785335),
        (
            "=PRICE(DATE(2025,4,1),DATE(2028,3,13),0.22,0.12,15,1,2)",
            62.736929069290866,
        ),
        (f"=ODDFPRICE({_ODDF},0.075,0.067,120,1,2)", 115.98854775223758),
        (f"=ODDFPRICE({_ODDF},0.075,0.067,1E-19,1,2)", 53.30610981955664),
        (f"=ODDLPRICE({_ODDL},0.075,0.0589,120,2,2)", 122.36705839417525),
        (f"=ODDLPRICE({_ODDL},0.08,0.0711,120,1,3)", 116.47338382128387),
        (f"=ODDLYIELD({_ODDL},0.075,121.51937811334447,120,2,1)", 0.05999999999999999),
        (f"=ODDLYIELD({_ODDL},0.075,162.34027777777777,120,1,4)", 0.020000000000000004),
        (f"=ODDFYIELD({_ODDF},0.075,131.5377155865953,120,1,1)", 0.04999999999851281),
        (f"=ODDFYIELD({_ODDF},0.08,125.83100063105158,120,1,3)", 0.05999999999854355),
        (f"=ODDFYIELD({_ODDF},0.075,115,120,1,5)", ExcelError.NUM),
    ],
)
def test_bonds(formula, value) -> None:
    _check(formula, value)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        # past 182 days TBILLEQ solves a quadratic; maturity may be a full year later
        ("=TBILLEQ(2040,2400,0.8)", 2.5066048253748145),
        ("=TBILLEQ(2040,2223,0.8)", 1.364497682211261),
        ("=TBILLEQ(45332,45650,0.1)", 0.10869554506360148),
        ("=TBILLEQ(14640,15006,0.5)", 0.8522961312491701),
        ("=TBILLPRICE(14640,15006,0.5)", 49.16666666666667),
        ("=TBILLYIELD(14640,15006,3000)", -0.9508196721311475),
        ("=TBILLEQ(1000,1366,0.5)", ExcelError.NUM),
        ("=TBILLPRICE(45332,45650,7)", ExcelError.NUM),
    ],
)
def test_tbills(formula, value) -> None:
    _check(formula, value)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=IRR({-20,5,5,5,5,5},17)", 0.07930826116414913),
        ("=IRR({-70,12,15})", -0.44350694133432755),
        ("=IRR({-20,5,5,-10,5})", -0.44892834955312866),
        ("=IRR({-400,1,1,1,1,1})", -0.6737366751808405),
        ("=IRR({-5,1})", -0.8),
        ("=IRR({-1000,230,200,125,200,10},-10)", ExcelError.VALUE),
        ("=IRR({-20,5,5,-10,5},-1)", ExcelError.VALUE),
        # rates <= -1 are allowed; no positive flow gives -1
        ("=MIRR({-5,4},-1,0.2)", -0.19999999999999996),
        ("=MIRR({-5,-3},0.1,0.2)", -1.0),
        ("=MIRR({-50,25,30},-12,-0.4)", -0.05131670194948612),
        ("=MIRR({-20,5,5,5,5,5},-0.5,2)", 0.9776301558892315),
        ("=MIRR({-1000,230,200,125,200,10},-1,2)", 0.9151642637250201),
        ("=MIRR({20,10,30,10,20,5},-2,2)", ExcelError.DIV0),
        ("=NOMINAL(0,10)", ExcelError.NUM),
        ("=EFFECT(0,10)", ExcelError.NUM),
        ("=DB(0,10,4,1,2)", 0.0),
        ("=DB(100,10.233,4.2312,3.2,12)", 14.1733713),
        ("=DDB(100,10.233,4.2312,3.2,1.5)", 13.532735530775124),
        ("=DDB(12,10,4,4.5,2)", ExcelError.NUM),
    ],
)
def test_rates_and_depreciation(formula, value) -> None:
    _check(formula, value)


def _row(values, dates) -> dict[tuple[int, int], str]:
    cells = {(c, 0): v for c, v in enumerate(values) if v is not None}
    cells.update({(c, 1): d for c, d in enumerate(dates)})
    return cells


_DATES = ["44958", "44986", "45017", "45078", "45108", "45139"]  # 2023-02-01 .. 2023-08-01


def test_xirr_xnpv() -> None:
    # Excel's XIRR stops ~1e-9 short of the root; rel=1e-8 covers it.
    unsorted = _row(["-55", "10", "5", "5", "5", "5"], ["100", "120", "300", "101", "200", "150"])
    _check("=XIRR(A1:F1,A2:F2)", -0.9271996639668942, unsorted, rel=1e-8)
    # Fractional dates truncate.
    frac = _row(
        ["-20", "9", "9", "9", "9", "9"], ["23", "23.67", "123.69", "400.992", "500", "500"]
    )
    _check("=XNPV(0.2,A1:F1,A2:F2)", 19.200525492837638, frac)
    _check("=XIRR(A1:F1,A2:F2)", 3.131423544883728, frac, rel=1e-8)
    loss = _row(["-400", "100", "10", "5", "6", "5"], _DATES)
    _check("=XNPV(-0.4,A1:F1,A2:F2)", ExcelError.NUM, loss)
    _check("=XIRR(A1:F1,A2:F2)", -0.9977533546974883, loss, rel=1e-8)
    # A blank is #NUM! in XNPV and 0 in XIRR; text is #VALUE! in XIRR.
    gap = _row(["-20", "5", "5", None, None, "5"], _DATES)
    _check("=XNPV(1,A1:F1,A2:F2)", ExcelError.NUM, gap)
    text = _row(["-70", "12", "15", "hello", "5", "5"], _DATES)
    _check("=XNPV(0.1,A1:F1,A2:F2)", ExcelError.NUM, text)
    _check("=XIRR(A1:F1,A2:F2)", ExcelError.VALUE, text)
    bad = _row(["-20", "8", "8", "8", "8", "8"], ["-100", "1", "2", "3", "4", "5"])
    _check("=XNPV(0.1,A1:F1,A2:F2)", ExcelError.NUM, bad)
    _check("=XIRR(A1:F1,A2:F2)", ExcelError.NUM, bad)


@pytest.mark.parametrize(
    "formula",
    [
        "=CUMIPMT(0.01,36,8000,A1,10,0)",
        "=CUMPRINC(0.0083,36,8000,3,10,A1)",
        "=TBILLEQ(A1,45731,0.5)",
        "=TBILLPRICE(45366,45731,A1)",
        "=NOMINAL(10,A1)",
        "=EFFECT(A1,2.9)",
    ],
)
def test_logical_cells_are_value_errors(formula) -> None:
    assert _ev(formula, {(0, 0): "TRUE"}) is ExcelError.VALUE
