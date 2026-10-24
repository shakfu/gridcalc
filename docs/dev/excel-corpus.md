# Excel corpus check

`scripts/excel_corpus.py` compares gridcalc's results with the values Excel saved in real workbooks. Excel stores each formula's last result beside the formula, so a file last saved by Excel carries its own expected answers. `excel-check.md` tests chosen formulas; this tests whatever real files contain.

    uv run python scripts/excel_corpus.py --json out.json path/to/*.xlsx

For each file the report gives:

- **agree / compared:** formula cells whose gridcalc result matches the saved value. Numbers compare with relative tolerance `--rel` (default 1e-9); text and errors compare exactly.
- **root / downstream:** a root mismatch reads no other mismatched cell. A downstream one does, so it is counted but not listed.
- **imported as values:** formula cells gridcalc read as their saved value, such as a data table. These are not compared.
- **without a saved value:** formula cells the file holds no result for. A file whose formulas all lack one was not last saved by Excel.

Root mismatches are then counted by the functions their formulas call.

## Survey of real workbooks

`scripts/xlsx_survey.py` needs no saved values. For each file it reports load time, unparseable formulas, missing functions, what a save would drop (`loader.xlsx_extras`), and what an xlsx save and reload changes.

    uv run python scripts/xlsx_survey.py --list files.txt --sample 2000 --json out.json

Run 2026-10-24 on 2,000 files sampled from Sheetpedia (`tianzl66/Sheetpedia_xlsx` on Hugging Face, CC-BY-SA-4.0). It mixes Enron files and Excel-forum attachments. openpyxl re-saved every file, so none has saved values to compare.

| | before | after |
|-|-|-|
| files loaded | 2,000 | 2,000 |
| unparseable formulas (of 558,513) | 48,248 | 46,054 |
| `#NAME?` results | 10,359 | 8,864 |
| files a round trip changes | 208 | 0 |

The fixes are in the CHANGELOG.

A second round added tables, `AGGREGATE`, array broadcasting and frozen panes, and sped up loading (CHANGELOG). Same 2,000 files:

| | after round 1 | after round 2 |
|-|-|-|
| unparseable formulas | 46,054 | 4,066 |
| `#NAME?` results | 8,864 | 7,857 |
| files a round trip changes | 0 | 0 |
| slowest three loads, 8 in parallel | 50-60 s | 18-33 s |

All 55 files with tables save and reload with the same tables and the same values. openpyxl reads the written table parts; no Excel or LibreOffice was available to open them. The corpus check moved to 76,683 of 79,104 (96.9%), 1,501 root mismatches, with no file worse. IronCalc's `tables.xlsx` keeps 35: `SUBTOTAL` there skips hidden and filtered rows, which gridcalc does not model.

What remains after round 1 is below; round 2 closed the structured references, `AGGREGATE` and frozen panes.

- Unparseable: structured references (`Table1[col]`), 42,182 cells in 55 files; references into other workbooks, 3,408 cells in 25 files. Those now show Excel's saved value. About 470 more are typos, `;` separators, or a reference union (`(A1:B2,C1:D2)`).
- Missing functions: `AGGREGATE` (5 files), `FILTERXML`, `GETPIVOTDATA`, and user-defined functions.
- A save drops, by files: conditional formatting 178, frozen panes 139, data validation 118, font effects 109, tables 106, comments 50, pivot tables 33, hyperlinks 30, charts 28, pattern fills 20, diagonal borders 15.
- Loads take up to 60 s; three files took over 25 s.

Rerunning the corpus check after these fixes: 76,476 of 79,104 agree (96.7%), 1,706 root mismatches. `BINOM.xlsx` now finishes; its 13 are argument checks that should give `#NUM!` or `#VALUE!`.

GitHub code search finds no binary files: its `.xlsx` hits are CSV text. It cannot supply Excel-saved workbooks.

## Limits

- Only `.xlsx` files are read. Many public spreadsheet corpora are `.xls`.
- gridcalc writes no saved value for a text or error result, so its own xlsx output cannot test those cells.

## Results

Run 2026-10-24 on 276 test workbooks: IronCalc's `xlsx/tests` and pycel's `tests/fixtures`, cloned from GitHub. 270 were last saved by Excel. They test functions at their edges, so the rates are lower than a typical workbook would give.

- 65,807 of 79,104 compared formula cells agree (83.2%).
- 12,296 root mismatches. 6,095 of them are `#NAME?`: a function gridcalc lacks.
- Missing, by mismatches: `FLOOR.PRECISE`, `ISO.CEILING`, `CEILING.PRECISE` (about 1,400 each), `REGEXTEST` (368), `BESSELJ`/`Y`/`I`/`K` (119 each), `SUBTOTAL` (68), `COTH`, `CSCH`, `SECH`, `ACOT`, `ACOTH`, `COT`, `CSC`, `SEC` (about 50 each), `BINOM.DIST.RANGE`, `MMULT`, `ERF.PRECISE`, `ERFC.PRECISE`, `ODDFPRICE`, `CELL`, `GAUSS`, and 20 more with under 15 each.
- Wrong answers, by mismatches: `ROMAN` with a `form` argument (3,101, one file), `FLOOR`/`CEILING`/`.MATH` (about 800), `ACCRINT` (255), `COUNTIF`/`COUNTIFS` with `"<>"` criteria (276), `TEXT` with `General` (127), `INDEX` edge cases, `XLOOKUP` match modes, `CONVERT` units, `LCM`, `WEEKNUM`.
- Structured table references (`Table1[col]`) are not parsed: 179 cells.
- `CHAR` of a control character reads as `_x0001_` in openpyxl, so its 56 mismatches are the harness's.

### After adding the 48 missing functions

Same corpus, same day: 71,154 of 79,104 agree (89.9%), and 6,983 root mismatches remain. The new functions account for under 500 of them. Most of those come from two shared gaps: implicit intersection of a range in a legacy formula, and date text in a numeric argument. `SUBTOTAL`'s 67 are structured table references. Open items are in `TODO.md`.

### After implicit intersection and date text

71,907 of 79,104 agree (90.9%), with 6,275 root mismatches. `ROMAN` with `form` is 3,096 of them, all in one file.

### After the wrong-answer round

76,211 of 78,836 agree (96.7%), 1,703 root mismatches. `ROMAN`, `FLOOR`/`CEILING`, `COUNTIF`/`COUNTIFS`, `ACCRINT`/`ACCRINTM` now agree in every case; `TEXT` misses 16. The largest remaining groups have under 70 each: `SUBTOTAL` (structured references), `INDEX`, `CHAR` (the harness), `XLOOKUP`, `CONVERT`, `LCM`, `GCD`, `INDIRECT`, `LINEST`, `WEEKNUM`. `BINOM.xlsx` was rerun after its CDF fix; the totals predate it.
