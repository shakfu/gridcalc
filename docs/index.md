# gridcalc

A programmable spreadsheet for developers and technical users, with Excel-ish formulas, Python escape hatches, XLSX interop, goal seek, and LP/MIP solving. It ships **two frontends over one engine**: a curses terminal app, and a desktop window that renders the same workbook in a webview.

Inspired by Serge Zaitsev's [kalk](https://github.com/zserge/kalk).

```sh
pip install gridcalc
gridcalc budget.json        # terminal
gridcalc-web budget.json    # desktop window  (needs the [web] extra)
```

## What it gives you

- **Excel-compatible formulas** (`=IF(A1>=B1, A1*0.05, 0)`) and arrays (`=SUM(A1:A10 * B1:B10)`) without leaving the terminal.

- **Multi-sheet workbooks** with cross-sheet refs (`=Sheet2!A1`) and a proper dep graph.

- **Three formula modes** per file: strict Excel, Excel-plus-`py.*`, or full Python `eval` with numpy/pandas.

- **xlsx interop** via OpenXLSX C++ -- read every sheet's formulas and values; export with cached values.

- **Linear, mixed-integer and quadratic programming** built in via HiGHS -- `:opt max B4 vars A4:A5 st D4:D6` solves from cells in the sheet, with shadow prices, infeasibility diagnosis, and RHS sweeps. Models persist in the workbook.

- **Goal seek** -- `:goal B10 = 100 by A1` adjusts a variable so a formula hits a target value.

- **Vim-style command line** (`:w`, `:e`, `:q`, `/search`, `y/p`, visual selection, undo), with **system-clipboard copy/paste** -- yank pushes values as TSV, paste pulls TSV in from other apps.

- **A desktop app as well as a terminal one** -- the same engine behind a mouse-driven grid with menus, a Ctrl-K command palette, and solver results painted onto the sheet. Most `:` commands are a [shared registry](https://github.com/shakfu/gridcalc/blob/main/src/gridcalc/commands.py) both frontends dispatch, so they behave identically in each.

## Where to start

| If you want to | Read |
|---|---|
| Get it installed | [Install](install.md) |
| See what using it feels like | [Quick tour](tour.md) |
| Use the mouse-driven desktop window | [Desktop app](desktop.md) |
| Write formulas | [Formulas](guide/formulas.md), [Formula modes](guide/modes.md) |
| Solve an LP, MIP, or QP from the sheet | [Optimization](guide/optimization.md) |
| Look up a `:` command | [Command reference](reference/commands.md) |
| Drive the engine from Python | [Python API](reference/api/index.md) |
| Know why it is built this way | [Design notes](topological.md) |

## Try the examples

The repository ships workbooks covering each mode and feature:

```sh
gridcalc example_excel.json          # sales report, named ranges, IF/MATCH
gridcalc example_hybrid.json         # progressive tax via py.* + aggregations
gridcalc example.json                # PYTHON: numpy/pandas, list comprehensions
gridcalc example_multisheet.json     # 3-sheet budget, cross-sheet formulas
gridcalc example_lp.json             # LP/MIP demo -- type :opt to solve
gridcalc example_goal.json           # goal-seek demo -- :goal B1 = 11 by A1
```

## Prior art

- [sc-im](https://github.com/andmarti1424/sc-im): an ncurses spreadsheet program for the terminal.

- [sheets](https://github.com/maaslalani/sheets): a terminal-based spreadsheet tool.

- [rustxl](https://rustxl.com): a fast, keyboard-driven spreadsheet with vim-style navigation and Excel-compatible formulas.

## License

MIT.
