# Cross-tab models

Status (2026-11-24): implemented in both frontends: data items, the PuLP subset, a background runner with cancel, a model editor (TUI `$EDITOR`, desktop CodeMirror), the "Show Model" overlay, and checks on save. Not built: xlsx storage, sparse `A`, automatic binding, solver tiers 1-4.

Goal: a SolverStudio-style model. Model text reads named cross-tab ranges, solves, and writes the solution back to the sheet. Builtin HiGHS first; other solvers through the same runner.

Prior art: [SolverStudio](https://solverstudio.org), [methods](https://solverstudio.org/solverstudio-methods/), [development notes](https://solverstudio.org/development/). The data-item rules below are read from its transportation example screenshots ([sheet](https://solverstudio.org/wp-content/uploads/2011/11/TransportationData.png), [dialog](https://solverstudio.org/wp-content/uploads/2011/11/TransportationScreenshotHighlighting.png)).

## Data items

A data item is a defined name plus two fields:

- `index`: zero, one or two other data item names.
- `missing`: raise (default) or a fixed value for an unknown key.

| Kind | Index | Python value |
|-|-|-|
| Set | none, 1-D range | `list` |
| Singleton | none, one cell | scalar |
| Indexed list | one | `dict[key, value]`; row or column orientation |
| Indexed table | two | `dict[(row_key, col_key), value]`; first index runs down, second across |

Values are evaluated cell values, so a parameter may be a formula. Blank value cells are left out of the dict, so `missing` covers them too. Whole-number index values become `int` keys. An item name must be a Python identifier; SolverStudio's escaping (`RHS1.up` -> `RHS1_up`) is not copied, since a refused name is clearer than a renamed one. Defined names already track row and column insertion, so data items need no range maintenance of their own.

JSON:

```json
"data_items": {
  "costs": {"index": ["Warehouses", "Bars"]},
  "flow":  {"index": ["Warehouses", "Bars"]},
  "demand": {"index": ["Bars"]}
}
```

`models` already holds `:opt` definitions, so model text will need another key.

xlsx storage (custom XML part) is deferred.

## Validation

Static checks run at save and again at solve. Save never executes model text; a save that ran it would let opening and saving a file run its code.

- Model text parses and passes `validate_code`.
- Every index names a data item that is a set.
- Value range shape matches index lengths.
- Index values are unique and non-blank.

Solve adds the run-time checks on write-back:

- A key not in the index is refused; a range cannot grow.
- A formula cell is refused, as in `:opt`.

## Write-back

Explicit, as in SolverStudio: the model assigns `flow[w, b] = x[w][b].varValue`. Writes are applied after the run as one `setcells_bulk` call and one undo step.

Automatic binding (a variable dict named `flow` fills item `flow`) is a possible later option. It changes only the runner side, since the child already returns writes as data.

## Model language

A PuLP-compatible subset: `LpProblem`, `LpVariable` (`.dicts`), `lpSum`, `+=`, `<=`/`>=`/`==`, `value`, `LpStatus`, `.varValue`, `LpInteger`, `LpBinary`. Unsupported PuLP features fail with a named error, not different behaviour.

PuLP over a custom API because existing SolverStudio and OR teaching models run as written, and tier 1 below runs the same text under real PuLP. Extending `:opt` with `SUMPRODUCT` and range constraints is worth doing separately, but it is cell-level Solver, not a model over data items.

Built: PuLP 2.x defaults (free variables, status codes, `varValue` `None` until optimal). Only optimal solves set values; a timed-out MIP's incumbent is dropped. Left out: solver selection, sensitivity (PuLP's `pi`/`dj` signs differ by solver, so matching them needs a reference run), `writeLP`/`writeMPS`, elastic constraints, quadratic terms.

`_opt.solve_lp` takes a dense `A` (`_opt.cpp:121`). 10k variables x 10k constraints is 800 MB. A sparse entry point is needed before large models.

## Runner

Every solve, builtin included, runs in a child process. Contract: data items as JSON in; writes, status, objective and log as JSON out.

Built:

- Model text lives on the sheet (`Sheet.model_text`, JSON `sheets[].model`), so rename and sheet undo carry it.
- Child: `python -I -m gridcalc._modelchild`. Builtins exclude the sandbox's blocked names. Imports: `pulp` (the subset), `math`, and the facades of `SAFE_MODULES`.
- Limits: `RLIMIT_AS` and `RLIMIT_CPU` in the child; the parent kills on wall clock (120 s) and polls RSS (2 GB), since macOS ignores `RLIMIT_AS`.
- Write-back: indexed items by key; a singleton by rebinding its name. Rebinding an indexed item or a set is an error, since its writes would be lost silently.
- A blocked builtin name the model binds itself (`vars` in PuLP's beer example) passes validation. The child has no such builtin, so a read before the binding is a NameError.

Out of process over in-process because:

- A hang or memory blowup kills the child, not the app with an unsaved sheet. `RLIMIT_AS` and a wall-clock `SIGKILL` cover both; a native HiGHS call cannot otherwise be interrupted.
- The model sees only the JSON it is sent, not the `Grid`.
- One runner serves every tier.

Cost: serialised tracebacks must map back to model-text line numbers; tests need a child-process fixture.

### Startup measurement

Apple M1, CPython 3.14.7, median of 15, after one warm-up run. Each child imports `gridcalc._opt` and solves a 2-variable LP unless noted.

| Method | Median |
|-|-|
| `subprocess`, `python -c pass` | 16.5 ms |
| `subprocess`, `python -I -S -c pass` | 11.2 ms |
| `subprocess`, import `_opt` + solve | 41.9 ms |
| `subprocess`, `import gridcalc.engine` | 60.2 ms |
| `multiprocessing` spawn | 52.4 ms |
| `multiprocessing` forkserver | 21.6 ms |

Decision: plain `subprocess`, no warm worker. 42 ms is under the 150 ms threshold set before measuring, and a warm worker adds state shared between solves. `forkserver` halves it if needed later; it is unavailable on Windows.

Measured again with the finished child (2026-11-24): 71 ms per run, 78 ms under `sandbox-exec`. The child imports `dataitems`, and through it `book` and `engine`; the table above imported `_opt` alone.

15 ms of the 22 ms `import gridcalc` is `importlib.metadata`, from `__version__` in `__init__.py`. Making it lazy would cut child startup by about a third.

## Other solvers

| Tier | Runner | Solvers |
|-|-|-|
| 0 | builtin subset | HiGHS via `_opt` |
| 1 | real `pulp`, same model text | CBC, HiGHS, Gurobi, CPLEX, SCIP |
| 2 | Pyomo, CVXPY, OR-Tools CP-SAT | as each supports |
| 3 | data-file writer + result reader | GMPL (`glpsol`), AMPL, GAMS, MiniZinc |
| 4 | NEOS via `xmlrpc.client` | remote; opt-in per solve, since data leaves the machine |

A cross-tab maps directly to GMPL's tabular parameter (`param costs: 1 2 3 4 5 := A 2 4 5 2 1 B 3 1 3 2 3;`).

Each language is a record: command, data writer, result reader. Plugins are never loaded from the workbook; a workbook that chose its plugin would choose code to run.

## First version

1. Data items: three kinds, JSON storage, static validation.
2. PuLP subset compiled to `solve_lp`.
3. Subprocess runner with rlimits and timeout.
4. `:model` / `:solve` in the TUI; a model pane in the web frontend.
5. Fixture: the PuLP beer distribution example. Solve, assert objective, save, reload, solve.

Later: "Show Model" range overlay, xlsx storage, sparse `A`, automatic binding, tier 1.

## Background runs

`ModelJob` splits a run into three steps: read the grid, run the child, write. Only the first and last touch the grid, so a frontend runs the middle step on a worker thread. The desktop `Api` holds its lock for the first and last only; the client polls `solve_status`, which hands the result out once.

The write re-reads every data item and compares it with what the child was sent. Any difference refuses the write. Comparing only the index values was the alternative; it would write a solution computed from costs that have since changed.

## Confinement

Layers, outermost first: the trust prompt; `validate_code` on the text; builtins without the blocked names; the import hook; an audit hook (`_modelchild._audit`); on macOS, `sandbox-exec` denying network, file writes and fork.

The audit hook allows `ctypes.dlopen` and `os.putenv` only while an allowed module imports, since numpy's import raises both. `print.__self__` reaches the real `builtins`, so trimmed builtins alone stop nothing; the tests use that route.

Linux has Landlock for unprivileged file confinement (kernel 5.13+). It is not used: it needs raw syscalls through ctypes, and could not be tested here.

## Duals

Reference run, PuLP 3.3.2, five LPs (max/min, `<=`/`>=`/`=`). CBC and HiGHS agree for a minimisation; for a maximisation PuLP's HiGHS interface negates `pi` and `dj`. CBC's sign is d(objective)/d(rhs) in the objective's direction, which does not depend on the solver, so the subset uses it. The `_opt` binding returns those signs unchanged. PuLP 4.3.1 is a Rust rewrite without `LpVariable.dicts`, so tier 1 must pin PuLP below 4.

## xlsx

One custom XML part, `customXml/itemN.xml`, root `{urn:gridcalc:models:1}gridcalc`, text a JSON document with `data_items` and per-sheet `models`. Excel 16.114 for Mac kept it through open and save.

## Tier 1: the PuLP library

Per-sheet `model_backend`, `builtin` or `pulp`; the text is unchanged. PuLP writes `<uuid>-pulp.mps` under `tempfile.gettempdir()`, starts `cbc` with `subprocess.Popen` and removes the file (audit trace, PuLP 3.3.2). So the pulp child gets three exceptions, each in the audit hook and, on macOS, in the `sandbox-exec` profile: writes and removals under a per-run `TMPDIR` the parent creates and deletes; `Popen` of a program under PuLP's `solverdir` or in `SOLVER_PROGRAMS` on `PATH`; `os.devnull`, which PuLP opens for `msg=0`. Profile paths are `-D` parameters, never profile text.

The child is a process-group leader, so the RSS cap sums the group and `_kill` signals it: CBC is a grandchild, and `proc.kill()` alone would orphan it.

PuLP 3.3 deprecates `PULP_CBC_CMD` in favour of `COIN_CMD` with `pulp[cbc]`; both are allowed.

Start-up after taking the engine, `importlib.metadata` and `traceback` out of the child: 39.6 ms per run under `sandbox-exec`, from 79 ms. The child imports `itemdict` for `ItemDict` instead of `dataitems`.

## GMPL

Vendored HiGHS 1.15.1 reads MPS and CPLEX LP only (`highs/io/Filereader.cpp`), so GMPL needs GLPK, which is GPL-3. Three routes were weighed:

- `glpsol` solves and gridcalc reads its `-o` report. Chosen: no C++ change, and GLPK stays a separate program.
- `glpsol --check --wlp` translates and HiGHS solves the LP file. Same HiGHS answers and dual signs as the builtin backend, but it still needs `glpsol`, plus an LP reader in `_opt` and a map from `flow(A,1)` names back to keys.
- `swiglpk` in the child. GPL code imported into gridcalc's process; murkier than starting a program.

The `-o` report puts a name over 12 characters on its own line, values on the next; an integer column has `*` before its activity; symbols with spaces are quoted. `gmpl.read_report` tells a name line from a value line by whether the fields past column 12 hold a bare number, which a name outside quotes cannot.

GMPL can write files (`table ... OUT`, `printf ... > "f"`) and its `table` drivers include ODBC and MySQL. `gmpl.problems` refuses both from a token scan before the run. glpsol is native, so the audit hook cannot see it: on macOS `sandbox-exec` confines it as it confines CBC; elsewhere the static check is the only layer.

## Pyomo

Pyomo 6.11 writes its `.lp` model and the solver's files under `tempfile.gettempdir()`, starts the solver with `subprocess.Popen` and removes the files (audit trace, 2026-11-24). It also reopens an `mkstemp` descriptor for writing, so the audit hook allows `open` on an integer: a descriptor grants no file it did not already have. Its import takes about 0.8 s, done before the hook. The import hook admits only the `pyomo` namespace, returning the top package for `import pyomo.environ as pyo` as `__import__` does.

## Quadratic objectives

Probed through `_opt` (2026-11-24): HiGHS solves a convex QP and a concave maximisation; a non-convex objective and a QP with integer columns both end in a bare `Highs_run failed`. The subset refuses MIQP before the solve and adds the convexity condition to the failure. `solve_lp_sparse` gained the dense ragged Hessian `solve_lp` already took. Quadratic variables are ordered first, so each lower-triangle row is no longer than the quadratic part, not the model.

Checked with Ipopt 3.14.20: Pyomo calls `os.putenv(b"PYOMO_AMPLFUNC", b"")` before starting it, and no other variable for ipopt or glpk. The hook allows `putenv`/`unsetenv` only for `AMPLFUNC`/`PYOMO_AMPLFUNC` with an empty value, and only for program backends. A non-empty value is a shared library the AMPL solver loads, the same risk as `LD_PRELOAD`, and the model can write files into its temp directory.

