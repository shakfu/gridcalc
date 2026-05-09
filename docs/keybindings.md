# Keybindings

Gridcalc's TUI key handling is split into a config-driven dispatch
layer (this document) and a hardcoded fallback chain that runs when
no user binding fires. All five contexts are wired: **grid**,
**entry**, **visual**, **cmdline**, **search**. User bindings fire
*before* the hardcoded fallback in each, so a binding *replaces* the
default meaning for that key rather than racing it.

## Where to put bindings

Edit `gridcalc.toml` -- either project-local at `./gridcalc.toml` or
user-level at `$XDG_CONFIG_HOME/gridcalc/gridcalc.toml`
(default: `~/.config/gridcalc/gridcalc.toml`). Project-local wins
when both exist. A working sample lives at `gridcalc.toml.example`
in the repository root.

```toml
[keys.grid]
next_sheet = ["Tab", "F4"]
prev_sheet = ["S-Tab", "F3"]
cursor_left  = ["Left", "h"]
cursor_down  = ["Down", "j"]
cursor_up    = ["Up", "k"]
cursor_right = ["Right", "l"]
```

Gridcalc ships with **no** user-bindable defaults. Every binding above
is opt-in -- the hardcoded fallback chain still runs when a user
binding doesn't match, so the unmodified arrow keys, Tab-as-cursor-right,
and so on continue to work out of the box.

## Contexts

| Context   | Where it fires                                | Self-insert? |
|-----------|-----------------------------------------------|--------------|
| `grid`    | Main grid keyloop (`mainloop`)                | No           |
| `entry`   | Cell-entry buffer (`entry`)                   | Yes          |
| `visual`  | Visual selection mode (`visual_mode`)         | No           |
| `cmdline` | `:` command line (`cmdline`)                  | Yes          |
| `search`  | `/` search prompt (`search_prompt`)           | Yes          |

**Self-insert** marks the three text-input contexts. In those, a
printable byte (`32 <= ch < 127`) **bypasses the dispatcher and
self-inserts into the buffer**, regardless of any user binding. This
is intentional: a stray `[keys.entry] cancel = ["a"]` must not lock
you out of typing the letter `a` into a cell. Non-printable keys
(`Esc`, `Tab`, `F-keys`, `C-<letter>`, arrow keys, etc.) dispatch
normally in every context.

## Actions

Action vocabulary is curated -- you cannot bind a key to an arbitrary
`:command` in v1; that's a v2 generalisation tracked in TODO.md. The
currently bindable actions:

### `[keys.grid]`

| Action         | Effect                                                       |
|----------------|--------------------------------------------------------------|
| `cursor_up`    | Move the cursor one row up (clamped at the locked top row).  |
| `cursor_down`  | Move the cursor one row down (clamped at `NROW - 1`).        |
| `cursor_left`  | Move the cursor one column left (clamped at the locked col). |
| `cursor_right` | Move the cursor one column right (clamped at `NCOL - 1`).    |
| `next_sheet`   | Activate the next sheet, wrapping at the end.                |
| `prev_sheet`   | Activate the previous sheet, wrapping at the start.          |

A binding fires *before* the hardcoded fallback chain, so binding
e.g. `Tab` to `next_sheet` *replaces* its previous "advance one
column" meaning -- the hardcoded fallback never sees the keystroke.

### `[keys.entry]`

Cell entry buffer. Printable chars always self-insert; only the
non-printable actions are useful here.

| Action                   | Effect                                                                |
|--------------------------|-----------------------------------------------------------------------|
| `cancel`                 | Discard the buffer, restore the cursor to its origin, exit entry.     |
| `commit_and_advance_row` | Write the buffer, advance one row down (clamped at `NROW - 1`).       |
| `commit_and_advance_col` | Write the buffer, advance one column right (clamped at `NCOL - 1`).   |
| `delete_back`            | Delete the last character of the buffer.                              |

### `[keys.visual]`

Visual selection mode. No self-insert -- every key is a command, so
printable bindings (`y`, `p`, `d`, `:`, `h`/`j`/`k`/`l`, etc.) fire
normally.

| Action          | Effect                                                          |
|-----------------|-----------------------------------------------------------------|
| `cancel`        | Exit visual mode without acting.                                |
| `yank`          | Copy the selection to the clipboard, exit.                      |
| `paste`         | Paste at the selection's top-left corner, exit.                 |
| `delete`        | Delete every cell in the selection, exit.                       |
| `enter_command` | Open the `:` command line scoped to the selection.              |
| `cursor_up`     | Extend the selection one row up.                                |
| `cursor_down`   | Extend the selection one row down.                              |
| `cursor_left`   | Extend the selection one column left.                           |
| `cursor_right`  | Extend the selection one column right.                          |

### `[keys.cmdline]`

The `:` command line. Printable chars self-insert.

| Action        | Effect                                  |
|---------------|-----------------------------------------|
| `cancel`      | Discard the command, exit the prompt.   |
| `commit`      | Run the command, exit.                  |
| `delete_back` | Delete the last character of the input. |

### `[keys.search]`

The `/` search prompt. Printable chars self-insert.

| Action        | Effect                                                       |
|---------------|--------------------------------------------------------------|
| `cancel`      | Discard the search, exit the prompt.                         |
| `commit`      | Run the search and jump to the first match (or warn if none).|
| `delete_back` | Delete the last character of the input.                      |

## Key-spec grammar

Emacs-short. Modifiers go first, separated by `-`:

| Form              | Meaning                                              |
|-------------------|------------------------------------------------------|
| `Tab`             | Plain Tab (ASCII 9)                                  |
| `Enter`           | Return / Enter                                       |
| `Esc`             | Escape (ASCII 27)                                    |
| `Space`           | Space                                                |
| `Backspace`       | Backspace                                            |
| `Delete`          | Delete (forward delete)                              |
| `Insert`          | Insert                                               |
| `Left` `Right` `Up` `Down` | Arrow keys                                |
| `Home` `End` `PgUp` `PgDn` | Navigation block                          |
| `F1` ... `F12`    | Function keys                                        |
| `a`, `Z`, `>`, `:`| A single literal printable character                 |
| `S-Tab`           | Shift+Tab                                            |
| `C-<letter>`      | Ctrl+letter (a-z; case-insensitive)                  |
| `C-Right`, `C-Left` | Ctrl+Arrow (xterm-style modifyCursorKeys)          |

### Combinations rejected at parse time

These are flagged with a warning at config load and the binding is
dropped -- they have no portable terminal encoding:

| Combo                    | Why                                              |
|--------------------------|--------------------------------------------------|
| `C-Tab`                  | Tab and Ctrl-Tab share byte 0x09                 |
| `M-<anything>`           | Meta/Alt is intercepted by the OS / window manager |
| `C-<punctuation>`        | Requires `modifyOtherKeys` or kitty keyboard protocol; not transmitted by default |
| `S-<anything-but-Tab>`   | Shift+arrow / Shift+letter are ambiguous or non-portable in v1 |

If you genuinely need one of these, the path is to either negotiate
the kitty keyboard protocol on startup and parse escape sequences
(out of scope for v1) or pick a different key.

### Combinations whose support is terminal-dependent

`C-Right` and `C-Left` are recognised at parse time, but resolution
to a curses keycode requires terminfo to define `kRIT5` / `kLFT5`.
Most modern emulators do; macOS Terminal.app by default does not
(user must add a key mapping in *Settings -> Profiles -> Keyboard*),
and the Linux text console has no encoding for them. When the
current terminal cannot resolve the binding, gridcalc emits a warning
to stderr at startup and skips it.

## Diagnostics

Two warning surfaces, both written to stderr at startup:

1. **Config-load warnings** -- printed by `emit_warnings(cfg)`. These
   come from `_parse_keys_table` and cover unknown contexts, unknown
   actions, wrong types, and parse-time-rejected key specs.
2. **Resolution warnings** -- printed once at `mainloop` entry. These
   come from `build_resolved_keymap` and cover bindings whose keycode
   isn't available on the current terminal, plus same-key-two-actions
   conflicts within a context (the latest binding wins).

A warning never aborts startup -- a misconfigured binding is simply
dropped from the resolved keymap.

## Internals (for code spelunkers)

- Parsing: `parse_keyspec` in `src/gridcalc/keys.py`. Runs at config
  load (no curses dependency).
- Resolution: `resolve_key` in the same module. Calls `curses.tigetstr`
  / `curses.keyname` for `C-Right`/`C-Left`, so it must run after
  `curses.initscr()`.
- Grid action registry: `_GRID_ACTIONS` in `src/gridcalc/tui.py`.
  Adding a grid action means: add it to `keys.KNOWN_ACTIONS["grid"]`,
  add a callable here, and document it in this file's table.
- Grid dispatcher: `_dispatch_grid_key` in `src/gridcalc/tui.py`.
  Pure function -- testable without a curses session (see
  `tests/test_tui.py::TestDispatchGridKey`).
- The other four contexts (`entry`, `visual`, `cmdline`, `search`)
  use a different shape: `_action_for(context, ch)` returns the
  bound action name (or `None`), and each context's existing
  if/elif chain matches on `action == "<name>" or ch == <hardcoded>`.
  This lets the actions read closed-over locals (`buf`, `origc`,
  `picking`, etc.) without lifting them into module scope. The
  dispatcher's `context in ("entry", "cmdline", "search")` branch is
  the self-insert override -- printable bytes return `None` so they
  always fall through to the hardcoded `32 <= ch < 127` branch.
- Module-level state: `_resolved_keymap` in `tui.py` is populated
  once by `mainloop` after curses init. The `_action_for` helper
  reads from it. Tests that exercise the helpers in isolation
  snapshot and restore this global per test.
