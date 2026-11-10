# Remaining gaps on untuned workbooks

Run 2026-11-09 on the 306 Sheetpedia files that Excel for Mac recalculated and saved. The sample and the earlier fixes are in `comparison.md`, section "Agreement on untuned workbooks".

| | Cells wrong | Cells compared | Files with a wrong cell |
|-|-|-|-|
| All files | 1,610 | 226,621 | 44 of 306 |
| Without the time-limit file | 1,232 | 221,844 | 43 of 305 |

The 1,610 cells trace to 998 root mismatches. A root reads no other wrong cell; the other cells are wrong only because they read one.

## Root mismatches by cause

| Cause | Root cells | Files | Fixable |
|-|-|-|-|
| 30 s recalc limit (`#CALC!`): 7,676 `AGGREGATE` formulas over 10,000 rows in `802559d...` | 378, varies with load | 1 | Needs native or vectorised element-wise operators (TODO, "Evaluator speed on large array formulas") |
| Numbers off by under 1e-6 relative, in one `SERIESSUM` file | 218 | 1 | Cause unknown |
| Excel gives a number, gridcalc gives text: names, `LET` | 110 | 3 | Probably |
| `RAND`, `RANDBETWEEN`, `NOW` | 87 | 11 | No: the values differ by design |
| `#NAME?`: the intersection operator in `(B:B) INDIRECT(..)`, unknown functions | 86 | 4 | Partly |
| Text differs: locale codes in `TEXT` (`"R$ #.##0,00"`), `FORMULATEXT` of an array formula | 74 | 6 | Partly |
| `#VALUE!`: `LET`, `BYROW`, `SCAN`, `N()` over an array, `CELL("filename")` | 24 | 9 | Partly |
| Other wrong numbers, `#N/A`, `CHAR` on Mac (Mac Roman) | 21 | 11 | Case by case |

The time-limit file and the volatile functions account for about 465 roots. The other roughly 530 are spread over about 25 files, a few cells each; no single fix covers many of them.

## Reproducing

```sh
# DIR: the extracted pii_processed_xlsx_0929 folder of tianzl66/Sheetpedia_xlsx
uv run python scripts/sheetpedia_sample.py DIR --n 400 --out random.txt
uv run python scripts/sheetpedia_sample.py DIR --n 126 --glob '*__*.xlsx' --out enron.txt
uv run python scripts/excel_resave.py --list sample.txt --out saved/
uv run python scripts/excel_gaps.py --list saved.txt --json gaps.json
```

`sample.txt` is `random.txt`, then the Enron files not already in it, up to 100. `saved.txt` lists the `dst` of each `ok` line in `saved/resave.jsonl`. The resave run here stopped after 327 files.

`excel_resave.py` needs a person at the screen. Files with external links show Excel's "update links" prompt, and each needs "Don't update" clicked. `open workbook ... update links do not update links` would avoid the prompt, but it failed with error -50 when given a POSIX path; an HFS path is untried.

`--from-json gaps.json --show "<cause>"` lists one example per file for a cause, without rescoring.
