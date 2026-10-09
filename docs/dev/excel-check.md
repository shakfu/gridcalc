# Excel check

Status: **run 2026-10-09 in Microsoft Excel for Mac 16.0300.** 25 of 52 cases agreed; 41 agree with gridcalc since. 25 cases were added after the run and await the next one: `text-9`..`text-14`, `num-1`, `crit-8`, `crit-9`, `db-3`, `db-4`, `yf-9`..`yf-20`, `misc-7`, `misc-8`.

`excel-check.xlsx` holds 77 formulas whose Excel result is unconfirmed. Each one comes from an open item in `TODO.md` or an *(inference)* verdict in `ironcalc-diff.md`. gridcalc's answers are filled in; Excel computes its own on open.

## Run it

1. Regenerate the workbook after any engine change: `uv run python scripts/excel_check.py docs/dev/excel-check.xlsx`.
2. Open it in Excel 365. Several cases need dynamic-array functions, so older versions do not apply. The file has no cached values, so Excel calculates every formula on open.
3. Check `setup` (row 2) is `TRUE`: the text, blank and error inputs are in place.
4. Filter column M for `FALSE`. Each is a disagreement.
5. Record the version (File > Account > About Excel) and each disagreement below. Move the confirmed item in `TODO.md` from "confirm against Excel" to a fix, or close it.

## Layout

| Columns | Content |
|-|-|
| A:H | Inputs. A2 and Z9 stay blank. G3 is `=NA()`. F1:G4 is a database with criteria in H1:H2. F6:G8 is a second one, with `=NA()` in its matched row G7 and criteria in H6:H7 |
| I | Case id |
| J | Formula as text |
| K | Formula, computed by Excel |
| L | gridcalc's result, stored as a number, text, logical or error |
| M | `TRUE` when K and L agree, comparing error types for errors |
| N | What is in doubt |

Array results are joined with `TEXTJOIN`, so no case spills into the next row. That also puts number-to-text formatting under test in those cases. Column K holds single-cell array formulas: stored as plain formulas, Excel would reduce a range passed to a one-value parameter to one cell. The cases in `PLAIN` in the script are stored as plain formulas, to compare with their array-formula twins. If Excel shows `#NAME?` in K, a function newer than Excel 2007 is missing from `_XLFN` in the script.

## Not covered by the sheet

These change formula text, so check them by hand:

- On a sheet `Tmp`, enter 1 in A2. On another sheet, enter `=Tmp!A2*2`. Delete `Tmp`. gridcalc rewrites the formula to `=#REF!*2`.
- Enter 5 in Sheet1!A3 and `=sheet1!A3*2` on another sheet. Delete Sheet1 row 2. gridcalc rewrites the formula to `=sheet1!A2*2`, keeping the case as typed.

## Results

Run 2026-10-09, Microsoft Excel for Mac, `AppVersion` 16.0300 (from `docProps/app.xml`; the build number was not recorded). `setup` is `TRUE`.

The first run had two faults in column M, fixed in `scripts/excel_check.py` since:

- `yf-1` read `FALSE` but agrees exactly. openpyxl writes floats with `%.16g`, so L held 0.16944444444444451 for 0.16944444444444445. L now holds such a value as a formula with all 17 digits.
- `text-8` read `TRUE` but disagrees. `=` ignores case on text, so `1E+20` matched `1e+20`. M now compares text with `EXACT`.

With both corrected, 27 cases disagree:

| Case | Excel | gridcalc | Cause |
|-|-|-|-|
| `pow-1` | 64 | 512 | `^` was right-associative; fixed in EXCEL mode |
| `text-1`..`text-3` | `0.00001`, `0.0000000001`, `-0.0000123` | `1e-05`, `1e-10`, `-1.23e-05` | `%g` formatting; fixed |
| `text-7` | `12345678901234500` | `1.23456789012346e+16` | Excel keeps 15 digits of a typed number *(inference)*; `num-1` checks it |
| `text-8` | `1E+20` | `1e+20` | exponent case; fixed |
| `blank-1`, `blank-2` | 3 | `#VALUE!` | blank number argument; fixed |
| `blank-3` | `""` | `#VALUE!` | blank count argument; fixed |
| `lift-2` | `5,0,7,-3` | `#VALUE!` | blank `A2` reaching `ROUND`; fixed |
| `crit-1`, `crit-2` | 1 | 0 | text `"3"` matches criterion `3` and `"3"`, but not `">1"` (`crit-3` agrees); fixed |
| `crit-5` | 4.5 | 0 | `sum_range` resized from its top-left; fixed |
| `arr-1` | 3 | `#VALUE!` | `ROWS(FILTER(...))`; fixed |
| `arr-2` | `2,2,1` | `4,0,1` | `FREQUENCY` with unsorted bins counts as if the bins were sorted |
| `arr-3` | `FALSE,FALSE,TRUE` | `#VALUE!` | `ISFORMULA` over a range; fixed |
| `db-1`, `db-2` | 4, 2 | `#N/A` | Excel ignores an error in a row the criteria do not match; fixed |
| `yf-2`, `yf-6` | 61/366, 365/366 | 61/365.5, 365/365.5 | basis 1: Excel averages year lengths only when the dates are more than a year apart *(inference from 4 cases)* |
| `yf-5`, `yf-7` | 1, 1 | 0.99722, 1.00278 | basis 0: end-of-February rules of US 30/360 |
| `misc-2` | `1.22464679914735E-16+2i` | `2i` | Excel computes `IMSQRT` in polar form and keeps the residue |
| `misc-3`, `misc-4` | `TRUE` | `#VALUE!` | text literal in `OR`/`XOR` |
| `misc-5` | 2 | `#N/A` | intended: Excel's answer depends on where its binary search probes, so gridcalc gives `#N/A` with a reason (CHANGELOG) |
| `misc-6` | `1` | `3` | `TEXT(3,1)`: the number 1 is a format code with a literal `1` |

`misc-3` and `misc-4` may depend on the harness *(inference)*. Column K holds array formulas. Microsoft's [`OR` page](https://support.microsoft.com/en-us/office/or-function-7d17ad14-8700-4281-b308-00b131e22af0) says text in an array or reference is ignored, and does not cover a text literal. `misc-7` and `misc-8` repeat them as plain formulas.

`date-1` settles the `EOMONTH` verdict in `ironcalc-diff.md`: Excel gives 59, as gridcalc does.

The two hand checks under "Not covered by the sheet" were not run.
