# Import and export

| Command | Reads | Writes | Notes |
|---|---|---|---|
| `:csv save/load` | CSV | CSV | Values only; a field starting with `=` loads as text |
| `:xlsx save/load` | `.xlsx` formulas + values | EXCEL mode: formulas + cached values; other modes: values only | `:xlsx load` switches to `EXCEL` |
| `:pd save/load` | CSV/TSV/JSON | same | Needs `gridcalc[extras]`; row 1 as headers; JSON keeps value types; fields load as `:csv load` does |

`:xlsx load` translates Excel formulas into gridcalc's `EXCEL` grammar and reads every worksheet, empty ones included. It replaces the whole workbook, including the code block and saved models. On import:

- Values keep their xlsx type. Text such as `00123` stays a label (the editor shows it as `"00123`; the leading `"` keeps it text when committed), booleans and error codes stay logical and error values, and export writes them back as such.

- Shared and array formulas import as their cached values.

- The grid matches Excel's, 16384 columns by 1048576 rows, so no cell of a valid xlsx is dropped.

- Chartsheets are skipped.

- Dates in a workbook using the 1904 date system are converted to gridcalc's 1900-based serials.

The load warns with a count of fallback formulas and dropped cells. The terminal app shows the warnings after `:o`, `:xlsx load` and at startup; the desktop app shows them after an open, but not for the file it starts with. The [headless CLI](../reference/cli.md) prints them to stderr.

`:xlsx save` writes named ranges as Excel defined names. A name without a sheet resolves on each formula's own sheet, so it is written as a sheet-local name on every sheet. `:xlsx load` reads that form back as one sheet-less name.

`:xlsx save` keeps bold, italic and underline, and `:xlsx load` reads them back. Any underline style imports as underline.

Both also keep:

- font face, size, colour and strikethrough, and the workbook's default font;
- solid fills;
- borders, each side with its style and colour;
- horizontal and vertical alignment, wrapping, indent and rotation;
- merged cells and row heights;
- frozen rows and columns, per sheet;
- tables, with their filters and style.

Formulas read a table by name and column, as in Excel: `=SUM(Sales[Qty])`, `=Sales[[#This Row],[Qty]]*2`, `=[@Qty]` inside the table. Inserting rows or columns inside a table grows it. Editing a header cell does not rename its column, as Excel does; formulas keep the old name.

Theme colours load as the colour they show. A blank cell that has only a fill or border is kept, and clearing a cell keeps these styles, as in Excel. The web view draws all of them except rotation and row heights. The terminal view shows horizontal alignment only.

Number formats and alignment cross in both directions. `$`, `%` and `I` become `0.00`, `0.00%` and `0`; a spec such as `,.2f` becomes `#,##0.00`; `L` and `R` become left and right alignment. On load, a plain xlsx number format becomes a spec, so `$` returns as `.2f`, which displays the same. Differences:

- `I` truncates and xlsx `0` rounds, so `2.7` shows `3` in Excel.
- `*` (bar chart) has no xlsx equivalent and is dropped.
- Other xlsx formats, such as `"$"#,##0.00`, `#,##0;[Red](#,##0)` or `# ?/?`, are kept as written and display as in Excel. `[Red]` colours the value in the web view.

`:xlsx save` rewrites the whole file from the workbook. Saving over an xlsx that has comments, charts, images, pattern or gradient fills, diagonal borders or font effects such as superscript asks first, because those are lost.

`:xlsx save` also writes column widths. The workbook's width in characters becomes each sheet's default column width. Per-column widths set in the desktop app are in pixels and convert approximately, because an xlsx width depends on the reader's font. `:xlsx load` reads both back; the first sheet's default sets the workbook width.

`:xlsx save` refuses an empty workbook and any sheet name Excel rejects: empty, longer than 31 characters, containing `: \ / ? * [ ]`, starting or ending with `'`, named `History`, or equal to another name ignoring case.

Functions outside the auto-loaded library produce `#NAME?`. The full list of what does not cross the boundary is in [Limitations](../reference/limitations.md).

The xlsx path goes through a C++ extension wrapping [OpenXLSX](https://github.com/troldal/OpenXLSX) rather than a pure-Python reader, which is why the core install needs no third-party runtime dependency to read a spreadsheet.
