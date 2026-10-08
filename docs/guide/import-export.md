# Import and export

| Command | Reads | Writes | Notes |
|---|---|---|---|
| `:csv save/load` | CSV | CSV | Values only; a field starting with `=` loads as text |
| `:xlsx save/load` | `.xlsx` formulas + values | EXCEL mode: formulas + cached values; other modes: values only | `:xlsx load` switches to `EXCEL` |
| `:pd save/load` | CSV/TSV/JSON | same | Needs `gridcalc[extras]`; row 1 as headers; JSON keeps value types; fields load as `:csv load` does |

`:xlsx load` translates Excel formulas into gridcalc's `EXCEL` grammar and reads every worksheet, empty ones included. It replaces the whole workbook, including the code block and saved models. On import:

- Values keep their xlsx type. Text such as `00123` stays a label, booleans become `=TRUE`/`=FALSE`, and known error codes become formulas such as `=#N/A`.

- Shared and array formulas import as their cached values.

- Cells beyond 256 columns or 1024 rows are dropped.

- Chartsheets are skipped.

- Dates in a workbook using the 1904 date system are converted to gridcalc's 1900-based serials.

The load warns with a count of fallback formulas and dropped cells. The terminal app shows the warnings after `:o`, `:xlsx load` and at startup; the desktop app shows them after an open, but not for the file it starts with. The [headless CLI](../reference/cli.md) prints them to stderr.

`:xlsx save` writes named ranges as Excel defined names. A name without a sheet resolves on each formula's own sheet, so it is written as a sheet-local name on every sheet. `:xlsx load` reads that form back as one sheet-less name.

`:xlsx save` keeps bold, italic and underline, and `:xlsx load` reads them back. Any underline style imports as underline.

Number formats and alignment cross in both directions. `$`, `%` and `I` become `0.00`, `0.00%` and `0`; a spec such as `,.2f` becomes `#,##0.00`; `L` and `R` become left and right alignment. On load, a plain xlsx number format becomes a spec, so `$` returns as `.2f`, which displays the same. Differences:

- `I` truncates and xlsx `0` rounds, so `2.7` shows `3` in Excel.
- `*` (bar chart) has no xlsx equivalent and is dropped.
- xlsx formats outside the `[,][.N][f|e|%]` grammar, such as currency symbols or colours, load unformatted.

`:xlsx save` rewrites the whole file from the workbook. Saving over an xlsx that has merged cells, comments, charts, images, fills, borders, font sizes or colours, frozen panes, row heights, other alignments or unmapped number formats asks first, because those are lost.

`:xlsx save` also writes column widths. The workbook's width in characters becomes each sheet's default column width. Per-column widths set in the desktop app are in pixels and convert approximately, because an xlsx width depends on the reader's font. `:xlsx load` reads both back; the first sheet's default sets the workbook width.

`:xlsx save` refuses an empty workbook and any sheet name Excel rejects: empty, longer than 31 characters, containing `: \ / ? * [ ]`, starting or ending with `'`, named `History`, or equal to another name ignoring case.

`INDIRECT` and 3D ranges (`Sheet1:Sheet3!A1:B2`) are deliberately unsupported, because they would defeat the static dependency graph. Functions outside the auto-loaded library produce `#NAME?`. The full list of what does not cross the boundary is in [Limitations](../reference/limitations.md).

The xlsx path goes through a C++ extension wrapping [OpenXLSX](https://github.com/troldal/OpenXLSX) rather than a pure-Python reader, which is why the core install needs no third-party runtime dependency to read a spreadsheet.
