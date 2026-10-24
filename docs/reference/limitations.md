# Limitations

Known gaps, each of them deliberate rather than pending:

- **External and cube functions** (`WEBSERVICE`, `RTD`, `IMAGE`, `CUBEVALUE`, `CUBEMEMBER`) are not implemented. They give `#NAME?`.

- **xlsx export of formulas is EXCEL mode only.** PYTHON and HYBRID syntax (`**`, list comprehensions, `py.*`) is not strict Excel, so those modes export values.

- **3D references** (`Jan:Mar!B2`) do not shift when rows or columns are inserted or deleted on one sheet of the run. Excel's rule for that case is unverified.

- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse time. Excel does not support them either.

- **A range over 65536 cells is read only to the workbook's last used row and column.** The rest is blank. Results match Excel except where the result's shape shows: `=A:A` spills the used rows, not 1048576, and `=ROWS(A:A*1)` counts them. Counting blanks and indexing past the used rows still answer for the whole range. One cell far down the sheet makes every such range read to it, and recalculation slows to match.

- **Whole-column and whole-row references** (`A:A`, `1:1`) work in EXCEL and HYBRID mode only.

- **xlsx styling is not complete.** Fonts, solid fills, borders, alignment, number formats, merged cells, row and column sizes are read and written ([Import and export](../guide/import-export.md)). Pattern and gradient fills, diagonal borders and font effects such as superscript are not. Saving over an xlsx that has any of them lists what will be lost and asks first. Styles can be loaded but not yet set from either view, except bold, italic, underline and number formats.

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

    It also listed `HYPERLINK`, which now shows its text but opens nothing.

    It also listed `INDIRECT`. A cell calling it now recalculates every
    time, as in Excel, and reads the cells it names on demand.

    It also said xlsx dates were neither read nor written. They now are:
    a date's number format is read, rendered, written back, and understood
    by `COUNTIF`-style criteria -- see [Dates](../guide/dates.md).
