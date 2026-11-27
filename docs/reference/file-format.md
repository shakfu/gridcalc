# File format

JSON, version 2. Version 1 files (single sheet, top-level `cells`) still load.

```json
{
  "version": 2,
  "mode": "HYBRID",
  "active": "Inputs",
  "code": "def margin(rev, cost):\n    return (rev - cost) / rev * 100\n",
  "names":  { "revenue": "A1:A12", "costs": "B1:B12" },
  "models": { "default": { "sense": "max", "objective": "B4",
                           "vars": "A4:A5", "constraints": "D4:D6" } },
  "sheets": [
    { "name": "Inputs", "cells": [["Rev","Cost"],[1000,600],[1200,700]] },
    { "name": "Summary","cells": [["Total","=SUM(Inputs!A2:A3)"]] }
  ],
  "format": { "width": 10 }
}
```

- **mode**: `"EXCEL"`, `"HYBRID"`, or `"PYTHON"`. Absent means `PYTHON`. See [Formula modes](../guide/modes.md).

- **sheets** (v2): each is `{name, cells}` with a 2D `cells` array.

- **cells**: rows of cell entries. An entry is `null`, a number, a string (label or `=` formula), or an object with `v` and optional `bold`, `underline`, `italic`, `fmt`, `fmtstr` and `label` keys. `"label": true` keeps text that looks like a number or formula, such as `"00123"`, as a label. Infinity is saved as the string `"1e999"` or `"-1e999"`, and NaN as `null`.

- **active** (v2): the name of the sheet to focus on load.

- **names**: workbook-global named ranges (sheet-relative when used).

- **models**: persisted LP/MIP definitions for `:opt` -- see [Optimization](../guide/optimization.md).

- **data_items**: named ranges and tables a sheet's model reads, keyed by name -- see [Cross-tab models](../guide/models.md). Each entry is an object, empty for a plain range:

    ```json
    "data_items": {
      "Bars":  {},
      "costs": {"index": ["Warehouses", "Bars"]},
      "flow":  {"index": ["Warehouses", "Bars"], "missing": 0, "output": true},
      "cost":  {"table": "Routes", "keys": ["Warehouse", "Bar"], "value": "cost"},
      "Warehouses": {"table": "Routes", "column": "Warehouse"}
    }
    ```

    `index` names up to two other items; `missing` is the value of a blank cell or unknown key; `output` marks an item the model fills; `table` with `keys`/`value`, or `column`, reads a table's rows instead of a range.

- **tables**: Excel tables, each `{name, sheet, ref, columns, header, totals}` and an optional `style`. Made by an xlsx load or `:table`.

- **iterate**: `{"count": 100, "delta": 0.001}` turns on iterative calculation for circular references, as Excel's option of that name: at most `count` sweeps, stopping when no cell changes by more than `delta`. Absent means off, and a cycle gives `#CIRC!`. EXCEL and HYBRID mode only.

- **code**: the per-workbook Python module string, editable with `:e`.

- **format**: `width`, the terminal column width in characters, and optional `fmt`, the workbook default number format set by `:gf` (one of `L R I G D $ % *`).

A sheet entry may carry **hidden_rows** and **filtered_rows**, lists of 0-based row indexes: the rows hidden, and those of them a filter hid. `SUBTOTAL` and `AGGREGATE` read them; neither view hides the rows.

A sheet entry may carry **model**, the sheet's solver model: `{"lang": "pulp", "text": "..."}`, plus `"backend": "pulp" | "pyomo" | "gmpl" | "cpsat" | "minizinc"` when it does not run on the builtin solver. Its text is code, so a file with a model raises the trust prompt.

A sheet entry may also carry **widths**, a `{"<column index>": pixels}` map recording columns resized in the [desktop app](../desktop.md). It is written only when a sheet has at least one resized column, and the curses renderer ignores it -- the terminal lays columns out from a single uniform width.

`.xlsx` is a separate path, read and written through a C++ extension rather than being a second native format -- see [Import and export](../guide/import-export.md).
