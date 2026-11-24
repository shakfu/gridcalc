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

The indexes can also go in brackets, the form `:items` and the overlay show: `:item costs[Warehouses, Bars]` is `:item costs Warehouses Bars`. `output=true` and `output=false` work as well as the bare `output`.

`:items` lists the items and every problem with them. `:unitem NAME` removes an item; the defined name stays.

### Long-format tables

A cross-tab has at most two indexes. For more, or for sparse data, keep one row per key in a table:

| Warehouse | Bar | Month | cost |
|-|-|-|-|
| A | 1 | jan | 2 |

`:table Routes` makes the selection a table, its first row the column names. Then:

| Command | Python value |
|-|-|
| `:item cost table=Routes` | `{("A", 1, "jan"): 2, ...}`: keys are all columns but the last, the value the last |
| `:item cost table=Routes keys=Warehouse,Bar value=cost` | the keys and value named; other columns are ignored |
| `:item Warehouses table=Routes column=Warehouse` | `["A", "B"]`: the column's distinct values, in row order |
| `:item supply table=Supply` | `{"A": 3100, ...}`: one key column gives plain keys |

Quote a column name with spaces: `keys="From WH,To Bar"`. Names match without regard to case, as in Excel.

The rules match cross-tab items. A blank value is a missing key, and `missing=` gives it a default. A blank, error or duplicate key is a problem. Writes, and `output` binding, go to existing rows; a key with no row is refused, since the table does not grow. A table item cannot be the index of a cross-tab item. In the desktop app, choose **Table rows** as the source in Data Items.

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

### Output items

An output item is filled from the model's variables, with no copy loop. Mark it with `output`, as in `:item flow Warehouses Bars output`, or the Output box in the desktop dialog. The model then rebinds the item's name to its variables:

```python
flow = LpVariable.dicts("Route", (Warehouses, Bars), 0)   # nested, as dicts makes it
# or: flow = {(w, b): LpVariable(...) for w in Warehouses for b in Bars}
...
prob.solve()
Result = prob.objective                                     # a one-cell output item
```

After the run, each key of the item's index is written with its variable's value. A key the bound dict lacks, or a variable with no value because the solve failed, refuses the whole write. Assigning keys, as `flow[w, b] = ...`, still works on an output item. Rebinding an item that is not an output is an error, so a variable that happens to share a name never overwrites cells.

`:solve` starts it in the background. The status line shows `SOLVING Ns`, and the sheet stays editable. `:cancel` stops it. When it ends, results are written as one undo step. A failed model writes nothing and reports the line and any `print` output. Writing a key outside the index, or into a formula cell, is refused. If a data item changed while the model ran, nothing is written: the solution answers the old data.

`:showmodel` colours data item cells red, as SolverStudio outlines them, and the status line names the item under the cursor. Run it again to turn it off.

## In the desktop app

**Data > Model Editor** opens a panel beside the grid. The editor is CodeMirror with Python highlighting. Text is saved to the workbook after a short pause; each save is one undo step. **Solve** runs in the background; **Cancel** stops it. Problems and the model's output show under the editor, and a failed run puts the cursor on the failing line.

**Data > Show Model** outlines each data item and labels it, such as `costs[Warehouses,Bars]`. A dashed outline marks an item with a problem; hover for the reason.

The PuLP subset: `LpProblem`, `LpVariable` (with `.dicts`), `lpSum`, `value`, `LpStatus`, and the sense, category and status constants. Anything else raises `PulpError` naming it. It follows PuLP 2 and 3; PuLP 4 is a different API. A model may import `pulp`, `math`, and the modules the [sandbox](../security-plan.md) marks safe.

The builtin backend also takes a quadratic objective: `prob += lpSum((Y[p] - a * X[p] - b) ** 2 for p in P)` fits a least-squares line. This goes beyond PuLP, which refuses a product of variables, so such a model does not run under the pulp backend. HiGHS solves it when it is convex (concave when maximising), with linear constraints and no integer variables; anything else is refused with the reason. A QP solve reports no `pi` or `dj`.

After an optimal LP solve, `constraint.pi` is the shadow price, d(objective)/d(right-hand side), and `variable.dj` the reduced cost, d(objective)/d(variable). Both are in the objective's own direction, as PuLP reports them with its default solver, CBC. A MIP has neither.

`print` output appears while the model runs: on the terminal's status line, and in the desktop panel. It is capped at 1 MB.

**Data > Data Items...** lists every data item with its range, indexes and problems. Clicking a range goes to it, switching sheet if needed. The form below makes the selection a data item; only sets are offered as indexes.

## Solvers

By default a model runs on the builtin PuLP subset, solved by HiGHS. With the [`[pulp]` extra](../install.md#the-pulp-extra) it can run under the PuLP library itself, with its solvers: `:model backend pulp` in the terminal, or the selector in the desktop panel. The setting is saved per sheet.

The model text stays the same. It may now use the rest of PuLP, such as `prob.solve(PULP_CBC_CMD(msg=0))` or `COIN_CMD`, `GLPK_CMD` and `HiGHS`. Solvers that need a network licence server do not work, since the model process has no network.

### Pyomo

With the [`[pyomo]` extra](../install.md#the-pyomo-extra), `:model backend pyomo` (or **Pyomo** in the desktop selector) runs a model written with Pyomo. Data items are globals, as for PuLP:

```python
import pyomo.environ as pyo

m = pyo.ConcreteModel()
m.x = pyo.Var(Warehouses, Bars, within=pyo.NonNegativeIntegers)
m.cost = pyo.Objective(expr=sum(costs[w, b] * m.x[w, b] for w in Warehouses for b in Bars))
m.sup = pyo.Constraint(Warehouses, rule=lambda m, w: sum(m.x[w, b] for b in Bars) <= supply[w])
m.dem = pyo.Constraint(Bars, rule=lambda m, b: sum(m.x[w, b] for w in Warehouses) >= demand[b])
results = pyo.SolverFactory("glpk").solve(m)
flow = m.x            # with flow an output item; or assign flow[w, b] = pyo.value(...)
```

Imports are limited to the `pyomo` package and the usual safe modules. The status comes from the one `SolverResults` the model keeps (`results` above), and the objective from the model's one active objective. Pyomo starts solver programs under the same rules as the pulp backend.

### GMPL

`:model backend gmpl` (or **GMPL (glpsol)** in the desktop selector) makes the sheet's model GMPL text, run by `glpsol` from GLPK ([install](../install.md#gmpl-models)):

```gmpl
set Warehouses; set Bars;
param costs{Warehouses, Bars}; param supply{Warehouses}; param demand{Bars};
var flow{Warehouses, Bars} >= 0, integer;
minimize cost: sum{w in Warehouses, b in Bars} costs[w,b] * flow[w,b];
s.t. sup{w in Warehouses}: sum{b in Bars} flow[w,b] <= supply[w];
s.t. dem{b in Bars}: sum{w in Warehouses} flow[w,b] >= demand[b];
end;
```

- Data items the model declares as a `set` or `param` are written to its data section, matched by name. A cross-tab or table item becomes a param with one subscript per key; `missing=` becomes its `default`. Undeclared items are left out.
- Results fill output items by name: output item `flow` gets the variable `flow`, key by key; an output item named like the objective (`cost`) gets its value. GMPL has no assignment back to data, so this is the only way out.
- `printf` and `display` go to the model output.
- `table` statements and `printf ... > "file"` are refused: they write files, and `table` drivers can reach databases.

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

The pulp, pyomo and gmpl backends relax two rules, because they write the model to a file and start a solver program. Writes are allowed only in a private temporary directory, deleted after the run. Programs may be started only from PuLP's bundled solvers, or `cbc`, `glpsol`, `highs`, `scip`, `cplex`, `gurobi_cl`, and the nonlinear solvers `ipopt`, `bonmin` and `couenne`, on `PATH`. Network stays denied. The memory cap and a cancel cover the solver too. `glpsol` is a native program, so outside macOS only the static check stops a GMPL model writing files.

## From Python and the command line

No CLI flag runs a model yet. From Python, `gridcalc.modelrun.run_model(grid)` runs the active sheet's model and writes its results, and `gridcalc.dataitems.read_items(grid)` returns the data items as the model sees them.

## Files

JSON and xlsx keep models and data items. An xlsx stores them in a custom XML part, which Excel keeps when it saves the file (checked with Excel 16.114 for Mac). CSV keeps neither, and saving as CSV warns.
