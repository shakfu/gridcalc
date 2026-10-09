from __future__ import annotations

from contextvars import ContextVar
from enum import Enum


class ExcelError(Enum):
    DIV0 = "#DIV/0!"
    NA = "#N/A"
    NAME = "#NAME?"
    REF = "#REF!"
    VALUE = "#VALUE!"
    NUM = "#NUM!"
    NULL = "#NULL!"
    CIRC = "#CIRC!"
    SPILL = "#SPILL!"
    CALC = "#CALC!"  # an empty array: Excel has none

    def __str__(self) -> str:
        return self.value


class FormulaError(Exception):
    pass


_BY_TEXT = {e.value: e for e in ExcelError}


def parse_error_literal(text: str) -> ExcelError | None:
    return _BY_TEXT.get(text.upper())


def first_error(*values: object) -> ExcelError | None:
    for v in values:
        if isinstance(v, ExcelError):
            return v
    return None


# The reason a function gave for an error, until the engine copies it to the
# cell. A ContextVar keeps concurrent recalcs in separate threads apart.
_reason: ContextVar[tuple[ExcelError, str] | None] = ContextVar("_reason", default=None)


def explain(err: ExcelError, why: str) -> ExcelError:
    """Return ``err``, recording ``why`` as the message its cell shows."""
    _reason.set((err, why))
    return err


def take_reason() -> tuple[ExcelError, str] | None:
    """The reason recorded since the last call, cleared."""
    r = _reason.get()
    if r is not None:
        _reason.set(None)
    return r
