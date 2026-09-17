# Import and export

| Command | Reads | Writes | Notes |
|---|---|---|---|
| `:csv save/load` | CSV | CSV | Plain text, fast |
| `:xlsx save/load` | `.xlsx` formulas + values | EXCEL mode: formulas + cached values; other modes: values only | `:xlsx load` switches to `EXCEL` |
| `:pd save/load` | CSV/TSV/JSON | same | Needs `gridcalc[extras]`; row 1 as headers; JSON keeps value types |

`:xlsx load` translates Excel formulas into gridcalc's `EXCEL` grammar and reads every worksheet, empty ones included. It replaces the whole workbook, including the code block and saved models. On import:

- Values keep their xlsx type. Text such as `00123` stays a label, booleans become `=TRUE`/`=FALSE`, and known error codes become formulas such as `=#N/A`.

- Shared and array formulas import as their cached values.

- Cells beyond 256 columns or 1024 rows are dropped.

- Chartsheets are skipped.

- Dates in a workbook using the 1904 date system are converted to gridcalc's 1900-based serials.

The load warns with a count of fallback formulas and dropped cells. The [headless CLI](../reference/cli.md) prints these warnings to stderr; the terminal and desktop apps do not show them.

`:xlsx save` refuses an empty workbook and any sheet name Excel rejects: empty, longer than 31 characters, containing `: \ / ? * [ ]`, starting or ending with `'`, named `History`, or equal to another name ignoring case.

`INDIRECT` and 3D ranges (`Sheet1:Sheet3!A1:B2`) are deliberately unsupported, because they would defeat the static dependency graph. Functions outside the auto-loaded library produce `#NAME?`. The full list of what does not cross the boundary is in [Limitations](../reference/limitations.md).

The xlsx path goes through a C++ extension wrapping [OpenXLSX](https://github.com/troldal/OpenXLSX) rather than a pure-Python reader, which is why the core install needs no third-party runtime dependency to read a spreadsheet.
