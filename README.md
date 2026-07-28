# gridcalc

[![PyPI](https://img.shields.io/pypi/v/gridcalc)](https://pypi.org/project/gridcalc/)
[![Python](https://img.shields.io/pypi/pyversions/gridcalc)](https://pypi.org/project/gridcalc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A programmable terminal spreadsheet for developers and technical users, with Excel-ish formulas, Python escape hatches, XLSX interop, goal seek, and LP/MIP solving.

Inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

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
- **Linear, mixed-integer & quadratic programming** built in via HiGHS --
  `:opt max B4 vars A4:A5 st D4:D6` solves from cells in the sheet, with
  shadow prices, infeasibility diagnosis, and RHS sweeps. Models persist
  in the workbook.
- **Goal-seek** -- `:goal B10 = 100 by A1` adjusts a variable so a
  formula hits a target value.
- **Vim-style command line** (`:w`, `:e`, `:q`, `/search`, `y/p`, visual
  selection, undo), with **system-clipboard copy/paste** -- yank pushes
  values as TSV, paste pulls TSV in from other apps.

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

The **core** install has **zero third-party runtime dependencies on
Linux and macOS** -- the full 300+ Excel function library (statistical
distributions, financial functions, `LINEST`/`TREND` regression, ...)
works on stdlib alone. (The 3.10 wheel pulls `tomli` for config-file
parsing; 3.11+ uses stdlib `tomllib`. On Windows only, `windows-curses`
is pulled in because curses is not in the Windows stdlib.)

The `[extras]` bundle enables, all at once:

- `np.array(...)` in formulas; LAPACK-backed solvers; faster `LINEST`.
- `pd.DataFrame(...)`, `:pd load/save`, DataFrame cell display.
- Pygments syntax-highlight in the load-time trust prompt.

### Experimental GUI (preview)

A frontend spike lives behind an optional extra (it is not the product;
see [`docs/gui.md`](docs/gui.md) for the direction). It reuses the headless
engine and formats cells exactly as the terminal does.

- **Web** (`gridcalc[web]`, the current direction) -- an editable grid in a
  desktop [pywebview](https://pywebview.flowrl.com/) window. The engine runs
  in-process on CPython; the browser view bridges to it directly (no server).

  ```sh
  pip install 'gridcalc[web]'
  gridcalc-web                    # demo workbook, or: gridcalc-web book.json
  ```

  It covers cell editing (in-cell or from the formula bar), navigation and
  selection, copy/cut/paste, fill, undo/redo, and per-cell and workbook number
  formats. A status bar reports the selection's aggregates and an
  unsaved-changes marker. Structural edits (insert/delete row and column),
  search, and named ranges are terminal-only for now.

  Optimization is where it goes beyond the terminal. `Optimize` reads a model
  off a selected block or loads one saved in the workbook (the same models
  `:opt run` executes), solves it, and then **paints the result onto the
  sheet** -- objective, decision cells, and each constraint marked binding or
  slack, with shadow prices and ranging in the hover text. `Goal Seek` and a
  parametric `Sweep` (plotting the objective against a constraint's
  right-hand side, breakpoints marked) round it out.

The extra pulls a native webview stack, kept out of the lean terminal build on
purpose; the curses app has no such dependency.

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
=LET(x, SUM(A1:A9), x/COUNT(A1:A9))   local bindings -- compute once, reuse
=FILTER(A1:A9, B1:B9 > 0)             dynamic arrays: FILTER/SORT/UNIQUE
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
`COUNTIF`, `AVERAGEIF`, `LET`, `VLOOKUP`, `HLOOKUP`, `XLOOKUP`, `XMATCH`,
`INDEX`, `MATCH`, `FILTER`, `SORT`, `UNIQUE`, `SEQUENCE`, `CONCATENATE`,
`LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `SUBSTITUTE`,
and 280+ others. Dynamic-array functions return whole rows/columns and
compose (`=INDEX(SORT(A1:B9), 1, 2)`).

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
:sheets                    Interactive picker: list sheets, select one to switch
:sheet                     List sheets inline (active marked *)
:sheet Inputs              Switch by name
:sheet 1                   Switch by zero-based index
:sheet add Outputs         Append (does not switch)
:sheet del Tmp             Remove (refused if last sheet)
:sheet rename Old New      Rename, rewriting `Old!` prefixes in formulas
:sheet move Inputs 0       Reorder
```

A workbook with more than one sheet shows a tab strip on the bottom line
(active tab highlighted, with an `i/n` position counter); single-sheet
workbooks leave that line clear. The status bar also prefixes the active
sheet name (`Inputs!A1`) whenever a workbook has multiple sheets.

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
active sheet, via a vendored copy of [HiGHS](https://highs.dev/) (MIT).
Models are **workbook-persistent**: define once, save the file, re-run
on reopen.

```text
:opt                                                                       Run the saved 'default' model
:opt max|min            (with a visual selection)                          Infer the model from the selected block
:opt max|min <cell> vars <cells> st <cells> [bounds <spec>] [int <cells>] [bin <cells>]
                                                                           Solve inline AND save as 'default'
:opt def <name> max|min <cell> ...                                         Save under <name>; does not execute
:opt run [<name>]                                                          Execute a saved model
:opt sens [<name>] [into[!] <cell>]                                        Sensitivity report -- paged, or written into cells
:opt sweep <cell> <lo>:<hi> [steps] [<name>]                               Re-solve across a range of RHS values
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

### Quadratic objectives

Objectives may contain squared decision variables and cross terms --
`=(A1-3)*(A1-3)`, `=A1^2 + A2^2`, `=A1*A2`, `=2*A1^2 + 3*A1` -- which
covers least-squares fitting, quadratic cost curves, target tracking,
and covariance-style objectives.

```text
:opt min C1 vars A1:A2 st D1
opt: OPTIMAL  obj=0  (quadratic)
```

Solved exactly as a QP; there is no approximation and no accuracy knob.

The objective must be **convex for a minimisation** (or concave for a
maximisation). Otherwise the optimum sits at a corner of the feasible
region, which is a different and much harder problem, and gridcalc
refuses it rather than returning a plausible wrong answer:

```text
opt: objective is not convex, so it has no interior minimum -- ...
```

Convexity is checked directly on the Hessian (symmetric elimination, no
numpy required), so the message names the real problem rather than
surfacing a solver failure.

Sensitivity analysis and infeasibility diagnosis are **withheld for
quadratic models**: their duals do not carry the shadow-price reading
the report describes. Same call as for MIPs. Integer variables cannot be
combined with a quadratic objective.

### Inferring the model from a selection

The layout above already says what the model is. Select the block with
`v`, then type `:opt max` (or `min`) and the components are read off it:

| Cell contents | Read as |
|---|---|
| formula rooted in a comparison (`=A4<=4`) | a constraint |
| any other formula (`=3*A4+5*A5`) | the objective |
| a plain number | a decision variable |
| labels, blanks | ignored |

For the sheet above, selecting `A3:D6` and typing `:opt max` is
equivalent to `:opt max B4 vars A4:A5 st D4:D6`.

Exactly one non-comparison formula must be in the selection; more than
one is ambiguous and reports the candidates so you can narrow it.
Blanks are deliberately **not** treated as decision variables -- a
selected rectangle is mostly whitespace, and promoting every gap to a
variable would build a model you never described.

The inferred model is saved as `default`, so the block only has to be
selected once: plain `:opt` re-runs it afterwards, and `:w` persists it.

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

### Sensitivity analysis

`:opt sens [<name>]` solves the model and then opens a report answering
the question a bare optimum does not: *what would change the answer?*

```text
Variable cells
   cell      value   reduced  obj coef coef from coef till
   A4            2         0         3         0       7.5
   A5            6         0         5         2       inf

Constraints   (* = binding)
   cell     shadow       rhs  activity     slack  rhs from  rhs till
   D4            0         4         2         2      -inf       inf
 * D5          1.5        12        12         0         6        18
 * D6            1        18        18         0        12        24
```

- **shadow price** -- objective gain per extra unit of right-hand side.
  `D5` is worth 1.5 per unit and `D6` is worth 1, so buying more of the
  `D5` resource pays better. `D4` has slack and is worth nothing.
- **rhs from/till** -- the range over which that shadow price holds.
  Past it the optimal basis changes and the price no longer applies.
- **reduced cost** -- for a variable stuck at a bound, how much the
  objective would move per unit if it were forced in. Zero for any
  variable already active.
- **coef from/till** -- how far an objective coefficient can move before
  the optimal mix changes.
- **`*`** -- the constraint is binding (zero slack). Derived from slack
  rather than from a non-zero shadow price, since a degenerate optimum
  can bind at a price of zero.

Sensitivity is **not reported for integer or binary models**: a
branch-and-bound dual describes one LP relaxation rather than the
integer problem, so there is no valid shadow-price reading. `:opt sens`
on such a model still solves it and says why the report is absent.

#### Writing the report into cells

`:opt sens into <cell>` writes the report into the sheet instead of
paging it, anchored at the given cell:

```text
:opt sens into F1
```

The numbers land as **values, not text**, so downstream formulas can
reference them:

```text
F13:  =G7*100        -> 150     (G7 holds a shadow price of 1.5)
```

That is the reason to write into cells rather than read a report: the
results become part of the sheet's own computation. Re-running the
command refreshes the block in place.

Layout, anchored at the target cell -- a blank row separates the two
tables, and positions are stable so formulas keep working across
re-runs:

```text
Variables    value  reduced  obj coef  coef from  coef till
<one row per decision variable>

Constraints  shadow  rhs  activity  slack  rhs from  rhs till
<one row per constraint>
```

The write **refuses to overwrite non-empty cells** and names the first
one blocking it; use `into!` to overwrite anyway. The whole rectangle
belongs to the report, including the separator row, so stray values
cannot end up sitting inside it. The write is a single undo step.

Unbounded ranging values are written as infinities and display as
`inf` / `-inf`.

### Parametric sweep

A shadow price answers *what is the next unit worth*. It cannot answer
*how much more should I buy*, because it stops being valid at the edge
of its `rhs from/till` range. `:opt sweep` re-solves across a range and
shows where the value changes:

```text
:opt sweep D5 6:24 9
```

```text
D5 right-hand side from 6 to 24   (* = marginal value changed)
            rhs objective     delta    shadow  status
              6        27        --       2.5
   *          8        30         3       1.5
             12        36         3       1.5
             18        45         3       1.5
   *         20        45         0         0
             24        45         0         0
```

Read that as: capacity is worth 1.5 per unit up to 18, and nothing at
all beyond it. Buy up to 18.

`steps` is the number of intervals (default 10), so the report has
`steps + 1` rows spanning the range inclusive. The optional trailing
name selects a saved model other than `default`.

The sweep is **read-only** -- each point substitutes the right-hand
side internally rather than editing the constraint formula, so the
sheet is untouched and there is nothing to undo. Points where the model
becomes infeasible or unbounded are kept in the series with their
status, since learning that a level is unattainable answers the
question too.

Available programmatically as `opt.sweep(...)`, and the underlying
substitution as `solve(rhs_override={cell: value})` for one-off what-if
questions.

### Infeasibility diagnosis

An infeasible model reports *which* constraints contradict each other,
not just that the model failed:

```text
opt: INFEASIBLE  conflict: D1, D2 (2 of 5 constraints)
```

The named cells are an **irreducible** conflicting set: together they
are still infeasible, and dropping any one of them makes the model
solvable again. Constraints that merely happen to be present are not
listed, which is the whole point -- narrowing 30 constraints to the 2
that actually fight is the difference between a dead end and a fix.

Found by a deletion filter (one solve per constraint, on the failure
path only), so a three-way conflict with no contradictory pair is
reported correctly where a pairwise check would miss it. Variable
bounds are held fixed rather than dropped, so a constraint that
contradicts its variable's bounds is reported as the conflict.

This runs automatically on every infeasible `:opt`; there is no
separate command.

### Unboundedness diagnosis

The mirror case. An unbounded model names the variable that can run
away, rather than only reporting that no optimum exists:

```text
opt: UNBOUNDED  unbounded: A5 -- add an upper bound or a constraint
```

A variable is reported when the constraints permit it to move without
limit in the direction that improves the objective -- established by
re-solving over the same feasible region with that variable as the
objective, so it is an exact answer rather than a large-number
heuristic. Variables with no objective coefficient are never blamed:
moving them cannot change the objective, so they are not the cause even
when they are themselves unbounded.

Like the infeasibility case, this runs automatically.

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
              :sort [col] [desc]   yank/paste: y/p (syncs system clipboard)
              undo/redo: u / Ctrl-R   (aliases: Ctrl-Z / Ctrl-Y)
Format        :f <spec>   :gf <spec>   :width <n>   Ctrl-B / Ctrl-U
Search        /pattern   n   N
Sheets        :sheets (picker)   :sheet [name|N|add|del|rename|move]
Names         :name <n> [range]   :names   :unname <n>
Modes         :mode [excel|hybrid|python]
Import/export :csv save/load   :xlsx save/load   :pd save/load
Optimization  :opt   :opt def   :opt run   :opt sens   :opt sweep
              :opt list   :opt undef
              :goal <cell> = <target> by <cell> [in <lo>:<hi>]
View          :view   E   :tv/:th/:tb/:tn (lock title rows/cols)
```

## Limitations

- **`INDIRECT`** is unsupported (would defeat the static dep graph).
- **`LAMBDA`** and its higher-order helpers (`MAP`, `REDUCE`, `BYROW`,
  ...) are unsupported; `LET` is supported. Dynamic-array results are
  packed into their origin cell rather than spilling into neighbours.
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

## Prior Art

- [sc-im](https://github.com/andmarti1424/sc-im): A ncurses spreadsheet program for terminal
- [sheets](https://github.com/maaslalani/sheets): A terminal based spreadsheet tool
- [rustxl](https://rustxl.com): A fast, keyboard-driven spreadsheet with vim-style navigation and Excel-compatible formulas.


## License

MIT
