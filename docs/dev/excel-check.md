# Excel check

Status: **sheet drafted, not yet run in Excel.**

`excel-check.xlsx` holds 52 formulas whose Excel result is unconfirmed. Each one comes from an open item in `TODO.md` or an *(inference)* verdict in `ironcalc-diff.md`. gridcalc's answers are filled in; Excel computes its own on open.

## Run it

1. Regenerate the workbook after any engine change: `uv run python scripts/excel_check.py docs/dev/excel-check.xlsx`.
2. Open it in Excel 365. Several cases need dynamic-array functions, so older versions do not apply. The file has no cached values, so Excel calculates every formula on open.
3. Check `setup` (row 2) is `TRUE`: the text, blank and error inputs are in place.
4. Filter column M for `FALSE`. Each is a disagreement.
5. Record the version (File > Account > About Excel) and each disagreement below. Move the confirmed item in `TODO.md` from "confirm against Excel" to a fix, or close it.

## Layout

| Columns | Content |
|-|-|
| A:H | Inputs. A2 and Z9 stay blank. G3 is `=NA()`. F1:G4 is a database with criteria in H1:H2 |
| I | Case id |
| J | Formula as text |
| K | Formula, computed by Excel |
| L | gridcalc's result, stored as a number, text, logical or error |
| M | `TRUE` when K and L agree, comparing error types for errors |
| N | What is in doubt |

Array results are joined with `TEXTJOIN`, so no case spills into the next row. That also puts number-to-text formatting under test in those cases. Column K holds single-cell array formulas: stored as plain formulas, Excel would reduce a range passed to a one-value parameter to one cell. If Excel shows `#NAME?` in K, a function newer than Excel 2007 is missing from `_XLFN` in the script.

## Not covered by the sheet

These change formula text, so check them by hand:

- On a sheet `Tmp`, enter 1 in A2. On another sheet, enter `=Tmp!A2*2`. Delete `Tmp`. gridcalc rewrites the formula to `=#REF!*2`.
- Enter 5 in Sheet1!A3 and `=sheet1!A3*2` on another sheet. Delete Sheet1 row 2. gridcalc rewrites the formula to `=sheet1!A2*2`, keeping the case as typed.

## Results

Not run yet.
