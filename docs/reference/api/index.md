# Python API

gridcalc's engine is usable without either frontend. A `Grid` loads a workbook, recalculates it, and hands back cell values; the solver and goal-seek modules operate on that same `Grid`.

```python
from gridcalc.engine import Grid

g = Grid()
g.jsonload("examples/example_lp.json")
g.recalc()
print(g.value(1, 3))
```

These pages cover the modules that make up that public boundary:

| Module | What it holds |
|---|---|
| [engine](engine.md) | `Grid`, `Sheet`, `Cell`, `Vec`, `NamedRange` -- the workbook model, both recalculation engines, and JSON load/save |
| [formula](formula.md) | The Excel formula language: lexer, parser, AST, evaluator, dependency extraction, error values |
| [opt](opt.md) | Building an LP, MIP, or QP from sheet cells and solving it, with sensitivity, sweeps, and diagnosis |
| [goalseek](goalseek.md) | One-dimensional root finding over a `Grid`, with auto-bracketing |
| [config](config.md) | `gridcalc.toml` loading and the parsed `Config` |
| [sandbox](sandbox.md) | AST validation, module classification, and workbook inspection without execution |

Deliberately not documented here: `gridcalc.tui` (the curses layer), `gridcalc.web` (the webview bridge), and `gridcalc.libs.xlsx` (the ~310-entry function library). They are internal to their frontends or, in the library's case, better described by the [function coverage audit](../../function_coverage.md) than by a wall of one-line signatures.

The pages are generated from the source with [mkdocstrings](https://mkdocstrings.github.io/), so the docstrings here are the ones in the code.
