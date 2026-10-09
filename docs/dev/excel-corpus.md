# Excel corpus check

`scripts/excel_corpus.py` compares gridcalc's results with the values Excel saved in real workbooks. Excel stores each formula's last result beside the formula, so a file last saved by Excel carries its own expected answers. `excel-check.md` tests chosen formulas; this tests whatever real files contain.

    uv run python scripts/excel_corpus.py --json out.json path/to/*.xlsx

For each file the report gives:

- **agree / compared:** formula cells whose gridcalc result matches the saved value. Numbers compare with relative tolerance `--rel` (default 1e-9); text and errors compare exactly.
- **root / downstream:** a root mismatch reads no other mismatched cell. A downstream one does, so it is counted but not listed.
- **imported as values:** formula cells gridcalc read as their saved value, such as a data table. These are not compared.
- **without a saved value:** formula cells the file holds no result for. A file whose formulas all lack one was not last saved by Excel.

Root mismatches are then counted by the functions their formulas call.

## Limits

- Only `.xlsx` files are read. Many public spreadsheet corpora are `.xls`.
- gridcalc writes no saved value for a text or error result, so its own xlsx output cannot test those cells.
