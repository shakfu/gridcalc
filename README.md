# gridcalc

[![PyPI](https://img.shields.io/pypi/v/gridcalc)](https://pypi.org/project/gridcalc/) [![Python](https://img.shields.io/pypi/pyversions/gridcalc)](https://pypi.org/project/gridcalc/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A programmable spreadsheet for developers and technical users, with Excel-ish formulas, Python escape hatches, XLSX interop, goal seek, and LP/MIP solving. It ships **two frontends over one engine**: a curses terminal app, and a desktop window that renders the same workbook in a webview.

Inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

![The terminal app: a sales report with IF/MATCH formulas, named ranges, and two spilled array results](https://raw.githubusercontent.com/shakfu/gridcalc/main/docs/media/terminal-large.png)

*The terminal app over `example_excel.json`.*

![The desktop app: the Optimize dialog reporting an optimal solve with shadow prices and RHS ranging](https://raw.githubusercontent.com/shakfu/gridcalc/main/docs/media/webview.png)

*The desktop app solving `example_lp.json` -- the solution is written to the sheet behind the dialog.*

```sh
pip install gridcalc
gridcalc budget.json        # terminal
gridcalc-web budget.json    # desktop window  (needs the [web] extra)
```

**Documentation: <https://shakfu.github.io/gridcalc/>** -- install, tour, formula reference, optimization guide, file format, Python API, and the design notes.

---

## What it gives you

- **Excel-compatible formulas** (`=IF(A1>=B1, A1*0.05, 0)`) and arrays (`=SUM(A1:A10 * B1:B10)`) without leaving the terminal.

- **Multi-sheet workbooks** with cross-sheet refs (`=Sheet2!A1`) and a proper dep graph.

- **Three formula modes** per file: strict Excel, Excel-plus-`py.*`, or full Python `eval` with numpy/pandas.

- **xlsx interop** via OpenXLSX C++ -- read every sheet's formulas + values; export with cached values.

- **Linear, mixed-integer & quadratic programming** built in via HiGHS -- `:opt max B4 vars A4:A5 st D4:D6` solves from cells in the sheet, with shadow prices, infeasibility diagnosis, and RHS sweeps. Models persist in the workbook.

- **Goal-seek** -- `:goal B10 = 100 by A1` adjusts a variable so a formula hits a target value.

- **Vim-style command line** (`:w`, `:e`, `:q`, `/search`, `y/p`, visual selection, undo), with **system-clipboard copy/paste** -- yank pushes values as TSV, paste pulls TSV in from other apps.

- **A desktop app as well as a terminal one** -- the same engine behind a mouse-driven grid with menus, a Ctrl-K command palette, and solver results painted onto the sheet. Most `:` commands are a [shared registry](src/gridcalc/commands.py) both frontends dispatch, so they behave identically in each.

## Install

```sh
pip install gridcalc            # core: zero third-party runtime deps
pip install 'gridcalc[extras]'  # adds numpy, pandas, pygments
pip install 'gridcalc[web]'     # adds the desktop window (gridcalc-web)
```

Or with [uv](https://docs.astral.sh/uv/): `uv tool install 'gridcalc[extras]'`.

The **core** install has **zero third-party runtime dependencies on Linux and macOS** -- the full 300+ Excel function library (statistical distributions, financial functions, `LINEST`/`TREND` regression, ...) works on stdlib alone. Details in the [install guide](https://shakfu.github.io/gridcalc/install/).

## A taste

Cells hold a number, a label (any non-`=`-prefixed string), or a formula (prefixed with `=`):

```text
        A          B          C
1  Revenue   Cost       Margin
2  1000      600        =(A2-B2)/A2*100      <- formula
3  1200      700        =(A3-B3)/A3*100
4  Total     =SUM(B2:B3) =AVG(C2:C3)
```

Press `:` for the command line -- `:w` saves, `:o` opens, `:q` quits, `v` selects, `u` undoes, `/` searches. The [quick tour](https://shakfu.github.io/gridcalc/tour/) covers the rest, and the [command reference](https://shakfu.github.io/gridcalc/reference/commands/) lists every command.

Try the shipped examples:

```sh
gridcalc example_excel.json          # sales report, named ranges, IF/MATCH
gridcalc example_hybrid.json         # progressive tax via py.* + aggregations
gridcalc example.json                # PYTHON: numpy/pandas, list-comprehensions
gridcalc example_multisheet.json     # 3-sheet budget, cross-sheet formulas
gridcalc example_lp.json             # LP/MIP demo -- type :opt to solve
gridcalc example_goal.json           # goal-seek demo -- :goal B1 = 11 by A1
```

## Documentation

| Topic | |
|---|---|
| Install, extras, source builds | <https://shakfu.github.io/gridcalc/install/> |
| Quick tour | <https://shakfu.github.io/gridcalc/tour/> |
| Desktop app (web frontend) | <https://shakfu.github.io/gridcalc/desktop/> |
| Formulas, functions, named ranges | <https://shakfu.github.io/gridcalc/guide/formulas/> |
| Optimization (LP/MIP/QP, sensitivity, sweeps) | <https://shakfu.github.io/gridcalc/guide/optimization/> |
| File format | <https://shakfu.github.io/gridcalc/reference/file-format/> |
| Python API | <https://shakfu.github.io/gridcalc/reference/api/> |
| Design notes (recalc, security, web frontend) | <https://shakfu.github.io/gridcalc/topological/> |

The pages are built from [`docs/`](docs/) with MkDocs; `make docs-serve` previews them locally.

## Development

```sh
make build      # rebuild the C++ extensions (_core, _opt)
make test       # unit tests
make qa         # lint + typecheck + test + format (Python and TypeScript)
make web-build  # compile the desktop app's React client
make docs       # build the documentation site
make wheel      # cpXX-cpXX wheel for current Python
```

The full target list is in the [development guide](https://shakfu.github.io/gridcalc/development/), and `make help` prints it.

## Prior Art

- [sc-im](https://github.com/andmarti1424/sc-im): A ncurses spreadsheet program for terminal

- [sheets](https://github.com/maaslalani/sheets): A terminal based spreadsheet tool

- [rustxl](https://rustxl.com): A fast, keyboard-driven spreadsheet with vim-style navigation and Excel-compatible formulas.

## License

MIT
