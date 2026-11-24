# Cross-tab models

A model is Python text, stored with a sheet, that reads named ranges as data, solves, and writes the solution back. Ranges are laid out as cross-tabs, as in [SolverStudio](https://solverstudio.org). The model language is a subset of [PuLP](https://coin-or.github.io/pulp/), solved by the builtin HiGHS solver.

For a model built from cell formulas instead, see [Optimization](optimization.md).

## Data items

A data item is a defined name a model can read. `:item` makes one. With a range selected, `:item NAME` also defines the name if it does not exist.

| Kind | Command | Range | Python value |
|-|-|-|-|
| Set | `:item Bars` | one row or column | `[1, 2, 3, 4, 5]` |
| Singleton | `:item Result` | one cell | the value |
| Indexed list | `:item demand Bars` | one row or column, as long as `Bars` | `{1: 500, 2: 900, ...}` |
| Indexed table | `:item costs Warehouses Bars` | rows as `Warehouses`, columns as `Bars` | `{("A", 1): 2, ...}` |

Rules:

- An index is a set: unique, non-blank values.
- A blank value cell is left out of the dict. Reading its key raises `KeyError`, unless `missing=VALUE` gives a default.
- A whole-number index value is an `int` key.
- A name must be a Python identifier.

`:items` lists the items and every problem with them. `:unitem NAME` removes an item; the defined name stays.

## The model

`:model` opens the active sheet's model in `$EDITOR`. Each data item is a global variable. A model writes results by assigning keys of an indexed item, or by assigning a singleton:

```python
from pulp import *

prob = LpProblem("Beer Distribution Problem", LpMinimize)
Routes = [(w, b) for w in Warehouses for b in Bars]
vars = LpVariable.dicts("Route", (Warehouses, Bars), 0, None, LpInteger)
prob += lpSum([vars[w][b] * costs[w, b] for (w, b) in Routes])
for w in Warehouses:
    prob += lpSum([vars[w][b] for b in Bars]) <= supply[w]
for b in Bars:
    prob += lpSum([vars[w][b] for w in Warehouses]) >= demand[b]
prob.solve()
for (w, b) in Routes:
    flow[w, b] = vars[w][b].varValue
Result = LpStatus[prob.status]
```

`:solve` starts it in the background. The status line shows `SOLVING Ns`, and the sheet stays editable. `:cancel` stops it. When it ends, results are written as one undo step. A failed model writes nothing and reports the line and any `print` output. Writing a key outside the index, or into a formula cell, is refused. If a data item changed while the model ran, nothing is written: the solution answers the old data.

`:showmodel` colours data item cells red, as SolverStudio outlines them, and the status line names the item under the cursor. Run it again to turn it off.

## In the desktop app

**Data > Model Editor** opens a panel beside the grid. The editor is CodeMirror with Python highlighting. Text is saved to the workbook after a short pause; each save is one undo step. **Solve** runs in the background; **Cancel** stops it. Problems and the model's output show under the editor, and a failed run puts the cursor on the failing line.

**Data > Show Model** outlines each data item and labels it, such as `costs[Warehouses,Bars]`. A dashed outline marks an item with a problem; hover for the reason.

The PuLP subset: `LpProblem`, `LpVariable` (with `.dicts`), `lpSum`, `value`, `LpStatus`, and the sense, category and status constants. Anything else raises `PulpError` naming it. It follows PuLP 2 and 3; PuLP 4 is a different API. A model may import `pulp`, `math`, and the modules the [sandbox](../security-plan.md) marks safe.

After an optimal LP solve, `constraint.pi` is the shadow price, d(objective)/d(right-hand side), and `variable.dj` the reduced cost, d(objective)/d(variable). Both are in the objective's own direction, as PuLP reports them with its default solver, CBC. A MIP has neither.

`print` output appears while the model runs: on the terminal's status line, and in the desktop panel. It is capped at 1 MB.

**Data > Data Items...** lists every data item with its range, indexes and problems. Clicking a range goes to it, switching sheet if needed. The form below makes the selection a data item; only sets are offered as indexes.

## Solvers

By default a model runs on the builtin PuLP subset, solved by HiGHS. With the [`[pulp]` extra](../install.md#the-pulp-extra) it can run under the PuLP library itself, with its solvers: `:model backend pulp` in the terminal, or the selector in the desktop panel. The setting is saved per sheet.

The model text stays the same. It may now use the rest of PuLP, such as `prob.solve(PULP_CBC_CMD(msg=0))` or `COIN_CMD`, `GLPK_CMD` and `HiGHS`. Solvers that need a network licence server do not work, since the model process has no network.

## Safety

A model is code. A file containing a model raises the trust prompt, xlsx included; a model in a file opened untrusted does not run. Saving checks every model and data item, and lists the problems; it does not run the model.

The model runs in a separate process with these limits:

| Limit | macOS | Linux | Windows |
|-|-|-|-|
| Wall clock, 120 s | yes | yes | yes |
| CPU time | yes | yes | no |
| Memory, 2 GB | parent watches it | address-space limit, and parent watches it | no |
| No file writes, processes, sockets or native calls (audit hook) | yes | yes | yes |
| Same, enforced by the OS (`sandbox-exec`) | yes | no | no |

The audit hook stops routes the static checks miss, but it is not an OS boundary: CPython documents audit hooks as unsuitable for sandboxing. On Linux and Windows nothing below it stops native code that gets loaded.

The pulp backend relaxes two rules, because PuLP writes its model to a file and starts a solver program. Writes are allowed only in a private temporary directory, deleted after the run. Programs may be started only from PuLP's bundled solvers, or `cbc`, `glpsol`, `highs`, `scip`, `cplex` and `gurobi_cl` on `PATH`. Network stays denied. The memory cap and a cancel cover the solver too.

## Files

JSON and xlsx keep models and data items. An xlsx stores them in a custom XML part, which Excel keeps when it saves the file (checked with Excel 16.114 for Mac). CSV keeps neither, and saving as CSV warns.
