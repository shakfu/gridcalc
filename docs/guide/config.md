# Configuration

An optional `gridcalc.toml`, looked up in `$PWD` first and then `$XDG_CONFIG_HOME/gridcalc/` (default `~/.config/gridcalc/`):

```toml
sandbox = true             # AST validation of formulas + code blocks
width   = 12               # default column width
format  = "G"              # default cell format

[keys.grid]
next_sheet  = ["Tab", "F4"]
prev_sheet  = ["S-Tab", "F3"]
cursor_left = ["Left", "h"]
cursor_down = ["Down", "j"]
cursor_up   = ["Up", "k"]
cursor_right= ["Right", "l"]
```

A fuller annotated example ships in the repository as [`gridcalc.toml.example`](https://github.com/shakfu/gridcalc/blob/main/gridcalc.toml.example).

## Keybindings

Every TUI context (`grid`, `entry`, `visual`, `cmdline`, `search`) is rebindable. User bindings fire **before** the hardcoded fallback chain, so binding `Tab` to `next_sheet` replaces its default cursor-right meaning rather than racing it.

See [Keybindings](../keybindings.md) for the keyspec grammar (`Tab`, `S-Tab`, `C-x`, `C-Right`, `F3`, and so on), the action registry, and the combinations that are rejected.

## Sandboxing

`sandbox = true` (the default) enables AST validation of formulas and code blocks: dunder access, dangerous attributes and builtins, and blocked imports are rejected before anything executes. Setting `sandbox = false`, or the environment variable `GRIDCALC_SANDBOX=0`, turns it off.

The threat model -- what the sandbox is and is not meant to stop -- is in [Security plan](../security-plan.md). The short version: a workbook can carry a Python code block, so opening an untrusted file in PYTHON or HYBRID mode is the main risk, and that is what the load-time trust prompt exists for.
