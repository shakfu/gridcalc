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
	:b              Blank current cell
	:clear          Clear entire sheet
	:f <fmt>        Format/style cell (b u i L R I G D $ % * or Python spec)
	:gf <fmt>       Set global format
	:width <n>      Set column width (4-40)
	:dr             Delete row
	:dc             Delete column
	:ir             Insert row
	:ic             Insert column
	:m              Move row/column (arrow keys to drag)
	:r              Replicate (copy with relative refs)
	:name <n> [range]  Define named range
	:names          List named ranges
	:unname <n>     Remove named range
	:tv/:th/:tb/:tn Lock/unlock title rows/columns

Other keys:

	>           Go to cell (type reference)
	!           Force recalculation
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
