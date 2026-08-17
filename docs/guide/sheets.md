# Multi-sheet workbooks

```text
:sheets                    Interactive picker: list sheets, select one to switch
:sheet                     List sheets inline (active marked *)
:sheet Inputs              Switch by name
:sheet 1                   Switch by zero-based index
:sheet add Outputs         Append (does not switch)
:sheet del Tmp             Remove (refused if last sheet)
:sheet rename Old New      Rename, rewriting `Old!` prefixes in formulas
:sheet move Inputs 0       Reorder
```

A workbook with more than one sheet shows a tab strip on the bottom line (active tab highlighted, with an `i/n` position counter); single-sheet workbooks leave that line clear. The status bar also prefixes the active sheet name (`Inputs!A1`) whenever a workbook has multiple sheets.

## Cross-sheet references

Reference cells on other sheets with `Sheet!cell`:

```text
=Sheet2!A1
=SUM(Sheet2!A1:A10)
=Sheet1!A1 + Sheet2!B1
```

The dependency graph is keyed on `(sheet, col, row)`, so cross-sheet recalculation works transparently.

Cross-sheet *ranges* (`Sheet1!A1:Sheet2!B5`) are not supported. Neither does Excel, and they would defeat the static dependency analysis -- see [Limitations](../reference/limitations.md).
