import pytest

from gridcalc.formula.ast_nodes import (
    Apply,
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
from gridcalc.formula.errors import ExcelError, FormulaError
from gridcalc.formula.parser import ParseError, parse


class TestParseApply:
    def test_lambda_direct_application(self) -> None:
        # LAMBDA(x, x+1)(5) -> Apply(Call("lambda", ...), (Number 5,)).
        n = parse("LAMBDA(x, x+1)(5)")
        assert isinstance(n, Apply)
        assert isinstance(n.func, Call)
        assert n.func.name == "lambda"
        assert n.args == (Number(5.0),)

    def test_parenthesized_application(self) -> None:
        n = parse("(LAMBDA(x, x))(9)")
        assert isinstance(n, Apply)
        assert n.args == (Number(9.0),)

    def test_chained_application(self) -> None:
        # A curried lambda applied twice: f(1)(2).
        n = parse("LAMBDA(x, LAMBDA(y, x+y))(1)(2)")
        assert isinstance(n, Apply)
        assert n.args == (Number(2.0),)
        assert isinstance(n.func, Apply)
        assert n.func.args == (Number(1.0),)

    def test_ordinary_call_is_not_apply(self) -> None:
        assert isinstance(parse("SUM(A1:A3)"), Call)


class TestParseSpillRef:
    def test_spill_ref(self) -> None:
        from gridcalc.formula.ast_nodes import SpillRef

        n = parse("A1#")
        assert n == SpillRef(CellRef(0, 0, False, False))

    def test_spill_ref_inside_call(self) -> None:
        from gridcalc.formula.ast_nodes import SpillRef

        n = parse("SUM(B2#)")
        assert isinstance(n, Call)
        assert n.args == (SpillRef(CellRef(1, 1, False, False)),)

    def test_plain_ref_is_not_spill(self) -> None:
        assert isinstance(parse("A1"), CellRef)


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


class TestQuotedSheetNames:
    """`'My Sheet'!A1` is the standard way to name a sheet whose name is not
    an identifier. A sheet with a space was creatable and importable from xlsx
    but could not be referenced from any formula, which made it unreachable."""

    def test_quoted_sheet_cellref(self):
        n = parse("'My Sheet'!A1")
        assert isinstance(n, CellRef)
        assert n.sheet == "My Sheet"

    def test_quoted_sheet_range(self):
        n = parse("'My Sheet'!A1:B2")
        assert isinstance(n, RangeRef)
        assert n.start.sheet == "My Sheet"

    def test_doubled_apostrophe_is_a_literal_apostrophe(self):
        n = parse("'It''s'!A1")
        assert isinstance(n, CellRef)
        assert n.sheet == "It's"

    def test_quoted_sheet_inside_a_call(self):
        n = parse("SUM('My Sheet'!A1:A3)")
        assert isinstance(n, Call)

    def test_unquoted_sheet_still_parses(self):
        n = parse("MySheet!A1")
        assert isinstance(n, CellRef)
        assert n.sheet == "MySheet"

    def test_unterminated_quote_is_an_error(self):
        with pytest.raises((FormulaError, ParseError)):
            parse("'My Sheet!A1")


class TestBooleanCallForm:
    """Excel spells the boolean literals both `TRUE` and `TRUE()`. The lexer
    resolves the bare word to a BOOL token before any function name is
    considered, so the call form has to be accepted where the literal is."""

    @pytest.mark.parametrize("src,expected", [("TRUE()", True), ("FALSE()", False)])
    def test_call_form_is_the_literal(self, src, expected):
        n = parse(src)
        assert isinstance(n, Bool)
        assert n.value is expected

    @pytest.mark.parametrize("src,expected", [("TRUE", True), ("FALSE", False)])
    def test_bare_form_still_works(self, src, expected):
        n = parse(src)
        assert isinstance(n, Bool)
        assert n.value is expected

    def test_call_form_nests(self):
        assert isinstance(parse("IF(TRUE(),1,2)"), Call)

    def test_arguments_do_not_make_it_a_literal(self):
        """Only the empty call form is the literal. `TRUE(1)` stays a generic
        application, which the evaluator refuses with #VALUE! -- Excel's
        answer too."""
        assert not isinstance(parse("TRUE(1)"), Bool)
