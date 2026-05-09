# gridcalc

[![PyPI](https://img.shields.io/pypi/v/gridcalc)](https://pypi.org/project/gridcalc/)
[![Python](https://img.shields.io/pypi/pyversions/gridcalc)](https://pypi.org/project/gridcalc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A terminal spreadsheet powered by Python formulas, inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

```sh
$ gridcalc budget.json
```

## Features

- **Three formula modes** (per file): `EXCEL` (strict Excel grammar, no Python),
  `HYBRID` (Excel grammar plus a `py.*` gateway to user-defined Python),
  `LEGACY` (Python `eval()`, full numpy/pandas/list-comprehensions). New TUI
  files default to HYBRID; existing files without an explicit mode load as
  LEGACY for back-compat.
- **Multi-sheet workbooks**: a workbook can contain any number of named
  sheets. Formulas reference cells on other sheets via `=Sheet2!A1`,
  `=SUM(Sheet2!A1:A10)`, etc.; cross-sheet recalc is wired through the
  dep graph. Manage sheets via `:sheet add/del/rename/list`; switch with
  `:sheet NAME` or `:sheet N`.
- **xlsx interop**: `:xlsx load` reads every sheet's formulas and values
  from an `.xlsx` file via the OpenXLSX-backed C++ shim and evaluates
  them with the EXCEL evaluator; `:xlsx save` writes computed values
  back, preserving sheet structure.
- **Curses-based TUI**: runs in any terminal, vim-style command mode
- **JSON file format**: spreadsheets stored as plain JSON, easy to version control or script
- **256 columns x 1024 rows**: column-major grid with four cell types (empty, number, label, formula)
- **Range arithmetic**: `A1:A10` expands to an array supporting element-wise math
- **NumPy / pandas support** (LEGACY mode): `np.array`, `np.linalg`, matrix
  multiply (`@`), DataFrames, `:view` for scrollable tables
- **Multi-format import/export**: `:csv`, `:xlsx`, `:pd` (CSV, TSV, Excel, JSON, Parquet)
- **Search**: `/` to search, `n`/`N` to cycle matches with position indicator
- **Copy/paste**: `y` to yank, `p` to paste (single cell or visual selection)
- **Sort**: `:sort [col] [desc]` to sort rows by column
- **Named ranges**: assign names to cell ranges and use them directly in formulas
- **Custom functions** (HYBRID/LEGACY): edit a Python code block (`:e`) to
  define functions, import modules, set constants
- **Excel-compatible function library**: IF, IFERROR, AND, OR, NOT, ROUND,
  AVERAGE, MEDIAN, SUMIF, COUNTIF, AVERAGEIF, VLOOKUP, HLOOKUP, INDEX, MATCH,
  CONCATENATE, LEFT, RIGHT, MID, LEN, TRIM, UPPER, LOWER, SUBSTITUTE, and
  many more (auto-loaded in EXCEL/HYBRID modes)
- **Built-in spreadsheet functions**: SUM, AVG, MIN, MAX, COUNT, ABS, SQRT, INT, plus Python's math module
- **Cell formatting**: bold, underline, italic, dollar/percent/integer/bar-chart formats, Python format specs
- **Absolute references**: `$A$1` syntax for references that stay fixed on replicate/insert/delete
- **Undo/redo**: full undo history with Ctrl-Z / Ctrl-Y
- **Sandbox**: AST-based validation blocks dangerous code in formulas and code blocks (LEGACY); EXCEL/HYBRID formulas don't use `eval()` at all
- **Configurable**: TOML config file (`gridcalc.toml`) with XDG lookup

## Install

From PyPI (requires Python 3.10+):

```sh
pip install gridcalc                  # core only -- stdlib + tomli (3.10)
pip install 'gridcalc[numpy]'         # adds ndarray support; speeds up regression
pip install 'gridcalc[pandas]'        # adds DataFrame support (implies numpy)
pip install 'gridcalc[viz]'           # syntax-highlighted code preview (Pygments)
pip install 'gridcalc[all]'           # everything
```

The core install has **zero third-party runtime dependencies** (just `tomli`
on Python 3.10 for TOML config; 3.11+ uses stdlib `tomllib`). All 300+
Excel functions, including the full statistical-distribution suite,
financial functions, and the regression family (`LINEST`/`LOGEST`/
`TREND`/`GROWTH`), work on stdlib alone.

Optional extras add capability or speed:

- `[numpy]` — enables `np.array(...)` formulas and ndarray cell values;
  also speeds up `_solve_linear_system` (LAPACK-backed) and the
  `LINEST`-family `X'X` build for large datasets. Pure-Python Gauss-Jordan
  is the fallback when numpy isn't installed.
- `[pandas]` — enables `pd.DataFrame(...)` formulas, the `:pd load` /
  `:pd save` commands, and DataFrame cell display.
- `[viz]` — Pygments syntax-highlighting for the trust-prompt code
  preview. Falls back to plain text when missing.

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install gridcalc
uv tool install 'gridcalc[all]'       # with all extras
```

Then run:

```sh
gridcalc                     # new spreadsheet
gridcalc budget.json         # open a JSON spreadsheet
gridcalc model.xlsx          # open an Excel file (read-only by default;
                             #   :xlsx save <name>.xlsx to write back)
```

### From source

```sh
git clone https://github.com/shakfu/gridcalc.git
cd gridcalc
uv run gridcalc
```

### Examples

Four example files ship with the repo:

```sh
gridcalc example_excel.json       # EXCEL mode: sales report, named ranges, IF/IFERROR/MATCH
gridcalc example_hybrid.json      # HYBRID mode: progressive tax via py.* + Excel aggregations
gridcalc example.json             # LEGACY mode: numpy/pandas/list-comprehension formulas
gridcalc example_multisheet.json  # EXCEL mode: 3-sheet budget model with cross-sheet formulas
```

## File format

Spreadsheets are stored as JSON. The current on-disk format is **v2**;
v1 files (single sheet, top-level `cells`) still load unchanged.

```json
{
  "version": 2,
  "mode": "HYBRID",
  "active": "Inputs",
  "code": "def margin(rev, cost):\n    return (rev - cost) / rev * 100\n",
  "names": {
    "revenue": "A1:A12",
    "costs":   "B1:B12"
  },
  "sheets": [
    {
      "name": "Inputs",
      "cells": [
        ["Revenue", "Cost", "Margin"],
        [1000, 600, "=py.margin(A1, B1)"],
        [1200, 700, "=py.margin(A2, B2)"]
      ]
    },
    {
      "name": "Summary",
      "cells": [
        ["Total margin", "=SUM(Inputs!C1:C12)"]
      ]
    }
  ],
  "format": {
    "width": 10
  }
}
```

- **mode** (optional): `"EXCEL"`, `"HYBRID"`, or `"LEGACY"`. Absent means
  `LEGACY` (back-compat with files saved before the modes feature). New
  files saved by the TUI default to `HYBRID`.
- **sheets** (v2): list of `{name, cells}` objects. Each sheet's `cells`
  is a 2D array (numbers, strings, formulas, or null) just like v1.
  v1 files have a top-level `cells` array instead and load as a single
  sheet named `Sheet1`.
- **active** (v2, optional): name of the sheet to make active on load;
  defaults to the first sheet.
- **cells** (v1 only): 2D array of cell values, single sheet.
- **code** (optional): Python code executed before formulas. In `HYBRID`
  mode, callables defined here are reachable from formulas as `py.<name>(...)`.
  In `LEGACY` mode, they are reachable as bare names.
- **requires** (optional, LEGACY): list of modules to load into the
  formula namespace (e.g. `["numpy"]` or `["numpy>=1.24"]` -- version
  specifiers are honoured).
- **names** (optional): named ranges, e.g. `"revenue": "A1:A12"`. Names
  are workbook-global and **sheet-relative**: a formula `=SUM(revenue)`
  on Sheet2 sums Sheet2!A1:A12, not the sheet where the name was
  defined. Use a sheet-qualified ref directly in the formula
  (`=SUM(Inputs!A1:A12)`) when you need to pin to a specific sheet.
- **format** (optional): display settings (currently only `width`)

xlsx files (`.xlsx`) can also be loaded directly with `:xlsx load` --
every sheet is read and the workbook is treated as `EXCEL` mode
automatically.

## Usage

Arrow keys navigate. Type a number or `=` to enter data. Formulas start
with `=` and are Python expressions. Anything else is a label.

Press `:` for the command line (vim-style):

	:q              Quit
	:q!             Force quit (no save prompt)
	:w [file]       Save
	:wq [file]      Save and quit
	:e              Edit code block in $EDITOR
	:o [file]       Open file
	:b              Blank current cell (or selection in visual mode)
	:clear          Clear entire sheet
	:f <fmt>        Format/style cell (b u i L R I G D $ % * or Python spec)
	:gf <fmt>       Set global format
	:width <n>      Set column width (4-40)
	:dr             Delete row (or selected rows in visual mode)
	:dc             Delete column (or selected columns in visual mode)
	:ir             Insert row
	:ic             Insert column
	:m              Move row/column (arrow keys to drag)
	:r              Replicate (copy with relative refs)
	:sort [col] [desc]  Sort rows by column (visual mode: sort selection)
	:view           View DataFrame/matrix as scrollable table
	:csv save [file]    Export evaluated values to CSV
	:csv load [file]    Import cells from CSV
	:xlsx save [file]   Export to .xlsx (values)
	:xlsx load [file]   Import from .xlsx (formulas + values, sets mode=EXCEL)
	:pd save [file]     Export via pandas (CSV, TSV, Excel, JSON, Parquet)
	:pd load [file]     Import via pandas (auto-detects format)
	:mode [excel|hybrid|legacy]   Show or set the formula evaluator mode
	:sheet              List sheets (active marked with *)
	:sheet <name>       Switch active sheet by name
	:sheet <N>          Switch active sheet by zero-based index
	:sheet add <name>   Append a new sheet (does not switch)
	:sheet del <name>   Remove sheet (refuses last sheet)
	:sheet rename <old> <new>   Rename sheet (rewrites formula text)
	:sheet move <name> <N>      Reorder sheet to zero-based index N
	:name <n> [range]   Define named range
	:names          List named ranges
	:unname <n>     Remove named range
	:tv/:th/:tb/:tn Lock/unlock title rows/columns

Other keys:

	>           Go to cell (type reference)
	/           Search (type pattern, Enter to find)
	n           Next search match
	N           Previous search match
	y           Yank (copy) current cell
	p           Paste yanked cell(s) at cursor
	v           Enter visual selection mode
	!           Force recalculation
	e / F2      Edit current cell (pre-fills existing content)
	E           Open object editor for Vec/ndarray/DataFrame cells
	"           Enter label
	Backspace   Clear cell
	Tab         Next column
	Enter       Next row
	Home        Jump to A1
	Ctrl-B      Toggle bold
	Ctrl-U      Toggle underline
	Ctrl-Z      Undo
	Ctrl-Y      Redo
	Ctrl-C      Quit

### Visual selection mode

Press `v` to enter visual mode. Arrow keys extend the selection from the
anchor cell. Selected cells are highlighted in magenta.

	y           Yank (copy) selection
	d           Delete (clear) all cells in selection
	p           Paste at selection origin
	Backspace   Delete (clear) all cells in selection
	:           Enter command line (commands apply to selection)
	Esc         Cancel

Commands that support visual selection: `:b` (blank range), `:f` (format
range), `:dr` (delete selected rows), `:dc` (delete selected columns),
`:sort` (sort selected rows).

### Object editor

Press `E` on a cell containing a Vec, NumPy array, or DataFrame to open
an interactive sub-grid editor. This lets you edit individual elements
without rewriting the entire formula.

	Arrow keys  Navigate cells
	Enter / e   Edit value under cursor
	H           Jump to column header row (DataFrame only)
	o / O       Insert row after / before current
	a / A       Insert column after / before current (ndarray/DataFrame)
	x           Delete current row
	X           Delete current column (ndarray/DataFrame)
	w           Save and exit
	Esc         Cancel (discard changes)

On save, the editor writes back a literal formula (`=Vec([...])`,
`=np.array([...])`, or `=pd.DataFrame({...})`).

## Modes

Each spreadsheet has one of three modes, controlling how formulas are
evaluated:

| Mode | Grammar | Python escape hatch | Sandbox needed | Use case |
|------|---------|---------------------|----------------|----------|
| `EXCEL` | strict Excel | none | no (no `eval`) | xlsx interop, untrusted files |
| `HYBRID` | Excel + `py.*` | code-block functions reachable as `py.foo(...)` | code blocks only | most new sheets |
| `LEGACY` | Python `eval()` | full Python expressions | full AST sandbox | numpy/pandas-heavy sheets, files predating modes |

Switch mode with `:mode <name>`. The TUI validates before switching:
if any formula doesn't parse in the target mode (e.g. switching from
LEGACY to EXCEL with a list comprehension still in a cell), the change
is refused with a one-line error pointing at the first offender.

The current mode is shown in the top-right of the status bar
(`[EXCEL]`, `[HYBRID]`, `[LEGACY]`).

Loading an `.xlsx` via `:xlsx load` automatically sets mode to `EXCEL`.

### Limitations

- **`INDIRECT`** is deliberately unsupported -- it would defeat static
  dependency analysis and the topological recalc ordering.
- **xlsx export writes values, not formulas.** Round-tripping formulas
  through `.xlsx` (level-c interop) is on the roadmap but not yet
  implemented. Multi-sheet structure *is* round-tripped; only the
  formula text is currently lost on save.
- **xlsx dates and styles** are not yet read or written by the
  OpenXLSX-backed `_core` shim. Date serials arrive as floats; styles
  and number formats are dropped.
- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse
  time -- Excel doesn't support them either; only `Sheet1!A1:B5`
  works.

## Formulas

Formulas are prefixed with `=`. Cell references like `A1`, `B3`, `AA10`
are available everywhere. Operators, precedence, and error values follow
Excel.

	=A1 + B1 * 2
	=(A1 + A2) / 2
	=2^10                       # exponent (right-associative)
	=50%                        # percent postfix; equals 0.5
	="hello " & A1              # string concatenation
	=IF(A1 > 0, "pos", "neg")   # string-returning formulas display as text
	=IF(A1 >= C1, A1*0.05, 0)
	=IFERROR(B1/C1, 0)          # catch #DIV/0!, #VALUE!, #N/A, etc.
	=SQRT(A3 + A2)

Formulas can return numbers, strings, booleans, ranges (1D arrays), or
Excel error values (`#DIV/0!`, `#N/A`, `#NAME?`, `#REF!`, `#VALUE!`,
`#NUM!`, `#NULL!`). Errors propagate through arithmetic and are
catchable with `IFERROR`/`IFNA`.

In `LEGACY` mode, `**` is supported instead of `^` and the full
Python expression language is available.

### Range syntax

Use `:` to reference a range of cells. Ranges expand into arrays (Vec)
that support element-wise arithmetic.

	=SUM(A1:A10)
	=AVG(B1:B3)
	=SUM(A1:A3 * B1:B3)

### Named ranges

Define a name for a cell range with `:name`, or in the JSON file's
`names` field. Names are injected as arrays and can be used directly in
formulas.

	=SUM(revenue)
	=SUM(revenue - costs)
	=MAX(revenue)
	=sum([x**2 for x in revenue])

### Custom functions

Use `:e` to open the code block in `$EDITOR`. The editor must block
until the file is closed (e.g., `vim`, `nano`, or `subl -w` for Sublime
Text). Define Python functions, import modules, set constants:

```python
def margin(rev, cost):
    return (rev - cost) / rev * 100

def compound(principal, rate, years):
    return principal * (1 + rate) ** years
```

In `HYBRID` mode, call them through the `py.*` namespace:
`=py.margin(A1, B1)`, `=py.compound(1000, 0.05, 10)`. This keeps the
Python boundary visible in every formula that crosses it.

In `LEGACY` mode, the same functions are reachable as bare names:
`=margin(A1, B1)`, `=compound(1000, 0.05, 10)`.

`EXCEL` mode forbids code blocks entirely.

### Built-in functions

Always available:

	SUM(x)    Sum of array or scalar
	AVG(x)    Average
	MIN(x)    Minimum
	MAX(x)    Maximum
	COUNT(x)  Number of elements
	ABS(x)    Absolute value (element-wise for arrays)
	SQRT(x)   Square root (element-wise for arrays)
	INT(x)    Truncate to integer (element-wise for arrays)

Math functions are preloaded: `sin`, `cos`, `tan`, `exp`, `log`,
`log2`, `log10`, `floor`, `ceil`, `pi`, `e`, `inf`.

Auto-loaded in `EXCEL`/`HYBRID` modes (Excel-compatible library):

	IF, IFERROR, AND, OR, NOT
	ROUND, ROUNDUP, ROUNDDOWN, MOD, POWER, SIGN
	AVERAGE, MEDIAN, SUMPRODUCT, LARGE, SMALL
	SUMIF, COUNTIF, AVERAGEIF
	VLOOKUP, HLOOKUP, INDEX, MATCH
	CONCATENATE, CONCAT, LEFT, RIGHT, MID, LEN
	TRIM, UPPER, LOWER, PROPER, SUBSTITUTE, REPT, EXACT

In `LEGACY` mode, the `math` module is available (`=math.factorial(10)`)
and Python builtins like `sum`, `min`, `max`, `abs`, `len` also work.

### Arrays

A formula can return an array. The cell displays the first element and
the count, e.g. `3.0[12]`. The full array is shown in the status bar.
Element-wise arithmetic works between arrays and scalars:

	=revenue * 1.1
	=revenue + costs

### Matrix operations (LEGACY mode)

When `numpy` is listed in `requires`, it is available as `np` in formulas.
Formulas can create and manipulate NumPy arrays:

	=np.array([[1,2],[3,4]])
	=np.eye(3)
	=np.linalg.det(A1)
	=np.linalg.inv(A1)
	=A1.T
	=A1 @ A2

Matrix cells display the shape, e.g. `[2x2]`. The full matrix is shown
in the status bar. Use `:view` to see the contents as a scrollable table.
Built-in functions like SUM and SQRT work element-wise on NumPy arrays.

### DataFrame operations (LEGACY mode)

When `pandas` is listed in `requires`, it is available as `pd` in formulas.
Formulas can create and manipulate DataFrames:

	=pd.DataFrame({'name': ['A','B','C'], 'val': [10,20,30]})
	=A1['val'].sum()
	=A1['val'].mean()
	=A1.describe()
	=A1.groupby('cat')['val'].sum()
	=A1[A1['val'] > 10]

DataFrame cells display `df[3x2]` (rows x columns). The status bar shows
column names. Use `:view` to see the full DataFrame as a scrollable table.

Series results are automatically converted to DataFrames.

### Import/export

Three import paths:

| Command | Reads | Writes | Notes |
|---------|-------|--------|-------|
| `:csv` | CSV | CSV | Plain text, fast |
| `:xlsx` | `.xlsx` formulas + values | `.xlsx` values | Sets mode to `EXCEL` on load; uses openpyxl |
| `:pd` | CSV/TSV/Excel/JSON/Parquet | same | Uses pandas; row 1 as headers |

	:csv save data.csv         Export evaluated values to CSV
	:csv load data.csv         Import cells from CSV
	:xlsx save results.xlsx    Export evaluated values to Excel
	:xlsx load model.xlsx      Import formulas + values from Excel
	:pd load data.parquet      Import via pandas (Parquet)
	:pd save results.json      Export via pandas (JSON records)

`:xlsx load` translates Excel formulas into the gridcalc EXCEL grammar
and reads every sheet in the workbook. Functions outside the
auto-loaded library produce `#NAME?`; `INDIRECT` is not supported
(deliberate -- it would defeat static dep analysis). Sheet-qualified
references (`Sheet1!A1`) work. xlsx export currently writes evaluated
values rather than formulas, but the multi-sheet structure round-trips.

### Cell references

References adjust automatically on replicate, insert, and delete.
Use `$` for absolute references: `$A$1` (fixed), `$A1` (fixed column),
`A$1` (fixed row).

### Multi-sheet workbooks

A workbook holds one or more named sheets. The status bar prefixes
the cell address with the active sheet name (`Sheet1!A1`) when the
workbook has more than one sheet; single-sheet workbooks keep the
original `A1` chrome.

	:sheet                    List all sheets (active marked *)
	:sheet add Inputs         Append "Inputs" (does not switch)
	:sheet del Tmp            Remove "Tmp" (refused if it's the last sheet)
	:sheet rename Old New     Rename + rewrite formula text
	:sheet move Inputs 0      Reorder "Inputs" to position 0 (first)
	:sheet Inputs             Switch active sheet by name
	:sheet 1                  Switch active sheet by zero-based index

Formulas reference cells on other sheets via the `Sheet!cell` syntax:

	=Sheet2!A1                       Cell on another sheet
	=SUM(Sheet2!A1:A10)              Cross-sheet range
	=Sheet1!A1 + Sheet2!A1           Mix in arithmetic

The dep graph carries sheet identity (`(sheet, c, r)` keys), so
changing a source cell on one sheet recalculates dependent formulas
on any sheet. Cross-sheet ranges (`Sheet1!A1:Sheet2!B5`) are rejected
at parse time -- Excel doesn't support them either; only same-sheet
ranges with a shared prefix work.

`:sheet rename OLD NEW` walks every formula on every sheet and
rewrites `OLD!` prefixes to `NEW!` (skipping matches inside string
literals like `="OLD!"`). The dep graph is rebuilt afterwards.

Named ranges (`:name`) are workbook-global and **sheet-relative**:
`revenue = A1:A12` defined on Sheet1 sums whichever sheet is active
when the formula runs. Use a sheet-qualified range
(`=SUM(Inputs!A1:A12)`) when you need to pin to a specific sheet.

## Formatting

Use `:f` to set the display format or style of a cell. All formats
and styles are persisted when saving.

### Text styles

Toggle with `:f` or keyboard shortcuts. Styles can be combined
in a single command:

	:f b            Toggle bold (also Ctrl-B)
	:f u            Toggle underline (also Ctrl-U)
	:f i            Toggle italic
	:f bi           Toggle bold + italic
	:f bui          Toggle bold + underline + italic

### Number formats

	:f $            Dollar (2 decimal places)
	:f %            Percentage (value * 100, 2 decimal places)
	:f I            Integer (truncate decimals)
	:f *            Bar chart (asterisks proportional to value)
	:f L            Left-align
	:f R            Right-align
	:f G            General (default)
	:f D            Use global format

Use `:gf` to set the global default format for all cells.

### Python format specs

For more control, pass any Python format specification:

	:f ,.2f         1,234.50 (comma thousands, 2 decimals)
	:f ,.0f         1,234,567 (comma thousands, no decimals)
	:f .1%          15.7% (percentage with 1 decimal)
	:f .4f          3.1416 (fixed 4 decimal places)
	:f .2e          1.23e+04 (scientific notation)

These use Python's `format()` builtin. Any valid
[format spec](https://docs.python.org/3/library/string.html#format-specification-mini-language)
works.

## Development

```sh
make test       # run tests
make lint       # ruff check
make format     # ruff format
make typecheck  # mypy
make qa         # lint + typecheck + test + format
```

### Publishing

```sh
make check        # build and check dist with twine
make publish-test # upload to TestPyPI
make publish      # upload to PyPI
```

## License

MIT
