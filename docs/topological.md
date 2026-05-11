# Topological recalc

Design note for replacing the fixed-point recalc loop with a dependency-graph
driven traversal. Status: **proposal, not implemented**. Linked from
`TODO.md` under Performance.

## Why

`xlsxload` on a 5000-cell sheet now runs in ~12 ms end-to-end. The
breakdown:

- C++ xlsx parse via `_core.xlsx_read`: ~4 ms
- `Grid.setcells_bulk` (writes + single recalc): ~8 ms

Of the 8 ms, the actual cell writes are ~1 ms; the rest is **one pass
through every formula in the sheet**. For sheets with many formulas (or
edits that change a value referenced by deep chains), recalc dominates,
and the cost is bounded only by `range(100)` in the loop below.

Topological recalc replaces this with a graph traversal that touches only
the transitive closure of cells affected by a change.

## How recalc works today

`Grid.recalc()` in EXCEL/HYBRID mode dispatches to `_recalc_formula()`
(`src/gridcalc/engine.py:929`). The hot loop:

```python
for _ in range(100):
    changed_cells = set()
    for (fc, fr), cl in self._cells.items():
        if cl.type != FORMULA:
            continue
        # parse if AST stale (text-keyed cache on Cell.ast_text)
        if cl.ast is None or cl.ast_text != cl.text:
            cl.ast = parse(cl.text.lstrip("="))
        oldval = cl.val
        result = evaluate(cl.ast, env)
        self._store_formula_result(cl, result)
        if cl.val != oldval or matrix_changed:
            changed_cells.add((fc, fr))
    if not changed_cells:
        break
if changed_cells:
    self._circular = set(changed_cells)
```

**Properties of the current design:**

- Every formula evaluates at least once per `recalc()` call.
- Every formula evaluates again on each subsequent pass until no value
  changes — fixed-point iteration.
- A 100-iteration cap prevents infinite loops; cells still differing
  after 100 passes are flagged as `_circular`.
- AST parsing is already cached per cell, keyed on text equality
  (`engine.py:952`). The cache survives across recalc calls.

**Cost.** For `F` formula cells settling in `P` passes, evaluation count
is `F * P`. Long dependency chains (`A1 -> B1 -> C1 -> ...` of length L)
need at least L passes to fully propagate. A sheet with 1000 chained
formulas could legitimately need 1000 passes — capped at 100, so it
doesn't converge and falsely registers as circular.

## What's already in place

The evaluator already collects per-cell read sets — `Env.refs_used`
(`src/gridcalc/formula/evaluator.py:38`):

```python
class Env:
    self.refs_used: set[tuple[int, int]] = set()

    def get_cell(self, c: int, r: int) -> object:
        self.refs_used.add((c, r))
        return self.cell_value(c, r)
```

Every `CellRef` and `RangeRef` resolution flows through `get_cell`, so
after `evaluate(ast, env)` returns, `env.refs_used` is the **set of
cells the formula actually read on this evaluation**. Today this set is
discarded.

The AST nodes are also already structured for static analysis
(`src/gridcalc/formula/ast_nodes.py:29`):

- `CellRef(col, row, abs_col, abs_row)` — a single cell.
- `RangeRef(start: CellRef, end: CellRef)` — a rectangular range.
- `Call(name, args)` / `PyCall(...)` / `BinOp` / `UnaryOp` / etc.

Walking the AST without evaluating gives the static dependency set for
most cells.

## Proposed design

### Two indexes

- **forward**: `dep_of: dict[(c,r), set[(c,r)]]` — which cells does this
  formula read? Populated when a formula is parsed/edited.
- **reverse**: `subscribers: dict[(c,r), set[(c,r)]]` — which formulas
  read this cell? Maintained as the inverse of `dep_of`.

For a formula cell `D5 = A1 + B2 + SUM(C1:C3)`:

```text
dep_of[D5]      = {A1, B2, C1, C2, C3}
subscribers[A1] += {D5}
subscribers[B2] += {D5}
subscribers[C1] += {D5}
subscribers[C2] += {D5}
subscribers[C3] += {D5}
```

### Static dependency extraction

Walk the cached AST in a function `_extract_refs(node) -> set[(c,r)]`:

- `CellRef` -> `{(node.col, node.row)}`.
- `RangeRef` -> the rectangular set (or a symbolic range entry — see
  "range explosion" below).
- `Call`/`BinOp`/`UnaryOp`/`Percent`/`PyCall` -> union of children's
  refs.
- Names (named ranges) -> resolve via the named-range table; treat as
  the underlying range.

This is pure-AST analysis; **no evaluation**.

### Recalc as graph traversal

When cell `X` changes:

1. **Compute closure.** BFS from `X` across `subscribers`. Result is the
   set of cells transitively affected by `X`.
2. **Topological sort** of the closure (Kahn's algorithm or DFS). The
   sort keys are the edges from `dep_of` restricted to the closure.
3. **Evaluate in topo order.** Each cell sees up-to-date inputs; one
   evaluation per cell.
4. **Cycle detection** is structural: if Kahn's algorithm leaves
   unvisited nodes, those nodes form a strongly-connected component.
   Mark them `#REF!` (cycle) — no need to "fail to converge in 100
   iterations" as a proxy for cycle detection.

### Bulk edits

`setcells_bulk` (or any multi-cell change) computes the **union** of
closures over all changed cells, sorts that union once, and evaluates.
For an `xlsxload` of pure values with no inter-cell refs, the union
closure is empty — recalc cost approaches zero.

## Cost comparison

For a sheet with `F` formula cells, `E` total dependency edges, edit
affecting `K` cells in the transitive closure:

| Metric | Today | Topological |
|---|---|---|
| Evaluations per edit | `F * P` | `K` |
| Worst case | `100 * F` | `O(F + E)` (whole sheet) |
| Cycle detection | "didn't converge" (false positives possible) | structural (exact) |
| Convergence cap | 100 iterations | none |
| Determinism | depends on dict iteration order across passes | topo order is canonical |

For typical edits where `K << F`, the speedup is `F * P / K` —
potentially three orders of magnitude on large sheets.

## Hard parts

The work isn't just "build a DAG." Several subtleties:

### 1. Dynamic references

Some functions read cells whose addresses depend on a **value**, not
text:

- `INDIRECT(A1)` — reads whatever cell `A1` names (e.g. `"B7"`).
  Already deliberately unsupported (`TODO.md:128`); leave it that way
  for the topo path.
- `OFFSET(A1, B1, 0)` — reads a cell offset by `B1`'s value.
- `INDEX(A:Z, row, col)` — reads a cell whose row/col are values.

For these, static `_extract_refs` cannot know the read set. Two options:

**(a) Conservative fallback.** Mark cells containing dynamic-ref
functions as "always recompute" — they're pinned to every recalc and
their outputs are downstream-broadcast. Equivalent to today's behaviour
for those specific cells.

**(b) Two-phase evaluation.** Evaluate the cell to learn its
`refs_used`, then re-add edges if the read set changed. Requires
re-running topo sort when edges change mid-recalc; loses some of the
benefit but bounds cost more tightly than the conservative path.

Recommendation: start with **(a)** since `OFFSET`/`INDEX` are uncommon
and the fallback is simple. Revisit if profiling shows them hot.

### 2. Range explosion

`SUM(A1:Z1000)` adds 26 000 reverse-index entries. Pathological cases
(`SUM(A:A)` over a whole column) blow up to `NROW = 1024` entries.

Three mitigations, in increasing complexity:

- **Sparse store.** Only insert subscribers for cells that *actually
  exist* in `Grid._cells`. A 26 000-cell range over an empty area adds
  nothing. Most large ranges in practice are sparse.
- **Interval representation.** Store ranges as
  `(c1, r1, c2, r2) -> {subscribers}`; query "who subscribes to cell
  (c,r)?" by intersecting against all stored rectangles. R-tree or
  per-column interval tree if rectangles get numerous.
- **Aggregation node.** Insert a synthetic node `RangeNode(A1:Z1000)`
  with one outgoing edge to each subscriber and incoming edges from the
  range cells. A change to any covered cell dirties the range node
  once, which dirties subscribers once.

Recommendation: ship with the **sparse store** approach; it covers the
common case and degrades gracefully. Aggregation nodes are correct but
add complexity — defer until a real workload demands them.

### 3. Named ranges and `py.*`

Named ranges are static (`NamedRange.c1, r1, c2, r2`) — resolve at
extraction time, no special handling.

The `py.*` gateway in HYBRID mode calls user code. User code receives
the `Env` and can call `env.get_cell` arbitrarily. Two options:

- Treat any cell containing a `PyCall` as **always-recompute** (same
  fallback as dynamic refs). Cheap and correct.
- Track `refs_used` from the `py.*` execution and treat them as edges,
  with the caveat that subsequent calls might read different cells.
  More expensive bookkeeping.

Start with always-recompute.

### 4. Edits to the graph

Operations that mutate the graph:

- **Cell text changes.** Old `dep_of[X]` is removed from each
  `subscribers[d]`; new `dep_of[X]` is computed from the new AST and
  re-added. `setcell` and `setcells_bulk` call this.
- **Cell deletion.** Drop the cell from both indexes; downstream
  subscribers see `None`/zero (existing behaviour).
- **Insert/delete row or column.** `_adjust_refs` already rewrites
  CellRef/RangeRef coordinates throughout the grid; the graph indexes
  must be rebuilt or remapped in lockstep. Easiest: rebuild from
  scratch after structural edits — they're rare and already O(N) in
  ref-rewriting cost.
- **Replicate.** Same as multi-cell setcell — call the bulk add.

### 5. PYTHON mode

`Grid.mode == PYTHON` uses Python `eval()` on raw text. No AST, no
`refs_used`, no static extraction. Topo recalc therefore can't see
dependencies and the fixed-point loop has to stay for this mode --
only EXCEL/HYBRID get the graph-driven traversal. (PYTHON mode was
previously called `LEGACY`; the rename doesn't change its semantics.)

## Implementation plan

Phased to minimise risk; each phase is independently shippable.

### Phase A: graph construction (no behaviour change)

- Add `Grid._dep_of` and `Grid._subscribers` as empty dicts.
- Add `_extract_refs(ast, named) -> set[(c,r)]` walking the AST.
- Hook `setcell` / `setcells_bulk` / cell-clear to maintain the
  indexes alongside the existing recalc.
- Add a `make qa` invariant: after recalc, every `(c, r)` in
  `_dep_of[X]` has `X in _subscribers[(c, r)]`.

Keep using fixed-point recalc; the graph is built but not yet consulted.
This ships safely and gives us telemetry on graph size.

### Phase B: topo recalc, EXCEL only, full-sheet rebuild

- Implement `_recalc_topo(dirty: set[(c,r)] | None = None)` that does
  the closure + topo sort + evaluation.
- If `dirty is None`, treat all formula cells as dirty (matches
  current `recalc()` semantics for a freshly loaded grid).
- Gate behind a feature flag (`Grid._use_topo_recalc = True`) so we
  can A/B test on the same sheet.
- Cells with `PyCall` or dynamic-ref functions get added to the dirty
  set unconditionally (always-recompute fallback).

Run the existing test suite under both engines; any divergence is a
bug in the new path.

### Phase C: incremental recalc on edits

- `setcell` passes `dirty={(c, r)}` to `_recalc_topo`; closure traversal
  handles propagation.
- `setcells_bulk` unions the dirty set across all writes, calls
  `_recalc_topo` once.

This is where the user-visible perf win lands.

### Phase D: HYBRID + cycle reporting

- Apply the same path to HYBRID mode (same evaluator).
- Replace the "didn't converge in 100 iterations" cycle marker with
  the structural SCC detection from topo sort. Surface a clearer
  `#REF!` value for cells in actual cycles.

### Phase E: range aggregation (only if needed)

Only revisit if profiling shows large ranges as a hot spot. Sparse
subscribers should cover the common case.

## Open questions

- **Granularity of "changed".** Today the loop checks `cl.val !=
  oldval` after evaluation. With topo, do we still check that, or
  trust the static graph? Static is faster but propagates on edits
  that don't actually change a downstream value. Probably keep the
  value-equality check at the leaf to short-circuit no-op
  propagation; it's cheap.
- **Volatile functions** (`NOW()`, `RAND()`, `TODAY()`). Excel marks
  these as volatile and recomputes on every recalc. We don't have
  them yet; if/when we do, they're equivalent to the always-recompute
  fallback.
- **Concurrency.** None of this is thread-safe. The TUI is
  single-threaded; not a current concern.

## When to actually do this

Defer until at least one of:

- `xlsxload` of a real workbook exceeds ~1 second.
- Long formula chains (>30 deep) start hitting the 100-iteration cap.
- An interactive edit takes >50 ms to settle on a sheet a user cares
  about.

Until then, the fixed-point loop is fine and the engineering cost
isn't earned. CI + wheel matrix have higher near-term leverage; revisit
this when a real workload presses on the recalc ceiling.
