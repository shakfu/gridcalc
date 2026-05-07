from __future__ import annotations

from .ast_nodes import (
    BinOp,
    Bool,
    Call,
    CellRef,
    ErrorLit,
    Name,
    Node,
    Number,
    Percent,
    PyCall,
    RangeRef,
    String,
    UnaryOp,
)
from .errors import FormulaError
from .lexer import (
    AMP,
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
    Token,
    tokenize,
)


class ParseError(FormulaError):
    pass


_COMPARE_OPS = {EQ, NE, LT, GT, LE, GE}


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        t = self.tokens[self.i]
        self.i += 1
        return t

    def _expect(self, kind: str) -> Token:
        t = self._advance()
        if t.kind != kind:
            raise ParseError(f"expected {kind}, got {t.kind} at {t.pos}")
        return t

    def parse(self) -> Node:
        node = self._expr()
        if self._peek().kind != EOF:
            t = self._peek()
            raise ParseError(f"unexpected {t.kind} at {t.pos}")
        return node

    def _expr(self) -> Node:
        return self._compare()

    def _compare(self) -> Node:
        node = self._concat()
        while self._peek().kind in _COMPARE_OPS:
            op = self._advance().value
            right = self._concat()
            node = BinOp(op, node, right)
        return node

    def _concat(self) -> Node:
        node = self._additive()
        while self._peek().kind == AMP:
            self._advance()
            right = self._additive()
            node = BinOp("&", node, right)
        return node

    def _additive(self) -> Node:
        node = self._multiplicative()
        while self._peek().kind in (PLUS, MINUS):
            op = self._advance().value
            right = self._multiplicative()
            node = BinOp(op, node, right)
        return node

    def _multiplicative(self) -> Node:
        node = self._exponent()
        while self._peek().kind in (STAR, SLASH):
            op = self._advance().value
            right = self._exponent()
            node = BinOp(op, node, right)
        return node

    def _exponent(self) -> Node:
        node = self._unary()
        if self._peek().kind == CARET:
            self._advance()
            right = self._exponent()
            node = BinOp("^", node, right)
        return node

    def _unary(self) -> Node:
        if self._peek().kind in (PLUS, MINUS):
            op = self._advance().value
            return UnaryOp(op, self._unary())
        return self._percent()

    def _percent(self) -> Node:
        node = self._primary()
        while self._peek().kind == PERCENT:
            self._advance()
            node = Percent(node)
        return node

    def _primary(self) -> Node:
        t = self._peek()
        if t.kind == NUMBER:
            self._advance()
            return Number(t.value)
        if t.kind == STRING:
            self._advance()
            return String(t.value)
        if t.kind == BOOL:
            self._advance()
            return Bool(t.value)
        if t.kind == ERROR_LIT:
            self._advance()
            return ErrorLit(t.value)
        if t.kind == CELLREF:
            return self._cellref_or_range()
        if t.kind == LPAREN:
            self._advance()
            node = self._expr()
            self._expect(RPAREN)
            return node
        if t.kind == IDENT:
            return self._ident_or_call()
        raise ParseError(f"unexpected {t.kind} at {t.pos}")

    def _cellref_or_range(self) -> Node:
        t = self._advance()
        col, row, ac, ar = t.value
        start = CellRef(col, row, ac, ar)
        if self._peek().kind == COLON:
            self._advance()
            t2 = self._expect(CELLREF)
            col2, row2, ac2, ar2 = t2.value
            end = CellRef(col2, row2, ac2, ar2)
            return RangeRef(start, end)
        return start

    def _ident_or_call(self) -> Node:
        t = self._advance()
        if t.value == "py" and self._peek().kind == DOT:
            self._advance()
            fname_tok = self._expect(IDENT)
            args = self._call_args()
            return PyCall(fname_tok.value, tuple(args))
        # Dotted function names: STDEV.S, PERCENTILE.INC, etc.
        # Only consume the dot if followed by IDENT and the dotted name
        # is followed by LPAREN, so plain Names with trailing dots (none
        # in our grammar) are unaffected.
        name = t.value
        while (
            self._peek().kind == DOT
            and self.i + 1 < len(self.tokens)
            and self.tokens[self.i + 1].kind == IDENT
        ):
            self._advance()  # DOT
            part = self._advance()  # IDENT
            name = f"{name}.{part.value}"
        if self._peek().kind == LPAREN:
            args = self._call_args()
            return Call(name.lower(), tuple(args))
        return Name(name)

    def _call_args(self) -> list[Node]:
        self._expect(LPAREN)
        args: list[Node] = []
        if self._peek().kind == RPAREN:
            self._advance()
            return args
        args.append(self._expr())
        while self._peek().kind == COMMA:
            self._advance()
            args.append(self._expr())
        self._expect(RPAREN)
        return args


def parse(text: str) -> Node:
    tokens = tokenize(text)
    return _Parser(tokens).parse()
