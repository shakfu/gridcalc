# gridcalc

A minimal spreadsheet for the terminal, based on Serge Zaitsev's Visicalc clone, [kalk](https://github.com/zserge/kalk).

Pure Python reimplementation of [pktcalc](https://github.com/sa/pktcalc) -- uses Python's own `eval()` for formulas instead of an embedded interpreter. Reads and writes JSON as its file format. File-compatible with pktcalc.

```sh
$ gridcalc budget.json
```

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

	uv run gridcalc              # run directly
	uv run gridcalc budget.json  # open a file

Or install as a tool:

	uv tool install .
	gridcalc budget.json

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

	make test       # run tests (120 pytest tests)

## License

MIT
