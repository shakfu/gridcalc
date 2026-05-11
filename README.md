# gridcalc

[![PyPI](https://img.shields.io/pypi/v/gridcalc)](https://pypi.org/project/gridcalc/)
[![Python](https://img.shields.io/pypi/pyversions/gridcalc)](https://pypi.org/project/gridcalc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A terminal spreadsheet powered by Python formulas. Vim-style command
line, curses TUI, JSON file format, zero runtime dependencies in the
core install. Inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

```sh
pip install gridcalc
gridcalc budget.json
```

---

## What it gives you

- **Excel-compatible formulas** (`=IF(A1>=B1, A1*0.05, 0)`) and arrays
  (`=SUM(A1:A10 * B1:B10)`) without leaving the terminal.
- **Multi-sheet workbooks** with cross-sheet refs (`=Sheet2!A1`) and a
  proper dep graph.
- **Three formula modes** per file: strict Excel, Excel-plus-`py.*`, or
  full Python `eval` with numpy/pandas.
- **xlsx interop** via OpenXLSX C++ -- read every sheet's
  formulas + values; export with cached values.
- **Linear & mixed-integer programming** built in via lp_solve -- `:opt max B4 vars
  A4:A5 st D4:D6` solves an LP from cells in the sheet. Models persist
  in the workbook.
- **Goal-seek** -- `:goal B10 = 100 by A1` adjusts a variable so a
  formula hits a target value.
- **Vim-style command line** (`:w`, `:e`, `:q`, `/search`, `y/p`, visual
  selection, undo).

Try it on the provided examples:

```sh
gridcalc example_excel.json          # sales report, named ranges, IF/MATCH
gridcalc example_hybrid.json         # progressive tax via py.* + aggregations
gridcalc example.json                # PYTHON: numpy/pandas, list-comprehensions
gridcalc example_multisheet.json     # 3-sheet budget, cross-sheet formulas
gridcalc example_lp.json             # LP/MIP demo -- type :opt to solve
gridcalc example_goal.json           # goal-seek demo -- :goal B1 = 11 by A1
```

## Install

Two options:

```sh
pip install gridcalc            # core: zero third-party runtime deps
pip install 'gridcalc[extras]'  # adds numpy, pandas, pygments
```

Or with [uv](https://docs.astral.sh/uv/): `uv tool install 'gridcalc[extras]'`.

The **core** install has **zero third-party runtime dependencies** --
the full 300+ Excel function library (statistical distributions,
financial functions, `LINEST`/`TREND` regression, ...) works on stdlib
alone. (The 3.10 wheel pulls `tomli` for config-file parsing; 3.11+
uses stdlib `tomllib`.)

The `[extras]` bundle enables, all at once:

- `np.array(...)` in formulas; LAPACK-backed solvers; faster `LINEST`.
- `pd.DataFrame(...)`, `:pd load/save`, DataFrame cell display.
- Pygments syntax-highlight in the load-time trust prompt.

## Quick tour

Cells hold a number, a label (any non-`=`-prefixed string), or a formula
(prefixed with `=`). Arrow keys move; `Enter` commits and moves down;
`Tab` commits and moves right.

```text
        A          B          C
1  Revenue   Cost       Margin
2  1000      600        =(A2-B2)/A2*100      <- formula
3  1200      700        =(A3-B3)/A3*100
4  Total     =SUM(B2:B3) =AVG(C2:C3)
```

Press `:` for the command line. The basics:

| Command | Purpose |
|---|---|
| `:w [file]` | save (extension `.json` or `.xlsx`) |
| `:o file` | open |
| `:q`, `:q!` | quit, force-quit |
| `:e` | edit the workbook's Python code block in `$EDITOR` |
| `u`, `Ctrl-R` | undo / redo |
| `v` | enter visual selection mode (then `y` yanks, `p` pastes) |
| `/text` | search (`n`/`N` to cycle matches) |
| `>` | go to a named cell (e.g. `> AA10`) |

A full command reference lives [in the Reference section below](#command-reference).

## Modes

Each workbook has one of three evaluation modes, controlling which
formulas parse and what's reachable from them:

| Mode | Grammar | Python escape hatch | Sandbox | Use case |
|---|---|---|---|---|
| `EXCEL` | strict Excel | none | not needed (no `eval`) | xlsx interop, untrusted files |
| `HYBRID` | Excel + `py.*` | code-block functions reachable as `py.foo(...)` | code blocks only | most new sheets |
| `PYTHON` | Python `eval()` | full Python expressions | full AST sandbox | numpy/pandas-heavy work |

Switch with `:mode <name>` -- the change is refused if any current
formula doesn't parse in the target mode. Files without an explicit
`mode` field load as `PYTHON` (back-compat). `:xlsx load` switches to
`EXCEL` automatically.

## Formulas

```text
=A1 + B1 * 2                          arithmetic, Excel precedence
=(A1 + A2) / 2                        grouping
=2^10                                 exponent (PYTHON: ** also works)
=50%                                  percent postfix -> 0.5
="hello " & A1                        string concat
=IF(A1 > 0, "pos", "neg")             conditionals
=IFERROR(B1/C1, 0)                    error catch -- #DIV/0!, #VALUE!, #N/A, ...
=SUM(A1:A10)                          range -> 1D array
=SUM(A1:A3 * B1:B3)                   element-wise array arithmetic
=SUM(revenue)                         named range
=py.margin(A1, B1)                    HYBRID: call a code-block function
```

Excel error values (`#DIV/0!`, `#N/A`, `#NAME?`, `#REF!`, `#VALUE!`,
`#NUM!`, `#NULL!`) propagate through arithmetic and are catchable with
`IFERROR`/`IFNA`.

**Built-in functions** (always available): `SUM`, `AVG`, `MIN`, `MAX`,
`COUNT`, `ABS`, `SQRT`, `INT`, plus everything in `math` (`sin`, `cos`,
`log`, `pi`, `e`, ...).

**Excel-compatible library** (auto-loaded in `EXCEL`/`HYBRID`): `IF`,
`IFERROR`, `AND`, `OR`, `NOT`, `ROUND`, `AVERAGE`, `MEDIAN`, `SUMIF`,
`COUNTIF`, `AVERAGEIF`, `VLOOKUP`, `HLOOKUP`, `INDEX`, `MATCH`,
`CONCATENATE`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`,
`SUBSTITUTE`, and 280+ others.

**PYTHON-only** extras: the `math` module, Python builtins (`sum`,
`min`, `max`, `abs`, `len`), list comprehensions, and -- when the
relevant extras are installed -- `np.array(...)`, `np.linalg`, matrix
multiply (`@`), and `pd.DataFrame(...)`.

### Named ranges & custom functions

```text
:name revenue A1:A12       Define a named range (workbook-global)
:names                     List
:unname revenue            Remove
```

Used directly in formulas: `=SUM(revenue)`, `=MAX(revenue - costs)`.

Open the per-workbook Python code block with `:e`. Anything defined there
becomes callable from formulas:

```python
def margin(rev, cost):
    return (rev - cost) / rev * 100
```

In `HYBRID`: `=py.margin(A1, B1)`. In `PYTHON`: `=margin(A1, B1)`.
`EXCEL` mode forbids code blocks entirely.

### Cell references

`$A$1` fixes both; `$A1` fixes the column; `A$1` fixes the row.
References adjust automatically on insert/delete/replicate.

## Multi-sheet workbooks

```text
:sheet                     List sheets (active marked *)
:sheet Inputs              Switch by name
:sheet 1                   Switch by zero-based index
:sheet add Outputs         Append (does not switch)
:sheet del Tmp             Remove (refused if last sheet)
:sheet rename Old New      Rename, rewriting `Old!` prefixes in formulas
:sheet move Inputs 0       Reorder
```

Reference cells on other sheets with `Sheet!cell`:

```text
=Sheet2!A1
=SUM(Sheet2!A1:A10)
=Sheet1!A1 + Sheet2!B1
```

The dep graph is keyed on `(sheet, col, row)` so cross-sheet recalc
works transparently. Cross-sheet *ranges* (`Sheet1!A1:Sheet2!B5`) are
not supported (Excel doesn't either).

## Optimization

`:opt` solves linear and mixed-integer programs defined by cells in the
active sheet, via a vendored copy of [lp_solve 5.5](https://lpsolve.sourceforge.net/).
Models are **workbook-persistent**: define once, save the file, re-run
on reopen.

```text
:opt                                                                       Run the saved 'default' model
:opt max|min <cell> vars <cells> st <cells> [bounds <spec>] [int <cells>] [bin <cells>]
                                                                           Solve inline AND save as 'default'
:opt def <name> max|min <cell> ...                                         Save under <name>; does not execute
:opt run [<name>]                                                          Execute a saved model
:opt list                                                                  List saved models
:opt undef <name>                                                          Remove a saved model
```

The **model** is sheet-resident: an objective formula in one cell,
decision-variable cells holding values, and constraint cells holding
comparison formulas like `=A1+A2<=10`. The constraint cells keep
evaluating during recalc, so the sheet shows live feasibility
(`TRUE`/`FALSE`) before and after the solve.

A worked example (also at `examples/example_lp.json`):

| | A | B | C | D |
|---|---|---|---|---|
| **3** | Decision | Objective | | Constraints |
| **4** | `0` | `=3*A4+5*A5` | | `=A4<=4` |
| **5** | `0` | | | `=2*A5<=12` |
| **6** | | | | `=3*A4+2*A5<=18` |

```text
:opt max B4 vars A4:A5 st D4:D6
```

Status bar shows `opt: OPTIMAL  obj=36`; `A4` and `A5` become `2.0`
and `6.0`; `u` rolls back.

**Clauses** (any order after `st`):

- `bounds A1=lo:hi, B2=lo:hi` -- per-variable bounds. `lo`/`hi` accept
  `inf`, `+inf`, `-inf`. Default is `[0, +inf)`.
- `int <cells>` -- decision variables are integer-valued (branch-and-bound).
- `bin <cells>` -- decision variables are binary (`{0,1}`); bounds
  clamped to `[0,1]`.

Cell lists everywhere accept ranges (`A1:A5`), comma-separated refs
(`A1,A3,B5`), or a mix.

Saved models live under `"models": {<name>: ...}` in the JSON file
and round-trip verbatim (the spec strings the user typed are stored,
not pre-resolved coords).

**Programmatic access:**

```python
from gridcalc.engine import Grid
from gridcalc.opt import solve

g = Grid()
g.jsonload("examples/example_lp.json")
g.recalc()
r = solve(g, objective_cell=(1, 3), decision_vars=[(0, 3), (0, 4)],
          constraint_cells=[(3, 3), (3, 4), (3, 5)], maximize=True)
print(r.status_name, r.objective, r.values)
```

### Goal-seek

For 1-D what-if ("what input makes this output equal X?"), use `:goal`:

```text
:goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]
```

```text
:goal B10 = 100 by A1                 auto-bracket from A1's current value
:goal B10 = 0 by A1 in -50:50         explicit search bracket
```

Uses bisection over `Grid.recalc()`; converges in milliseconds at
spreadsheet scale. The variable cell must hold a value (not a formula).
On success the variable cell is overwritten; `u` rolls back. Unlike
`:opt`, goal-seek isn't persisted -- the three args fit on one line, so
retyping is faster than naming.

## Formatting

```text
:f b                Toggle bold (also Ctrl-B)
:f u                Toggle underline (also Ctrl-U)
:f i                Toggle italic
:f bi               Combine: bold + italic

:f $                Dollar (2 decimal places)
:f %                Percentage (value*100, 2 decimals)
:f I                Integer (truncate)
:f *                Bar chart (asterisks proportional to value)
:f L | R | G | D    Left / right / general / use-global-format

:f ,.2f             Any Python format spec: 1,234.50
:f .1%              15.7%
:f .2e              1.23e+04
```

`:gf <fmt>` sets the workbook-wide default format. `:width <n>` sets
column width (4-40). Labels longer than the column width spill into
adjacent empty cells, Excel-style.

## Import / export

| Command | Reads | Writes | Notes |
|---|---|---|---|
| `:csv save/load` | CSV | CSV | Plain text, fast |
| `:xlsx save/load` | `.xlsx` formulas + values | EXCEL-mode: formulas + cached values; other modes: values only | `:xlsx load` switches to `EXCEL` |
| `:pd save/load` | CSV/TSV/Excel/JSON/Parquet | same | Uses pandas; row 1 as headers |

`:xlsx load` translates Excel formulas into gridcalc's `EXCEL` grammar
and reads every sheet. `INDIRECT` and 3D ranges (`Sheet1:Sheet3!A1:B2`)
are deliberately unsupported -- they'd defeat the static dep graph.
Functions outside the auto-loaded library produce `#NAME?`.

## File format

JSON, v2. v1 (single sheet, top-level `cells`) still loads.

```json
{
  "version": 2,
  "mode": "HYBRID",
  "active": "Inputs",
  "code": "def margin(rev, cost):\n    return (rev - cost) / rev * 100\n",
  "names":  { "revenue": "A1:A12", "costs": "B1:B12" },
  "models": { "default": { "sense": "max", "objective": "B4",
                           "vars": "A4:A5", "constraints": "D4:D6" } },
  "sheets": [
    { "name": "Inputs", "cells": [["Rev","Cost"],[1000,600],[1200,700]] },
    { "name": "Summary","cells": [["Total","=SUM(Inputs!A2:A3)"]] }
  ],
  "format": { "width": 10 }
}
```

- **mode**: `"EXCEL"` | `"HYBRID"` | `"PYTHON"`. Absent → `PYTHON`.
- **sheets** (v2): each is `{name, cells}` with a 2D `cells` array.
- **active** (v2): name of the sheet to focus on load.
- **names**: workbook-global named ranges (sheet-relative when used).
- **models**: persisted LP/MIP definitions (see [Optimization](#optimization)).
- **code**: per-workbook Python module string, editable via `:e`.

## Configuration

Optional `gridcalc.toml` (lookup: `$PWD` then `$XDG_CONFIG_HOME/gridcalc/`):

```toml
sandbox = true             # AST validation of formulas + code blocks
width   = 12               # default column width
format  = "G"              # default cell format

[keys.grid]
next_sheet  = ["Tab", "F4"]
prev_sheet  = ["S-Tab", "F3"]
cursor_left = ["Left", "h"]
cursor_down = ["Down", "j"]
cursor_up   = ["Up", "k"]
cursor_right= ["Right", "l"]
```

Every TUI context (`grid`, `entry`, `visual`, `cmdline`, `search`) is
rebindable. User bindings fire **before** the hardcoded fallback chain,
so `Tab → next_sheet` replaces the default cursor-right meaning. See
[`docs/keybindings.md`](docs/keybindings.md) for the keyspec grammar
(`Tab`, `S-Tab`, `C-x`, `C-Right`, `F3`, ...) and rejected combinations.

## Command reference

```text
File          :w [file]   :wq   :q   :q!   :o file   :e
Edit          :b   :clear   :dr   :dc   :ir   :ic   :m   :r
              :sort [col] [desc]   yank/paste: y/p   undo/redo: u / Ctrl-R
Format        :f <spec>   :gf <spec>   :width <n>   Ctrl-B / Ctrl-U
Search        /pattern   n   N
Sheets        :sheet [name|N|add|del|rename|move]
Names         :name <n> [range]   :names   :unname <n>
Modes         :mode [excel|hybrid|python]
Import/export :csv save/load   :xlsx save/load   :pd save/load
Optimization  :opt   :opt def   :opt run   :opt list   :opt undef
              :goal <cell> = <target> by <cell> [in <lo>:<hi>]
View          :view   E   :tv/:th/:tb/:tn (lock title rows/cols)
```

## Limitations

- **`INDIRECT`** is unsupported (would defeat the static dep graph).
- **xlsx export of formulas is EXCEL-mode only** -- PYTHON/HYBRID
  syntax (`**`, list comprehensions, `py.*`) isn't strict Excel.
- **3D range refs** (`Sheet1:Sheet3!A1:B2`) are unsupported (returns
  `nan`). Workaround: expand manually with `+`.
- **Cross-sheet ranges** (`Sheet1!A1:Sheet2!B5`) are rejected at parse
  time -- Excel doesn't support them either.
- **xlsx dates and styles** aren't read or written; date serials
  arrive as floats.

## Development

```sh
make build      # rebuild the C++ extensions (_core, _opt)
make test       # unit tests
make test-tty   # PTY-driven curses integration tests (slow, requires xterm-256color)
make lint       # ruff check
make typecheck  # mypy
make qa         # lint + typecheck + test + format

make wheel       # cpXX-cpXX wheel for current Python
make wheel-abi3  # single cp312-abi3 wheel (Python>=3.12)
make sdist       # source distribution
make publish     # upload to PyPI (after make check)
```

The abi3 build is gated on `GRIDCALC_STABLE_ABI=ON` (CMake) +
`wheel.py-api=cp312` (scikit-build-core). Per-version wheels and the
abi3 wheel have separate CI workflows under `.github/workflows/`.

## License

MIT
