# Excel check

Status: **second run 2026-10-21 in Microsoft Excel for Mac**, `AppVersion` 16.0300. 79 of 87 cases agreed; gridcalc has since been changed to match 6 more. `misc-2` and `misc-5` still disagree. The `3d-1` row-insert hand check was not run.

`excel-check.xlsx` holds 87 formulas whose Excel result is unconfirmed. Each one comes from an open item in `TODO.md` or an *(inference)* verdict in `ironcalc-diff.md`. gridcalc's answers are filled in; Excel computes its own on open.

## Run it

1. Regenerate the workbook after any engine change: `uv run python scripts/excel_check.py build/excel-check.xlsx`.
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
| Sheets `S3a`..`S3c` | Inputs for the `3d-*` cases: B2 holds 10, 20 and 30, and `S3b!B3` holds text |

Array results are joined with `TEXTJOIN`, so no case spills into the next row. That also puts number-to-text formatting under test in those cases. Column K holds single-cell array formulas: stored as plain formulas, Excel would reduce a range passed to a one-value parameter to one cell. The cases in `PLAIN` in the script are stored as plain formulas, to compare with their array-formula twins. If Excel shows `#NAME?` in K, a function newer than Excel 2007 is missing from `_XLFN_NAMES` in `engine.py`.

## Not covered by the sheet

These change formula text, so check them by hand:

- On a sheet `Tmp`, enter 1 in A2. On another sheet, enter `=Tmp!A2*2`. Delete `Tmp`. gridcalc rewrites the formula to `=#REF!*2`.
- Enter 5 in Sheet1!A3 and `=sheet1!A3*2` on another sheet. Delete Sheet1 row 2. gridcalc rewrites the formula to `=sheet1!A2*2`, keeping the case as typed.
- After recording the run, select `S3b` alone and insert a row above row 2. Then read `3d-1` on `check`. 40 with the formula unchanged means Excel leaves a 3D reference alone when one sheet of the run gains a row, as gridcalc does. 20 with the formula reading `S3a:S3c!B3` means Excel shifts it.

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

### Run 2026-10-21

Microsoft Excel for Mac, version not recorded. Read from a PDF export of the computed sheet, so values carry 9 decimals at most. `setup` is `TRUE`. 29 cases read `FALSE`:

| Case | Excel | gridcalc | Verdict |
|-|-|-|-|
| `text-7`, `num-1` | `12345678901234500`, 0 | `12345678901234600`, 68 | Excel keeps 15 digits of a typed number; confirmed |
| `text-9`, `text-10` | `0.00000000001`, `0.000000000000001` | `1E-11`, `1E-15` | plain decimals past exponent -10; `text-11` (`1E-19`) and `text-12` (`3.33333333333333E-11`) are scientific in both |
| `crit-8`, `crit-9` | 4, 3 | 2, 2 | `"<>"` counts text and blanks |
| `arr-2` | `2,2,1` | `4,0,1` | unchanged |
| `db-4` | 0 | `#N/A` | `DCOUNT` skips an error in a matched row; `DSUM` propagates it (`db-3` agrees) |
| `yf-2`, `yf-6`, `yf-10`..`yf-12`, `yf-14` | | | basis 1 year length; rule in `TODO.md` |
| `yf-5`, `yf-7`, `yf-18`, `yf-19` | | | basis 0 end-of-February rules; rule in `TODO.md` |
| `yf-3`, `yf-8`, `yf-15`, `yf-16` | | | harness, not gridcalc; see below |
| `misc-2` | `1.22464679914735E-16+2i` | `2i` | unchanged |
| `misc-3`, `misc-4`, `misc-7`, `misc-8` | `TRUE` | `#VALUE!` | text literal ignored in `OR`/`XOR`, as a plain formula too |
| `misc-5` | 2 | `#N/A` | intended, as before |
| `misc-6` | `1` | `3` | unchanged |

`yf-3`, `yf-8`, `yf-15` and `yf-16` show the same value in K and L. In each, gridcalc's result is the correctly rounded exact ratio (613/360, 366/365.5, 366/365.5, 60/360). Each is one of the 8 cases whose L is written as a 17-digit formula, and `num-1` shows Excel keeps only 15 digits of a typed number. So L loses digits that K keeps *(inference)*. `yf-1` takes the same path and reads `TRUE`; why is not known. The script now writes every number in L as a stored value with 17 digits, not a formula.

### Run 2026-10-21, second

Microsoft Excel for Mac, `AppVersion` 16.0300 (from `docProps/app.xml`). Read from the workbook Excel saved, so values are exact. `setup` is `TRUE`. 8 cases read `FALSE`:

| Case | Excel | gridcalc | Verdict |
|-|-|-|-|
| `text-9`, `text-10`, `text-15`..`text-17` | `0.00000000001`, ..., `-0.000000000000000001` | `1E-11`, ..., `-1E-18` | scientific form only past 20 characters of plain text, sign excluded; fixed |
| `logic-1` | `TRUE` | `#VALUE!` | `AND` skips typed text, as `OR` does; fixed |
| `misc-2` | `1.22464679914735E-16+2i` | `2i` | unchanged |
| `misc-5` | 2 | `#N/A` | intended, as before |

The 20-character rule fits all 19 `text-*` cases. `text-16` (21 characters with the sign) is plain, and `text-19` (21 without it) is scientific. `logic-2` and `logic-3` agree: `OR("a")` is `#VALUE!` and typed `"TRUE"` counts. `3d-1` and `3d-2` agree.
