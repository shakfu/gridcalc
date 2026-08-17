# Goal seek

For one-dimensional what-if ("what input makes this output equal X?"), use `:goal`:

```text
:goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]
```

```text
:goal B10 = 100 by A1                 auto-bracket from A1's current value
:goal B10 = 0 by A1 in -50:50         explicit search bracket
```

Uses bisection over `Grid.recalc()`, which converges in milliseconds at spreadsheet scale. The variable cell must hold a value, not a formula. On success the variable cell is overwritten; `u` rolls back.

Unlike [`:opt`](optimization.md), goal seek is not persisted in the workbook -- the three arguments fit on one line, so retyping is faster than naming.

Bisection is slow asymptotically, but correctness, simplicity, and graceful failure on non-monotonic or noisy formulas are worth more here than the iteration count. The reasoning is in the module docstring: see the [`goalseek` API reference](../reference/api/goalseek.md).
