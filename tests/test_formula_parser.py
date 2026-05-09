import pytest

from gridcalc.formula.ast_nodes import (
    BinOp,
    Bool,
    Call,
    CellRef,
    ErrorLit,
    Name,
    Number,
    Percent,
    PyCall,
    RangeRef,
    String,
    UnaryOp,
)
from gridcalc.formula.errors import ExcelError
from gridcalc.formula.parser import ParseError, parse


class TestParseLiterals:
    def test_number(self):
        assert parse("42") == Number(42.0)

    def test_string(self):
        assert parse('"hi"') == String("hi")

    def test_bool(self):
        assert parse("TRUE") == Bool(True)

    def test_error(self):
        assert parse("#DIV/0!") == ErrorLit(ExcelError.DIV0)

    def test_leading_equals(self):
        assert parse("=42") == Number(42.0)


class TestParseRefs:
    def test_cellref(self):
        assert parse("A1") == CellRef(0, 0, False, False)

    def test_absolute(self):
        assert parse("$B$3") == CellRef(1, 2, True, True)

    def test_range(self):
        n = parse("A1:B3")
        assert n == RangeRef(CellRef(0, 0, False, False), CellRef(1, 2, False, False))

    def test_named(self):
        assert parse("myrange") == Name("myrange")

    def test_sheet_qualified_cellref(self):
        assert parse("Sheet2!A1") == CellRef(0, 0, False, False, sheet="Sheet2")

    def test_sheet_qualified_cellref_absolute(self):
        assert parse("Data!$B$3") == CellRef(1, 2, True, True, sheet="Data")

    def test_sheet_qualified_range_prefix_propagates(self):
        n = parse("Sheet2!A1:B3")
        assert n == RangeRef(
            CellRef(0, 0, False, False, sheet="Sheet2"),
            CellRef(1, 2, False, False, sheet="Sheet2"),
        )

    def test_sheet_qualified_range_redundant_prefix_ok(self):
        # Excel accepts Sheet2!A1:Sheet2!B3 (same sheet on both sides).
        n = parse("Sheet2!A1:Sheet2!B3")
        assert n == RangeRef(
            CellRef(0, 0, False, False, sheet="Sheet2"),
            CellRef(1, 2, False, False, sheet="Sheet2"),
        )

    def test_cross_sheet_range_rejected(self):
        import pytest

        with pytest.raises(Exception, match="cross-sheet"):
            parse("Sheet1!A1:Sheet2!B5")

    def test_unsheeted_range_with_sheeted_end_rejected(self):
        import pytest

        with pytest.raises(Exception, match="cross-sheet"):
            parse("A1:Sheet2!B5")


class TestParseOperators:
    def test_addition(self):
        assert parse("1+2") == BinOp("+", Number(1.0), Number(2.0))

    def test_left_assoc_additive(self):
        # 1-2-3 -> ((1-2)-3)
        n = parse("1-2-3")
        assert n == BinOp("-", BinOp("-", Number(1.0), Number(2.0)), Number(3.0))

    def test_precedence_mul_over_add(self):
        # 1+2*3 -> 1 + (2*3)
        n = parse("1+2*3")
        assert n == BinOp("+", Number(1.0), BinOp("*", Number(2.0), Number(3.0)))

    def test_paren_overrides(self):
        n = parse("(1+2)*3")
        assert n == BinOp("*", BinOp("+", Number(1.0), Number(2.0)), Number(3.0))

    def test_exp_right_assoc(self):
        # 2^3^2 -> 2^(3^2) -> 512 semantically
        n = parse("2^3^2")
        assert n == BinOp("^", Number(2.0), BinOp("^", Number(3.0), Number(2.0)))

    def test_unary_minus(self):
        assert parse("-3") == UnaryOp("-", Number(3.0))

    def test_unary_in_expr(self):
        # 2^-3 -> 2^(unary-3)
        n = parse("2^-3")
        assert n == BinOp("^", Number(2.0), UnaryOp("-", Number(3.0)))

    def test_percent(self):
        # 50% -> Percent(50)
        assert parse("50%") == Percent(Number(50.0))

    def test_percent_postfix_chain(self):
        # 50%% (silly but legal) -> Percent(Percent(50))
        assert parse("50%%") == Percent(Percent(Number(50.0)))

    def test_concat(self):
        assert parse('"a"&"b"') == BinOp("&", String("a"), String("b"))

    def test_compare(self):
        n = parse("A1<>B1")
        assert n == BinOp("<>", CellRef(0, 0, False, False), CellRef(1, 0, False, False))

    def test_compare_all_ops(self):
        for op in ["=", "<>", "<", ">", "<=", ">="]:
            n = parse(f"1{op}2")
            assert isinstance(n, BinOp) and n.op == op


class TestParseCalls:
    def test_no_args(self):
        assert parse("NOW()") == Call("now", ())

    def test_one_arg(self):
        assert parse("ABS(-1)") == Call("abs", (UnaryOp("-", Number(1.0)),))

    def test_multiple_args(self):
        n = parse("SUM(A1, B2, 3)")
        assert n == Call(
            "sum",
            (
                CellRef(0, 0, False, False),
                CellRef(1, 1, False, False),
                Number(3.0),
            ),
        )

    def test_function_name_lowercased(self):
        # function names are case-insensitive
        n = parse("Sum(1)")
        assert isinstance(n, Call) and n.name == "sum"

    def test_nested(self):
        n = parse("IF(A1>0, SUM(B1:B10), 0)")
        assert isinstance(n, Call) and n.name == "if"
        assert len(n.args) == 3

    def test_range_arg(self):
        n = parse("SUM(A1:B3)")
        assert n == Call(
            "sum",
            (RangeRef(CellRef(0, 0, False, False), CellRef(1, 2, False, False)),),
        )


class TestParsePyCall:
    def test_simple(self):
        n = parse("py.foo(1)")
        assert n == PyCall("foo", (Number(1.0),))

    def test_no_args(self):
        assert parse("py.bar()") == PyCall("bar", ())

    def test_py_alone_is_name(self):
        # 'py' without dot+ident is just a Name
        assert parse("py") == Name("py")

    def test_py_dot_requires_ident(self):
        with pytest.raises(ParseError):
            parse("py.()")


class TestParseErrors:
    def test_unbalanced_paren(self):
        with pytest.raises(ParseError):
            parse("(1+2")

    def test_trailing_garbage(self):
        with pytest.raises(ParseError):
            parse("1+2 3")

    def test_trailing_comma(self):
        with pytest.raises(ParseError):
            parse("SUM(1,2,)")

    def test_empty(self):
        with pytest.raises(ParseError):
            parse("")

    def test_range_needs_cellref_after_colon(self):
        with pytest.raises(ParseError):
            parse("A1:5")
