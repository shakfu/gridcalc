# Import and export

| Command | Reads | Writes | Notes |
|---|---|---|---|
| `:csv save/load` | CSV | CSV | Plain text, fast |
| `:xlsx save/load` | `.xlsx` formulas + values | EXCEL mode: formulas + cached values; other modes: values only | `:xlsx load` switches to `EXCEL` |
| `:pd save/load` | CSV/TSV/Excel/JSON/Parquet | same | Uses pandas; row 1 as headers |

`:xlsx load` translates Excel formulas into gridcalc's `EXCEL` grammar and reads every sheet.

`INDIRECT` and 3D ranges (`Sheet1:Sheet3!A1:B2`) are deliberately unsupported, because they would defeat the static dependency graph. Functions outside the auto-loaded library produce `#NAME?`. The full list of what does not cross the boundary is in [Limitations](../reference/limitations.md).

The xlsx path goes through a C++ extension wrapping [OpenXLSX](https://github.com/troldal/OpenXLSX) rather than a pure-Python reader, which is why the core install needs no third-party runtime dependency to read a spreadsheet.
