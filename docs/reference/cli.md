# Headless CLI

`gridcalc book.json` opens the editor. If `book.json` does not exist, the editor starts an empty workbook and `:w` creates the file. Add any operation flag and the same command line becomes a batch run that never opens a window, prints its result to stdout, and exits — so a solve can be driven by cron, a Makefile, a CI job, or another program.

```sh
gridcalc plan.json --solve                       # run the saved 'default' model
gridcalc plan.json --solve 'max B4 vars A4:A5 st D4:D6'
gridcalc plan.json --solve with_caps --sens      # a named model, with duals
gridcalc plan.json --sweep 'D5 6:24 9'           # parametric right-hand side
gridcalc book.json --goal 'B10 = 100 by A1'      # goal seek
gridcalc book.json --eval '=SUM(A1:A10)'         # evaluate a formula
gridcalc book.xlsx --convert book.json           # format conversion
gridcalc loan.xlsx --set Rate=0.04 --get Payment # inputs and outputs by defined name
```

The spec strings are the ones the terminal uses. `--solve 'max B4 vars A4:A5 st D4:D6'` is the argument of `:opt`, and `--goal 'B10 = 100 by A1'` the argument of `:goal`; both are parsed by the same module the interactive commands use, so a spec that works in one works in the other. See [Optimization](../guide/optimization.md) and [Goal seek](../guide/goal-seek.md) for what the grammar means.

## Operations

| Flag | Does |
|---|---|
| `--solve [MODEL\|SPEC]` | Run a model. Bare, it runs the workbook's saved `default`; a name runs that saved model; anything starting with `max`/`min` is an inline spec. |
| `--sens` | With `--solve`, add shadow prices, reduced costs and ranging. Ignored for MIPs, whose duals describe one relaxation rather than the integer problem. |
| `--diagnose` | With `--solve`, explain a failure: the conflicting constraint set on `INFEASIBLE`, the runaway variables on `UNBOUNDED`. |
| `--goal SPEC` | Goal seek: `<cell> = <target> by <cell> [in <lo>:<hi>]`. |
| `--sweep SPEC` | Re-solve across a range of right-hand sides: `<cell> <lo>:<hi> [steps] [model]`. Never writes to the sheet. |
| `--set NAME=VALUE` | Write a value to a defined name or a cell before anything else runs. Repeatable. See [Named inputs and outputs](#named-inputs-and-outputs). |
| `--inputs FILE` | A JSON object of inputs, or a list of objects to run one after another. `-` reads stdin. |
| `--get NAME` | Report a defined name or a cell. Repeatable. Bare with `--set` or `--inputs`, every defined name is reported. |
| `--eval FORMULA` | Evaluate a formula against the workbook and report its value. Repeatable; never modifies the sheet. |
| `--convert PATH` | Write the workbook out. The format follows the extension — `.xlsx`, `.csv`, otherwise JSON. |
| `--apply` | Let `--solve` and `--goal` write their result into the grid. |
| `--sheet NAME` | Operate on a named sheet instead of the workbook's active one. |
| `--trust` | Run the workbook's Python: its code block, required modules and PYTHON-mode formulas. Without it none of these run, and stderr says so. |
| `--format json\|text` | Output shape. Defaults to `json`. |

Operations run in a fixed order — set, eval, solve, goal, sweep, get, convert — regardless of the order the flags appear in, so `--convert` always sees the state the others left and a command line means the same thing however it is written. One run can answer several questions; each lands under its own key.

## Named inputs and outputs

A workbook can be run as a function of its defined names, without opening it:

```sh
gridcalc loan.xlsx --set Rate=0.04 --set Years=15 --get Payment --get Schedule#
gridcalc loan.xlsx --inputs cases.json --get Payment     # one run per case
```

- **Targets** are defined names (case-insensitive), sheet-qualified local names (`Inputs!Rate`), or cells and ranges (`B2`, `Out!D1:D3`). `Name#` reads the whole array the formula at `Name` spills. A name defined as a formula (`=0.2`) can be read but not set.
- **Values** are JSON: `0.05`, `true`, `null` (a blank), `"12"` (text), or a list of rows for a range. A one-row or one-column range also takes a flat list (`[1,2,3]`). A `--set` value that is not valid JSON is text, so `--set Region=North` works without quoting. Text is never read as a formula.
- **Outputs**: a scalar for one cell, a list of rows for a range or a spill, and `{"error": "#DIV/0!"}` for a cell holding an error.
- **A list in `--inputs`** runs each case from the workbook as loaded: a case's inputs are put back before the next one. `--set` values apply to every case.
- **Writing back**: `--set` with `--convert out.xlsx` saves the workbook with the inputs in place.

```json
{
  "inputs": {"Rate": 0.04, "Years": 15},
  "outputs": {"Payment": -2219.06, "Schedule#": [[1.0], [2.0]]}
}
```

With a list in `--inputs`, the result is `{"runs": [{"inputs": {...}, "outputs": {...}}, ...]}`.

From Python, `gridcalc.book.Book` does the same:

```python
from gridcalc.book import Book

book = Book.open("loan.xlsx")
book.run({"Rate": 0.04}, ["Payment"])   # inputs are restored afterwards
book.set({"Rate": 0.04}); book.save("filled.xlsx")
```

An unknown name, a value of the wrong shape, or an input to a formula name exits 1 before anything is written.

## Nothing is written unless you ask

`--solve` and `--goal` report what they found and leave the workbook alone. `--apply` lets them write into the in-memory grid, and that only reaches disk if `--convert` is also given:

```sh
gridcalc plan.json --solve                                  # answer only
gridcalc plan.json --solve --apply --convert solved.json    # answer + a new file
```

There is deliberately no flag that overwrites the input file in place. A batch tool that rewrites the workbook you asked it a question about is one you cannot safely run twice.

`--eval` borrows a real cell out at the far corner of the sheet to evaluate in — which is what makes a relative reference mean what it would if typed into the grid — and restores it afterwards, so the workbook `--convert` writes is the one that was loaded.

## Exit codes

The result is in the exit code as well as the output, so a shell can branch on it without parsing anything:

| Code | Meaning |
|---|---|
| `0` | The operation ran and succeeded. |
| `2` | It ran and the answer was negative: `INFEASIBLE`, `UNBOUNDED`, `TIMEOUT`, or a goal seek that iterated without converging. There is output to read. |
| `1` | It never ran: a bad spec, a missing file, no such model, or a goal seek rejected before searching. The message is on stderr and **stdout is empty**. |

The distinction between `2` and `1` is the one that matters in automation:

```sh
if gridcalc plan.json --solve > result.json; then
    echo "feasible"
elif [ $? -eq 2 ]; then
    echo "no feasible plan -- alerting"     # a result
else
    echo "the job is broken"                # an error
fi
```

## Output schema

`--format json` is the contract; treat it as stable. `--format text` is for reading with your eyes and nothing should parse it.

The top-level object carries one key per operation that ran:

```json
{
  "solve": { ... },
  "goal": { ... },
  "sweep": { ... },
  "eval": [ ... ],
  "inputs": { ... },
  "outputs": { ... },
  "runs": [ ... ],
  "convert": { ... }
}
```

Two conventions hold everywhere. **Cells are A1 strings**, because a JSON object cannot key on a coordinate pair. **Every non-finite number is `null`** — JSON has no `Infinity` or `NaN`, so an unbounded objective and a missing ranging limit both come out as `null` rather than a token no conforming parser accepts.

### `solve`

```json
{
  "status": "OPTIMAL",
  "optimal": true,
  "objective": 36.0,
  "values": {"A4": 2.0, "A5": 6.0},
  "applied": false,
  "quadratic": false,
  "model": {"sense": "max", "objective": "B4", "vars": "A4:A5", "constraints": "D4:D6"}
}
```

`sensitivity` is present only with `--sens`, and `conflict` / `unbounded` only when `--diagnose` had something to report — a key's presence means it was computed, not merely requested.

```json
{
  "sensitivity": {
    "variables": [
      {"cell": "A4", "value": 2.0, "reduced_cost": 0.0,
       "obj_coef": 3.0, "obj_from": 0.0, "obj_till": 7.5}
    ],
    "constraints": [
      {"cell": "D6", "shadow_price": 1.0, "rhs": 18.0, "activity": 18.0,
       "slack": 0.0, "binding": true, "rhs_from": 12.0, "rhs_till": 24.0}
    ]
  },
  "conflict": ["D1", "D2"],
  "unbounded": ["A1"]
}
```

### `sweep`

`breakpoint` marks a point whose shadow price differs from the previous one — where the marginal value of the resource changed, which is the reason to sweep rather than read a single shadow price.

```json
{
  "constraint": "D5",
  "points": [
    {"rhs": 6.0, "status": "OPTIMAL", "objective": 27.0,
     "shadow_price": 2.5, "delta": null, "breakpoint": false}
  ],
  "breakpoints": [9.0, 21.0]
}
```

### `goal`

```json
{
  "converged": true, "iterations": 1,
  "formula_cell": "B1", "var_cell": "A1", "target": 11.0,
  "var_value": 4.0, "formula_value": 11.0, "residual": 0.0,
  "applied": false
}
```

### `eval` and `convert`

`eval` is a list in the order the flags were given. A cell that evaluated to an error reports it in `error` with `value` set to `null`.

```json
{
  "eval": [
    {"formula": "=SUM(A1:A10)", "text": "70600", "value": 70600.0, "error": null},
    {"formula": "=NOSUCHFUNC()", "text": "#NAME?", "value": null, "error": "#NAME?"}
  ],
  "convert": {"path": "out.xlsx", "format": "xlsx", "cells": 17}
}
```

## Notes

- Configuration still loads, so sandbox policy and enabled libraries are the same as they would be interactively — a batch answer has to match the one you would get on screen. Config warnings and load warnings, such as xlsx cells dropped past the grid, go to stderr, where they cannot corrupt the JSON a caller is parsing.

- A workbook carrying a `code` block loads formulas-only, exactly as an unanswered interactive open does. There is no prompt to answer in a batch run, and the safe default is the only one that can be taken without asking.

- Formula export to xlsx is EXCEL-mode only; see [Limitations](limitations.md).
