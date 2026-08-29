# Sandbox process isolation

Status: **not implemented**. This note records the design and the reasons it
has not been built, so the decision does not have to be rediscovered.

## Problem

`docs/security-plan.md` lists four layers, none of which is a process
boundary. Two consequences are documented there as caveats:

- **Filesystem reach.** `_make_eval_globals` (`engine.py:379`) puts whole
  module objects in the namespace, so approved workbook code calls
  `np.savetxt('/anywhere', ...)`. AST validation cannot stop this: `savetxt`
  is an ordinary attribute on an approved module.
- **No resource ceiling.** Workbook code runs in the application's own
  process (`engine.py:1573`). `while True: pass` hangs gridcalc and an
  unbounded allocation exhausts its memory. Neither is distinguishable from
  legitimate computation by inspecting a syntax tree.

These are separate goals. Isolation addresses both, but by different
mechanisms and with different portability.

## Unit of isolation

Relocate `_recalc_python` (`engine.py:1552`), not individual cells. The
parent sends the populated cell values and the code block; the child runs
`exec` and the whole 100-pass fixpoint loop; the parent receives one value
per cell. That is one round trip per recalc.

Per-cell IPC is not viable. The sheet is 256 x 1024 and the loop runs up to
100 passes, so per-cell calls would cost millions of round trips per recalc.

Keep one child warm across recalcs. `fork` is cheap on Unix, but Windows has
no `fork` and pays full interpreter startup, which a per-recalc spawn would
put on the keystroke path.

## Three parts

### 1. Resource limits -- portable

In the child, before user code runs:

- `resource.setrlimit(RLIMIT_AS, ...)` caps address space.
- `resource.setrlimit(RLIMIT_CPU, ...)` caps CPU seconds.
- A parent-side wall-clock timeout with `SIGKILL` catches everything else,
  including a child blocked rather than spinning.

This is the whole answer to hangs and memory exhaustion, and it works on
Linux and macOS today.

### 2. Filesystem confinement -- not portable

`setrlimit` does nothing about `np.savetxt`. Real confinement needs the
operating system:

| Platform | Mechanism | Assessment |
|----------|-----------|------------|
| Linux | Landlock, or seccomp with a syscall filter | Workable |
| macOS | `sandbox_init` | Deprecated, poorly documented |
| Windows | AppContainer / job objects | Separate design entirely |

There is no portable Python answer. Be honest about the result: isolation
buys availability on every platform, and file confinement mainly on Linux.

### 3. The channel -- the subtle part

The child is untrusted, so **the parent must never `pickle.loads` what the
child returns**. Doing so moves arbitrary code execution across the pipe
rather than containing it, and the parent is the privileged side.

The channel needs a typed wire format that refuses anything it does not
recognise:

- number, string, bool, `ExcelError`
- `Vec`: shape plus a flat array of floats
- `ndarray`: dtype, shape, raw buffer

`DataFrame` cells are the awkward case: the editor in `tui/objedit.py`
supports them, and they have no small typed encoding. Options are to
restrict them to a columnar subset, or to decline to return them across the
boundary at all.

## The HYBRID problem

PYTHON mode fits the model above. HYBRID does not.

Its `py.*` gateway is resolved by `_eval_pycall`
(`formula/evaluator.py:842`) against a registry built by
`_build_py_registry` (`engine.py:1755`). That call happens *mid-expression*,
inside the Excel evaluator, which runs in the parent. So HYBRID needs either
a round trip per `py.*` call, or the Excel evaluator moved into the child
as well.

Neither is attractive. Moving the evaluator across drags the dependency
graph and the cell store with it.

## Alternatives considered

### A curated module facade

The filesystem reach exists only because whole module objects are handed to
workbook code. Expose a facade instead: `np.array`, `np.mean`,
`np.linalg.solve`, and not `save`, `savetxt`, `load`, `fromfile`.

- Closes the demonstrated vector portably, with no IPC, no wire format, and
  no HYBRID problem.
- Does not address resource exhaustion. A hang is a far cheaper outcome than
  exfiltration, so this trades the lesser risk for a much lower cost.
- Cost is ongoing curation: every newly approved module needs a facade, and
  an omission is silent.

### Decline to run untrusted code

Already built. `LoadPolicy.formulas_only()` (`sandbox.py:395`) loads cells
and formulas and never executes the code block; the web loader defaults to
it.

Isolation is only worth its cost if gridcalc wants to *offer* "run a
stranger's workbook code" as a feature. Declining is free and is the current
answer for every frontend except the TUI trust prompt.

## Recommendation

Ordered by cost against risk removed:

1. Keep `formulas_only` as the default for anything not typed by the user.
   Done.
2. Build the module facade. It removes the severe outcome (arbitrary file
   read and write) at a fraction of the cost.
3. Build process isolation only if untrusted execution becomes a supported
   feature, and scope it to PYTHON mode first. Treat HYBRID's `py.*` gateway
   as a separate decision.

Do not describe the current sandbox as a security boundary in the meantime.
`docs/security-plan.md` says the trust gate is the boundary, which remains
accurate.
