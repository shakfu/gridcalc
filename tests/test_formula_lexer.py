import pytest

from gridcalc.formula.errors import ExcelError, FormulaError
from gridcalc.formula.lexer import (
    AMP,
    BANG,
    BOOL,
    CARET,
    CELLREF,
    COLON,
    COMMA,
    DOT,
    EOF,
    EQ,
    ERROR_LIT,
    GE,
    GT,
    IDENT,
    LE,
    LPAREN,
    LT,
    MINUS,
    NE,
    NUMBER,
    PERCENT,
    PLUS,
    RPAREN,
    SLASH,
    STAR,
    STRING,
    tokenize,
)


def kinds(text):
    return [t.kind for t in tokenize(text) if t.kind != EOF]


class TestLexerBasic:
    def test_empty(self):
        toks = tokenize("")
        assert len(toks) == 1
        assert toks[0].kind == EOF

    def test_strips_leading_equals(self):
        toks = tokenize("=1+2")
        assert [t.kind for t in toks] == [NUMBER, PLUS, NUMBER, EOF]

    def test_optional_leading_equals(self):
        assert kinds("1+2") == [NUMBER, PLUS, NUMBER]

    def test_whitespace_ignored(self):
        assert kinds("  1  +  2  ") == [NUMBER, PLUS, NUMBER]


class TestLexerNumbers:
    def test_int(self):
        t = tokenize("42")[0]
        assert t.kind == NUMBER and t.value == 42.0

    def test_float(self):
        t = tokenize("3.14")[0]
        assert t.kind == NUMBER and t.value == 3.14

    def test_leading_dot(self):
        t = tokenize(".5")[0]
        assert t.kind == NUMBER and t.value == 0.5

    def test_exponent(self):
        t = tokenize("1.5e3")[0]
        assert t.kind == NUMBER and t.value == 1500.0

    def test_negative_exponent(self):
        t = tokenize("2e-2")[0]
        assert t.kind == NUMBER and t.value == 0.02


class TestLexerStrings:
    def test_simple(self):
        t = tokenize('"hello"')[0]
        assert t.kind == STRING and t.value == "hello"

    def test_embedded_quote(self):
        t = tokenize('"a""b"')[0]
        assert t.kind == STRING and t.value == 'a"b'

    def test_unterminated(self):
        with pytest.raises(FormulaError):
            tokenize('"oops')


class TestLexerBools:
    def test_true(self):
        t = tokenize("TRUE")[0]
        assert t.kind == BOOL and t.value is True

    def test_false_lower(self):
        t = tokenize("false")[0]
        assert t.kind == BOOL and t.value is False


class TestLexerCellRefs:
    def test_a1(self):
        t = tokenize("A1")[0]
        assert t.kind == CELLREF
        assert t.value == (0, 0, False, False)

    def test_z1(self):
        t = tokenize("Z1")[0]
        assert t.value == (25, 0, False, False)

    def test_aa1(self):
        t = tokenize("AA1")[0]
        assert t.value == (26, 0, False, False)

    def test_absolute_col(self):
        t = tokenize("$A1")[0]
        assert t.value == (0, 0, True, False)

    def test_absolute_row(self):
        t = tokenize("A$1")[0]
        assert t.value == (0, 0, False, True)

    def test_both_absolute(self):
        t = tokenize("$A$1")[0]
        assert t.value == (0, 0, True, True)

    def test_lowercase(self):
        t = tokenize("a1")[0]
        assert t.value == (0, 0, False, False)

    def test_range(self):
        assert kinds("A1:B2") == [CELLREF, COLON, CELLREF]

    def test_ident_not_cellref(self):
        # SUM has no digits => IDENT, not CELLREF
        t = tokenize("SUM")[0]
        assert t.kind == IDENT and t.value == "SUM"

    def test_alnum_after_cellref_means_ident(self):
        # A1B should be IDENT (not a valid cellref pattern)
        t = tokenize("A1B")[0]
        assert t.kind == IDENT


class TestLexerErrorLit:
    def test_div0(self):
        t = tokenize("#DIV/0!")[0]
        assert t.kind == ERROR_LIT and t.value == ExcelError.DIV0

    def test_na(self):
        t = tokenize("#N/A")[0]
        assert t.value == ExcelError.NA

    def test_name(self):
        t = tokenize("#NAME?")[0]
        assert t.value == ExcelError.NAME

    def test_value(self):
        t = tokenize("#VALUE!")[0]
        assert t.value == ExcelError.VALUE


class TestLexerOperators:
    def test_arithmetic(self):
        assert kinds("+ - * / ^") == [PLUS, MINUS, STAR, SLASH, CARET]

    def test_concat(self):
        assert kinds('"a"&"b"') == [STRING, AMP, STRING]

    def test_percent(self):
        assert kinds("50%") == [NUMBER, PERCENT]

    def test_compare(self):
        assert kinds("1=2 1<>2 1<=2 1>=2 1<2 1>2") == [
            NUMBER,
            EQ,
            NUMBER,
            NUMBER,
            NE,
            NUMBER,
            NUMBER,
            LE,
            NUMBER,
            NUMBER,
            GE,
            NUMBER,
            NUMBER,
            LT,
            NUMBER,
            NUMBER,
            GT,
            NUMBER,
        ]

    def test_parens_comma(self):
        assert kinds("SUM(A1,B1)") == [IDENT, LPAREN, CELLREF, COMMA, CELLREF, RPAREN]

    def test_py_dot(self):
        assert kinds("py.foo(1)") == [IDENT, DOT, IDENT, LPAREN, NUMBER, RPAREN]

    def test_sheet_qualified_cellref(self):
        assert kinds("Sheet1!A1") == [IDENT, BANG, CELLREF]

    def test_sheet_qualified_range(self):
        assert kinds("Sheet1!A1:B5") == [IDENT, BANG, CELLREF, COLON, CELLREF]


class TestLexerErrors:
    def test_unknown_char(self):
        with pytest.raises(FormulaError):
            tokenize("@")
