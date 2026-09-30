# gridcalc vs. l123 + IronCalc

Status: **comparison note, 2026-09-28.** No decision taken.

[l123](https://github.com/duane1024/l123) is a Rust terminal spreadsheet that emulates Lotus 1-2-3 R3.4a. It uses [IronCalc](https://www.ironcalc.com) as its calculation engine. This note compares that split with gridcalc's own engine. Claims marked *(inference)* are not verified.

## Core difference

l123 lists "not a compute-core reimplementation" as a non-goal. `l123-engine` wraps IronCalc behind an `Engine` trait so the engine can be swapped. Lotus syntax (`@SUM(A1..A5)`, `#AND#`) is translated to Excel syntax before IronCalc sees it. l123's own work is the Lotus UI, pinned by 232 acceptance transcripts.

gridcalc owns its engine:

- `engine.py`: 3.9k lines, including topological recalc.
- `formula/`: 2k lines of lexer, parser, evaluator.
- `libs/xlsx.py`: 6.8k lines, ~426 Excel names (`docs/function_coverage.md`).
- C++ only for xlsx I/O (`_core.cpp`, OpenXLSX) and HiGHS (`_opt.cpp`).

## Comparison

| | l123 + IronCalc | gridcalc |
|-|-|-|
| Language | Rust, native | Python evaluator; C++ for I/O and solver |
| Recalc | Full `evaluate()` only in the Python API | Incremental over a dependency graph |
| Differentiator | Lotus UX: slash menus, 13 modes, macros, charts, print, WK3 read | Engine: Python modes, LP/MIP/QP, goal seek, headless JSON CLI |
| Functions | "300+", plus 100+ in the Aug 2026 release | ~426, including LET/LAMBDA/MAP/REDUCE and dynamic arrays |
| Dynamic arrays | Added Aug 2026 | Shipped, with spill fixpoint |
| xlsx | IronCalc round-trip, including styles, merges, frozen panes | Formulas + cached values via OpenXLSX |
| User extension | Named LAMBDAs only; no host-language functions | `py.*`, PYTHON mode |
| Correctness burden | IronCalc project (2k commits, 4.2k stars) | One maintainer |
| Dependency risk | IronCalc is pre-1.0; API churn | None external |

## Costs of gridcalc's approach

1. Excel semantics are open-ended: coercion, error propagation, date-system quirks, locale parsing.
2. Evaluation runs in Python: a scalar formula costs 6-8 us, against 0.4-0.8 us in IronCalc. See the benchmark below.
3. xlsx passes through gridcalc's cell model. Features it lacks (styles, conditional formats) are likely lost on round-trip *(inference)*.

## Costs of l123's approach

1. HYBRID and PYTHON modes need the engine to call into Python mid-evaluation. A closed Rust engine without custom-function hooks blocks this.
2. Goal seek and sweeps re-evaluate many times. IronCalc's Python API offers only a full `evaluate()` per change, and returns formulas as text, not an AST.
3. The Lotus-to-Excel rewrite loses information wherever Lotus and Excel semantics differ.

## Alternative framing

The question is where gridcalc's distinct value lies. l123 treats the engine as a commodity and differentiates on UX. gridcalc differentiates on the engine, so owning it is defensible. The cost is permanent Excel-conformance work.

A hybrid is possible: IronCalc (`pip install ironcalc`) for EXCEL mode only, the Python evaluator for HYBRID and PYTHON. This gives two engines with two sets of semantics. One workbook could compute differently after a mode switch. HYBRID cannot move to IronCalc: it has no host-language function hook (see below).

## Open questions

- Is the engine the product, or a means to the solver and CLI?
- Are conformance tests checked against Excel-computed values or hand-written expectations? The differential run found 16 semantic bugs the suite did not catch.
- Does IronCalc's Rust API expose incremental recalc or the AST? The Python API (0.8.3) exposes neither. Custom functions: see below.

## User-defined functions

Checked against IronCalc `main` at `0e4af46` (2026-09-25) and the 0.8.3 Python bindings.

Supported: a LAMBDA stored under a defined name, as in Excel.

```python
m.new_defined_name("HYPOT2", None, "=LAMBDA(a,b, SQRT(a*a+b*b))")
m.set_user_input(0, 1, 1, "=HYPOT2(3,4)")   # 5.0
```

Named LAMBDAs also work as `MAP` arguments, bind through `LET`, and survive an xlsx round trip.

Not supported: a function written in Python, Rust or JavaScript.

- Built-in functions are a closed `enum Function` (`base/src/functions/mod.rs`, 496 variants), dispatched by `evaluate_function`.
- The parser turns an unknown name into `Node::NamedFunctionKind`. Evaluation (`base/src/model.rs:700`) resolves it against LET-bound variables, then defined-name LAMBDAs. Anything else is `#NAME?`. No other lookup exists.
- No registration API exists in `base/` or `bindings/`.
- The request is [#342](https://github.com/ironcalc/IronCalc/issues/342), "support for custom functions", open since 2025-05-09 with no replies. The broader [#65](https://github.com/ironcalc/IronCalc/issues/65), "Embedding and extending IronCalc", has been open since 2024-05-03 and is described as research.

For gridcalc:

- A LAMBDA library could cover formula-level helpers. It cannot cover `py.*`, which calls arbitrary Python such as numpy or pandas.
- A fork could add a host callback where `NamedFunctionKind` falls through to `#NAME?`. Full re-evaluation means no dependency tracking is needed. Volatility, error mapping, and holding the GIL during `evaluate()` would need design *(inference; not prototyped)*.

## Differential testing

`scripts/diff_ironcalc.py` runs 15,085 generated calls and 48 fixture formulas through both engines. It found crashes in both, 16 gridcalc semantic bugs (since fixed) and 11 IronCalc candidates. Triage: `docs/dev/ironcalc-diff.md`.

## Recalc benchmark

EXCEL mode, IronCalc 0.8.3 Python bindings, CPython 3.14.7, x86_64 Linux (Ryzen 9 PRO 6950H), 2026-09-30. Best of 3 runs. `n` is the formula count. Reproduce with `uv run --with ironcalc python scripts/bench_recalc.py -e gridcalc -e ironcalc -r 3`. Both engines give the same values on every workload.

- **chain**: cell k is `=<cell k-1>+1`. One dependency chain of depth n.
- **flat**: n constants and n formulas `=X*2+1`, each reading one constant. Depth 1.
- **ranges**: 1000 constants in `A1:A1000` and n formulas `=SUM(A1:A1000)+k`.

Columns:

- **load**: write every cell, then recalc. gridcalc: `setcells_bulk`. IronCalc: one `set_user_input` per cell, then `evaluate()`.
- **full**: recalc with nothing changed.
- **edit-root**: set the root constant. Every formula depends on it.
- **edit-leaf**: set the last formula. Nothing depends on it.

IronCalc's Python API has no incremental recalc, so each edit is `set_user_input` plus a full `evaluate()`.

| Workload | n | Engine | load | full | edit-root | edit-leaf |
|-|-|-|-|-|-|-|
| chain | 10k | gridcalc | 0.15 s | 0.06 s | 0.03 s | 0.10 ms |
| | | IronCalc | 0.02 s | 0.005 s | 0.005 s | 4.9 ms |
| flat | 10k | gridcalc | 0.16 s | 0.06 s | <1 ms | 0.05 ms |
| | | IronCalc | 0.03 s | 0.004 s | 0.004 s | 4.4 ms |
| ranges | 10k | gridcalc | 0.27 s | 0.14 s | 0.10 s | 0.08 ms |
| | | IronCalc | 0.51 s | 0.41 s | 0.41 s | 413 ms |
| chain | 100k | gridcalc | 1.46 s | 0.81 s | 0.44 s | 0.11 ms |
| | | IronCalc | 0.27 s | 0.08 s | 0.08 s | 82 ms |
| flat | 100k | gridcalc | 2.21 s | 0.77 s | <1 ms | 0.06 ms |
| | | IronCalc | 0.37 s | 0.07 s | 0.08 s | 74 ms |
| ranges | 100k | gridcalc | 3.08 s | 1.65 s | 1.10 s | 0.11 ms |
| | | IronCalc | 13.2 s | 4.74 s | 4.75 s | 4737 ms |

Findings:

- Scalar full recalc: IronCalc is 10-15x faster, 0.4-0.8 us per formula against gridcalc's 6-8 us.
- Range full recalc: gridcalc is about 3x faster. It evaluates a shared range once per pass; IronCalc appears to re-read it per formula *(inference from timings)*.
- Edits: gridcalc recalcs only the dirty closure, so a leaf edit takes 0.05-0.11 ms against IronCalc's 4.4-4737 ms. A root edit on chain 100k is the one edit case IronCalc wins, 0.08 s against 0.44 s.

### gridcalc range workload, before and after

Single runs on arm64 macOS, ranges at 10k. Each row includes the ones above it.

| Change | load | full | edit-root |
|-|-|-|-|
| 0.8.0 | 14.4 s | 8.3 s | 2.8 s |
| Resolve each sheet name once per formula | 10.5 s | 6.4 s | 2.8 s |
| Drop dead `Env.refs_used` tracking | 9.9 s | 6.2 s | 1.8 s |
| Memoize numbers and first error on the range `Vec` | 9.2 s | 4.0 s | 0.23 s |
| Skip per-cell registration while the graph is unbuilt | 4.5 s | 3.9 s | 0.24 s |
| One `RangeKey` graph node per distinct range (Phase E) | 0.28 s | 0.14 s | 0.10 s |

At 100k, 0.8.0 took 260 s to load, 109 s for a full recalc and 34.7 s for a root edit.

### gridcalc scalar workload, before and after

Full recalc of 20k `=X*2+1` formulas, microseconds per formula, best of 9. Same machine as the benchmark. Each row includes the ones above it.

| Change | full |
|-|-|
| 0.9.0 | 13.1 |
| Dispatch `_eval` on node type through a dict | 12.5 |
| Resolve each sheet once per pass; store a float before the type tests | 11.8 |
| Arithmetic on two floats skips array and coercion checks | 9.6 |
| Import once per module, not per dependency refresh | 8.3 |
| Dependency walks test the exact node type | 7.3 |

What remains in that 7.3 us, from timers inside `_recalc_topo`:

- Graph rebuild: about 2.9 us. A full `recalc()` always rebuilds, because undo, sort and the CLI write cells directly (`docs/topological.md`).
- `evaluate()`: about 1.7 us. With a function call it is 4.5 us (`=ROUND(X/3,2)`).
- Kahn ordering, the loop, the result store and spill check: about 2.5 us.

Load parses each formula, which a recalc does not. Parsing costs 6-18 us per formula, about half of it in the tokenizer.

Evaluation is 13-41% of a full recalc across four workloads (`=A1+1`, `=X*2+1`, `=ROUND(X/3,2)`, `=IF(X>5,X*2,X-1)`). A C++ tree walker with zero cost would gain at most 1.2-1.7x. Compiling each AST to Python closures gained 6% over dict dispatch in a prototype: the cost was in the helpers under each operator, not in dispatch.

## Sources

- [l123](https://github.com/duane1024/l123)
- [IronCalc site](https://www.ironcalc.com), [repo](https://github.com/ironcalc/IronCalc), [blog](https://blog.ironcalc.com/), [roadmap](https://www.ironcalc.com/roadmap.html), [PR #1420](https://github.com/ironcalc/IronCalc/pull/1420)
