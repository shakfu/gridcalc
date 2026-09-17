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

- **models**: persisted LP/MIP definitions -- see [Optimization](../guide/optimization.md).

- **code**: the per-workbook Python module string, editable with `:e`.

A sheet entry may also carry **widths**, a `{"<column index>": pixels}` map recording columns resized in the [desktop app](../desktop.md). It is written only when a sheet has at least one resized column, and the curses renderer ignores it -- the terminal lays columns out from a single uniform width.

`.xlsx` is a separate path, read and written through a C++ extension rather than being a second native format -- see [Import and export](../guide/import-export.md).
