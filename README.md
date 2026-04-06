# gridcalc

[![PyPI](https://img.shields.io/pypi/v/gridcalc)](https://pypi.org/project/gridcalc/)
[![Python](https://img.shields.io/pypi/pyversions/gridcalc)](https://pypi.org/project/gridcalc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A terminal spreadsheet powered by Python formulas, inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

```sh
$ gridcalc budget.json
```

## Features

- **Python formulas**: cell formulas are Python expressions evaluated with `eval()`
- **Curses-based TUI**: runs in any terminal, vim-style command mode
- **JSON file format**: spreadsheets stored as plain JSON, easy to version control or script
- **256 columns x 1024 rows**: column-major grid with four cell types (empty, number, label, formula)
- **Range arithmetic**: `A1:A10` expands to a `Vec` array supporting element-wise math
- **NumPy support**: use `np.array`, `np.linalg`, matrix multiply (`@`), and other numpy operations in formulas
- **Pandas support**: create and manipulate DataFrames in formulas, view as scrollable tables
- **CSV/pandas import/export**: `:csv` for plain CSV, `:pd` for pandas-powered multi-format I/O (CSV, TSV, Excel, JSON, Parquet)
- **Search**: `/` to search, `n`/`N` to cycle matches with position indicator
- **Copy/paste**: `y` to yank, `p` to paste (single cell or visual selection)
- **Sort**: `:sort [col] [desc]` to sort rows by column
- **Named ranges**: assign names to cell ranges and use them directly in formulas
- **Custom functions**: edit a Python code block (`:e`) to define functions, import modules, set constants
- **Built-in spreadsheet functions**: SUM, AVG, MIN, MAX, COUNT, ABS, SQRT, INT, plus Python's math module
- **Cell formatting**: bold, underline, italic, dollar/percent/integer/bar-chart formats, Python format specs
- **Absolute references**: `$A$1` syntax for references that stay fixed on replicate/insert/delete
- **Undo/redo**: full undo history with Ctrl-Z / Ctrl-Y
- **Sandbox**: AST-based validation blocks dangerous code in formulas and code blocks
- **Configurable**: TOML config file (`gridcalc.toml`) with XDG lookup

## Install

From PyPI (requires Python 3.10+):

```sh
pip install gridcalc
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install gridcalc
```

Then run:

```sh
gridcalc                     # new spreadsheet
gridcalc budget.json         # open a file
```

### From source

```sh
git clone https://github.com/shakfu/gridcalc.git
cd gridcalc
uv run gridcalc
```

## File format

Spreadsheets are stored as JSON:

```json
{
  "code": "def margin(rev, cost):\n    return (rev - cost) / rev * 100\n",
  "requires": ["numpy"],
  "names": {
    "revenue": "A1:A12",
    "costs": "B1:B12"
  },
  "cells": [
    ["Revenue", "Cost", "Margin"],
    [1000, 600, "=margin(A1, B1)"],
    [1200, 700, "=margin(A2, B2)"]
  ],
  "format": {
    "width": 10
  }
}
```

- **cells**: 2D array of cell values (numbers, strings, formulas, or null)
- **code** (optional): Python code executed before formulas (functions, imports, constants)
- **requires** (optional): list of modules to load into the formula namespace (e.g. `["numpy"]`)
- **names** (optional): named ranges mapping names to cell ranges
- **format** (optional): display settings (currently only `width`)

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
	:pd save [file]     Export via pandas (CSV, TSV, Excel, JSON, Parquet)
	:pd load [file]     Import via pandas (auto-detects format)
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

## Formulas

Formulas are Python expressions prefixed with `=`. Cell references like
`A1`, `B3`, `AA10` are available as variables.

	=A1 + B1 * 2
	=(A1 + A2) / 2
	=A1 ** 2
	=SQRT(A3 + A2)

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
import statistics

def margin(rev, cost):
    return (rev - cost) / rev * 100

def compound(principal, rate, years):
    return principal * (1 + rate) ** years

TAX_RATE = 0.21
```

Then use them in formulas: `=margin(A1, B1)`, `=compound(1000, 0.05, 10)`.

### Built-in functions

	SUM(x)    Sum of array or scalar
	AVG(x)    Average
	MIN(x)    Minimum
	MAX(x)    Maximum
	COUNT(x)  Number of elements
	ABS(x)    Absolute value (element-wise for arrays)
	SQRT(x)   Square root (element-wise for arrays)
	INT(x)    Truncate to integer (element-wise for arrays)

Math functions are preloaded: `sin`, `cos`, `tan`, `exp`, `log`,
`log2`, `log10`, `floor`, `ceil`, `pi`, `e`, `inf`. The `math` module
is also available for anything else (`=math.factorial(10)`).

Python builtins like `sum`, `min`, `max`, `abs`, `len` also work.

### Arrays

A formula can return an array. The cell displays the first element and
the count, e.g. `3.0[12]`. The full array is shown in the status bar.
Element-wise arithmetic works between arrays and scalars:

	=revenue * 1.1
	=revenue + costs

### Matrix operations

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

### DataFrame operations

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

`:csv` provides plain CSV import/export. `:pd` uses pandas for richer
format support:

	:csv save data.csv      Export evaluated values to CSV
	:csv load data.csv      Import cells from CSV
	:pd load data.csv       Import via pandas (CSV, auto-typed)
	:pd load data.xlsx      Import from Excel
	:pd load data.parquet   Import from Parquet
	:pd load data.tsv       Import from TSV
	:pd load data.json      Import from JSON
	:pd save results.xlsx   Export to Excel
	:pd save results.json   Export to JSON (records format)

`:pd load` places column headers in row 1 and data below. `:pd save`
uses row 1 as column headers.

### Cell references

References adjust automatically on replicate, insert, and delete.
Use `$` for absolute references: `$A$1` (fixed), `$A1` (fixed column),
`A$1` (fixed row).

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
