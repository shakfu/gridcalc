"""The dict a model sees for an indexed data item.

Kept apart from :mod:`gridcalc.dataitems`, which imports the engine: the model's
child process needs only this, and the engine import is most of its startup.
"""

from __future__ import annotations

from typing import Any

Key = Any  # a scalar, or a (row_key, col_key) tuple

_RAISE: Any = object()


class DataItemError(Exception):
    """A data item that cannot be read, or a write it cannot take."""


class ItemDict(dict[Key, Any]):
    """An indexed item's values. Records writes; refuses keys outside the index."""

    def __init__(self, name: str, keys: list[Key], values: dict[Key, Any], missing: Any) -> None:
        super().__init__(values)
        self.name = name
        self.index_keys = frozenset(keys)
        self.missing = missing
        self.writes: dict[Key, Any] = {}

    def __missing__(self, key: Key) -> Any:
        if key in self.index_keys and self.missing is not _RAISE:
            return self.missing
        why = "is blank" if key in self.index_keys else "is not in its index"
        raise KeyError(f"{self.name}[{key!r}] {why}")

    def __setitem__(self, key: Key, value: Any) -> None:
        if key not in self.index_keys:
            raise DataItemError(f"{self.name}[{key!r}] is not in its index; a range cannot grow")
        super().__setitem__(key, value)
        self.writes[key] = value
