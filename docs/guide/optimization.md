# Optimization

`:opt` solves linear and mixed-integer programs defined by cells in the active sheet, via a vendored copy of [HiGHS](https://highs.dev/) (MIT). Models are **workbook-persistent**: define once, save the file, re-run on reopen.

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

The **model** is sheet-resident: an objective formula in one cell, decision-variable cells holding values, and constraint cells holding comparison formulas like `=A1+A2<=10`. The constraint cells keep evaluating during recalculation, so the sheet shows live feasibility (`TRUE`/`FALSE`) before and after the solve.

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

The status bar shows `opt: OPTIMAL  obj=36`; `A4` and `A5` become `2.0` and `6.0`; `u` rolls back.

## Quadratic objectives

Objectives may contain squared decision variables and cross terms -- `=(A1-3)*(A1-3)`, `=A1^2 + A2^2`, `=A1*A2`, `=2*A1^2 + 3*A1` -- which covers least-squares fitting, quadratic cost curves, target tracking, and covariance-style objectives.

```text
:opt min C1 vars A1:A2 st D1
opt: OPTIMAL  obj=0  (quadratic)
```

Solved exactly as a QP; there is no approximation and no accuracy knob.

The objective must be **convex for a minimisation** (or concave for a maximisation). Otherwise the optimum sits at a corner of the feasible region, which is a different and much harder problem, and gridcalc refuses it rather than returning a plausible wrong answer:

```text
opt: objective is not convex, so it has no interior minimum -- ...
```

Convexity is checked directly on the Hessian (symmetric elimination, no numpy required), so the message names the real problem rather than reporting a bare solver failure.

Sensitivity analysis and infeasibility diagnosis are **withheld for quadratic models**: their duals do not carry the shadow-price reading the report describes. Integer variables cannot be combined with a quadratic objective.

## Inferring the model from a selection

The layout above already says what the model is. Select the block with `v`, then type `:opt max` (or `min`) and the components are read off it:

| Cell contents | Read as |
|---|---|
| formula rooted in a comparison (`=A4<=4`) | a constraint |
| any other formula (`=3*A4+5*A5`) | the objective |
| a plain number | a decision variable |
| labels, blanks | ignored |

For the sheet above, selecting `A3:D6` and typing `:opt max` is equivalent to `:opt max B4 vars A4:A5 st D4:D6`.

Exactly one non-comparison formula must be in the selection; more than one is ambiguous and reports the candidates so you can narrow it. Blanks are deliberately **not** treated as decision variables -- a selected rectangle is mostly whitespace, and promoting every gap to a variable would build a model you never described.

The inferred model is saved as `default`, so the block only has to be selected once: plain `:opt` re-runs it afterwards, and `:w` persists it.

## Clauses

Any order after `st`:

- `bounds A1=lo:hi, B2=lo:hi` -- per-variable bounds. `lo` and `hi` accept `inf`, `+inf`, `-inf`. The default is `[0, +inf)`.

- `int <cells>` -- decision variables are integer-valued (branch and bound).

- `bin <cells>` -- decision variables are binary (`{0,1}`); bounds clamped to `[0,1]`.

Cell lists everywhere accept ranges (`A1:A5`), comma-separated refs (`A1,A3,B5`), or a mix.

Saved models live under `"models": {<name>: ...}` in the JSON file and round-trip verbatim -- the spec strings you typed are stored, not pre-resolved coordinates. See [File format](../reference/file-format.md).

## Sensitivity analysis

`:opt sens [<name>]` solves the model and then opens a report answering the question a bare optimum does not: *what would change the answer?*

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

- **shadow price** -- objective gain per extra unit of right-hand side. `D5` is worth 1.5 per unit and `D6` is worth 1, so buying more of the `D5` resource pays better. `D4` has slack and is worth nothing.

- **rhs from/till** -- the range over which that shadow price holds. Past it the optimal basis changes and the price no longer applies.

- **reduced cost** -- for a variable stuck at a bound, how much the objective would move per unit if it were forced in. Zero for any variable already active.

- **coef from/till** -- how far an objective coefficient can move before the optimal mix changes.

- **`*`** -- the constraint is binding (zero slack). Derived from slack rather than from a non-zero shadow price, since a degenerate optimum can bind at a price of zero.

Sensitivity is **not reported for integer or binary models**: a branch-and-bound dual describes one LP relaxation rather than the integer problem, so there is no valid shadow-price reading. `:opt sens` on such a model still solves it and says why the report is absent.

### Writing the report into cells

`:opt sens into <cell>` writes the report into the sheet instead of paging it, anchored at the given cell:

```text
:opt sens into F1
```

The numbers land as **values, not text**, so downstream formulas can reference them:

```text
F13:  =G7*100        -> 150     (G7 holds a shadow price of 1.5)
```

That is the reason to write into cells rather than read a report: the results become part of the sheet's own computation. Re-running the command refreshes the block in place.

The layout, anchored at the target cell -- a blank row separates the two tables, and positions are stable so formulas keep working across re-runs:

```text
Variables    value  reduced  obj coef  coef from  coef till
<one row per decision variable>

Constraints  shadow  rhs  activity  slack  rhs from  rhs till
<one row per constraint>
```

The write **refuses to overwrite non-empty cells** and names the first one blocking it; use `into!` to overwrite anyway. The whole rectangle belongs to the report, including the separator row, so stray values cannot end up sitting inside it. The write is a single undo step.

Unbounded ranging values are written as infinities and display as `inf` / `-inf`.

## Parametric sweep

A shadow price answers *what is the next unit worth*. It cannot answer *how much more should I buy*, because it stops being valid at the edge of its `rhs from/till` range. `:opt sweep` re-solves across a range and shows where the value changes:

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

Read that as: capacity is worth 1.5 per unit up to 18, and nothing at all beyond it. Buy up to 18.

`steps` is the number of intervals (default 10), so the report has `steps + 1` rows spanning the range inclusive. The optional trailing name selects a saved model other than `default`.

The sweep is **read-only** -- each point substitutes the right-hand side internally rather than editing the constraint formula, so the sheet is untouched and there is nothing to undo. Points where the model becomes infeasible or unbounded are kept in the series with their status, since learning that a level is unattainable answers the question too.

Available programmatically as [`opt.sweep(...)`](../reference/api/opt.md), and the underlying substitution as `solve(rhs_override={cell: value})` for one-off what-if questions.

## Infeasibility diagnosis

An infeasible model reports *which* constraints contradict each other, not just that the model failed:

```text
opt: INFEASIBLE  conflict: D1, D2 (2 of 5 constraints)
```

The named cells are an **irreducible** conflicting set: together they are still infeasible, and dropping any one of them makes the model solvable again. Constraints that merely happen to be present are not listed, which is the whole point -- narrowing 30 constraints to the 2 that actually fight is the difference between a dead end and a fix.

Found by a deletion filter (one solve per constraint, on the failure path only), so a three-way conflict with no contradictory pair is reported correctly where a pairwise check would miss it. Variable bounds are held fixed rather than dropped, so a constraint that contradicts its variable's bounds is reported as the conflict.

This runs automatically on every infeasible `:opt`; there is no separate command.

## Unboundedness diagnosis

The mirror case. An unbounded model names the variable that can run away, rather than only reporting that no optimum exists:

```text
opt: UNBOUNDED  unbounded: A5 -- add an upper bound or a constraint
```

A variable is reported when the constraints permit it to move without limit in the direction that improves the objective. That is established by re-solving over the same feasible region with that variable as the objective, so it is an exact answer rather than a large-number heuristic. Variables with no objective coefficient are never blamed: moving them cannot change the objective, so they are not the cause even when they are themselves unbounded.

Like the infeasibility case, this runs automatically.

## Programmatic access

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

Full signatures in the [`opt` API reference](../reference/api/opt.md).
