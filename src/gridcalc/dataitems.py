"""Data items: defined names read as Python sets, scalars and indexed dicts.

A data item is a defined name plus an ``index`` of zero, one or two other
data items, as in SolverStudio. Design: ``docs/dev/crosstab-model.md``.

    Set           no index, one row or column   -> list
    Singleton     no index, one cell            -> scalar
    Indexed list  one index, one row or column  -> {key: value}
    Indexed table two indexes                   -> {(row_key, col_key): value}

The first index of a table runs down its rows, the second across its columns.
Blank value cells are left out of the dict, so ``missing`` covers them as it
covers unknown keys. A model writes results by assigning keys of an indexed
item or by returning a singleton's value; :func:`apply_writes` puts them in
the sheet.
"""

from __future__ import annotations

import keyword
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .book import Book, BookError, Target, _scalar
from .engine import FORMULA, Grid, Table, cellname
from .formula.errors import ExcelError
from .itemdict import _RAISE as _RAISE
from .itemdict import DataItemError as DataItemError
from .itemdict import ItemDict as ItemDict
from .itemdict import Key as Key


@dataclass(frozen=True)
class DataItem:
    """The index names and missing-key policy of one defined name."""

    index: tuple[str, ...] = ()
    missing: Any = _RAISE  # _RAISE, or the value an unknown or blank key reads as
    # Filled from a model variable of the same name after a solve: the model
    # rebinds the name to its variables, and each index key's value is written.
    output: bool = False
    # A long-format item: rows of an Excel table, keyed by its `keys` columns
    # (default: all but the last) with values from `value` (default: the last).
    # With `column`, a set of that column's distinct values instead.
    table: str | None = None
    keys: tuple[str, ...] = ()
    value: str | None = None
    column: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.index:
            out["index"] = list(self.index)
        if self.missing is not _RAISE:
            out["missing"] = self.missing
        if self.output:
            out["output"] = True
        if self.table is not None:
            out["table"] = self.table
            if self.keys:
                out["keys"] = list(self.keys)
            if self.value is not None:
                out["value"] = self.value
            if self.column is not None:
                out["column"] = self.column
        return out

    @classmethod
    def from_json(cls, d: Any) -> DataItem:
        if not isinstance(d, dict):
            raise DataItemError("entry is not an object")
        index = d.get("index", [])
        if not isinstance(index, list) or not all(isinstance(x, str) for x in index):
            raise DataItemError("index is not a list of names")
        missing = d.get("missing", _RAISE)
        if missing is not _RAISE:
            try:
                missing = _scalar("missing", missing)
            except BookError as exc:
                raise DataItemError(str(exc)) from exc
        output = d.get("output", False)
        if not isinstance(output, bool):
            raise DataItemError("output is not true or false")
        table, value, column = d.get("table"), d.get("value"), d.get("column")
        keys = d.get("keys", [])
        for field, v in (("table", table), ("value", value), ("column", column)):
            if v is not None and not (isinstance(v, str) and v):
                raise DataItemError(f"{field} is not a name")
        if not isinstance(keys, list) or not all(isinstance(k, str) and k for k in keys):
            raise DataItemError("keys is not a list of column names")
        if table is None and (keys or value is not None or column is not None):
            raise DataItemError("keys, value and column need a table")
        if column is not None and (keys or value is not None):
            raise DataItemError("column makes a set; it takes no keys or value")
        return cls(tuple(index), missing, output, table, tuple(keys), value, column)


# --- reading ----------------------------------------------------------------


def _key(v: Any) -> Any:
    """An index cell's value as a dict key: a whole number reads as an int."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _cell_values(g: Grid, t: Target) -> list[list[Any]]:
    return [
        [g._cell_lookup_value(c, r, t.sheet) for c in range(t.c1, t.c2 + 1)]
        for r in range(t.r1, t.r2 + 1)
    ]


def _where(t: Target, i: int = 0, j: int = 0) -> str:
    return f"{t.sheet}!{cellname(t.c1 + j, t.r1 + i)}"


class _Resolved:
    """An item's rectangle and cell values, or why it has none."""

    def __init__(self, book: Book, name: str) -> None:
        self.target: Target | None = None
        self.values: list[list[Any]] = []
        self.problem = ""
        if not name.isidentifier() or keyword.iskeyword(name):
            self.problem = f"{name}: not a Python identifier, so a model cannot name it"
            return
        try:
            t = book.resolve(name)
        except BookError as exc:
            self.problem = f"{name}: {exc}"
            return
        if t.formula is not None:
            self.problem = f"{name}: defined as a formula, not a range"
            return
        self.target = t
        self.values = _cell_values(book.grid, t)

    @property
    def flat(self) -> list[Any]:
        return [v for row in self.values for v in row]


def _index_problems(name: str, res: _Resolved, t: Target) -> list[str]:
    """Why an index item's values cannot serve as keys."""
    rows, cols = t.shape
    if rows != 1 and cols != 1:
        return [f"{name}: an index must be one row or one column, not {rows}x{cols}"]
    out: list[str] = []
    seen: dict[Any, int] = {}
    for n, v in enumerate(res.flat):
        i, j = (0, n) if rows == 1 else (n, 0)
        if v is None or v == "":
            out.append(f"{name}: blank index value at {_where(t, i, j)}")
        elif isinstance(v, ExcelError):
            out.append(f"{name}: {v} at {_where(t, i, j)}")
        elif _key(v) in seen:
            out.append(f"{name}: duplicate index value {_key(v)!r} at {_where(t, i, j)}")
        else:
            seen[_key(v)] = n
    return out


def _resolve_all(g: Grid) -> tuple[dict[str, _Resolved], list[str]]:
    book = Book(g)
    items: dict[str, DataItem] = g.data_items
    by_fold = {n.casefold(): n for n in items}
    res = {name: _Resolved(book, name) for name, it in items.items() if it.table is None}
    problems = [r.problem for r in res.values() if r.problem]
    index_ok: dict[str, bool] = {}
    for name, item in items.items():
        if item.table is not None:
            continue
        r = res[name]
        if r.target is None:
            continue
        if len(item.index) > 2:
            problems.append(f"{name}: at most two indexes, got {len(item.index)}")
            continue
        sizes: list[int] = []
        for ix in item.index:
            ix_name = by_fold.get(ix.casefold())
            if ix_name is None:
                problems.append(f"{name}: index {ix} is not a data item")
                continue
            if items[ix_name].index:
                problems.append(f"{name}: index {ix_name} is itself indexed")
                continue
            if items[ix_name].table is not None:
                problems.append(f"{name}: index {ix_name} is a table item; use a range")
                continue
            ix_res = res[ix_name]
            if ix_res.target is None:
                continue  # reported under its own name
            if ix_name not in index_ok:
                ix_problems = _index_problems(ix_name, ix_res, ix_res.target)
                problems += ix_problems
                index_ok[ix_name] = not ix_problems
            sizes.append(len(ix_res.flat))
        if len(sizes) != len(item.index):
            continue
        rows, cols = r.target.shape
        if item.output and not item.index and (rows, cols) != (1, 1):
            problems.append(f"{name}: a set cannot be an output; give it an index")
        if not item.index:
            if rows != 1 and cols != 1:
                problems.append(f"{name}: a {rows}x{cols} range needs two indexes")
        elif len(sizes) == 1:
            if (rows != 1 and cols != 1) or rows * cols != sizes[0]:
                problems.append(
                    f"{name}: {rows}x{cols} does not match index {item.index[0]} of {sizes[0]}"
                )
        elif (rows, cols) != (sizes[0], sizes[1]):
            problems.append(
                f"{name}: {rows}x{cols} does not match indexes"
                f" {item.index[0]} x {item.index[1]} ({sizes[0]}x{sizes[1]})"
            )
    problems += _resolve_tables(g)[1]
    return res, problems


@dataclass
class _TableData:
    """A table item's table, its data rows, and the columns it reads."""

    table: Table
    rows: list[int]
    key_cols: list[int]  # the set's column when value_col is None
    value_col: int | None
    key_names: tuple[str, ...]


def _resolve_tables(g: Grid) -> tuple[dict[str, _TableData], list[str]]:
    """Each table item's columns and rows, and every problem with them."""
    out: dict[str, _TableData] = {}
    problems: list[str] = []
    tables = {t.name.casefold(): t for t in g.tables}
    for name, item in g.data_items.items():
        if item.table is None:
            continue
        if not name.isidentifier() or keyword.iskeyword(name):
            problems.append(f"{name}: not a Python identifier, so a model cannot name it")
            continue
        t = tables.get(item.table.casefold())
        if t is None:
            problems.append(f"{name}: no table {item.table}")
            continue
        if item.index:
            problems.append(f"{name}: a table item takes keys, not an index")
            continue
        cols = {c.casefold(): t.c1 + i for i, c in enumerate(t.columns)}

        lo, hi = t.data_rows()
        rows = list(range(lo, hi + 1))
        if item.column is not None:
            c = cols.get(item.column.casefold())
            if c is None:
                problems.append(f"{name}: table {t.name} has no column {item.column}")
                continue
            if item.output:
                problems.append(f"{name}: a set cannot be an output")
                continue
            out[name] = _TableData(t, rows, [c], None, (item.column,))
            continue
        keys = item.keys or tuple(t.columns[:-1])
        value = item.value or t.columns[-1]
        if not keys:
            problems.append(f"{name}: table {t.name} has one column; it needs key columns too")
            continue
        unknown = [n for n in (*keys, value) if n.casefold() not in cols]
        if unknown:
            problems.append(f"{name}: table {t.name} has no column {', '.join(unknown)}")
            continue
        if value.casefold() in {k.casefold() for k in keys}:
            problems.append(f"{name}: column {value} is both a key and the value")
            continue
        data = _TableData(
            t,
            rows,
            [c for k in keys if (c := cols.get(k.casefold())) is not None],
            cols.get(value.casefold()),
            keys,
        )
        seen: dict[Any, int] = {}
        for r in rows:
            at = f"{t.sheet}!{cellname(data.key_cols[0], r)}"
            k = _row_key(g, data, r)
            if k is None:
                problems.append(f"{name}: blank or error key in row {r + 1} ({at})")
            elif k in seen:
                problems.append(f"{name}: duplicate key {k!r} in rows {seen[k] + 1} and {r + 1}")
            else:
                seen[k] = r
        out[name] = data
    return out, problems


def _row_key(g: Grid, d: _TableData, r: int) -> Any:
    """Row ``r``'s key: a value, or a tuple for several key columns; None if any is blank."""
    parts = []
    for c in d.key_cols:
        v = g._cell_lookup_value(c, r, d.table.sheet)
        if v is None or v == "" or isinstance(v, ExcelError):
            return None
        parts.append(_key(v))
    return parts[0] if len(parts) == 1 else tuple(parts)


def _read_table(g: Grid, name: str, item: DataItem, d: _TableData, errors: list[str]) -> Any:
    sheet = d.table.sheet
    if d.value_col is None:  # a set of one column's distinct values, in row order
        seen: dict[Any, None] = {}
        for r in d.rows:
            v = g._cell_lookup_value(d.key_cols[0], r, sheet)
            if isinstance(v, ExcelError):
                errors.append(f"{name}: {v} at {sheet}!{cellname(d.key_cols[0], r)}")
            elif v is not None and v != "":
                seen.setdefault(_key(v))
        return list(seen)
    keys, values = [], {}
    for r in d.rows:
        k = _row_key(g, d, r)
        keys.append(k)
        v = g._cell_lookup_value(d.value_col, r, sheet)
        if isinstance(v, ExcelError):
            errors.append(f"{name}: {v} at {sheet}!{cellname(d.value_col, r)}")
        elif v is not None and v != "":
            values[k] = v
    return ItemDict(name, keys, values, item.missing)


@dataclass(frozen=True)
class ItemBox:
    """Where a data item sits, for drawing it over the grid."""

    name: str
    label: str  # `costs[Warehouses,Bars]`
    sheet: str
    c1: int
    r1: int
    c2: int
    r2: int
    problem: str  # the first validation problem naming this item, or ""


def boxes(g: Grid) -> list[ItemBox]:
    """Each data item that resolves to a range, with its label and any problem."""
    res, problems = _resolve_all(g)
    tables = _resolve_tables(g)[0]
    out: list[ItemBox] = []
    for name, item in g.data_items.items():
        problem = next((p for p in problems if p.startswith(f"{name}:")), "")
        if item.table is not None:
            d = tables.get(name)
            if d is None:
                continue
            tb = d.table
            label = f"{name}[{','.join(d.key_names)}]" if d.value_col is not None else name
            label += " out" if item.output else ""
            out.append(ItemBox(name, label, tb.sheet, tb.c1, tb.r1, tb.c2, tb.r2, problem))
            continue
        t = res[name].target
        if t is None:
            continue
        label = f"{name}[{','.join(item.index)}]" if item.index else name
        if item.output:
            label += " out"
        problem = next((p for p in problems if p.startswith(f"{name}:")), "")
        out.append(ItemBox(name, label, t.sheet, t.c1, t.r1, t.c2, t.r2, problem))
    return out


def describe(item: DataItem) -> str:
    """A table item's source, as `:items` shows it: `table Routes [Warehouse, Bar] -> cost`."""
    if item.table is None:
        return ""
    if item.column is not None:
        return f"table {item.table} column {item.column}"
    keys = f" [{', '.join(item.keys)}]" if item.keys else ""
    value = f" -> {item.value}" if item.value else ""
    return f"table {item.table}{keys}{value}"


def validate(g: Grid) -> list[str]:
    """Every problem with ``g.data_items``, one line each. Runs no model code."""
    return _resolve_all(g)[1]


def _cell_keys(g: Grid, name: str, item: DataItem, res: dict[str, _Resolved]) -> list[Key]:
    """The key of each cell of ``name``, row by row."""
    by_fold = {n.casefold(): n for n in g.data_items}
    keys = [[_key(v) for v in res[by_fold[ix.casefold()]].flat] for ix in item.index]
    if len(keys) == 1:
        return keys[0]
    return [(a, b) for a in keys[0] for b in keys[1]]


def read_items(g: Grid) -> dict[str, Any]:
    """Each data item's value, by name. Raises :class:`DataItemError` listing every problem."""
    res, problems = _resolve_all(g)
    if problems:
        raise DataItemError("\n".join(problems))
    out: dict[str, Any] = {}
    errors: list[str] = []
    tables = _resolve_tables(g)[0]
    for name, item in g.data_items.items():
        if item.table is not None:
            out[name] = _read_table(g, name, item, tables[name], errors)
            continue
        r = res[name]
        t = r.target
        if t is None:  # unreachable: validation reported it
            continue
        rows, cols = t.shape
        flat = r.flat
        for n, v in enumerate(flat):
            if isinstance(v, ExcelError):
                errors.append(f"{name}: {v} at {_where(t, n // cols, n % cols)}")
        if not item.index:
            out[name] = flat[0] if rows == cols == 1 else flat
            continue
        keys = _cell_keys(g, name, item, res)
        values = {k: v for k, v in zip(keys, flat, strict=True) if v is not None and v != ""}
        out[name] = ItemDict(name, keys, values, item.missing)
    if errors:
        raise DataItemError("\n".join(errors))
    return out


# --- writing ----------------------------------------------------------------


def plan_writes(g: Grid, writes: Mapping[str, Any]) -> dict[tuple[str, int, int], Any]:
    """The cell each write lands in. Raises before anything is written.

    ``writes`` maps an indexed item to ``{key: value}``, or a singleton to its value.
    """
    res, problems = _resolve_all(g)
    if problems:
        raise DataItemError("\n".join(problems))
    by_fold = {n.casefold(): n for n in g.data_items}
    plan: dict[tuple[str, int, int], Any] = {}
    errors: list[str] = []
    tables = _resolve_tables(g)[0]
    for wname, value in writes.items():
        name = by_fold.get(wname.casefold())
        if name is None:
            errors.append(f"{wname}: not a data item")
            continue
        item = g.data_items[name]
        if item.table is not None:
            d = tables[name]
            if d.value_col is None:
                errors.append(f"{name}: a set cannot be written")
                continue
            if not isinstance(value, Mapping):
                errors.append(f"{name}: write a {{key: value}} mapping to a table item")
                continue
            rows_by_key = {_row_key(g, d, r): r for r in d.rows}
            tcells: dict[tuple[int, int], Any] = {}
            for k, v in value.items():
                row = rows_by_key.get(k)
                if row is None:
                    errors.append(f"{name}[{k!r}] is not a row of table {d.table.name}")
                    continue
                tcells[(d.value_col, row)] = v
            _plan_cells(g, name, d.table.sheet, tcells, plan, errors)
            continue
        t = res[name].target
        if t is None:  # unreachable: validation reported it
            continue
        rows, cols = t.shape
        if not item.index:
            if rows != 1 or cols != 1:
                errors.append(f"{name}: a set cannot be written")
                continue
            cells = {(t.c1, t.r1): value}
        else:
            if not isinstance(value, Mapping):
                errors.append(f"{name}: write a {{key: value}} mapping to an indexed item")
                continue
            pos = {k: n for n, k in enumerate(_cell_keys(g, name, item, res))}
            cells = {}
            for k, v in value.items():
                n = pos.get(k)
                if n is None:
                    errors.append(f"{name}[{k!r}] is not in its index; a range cannot grow")
                    continue
                cells[(t.c1 + n % cols, t.r1 + n // cols)] = v
        _plan_cells(g, name, t.sheet, cells, plan, errors)
    if errors:
        raise DataItemError("\n".join(errors))
    return plan


def _plan_cells(
    g: Grid,
    name: str,
    sheet_name: str,
    cells: Mapping[tuple[int, int], Any],
    plan: dict[tuple[str, int, int], Any],
    errors: list[str],
) -> None:
    """Add ``cells`` to ``plan``, refusing formula cells and values a cell cannot hold."""
    sheet = g._sheet_by_name(sheet_name)
    for (c, r), v in cells.items():
        cl = sheet._cells.get((c, r)) if sheet is not None else None
        if cl is not None and cl.type == FORMULA:
            errors.append(f"{name}: {sheet_name}!{cellname(c, r)} holds a formula")
            continue
        try:
            plan[(sheet_name, c, r)] = _scalar(name, v)
        except BookError as exc:
            errors.append(str(exc))


def apply_writes(g: Grid, writes: Mapping[str, Any], undo: Any = None) -> int:
    """Write ``writes`` (see :func:`plan_writes`) as one undo step. Returns the cell count."""
    plan = plan_writes(g, writes)
    if not plan:
        return 0
    if undo is not None:
        _save_undo(g, undo, plan)
    Book(g)._apply(plan)
    return len(plan)


def _save_undo(g: Grid, undo: Any, plan: Mapping[tuple[str, int, int], Any]) -> None:
    """Snapshot the written cells' bounding box, or the workbook when they span sheets.

    A region costs the cells stored inside it; a workbook snapshot copies every cell.
    """
    sheets = {s for s, _, _ in plan}
    if len(sheets) != 1:
        undo.save_grid(g)
        return
    target = g._sheet_by_name(next(iter(sheets)))
    if target is None:
        undo.save_grid(g)
        return
    cols = [c for _, c, _ in plan]
    rows = [r for _, _, r in plan]
    active = g.active
    g.active = g.sheets.index(target)
    try:
        undo.save_region(g, min(cols), min(rows), max(cols), max(rows))
    finally:
        g.active = active


def collect_writes(items: Mapping[str, Any]) -> dict[str, dict[Key, Any]]:
    """The writes recorded on each :class:`ItemDict` in ``items``."""
    return {n: dict(v.writes) for n, v in items.items() if isinstance(v, ItemDict) and v.writes}
