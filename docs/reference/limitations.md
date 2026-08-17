# Limitations

Known gaps, each of them deliberate rather than pending:

- **`INDIRECT`** is unsupported. A reference computed at evaluation time cannot be seen by the static dependency extractor, so the recalculation order would be wrong -- see [Topological recalc](../topological.md).

- **`LAMBDA`** and its higher-order helpers (`MAP`, `REDUCE`, `BYROW`, and the rest) are unsupported; `LET` is supported. Dynamic-array results are packed into their origin cell rather than spilling into neighbours.

- **xlsx export of formulas is EXCEL mode only.** PYTHON and HYBRID syntax (`**`, list comprehensions, `py.*`) is not strict Excel, so those modes export values.

- **3D range refs** (`Sheet1:Sheet3!A1:B2`) are unsupported and return `nan`. Workaround: expand them manually with `+`.

- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse time. Excel does not support them either.

- **xlsx dates and styles** are neither read nor written; date serials arrive as floats.

The [Excel function coverage audit](../function_coverage.md) tracks the function library itself against Microsoft's documented set, including which absences are architectural and which are merely unimplemented.

For what the desktop frontend does not do yet -- a separate question from engine limitations -- see [Desktop app](../desktop.md).
