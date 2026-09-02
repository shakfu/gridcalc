# Limitations

Known gaps, each of them deliberate rather than pending:

- **`INDIRECT`** is unsupported. A reference computed at evaluation time cannot be seen by the static dependency extractor, so the recalculation order would be wrong -- see [Topological recalc](../topological.md).

- **xlsx export of formulas is EXCEL mode only.** PYTHON and HYBRID syntax (`**`, list comprehensions, `py.*`) is not strict Excel, so those modes export values.

- **3D range refs** (`Sheet1:Sheet3!A1:B2`) are unsupported and return `nan`. Workaround: expand them manually with `+`.

- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse time. Excel does not support them either.

- **xlsx dates and styles** are neither read nor written; date serials arrive as floats.

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
