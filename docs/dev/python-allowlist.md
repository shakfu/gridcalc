# PYTHON-mode formula allowlist

Status: **proposed, not implemented.**

## Problem

A PYTHON-mode workbook's formulas are passed to `eval()`. Opening an untrusted one runs Python with no code block involved:

- `"{0.__globals__[os].environ[HOME]}".format(SUM)` read the environment. `validate_formula` now refuses it, but it rejects known patterns only.
- `sum(1 for _ in range(10**100))` hangs the load.

Both use only names gridcalc itself puts in the namespace. Neither needs a code block or `requires`.

The current fix sets `FileInfo.python_formulas` (`sandbox.py:471`) for any PYTHON-mode file with at least one formula. Every such file raises the trust prompt. That includes files of plain arithmetic:

| File | Mode | Formulas | Example |
|---|---|---|---|
| `example_goal.json` | PYTHON | 1 | `=2*A1+3` |
| `example_lp.json` | PYTHON | 5 | `=3*A4+5*A5`, `=A4<=4` |
| `example.json` | none (PYTHON) | 52 | `=B3-C3`, `=sin(pi/6)`, `=tax(B3)` |

A prompt on harmless files trains the user to press `l` without reading.

## Proposal

Set `python_formulas` only when some formula falls outside an allowlist. A file whose every formula is on the allowlist loads silently and evaluates normally.

The allowlist decides only whether to prompt. Evaluation is unchanged: an approved file, or a file that passes, is still `eval()`ed with the full namespace.

A formula passes when all of these hold:

1. Its raw text is at most `MAXIN` (256) characters. The TUI already caps typed input at this length (`tui/__init__.py:281`). JSON-loaded formulas have no cap.
2. After `_expand_ranges` (`engine.py:846`), it parses with `ast.parse(mode="eval")`.
3. Every AST node is on the node list below.
4. Every `Name` is on the name list below.

Anything else prompts. The check refuses by default. It is not built on `validate_formula`, which rejects known-bad patterns and allows the rest.

## Node list

| Node | Condition |
|---|---|
| `Expression` | Root only |
| `Constant` | `int`, `float` or `bool`. No `str`, `bytes`, `None` or `...` |
| `Name` | `Load` context, on the name list |
| `BinOp` | `Add Sub Mult Div FloorDiv Mod` |
| `BinOp` `Pow` | Right operand a numeric `Constant` with absolute value at most 64; left operand contains no `Pow` |
| `UnaryOp` | `UAdd USub Not` |
| `BoolOp` | `And Or` |
| `IfExp` | -- |
| `Compare` | `Eq NotEq Lt LtE Gt GtE` |
| `Call` | `func` is a `Name` on the callable list; no `keywords`, no `Starred` |
| `List` | Only as the sole argument of `Vec(...)` |

Refused, with the reason:

- `Attribute`, `Subscript`: the format-string read reaches `__globals__` through attribute access, and indexing walks what it reaches.
- `ListComp`, `SetComp`, `DictComp`, `GeneratorExp`: the hang above.
- `Lambda`, `Starred`, `Dict`, `Set`, `Tuple`, `JoinedStr`: no spreadsheet use.
- `LShift RShift BitAnd BitOr BitXor Invert`: `1 << 10**8` builds a 100M-bit integer.
- `MatMult`, `In`, `NotIn`, `Is`, `IsNot`: no spreadsheet use.

## Name list

Values:

- Cell references `A1` to `IV1024`, after `$` is stripped.
- Names in the file's `names` object.
- `pi e inf nan True False`.

Callable, a subset of `_make_eval_globals` (`engine.py:418`):

- `SUM AVG MIN MAX COUNT ABS SQRT INT`
- `sin cos tan asin acos atan atan2 exp log log2 log10 floor ceil fabs fsum isnan isinf degrees radians`
- `abs min max round int float len`
- `Vec`, only in the form `Vec([...])` that `_expand_ranges` emits.

Excluded from the namespace:

| Name | Reason |
|---|---|
| `range map filter zip enumerate sum list tuple` | Iteration. `range` feeds the hang |
| `isinstance None` | No spreadsheet use |
| `math` | Useful only through `Attribute`, which is refused |
| `xlsx` lib (410 functions) | Loaded in PYTHON mode when a file sets `"libs": ["xlsx"]`. `SEQUENCE`, `MUNIT` and similar allocate arrays sized by their arguments |
| Code-block functions (`tax`) | The code block prompts anyway |

Derive the name list in code from `_make_eval_globals()` minus an explicit exclusion set. Do not write the list out a second time. A test fails when the namespace gains a name that is in neither set, so a new builtin cannot widen the allowlist without review.

## Why `**` is restricted

Cell values are floats. I verified this for the paths that store results:

- `parse_number("9")` returns `float`.
- Scalar results are stored with `float(result)` (`engine.py:1865`, `:1883`).
- With `A1 = 9`, `=A1:A1*1` stores `[9.0]` in `cl.arr`, and `=A1:A1**64` stores a `float` element. `Vec` arithmetic is element-wise.

A chain across cells therefore overflows fast. `B1 = A1**64`, `C1 = B1**64` stops with `OverflowError` after a few cells.

Unbounded integers come only from literals inside one formula. `9**9**9` has about 370M digits. Nesting `((9**64)**64)**64...` grows the digit count by 64 times per level. The rule allows a literal exponent of at most 64 and forbids `Pow` in the base. That bounds one power to 9^64, about 61 digits.

The 256-character cap bounds products of such powers. `9**64*9**64*...` fits about 25 factors, about 1,500 digits.

## Effect on the examples

| File | Result | Reason |
|---|---|---|
| `example_goal.json` | silent | Arithmetic only |
| `example_lp.json` | silent | Arithmetic and `Compare` only |
| `example.json` | prompts | Code block; `tax` is not on the list |
| format-string read | prompts | `Attribute`, `str` constant |
| generator hang | prompts | `GeneratorExp`, `range` |

## Tests

- Each refused node type prompts. Use one minimal formula per type.
- Each allowed node type loads silently and evaluates.
- `Pow`: `A1**2` passes; `A1**B1`, `9**65` and `(9**2)**2` prompt.
- A 257-character formula of allowed nodes prompts.
- The namespace test above: every name from `_make_eval_globals()` is either allowed or excluded.
- The two attacks prompt.
- `example_goal.json` and `example_lp.json` load without a prompt, which removes the fixture change in `tests/integration/conftest.py`.

## Limits

- The allowlist is a security boundary. It holds only while it refuses by default and while no allowed function can reach object internals or run without bound.
- It checks syntax. If an allowed function's behaviour changes, for example `fsum` accepting a generator, the allowlist does not notice. The namespace test covers new names, not changed ones.
- `SUM` over a full-sheet range is bounded by the 256 x 1024 grid, not by the allowlist. I have not measured its cost at that size.

## Alternatives considered

- **Prompt for every PYTHON-mode file with formulas.** Implemented now. Safe, but it prompts on the shipped examples.
- **Prompt only for a code block or `requires`.** The behaviour before the fix. Both attacks load with no prompt.
- **Default a missing `mode` to EXCEL.** EXCEL formulas use gridcalc's own evaluator, not `eval()`. It breaks v1 files, whose formulas are Python syntax. An explicit `"mode": "PYTHON"` still needs this allowlist or the prompt.
- **Evaluate in a limited worker process.** See `sandbox-isolation.md`. It bounds the hang, but not the environment read.
