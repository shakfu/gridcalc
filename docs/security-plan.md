# pycalc Security Plan

## Problem Statement

pycalc evaluates user-provided formulas with Python's `eval()` and executes code
blocks with `exec()`. This is the source of its power -- users get the full
expressiveness of Python expressions, including list comprehensions, math
functions, and (with this plan) third-party libraries like numpy. But `eval()`
and `exec()` are also the primary attack surface if pycalc ever loads untrusted
content.

Python was never designed to be sandboxed. Every few years someone discovers a
new escape through `__class__.__subclasses__()` or similar introspection chains.
Restricting builtins alone is insufficient. Full Python library access and secure
sandboxing are fundamentally in tension -- if numpy is in the eval namespace, a
formula can call `np.save()`. You cannot expose a library's power while blocking
all its side effects.

This plan takes a layered approach: no single layer is sufficient, but together
they provide meaningful defense against the real threat (untrusted files) without
sacrificing power for the interactive user.

## Threat Model

| Scenario                        | Threat                              | Real? |
|---------------------------------|-------------------------------------|-------|
| User types formulas at keyboard | None -- they are attacking themselves | No    |
| User types code in `:e` editor  | None -- intentional                 | No    |
| User loads untrusted .json file | Malicious formulas + code blocks    | Yes   |
| User shares a spreadsheet       | Accidental code exposure            | Low   |

The only real threat is **loading a file from an untrusted source**. The user
sitting at the keyboard is the trust boundary.

## Architecture: Four Layers

### Layer 1: Module Registry

Users declare which third-party libraries are available, either per-spreadsheet
(via a `"requires"` field in the JSON file) or globally. pycalc imports approved
modules and injects them into the formula eval namespace.

Modules are classified into three categories:

- **Safe** (compute-only, no meaningful side effects): `numpy`, `scipy`, `sympy`,
  `decimal`, `fractions`, `statistics`, `cmath`, `itertools`, `functools`,
  `operator`, `collections`. These are injected directly (e.g., `np` for numpy).

- **Side-effect** (can do I/O but are commonly needed): `matplotlib`, `pandas`,
  `csv`, `openpyxl`. These are injected but flagged at the trust prompt.

- **Blocked** (filesystem, network, process control): `os`, `sys`, `subprocess`,
  `shutil`, `pathlib`, `socket`, `http`, `importlib`, `ctypes`, `pickle`, etc.
  Never injected, even if requested.

Common aliases are applied automatically: `numpy` -> `np`, `pandas` -> `pd`,
`matplotlib.pyplot` -> `plt`.

### Layer 2: AST Validation (Defense-in-Depth)

Before `eval()`, every formula is parsed with `ast.parse()` and the AST is
walked to block dangerous patterns:

- **Dunder attribute access** is blocked: `x.__class__`, `x.__subclasses__()`,
  `x.__globals__`, etc. This prevents the known class of Python sandbox escapes
  that crawl the object graph from any object to `object.__subclasses__()` and
  from there to `os`, `subprocess`, etc.

- **Dangerous names** are blocked: `__import__`, `eval`, `exec`, `compile`,
  `getattr`, `setattr`, `delattr`, `globals`, `locals`, `type`, `super`, `open`,
  `breakpoint`, etc.

- **Dangerous internal attributes** are blocked: `func_globals`, `f_globals`,
  `co_consts`, `tb_frame`, `gi_frame`, etc.

What remains allowed:
- Arithmetic, comparisons, boolean logic
- Function calls (`SUM(A1:A3)`, `np.mean(x)`)
- Attribute access on non-dunder names (`np.array`, `df.groupby`)
- List/set/dict comprehensions and generator expressions
- Lambda expressions
- Subscript and slice access (`vals[0]`, `arr[1:3]`)

This is not airtight -- new escape vectors get discovered. But it blocks all
*known* Python sandbox escapes while preserving full library access. It is
defense-in-depth, not the primary security boundary.

### Layer 3: Trust Gate on File Load

When loading a `.json` spreadsheet that contains code blocks or module
requirements, the user is prompted before anything executes:

**Terminal prompt (startup):**
```
Loading: budget.json
  Cells: 47 (12 formulas)
  Requires: numpy, matplotlib [side_effect]
  Code: 8 lines

  [a]pprove  [f]ormulas only  [v]iew code  [c]ancel:
```

**Curses prompt (`:o` command):**
Same information, rendered in the TUI.

Options:
- **Approve** -- load everything (code block, modules, formulas)
- **Formulas only** -- load cell data and formulas, skip code block and modules
- **View code** -- display the code block for review
- **Cancel** -- abort the load

Files with no code block and no `requires` field load silently (backward
compatible). AST validation still applies to all formulas.

This is the same trust model browsers use for Office macros: the file format can
carry executable content, but loading it requires explicit consent.

### Layer 4: Restricted Builtins (Existing)

The eval globals dict restricts `__builtins__` to a curated set: `abs`, `min`,
`max`, `sum`, `len`, `int`, `float`, `round`, `range`, `enumerate`, `zip`,
`map`, `filter`, `list`, `tuple`, `True`, `False`, `None`, `isinstance`. This
blocks `__import__`, `open`, `exec`, `eval`, `getattr`, and other dangerous
builtins at the Python level. Combined with AST validation, this provides
two independent barriers.

## Layer Summary

| Layer              | What it does                                | What it catches                          |
|--------------------|---------------------------------------------|------------------------------------------|
| Module registry    | Controls what is in the namespace           | Blocks os/subprocess/socket entirely     |
| AST validation     | Blocks dunder introspection chains          | Privilege escalation from objects         |
| Trust gate on load | User approves before code/formulas execute  | Malicious .json files                    |
| Restricted builtins| Limits Python builtins in eval              | Direct access to dangerous functions     |

## JSON File Format Extension

The `requires` field declares module dependencies:

```json
{
  "requires": ["numpy", "matplotlib"],
  "code": "def custom_func(x): return np.mean(x)",
  "cells": [
    [10, 20, 30],
    ["=custom_func(A1:A3)"]
  ]
}
```

Files without `requires` are fully backward compatible.

## Caveats

- If the user approves a file and numpy is available, a formula could still call
  `np.save('/tmp/exfil', data)`. The trust gate is the real security boundary;
  AST validation reduces blast radius but cannot prevent all side effects of
  approved libraries.

- Code blocks (`:e` editor) run unrestricted. This is intentional -- the user is
  the trust boundary. Code blocks from JSON files require explicit approval.

- Named ranges that shadow module aliases (e.g., a range named `np`) will
  override the module in the eval namespace. This is documented behavior.

- The `exec()` of the code block runs on every recalc pass. Functions defined in
  code blocks are redefined each time. This is harmless but wasteful.

## Implementation

- `pycalc/sandbox.py` -- module classification, AST validation, FileInfo,
  LoadPolicy
- `pycalc/engine.py` -- integration (validate_formula in recalc, requires in
  Grid, jsoninspect, policy-aware jsonload)
- `pycalc/tui.py` -- trust gate prompts (curses and terminal)
- `tests/test_sandbox.py` -- comprehensive tests
