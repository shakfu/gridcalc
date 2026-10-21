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

`u` undoes `:sheet add`, `del`, `rename` and `move`.

## Cross-sheet references

Reference cells on other sheets with `Sheet!cell`:

```text
=Sheet2!A1
=SUM(Sheet2!A1:A10)
=Sheet1!A1 + Sheet2!B1
```

Quote a name that is not a plain identifier -- one containing spaces or punctuation -- and double the apostrophe to include one:

```
='My Sheet'!A1
=SUM('Q1 Results'!A1:A10)
='It''s'!B2
```

A sheet name matches in any case, as in Excel: `=data!A1` reads the sheet `Data`. So two sheets cannot differ only by case. A reference to a sheet that does not exist gives `#REF!`.

Deleting a sheet rewrites references to it as `#REF!`, as Excel does: `=Tmp!A2*2` becomes `=#REF!*2`. A sheet added later under the same name does not revive the reference. `u` restores both the sheet and the references.

The dependency graph is keyed on `(sheet, col, row)`, so cross-sheet recalculation works transparently.

Inserting, deleting or swapping rows and columns moves only the references that resolve against the edited sheet. A formula on another sheet that names this one follows the edit; one on this sheet that names another is left alone, because that sheet's lines did not move.

Cross-sheet *ranges* (`Sheet1!A1:Sheet2!B5`) are not supported. Neither does Excel.

## 3D references

A 3D reference reads the same cells on a run of sheets: `=SUM(Jan:Mar!B2)` adds B2 on `Jan`, `Mar` and every sheet between them. Quote the span when a name needs it: `='Q1 a:Q4 b'!A1`.

- The run is by sheet position. Moving a sheet into or out of it changes the result.
- Only `SUM`, `AVERAGE`, `COUNT`, `COUNTA`, `MAX`, `MIN`, `PRODUCT`, the `STDEV` and `VAR` families and their `A` forms accept one, as in Excel. Elsewhere it gives `#VALUE!`.
- Renaming an end rewrites the reference. Deleting an end moves it inward; deleting the only sheet gives `#REF!`.
- Copying shifts it like any reference. Inserting or deleting rows on one sheet of the run does not.
