from __future__ import annotations

from enum import Enum


class ExcelError(Enum):
    DIV0 = "#DIV/0!"
    NA = "#N/A"
    NAME = "#NAME?"
    REF = "#REF!"
    VALUE = "#VALUE!"
    NUM = "#NUM!"
    NULL = "#NULL!"

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
