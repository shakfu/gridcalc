# gridcalc Security Plan

## Problem Statement

gridcalc evaluates user-provided formulas with Python's `eval()` and executes code blocks with `exec()`. This is the source of its power -- users get the full expressiveness of Python expressions, including list comprehensions, math functions, and (with this plan) third-party libraries like numpy. But `eval()` and `exec()` are also the primary attack surface if gridcalc ever loads untrusted content.

Python was never designed to be sandboxed. Every few years someone discovers a new escape through `__class__.__subclasses__()` or similar introspection chains. Restricting builtins alone is insufficient. Full Python library access and secure sandboxing are fundamentally in tension -- if numpy is in the eval namespace, a formula can call `np.save()`. You cannot expose a library's power while blocking all its side effects.

This plan takes a layered approach: no single layer is sufficient, but together they provide meaningful defense against the real threat (untrusted files) without sacrificing power for the interactive user.

## Threat Model

| Scenario                        | Threat                              | Real? |
|---------------------------------|-------------------------------------|-------|
| User types formulas at keyboard | None -- they are attacking themselves | No    |
| User types code in `:e` editor  | None -- intentional                 | No    |
| User loads untrusted .json file | Malicious formulas + code blocks    | Yes   |
| User shares a spreadsheet       | Accidental code exposure            | Low   |
| User loads a .json with no or unknown `mode` | Loads as PYTHON mode; formulas are `eval()`ed | Yes; gated by the trust prompt |
| User starts gridcalc in a directory holding a `gridcalc.toml` | `sandbox = false` or `editor` there | No; both keys are ignored in a CWD config |

The only real threat is **loading a file from an untrusted source**. The user sitting at the keyboard is the trust boundary. A config file in the working directory is untrusted content too, so it cannot set `sandbox` or `editor`.

## Architecture: Four Layers

### Layer 1: Module Registry

Users declare which third-party libraries are available, either per-spreadsheet (via a `"requires"` field in the JSON file) or globally. gridcalc imports approved modules and injects them into the formula eval namespace.

Modules are classified into three categories:

- **Safe**: `numpy` with `numpy.linalg`, `numpy.fft`, `numpy.random` and `numpy.polynomial`, and `decimal`, `fractions`, `statistics`, `cmath`, `itertools`, `functools`, `operator`, `collections`. A safe module reaches the workbook as a `ModuleFacade`: an object holding the reviewed names in `_module_names.py` and nothing else. `np.array` is numpy's function; `np.f2py`, `np.ctypeslib`, `np.savetxt` and every other unlisted name raise `AttributeError`. A test fails when an installed module has a public name that is neither listed nor excluded. `module_facades = false` in the user config hands over whole modules instead, and the prompt then lists them as unrestricted.

- **Unrestricted** (`side_effect` in the code): `matplotlib`, `matplotlib.pyplot`, `pandas`, `csv`, `xlsxwriter`, `scipy`, `sympy`. These have no facade. They are injected as module objects and flagged at the trust prompt. A module object reaches every module it imported, so approving one approves arbitrary code.

- **Blocked** (filesystem, network, process control): `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `socket`, `http`, `importlib`, `ctypes`, `pickle`, etc. Never injected, even if requested.

- **Unknown** (everything else): refused unless the user approves them as a separate, deliberate answer at the trust prompt. The blocklist names the dangers known when it was written, so "not blocked" was never the same claim as "safe" -- `runpy` runs a Python file and `sqlite3` writes one, and neither appears above. The refusal precedes the import, so a module with an import-time side effect does not get to run before being turned down.

Common aliases are applied automatically: `numpy` -> `np`, `pandas` -> `pd`, `matplotlib.pyplot` -> `plt`.

### Layer 2: AST Validation (Defense-in-Depth)

Before `eval()`, every formula is parsed with `ast.parse()` and the AST is walked to block dangerous patterns:

- **Dunder attribute access** is blocked: `x.__class__`, `x.__subclasses__()`, `x.__globals__`, etc. This prevents the known class of Python sandbox escapes that crawl the object graph from any object to `object.__subclasses__()` and from there to `os`, `subprocess`, etc.

- **Dangerous names** are blocked: `__import__`, `eval`, `exec`, `compile`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `type`, `super`, `open`, `breakpoint`, etc.

- **Dangerous internal attributes** are blocked: `func_globals`, `f_globals`, `co_consts`, `tb_frame`, `gi_frame`, etc.

- **`str.format` templates that read attributes or items** are blocked: `"{0.__globals__}".format(f)`. `format` and `format_map` are allowed only on a string literal with plain fields (`{}`, `{0}`, `{name}`), so a template built at run time is refused.

What remains allowed:

- Arithmetic, comparisons, boolean logic

- Function calls (`SUM(A1:A3)`, `np.mean(x)`)

- Attribute access on non-dunder names (`np.array`, `df.groupby`)

- List/set/dict comprehensions and generator expressions

- Lambda expressions

- Subscript and slice access (`vals[0]`, `arr[1:3]`)

This is not airtight -- new escape vectors get discovered. ~~But it blocks all *known* Python sandbox escapes while preserving full library access.~~ It does not: the check is syntactic, and string-borne attribute access passes it (see "Known gaps"). It is defense-in-depth, not the primary security boundary.

### Layer 3: Trust Gate on File Load

When loading a `.json` spreadsheet that contains code blocks, module requirements, or PYTHON-mode formulas, the user is prompted before anything executes:

**Terminal prompt (startup):**

```text
Loading: budget.json
  Cells: 47 (12 formulas)
  Requires: numpy, matplotlib [side_effect]
  Code: 8 lines

  [a]pprove  [f]ormulas only  [v]iew code  [c]ancel:
```

**Curses prompt (`:o` command):** Same information, rendered in the TUI.

Options:

- **Approve** -- load everything (code block, modules, formulas)

- **Formulas only** -- load cell data and formulas, skip code block and modules. PYTHON-mode formulas are Python, so they load unevaluated and show `#N/A`.

- **View code** -- display the code block for review

- **Cancel** -- abort the load

Files with no code block, no `requires` field and no PYTHON-mode formulas load silently. Formulas in EXCEL and HYBRID mode go through gridcalc's own evaluator, not `eval()`. The prompt prints workbook text with control characters escaped, so a terminal sequence in the code cannot hide lines of it.

This is the same trust model browsers use for Office macros: the file format can carry executable content, but loading it requires explicit consent.

### Layer 4: Restricted Builtins (Existing)

The eval globals dict restricts `__builtins__` to a curated set: `abs`, `min`, `max`, `sum`, `len`, `int`, `float`, `round`, `range`, `enumerate`, `zip`, `map`, `filter`, `list`, `tuple`, `True`, `False`, `None`, `isinstance`. This blocks `__import__`, `open`, `exec`, `eval`, `getattr`, and other dangerous builtins at the Python level. Combined with AST validation, this provides two independent barriers.

## Layer Summary

| Layer              | What it does                                | What it catches                          |
|--------------------|---------------------------------------------|------------------------------------------|
| Module registry    | Controls what is in the namespace           | Blocks os/subprocess/socket entirely     |
| AST validation     | Blocks dunder introspection chains          | Privilege escalation from objects         |
| Trust gate on load | User approves before code/modules execute   | Malicious code blocks in .json files     |
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

- If the user approves a file and numpy is available, a formula could still call `np.save('/tmp/exfil', data)`. The trust gate is the real security boundary; AST validation reduces blast radius but cannot prevent all side effects of approved libraries.

- There is no resource boundary. Workbook code runs in the application's own process, and AST validation permits loops, comprehensions, and large allocations, because none of those is distinguishable from legitimate computation by inspecting the syntax tree. `while True: pass` hangs the application and an unbounded allocation exhausts its memory. Containing this needs a worker process with wall-clock and memory limits, not a stricter validator: the four layers above address what untrusted code can *reach*, not how long it may run. Until that exists, an approved workbook is trusted with the session's availability as well as its data.

- Code blocks (`:e` editor) run unrestricted. This is intentional -- the user is the trust boundary. Code blocks from JSON files require explicit approval.

- Named ranges that shadow module aliases (e.g., a range named `np`) will override the module in the eval namespace. This is documented behavior.

- The `exec()` of the code block runs on every recalc pass. Functions defined in code blocks are redefined each time. This is harmless but wasteful.

## Known gaps

- **Formula validation missed string-borne attribute access (S1). Closed.** `str.format` and `str.format_map` read the attributes and items their template names, so `"{0.__globals__[os].environ[HOME]}".format(SUM)` read the environment with no `Attribute` node to refuse. Both methods are now allowed only on a string literal whose fields are plain names or positions. `attrgetter`, `methodcaller`, `vformat` and `get_field` are refused by name.

- **Formulas-only still evaluated formulas (S2). Closed.** `formulas_only()` now leaves PYTHON-mode formulas unevaluated, and `FileInfo.python_formulas` makes such a file raise the prompt.

- **A missing or unknown `mode` loads as PYTHON (S3). Mitigated.** The default is unchanged, so v1 files keep their meaning. Such a file now raises the prompt when it has formulas.

- **A working-directory `gridcalc.toml` can disable the sandbox (S4).** Config lookup checks the CWD before `$XDG_CONFIG_HOME`. The TUI and the headless CLI apply its `sandbox` key. With `sandbox = false`, validation and the startup trust prompt are both off. `GRIDCALC_SANDBOX` overrides config when set.

- **The startup trust prompt prints the code preview unescaped (S5).** Terminal escape sequences in a code comment can hide lines on screen.

- **Module classification used the top-level name (S6). Closed.** `numpy.ctypeslib` classified as safe. A submodule is now classified by its own dotted name; only `blocked` passes down from a package.

- **An approved module handed out every module it imported (S8). Closed for safe modules.** The formula namespace held the module object, and any non-dunder attribute is allowed: with `numpy` approved, `np.f2py.os` was `os` and `np._globals.enum.bltns` was `builtins`. Refusing attributes named after blocked modules does not hold, because `np.f2py.f2py2e.argparse._os` is `os`. Safe modules are now facades. Modules without one are still whole and are labelled unrestricted. Methods on values (`ndarray.tofile`, `DataFrame.to_csv`) are outside a facade. See `TODO.md`.

- **No limit on formula depth or run time (S7).** Neither needs approval. A deeply nested formula raises `RecursionError`, which the web and CLI load paths now catch. A formula that builds a 10^8-element array hangs the session.

## Implementation

- `gridcalc/sandbox.py` -- module classification, AST validation, FileInfo, LoadPolicy

- `gridcalc/engine.py` -- integration (validate_formula in recalc, requires in Grid, jsoninspect, policy-aware jsonload)

- `gridcalc/tui/commands.py` -- trust gate prompt (curses)

- `gridcalc/web/frontend/src/components/TrustDialog.tsx` -- the same gate in the desktop app; `gridcalc/loader.py:needs_trust` decides when either frontend must ask

- `tests/test_sandbox.py` -- comprehensive tests
