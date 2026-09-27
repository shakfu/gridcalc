# Limitations

Known gaps, each of them deliberate rather than pending:

- **`INDIRECT`** is unsupported. A reference computed at evaluation time cannot be seen by the static dependency extractor, so the recalculation order would be wrong -- see [Topological recalc](../topological.md).

- **xlsx export of formulas is EXCEL mode only.** PYTHON and HYBRID syntax (`**`, list comprehensions, `py.*`) is not strict Excel, so those modes export values.

- **3D range refs** (`Sheet1:Sheet3!A1:B2`) are unsupported and return `nan`. Workaround: expand them manually with `+`.

- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse time. Excel does not support them either.

- **Grid size** is 256 columns by 1024 rows per sheet. xlsx import drops cells outside it and warns. A reference past the grid (`=A2000`) reads as an empty cell, and copying a formula so a reference leaves the grid writes `#REF!`.

- **Whole-column and whole-row references** (`A:A`, `1:1`) do not parse. Write the range out (`A1:A1024`).

- **xlsx styling is partial.** Bold, italic, underline, left and right alignment, column widths, date formats and plain number formats (`0.00`, `#,##0.00`, `0.0%`, `0.00E+00`) are read and written. Font sizes, colours and faces, fills, borders, centred, vertical or wrapped alignment, merged cells, row heights and formats such as currency are not. Saving over an xlsx that has any of them lists what will be lost and asks first.

The [Excel function coverage audit](../function_coverage.md) tracks the function library itself against Microsoft's documented set, including which absences are architectural and which are merely unimplemented.

For what the desktop frontend does not do yet -- a separate question from engine limitations -- see [Desktop app](../desktop.md).

!!! note "No longer limitations"

    This page once listed `LAMBDA` and its higher-order helpers (`MAP`,
    `REDUCE`, `SCAN`, `BYROW`, `BYCOL`, `MAKEARRAY`), `OFFSET`, and the
    packing of dynamic-array results into their origin cell. All three
    have since shipped: lambdas are a first-class value type, `OFFSET`
    returns a real reference, and array results spill into neighbouring
    cells. `tests/test_docs_conformance.py` now fails if a function named
    on this page is one the evaluator actually resolves.

    It also said xlsx dates were neither read nor written. They now are:
    a date's number format is read, rendered, written back, and understood
    by `COUNTIF`-style criteria -- see [Dates](../guide/dates.md).
