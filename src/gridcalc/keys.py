"""Keybinding parser, registry, and resolver.

This is the data + parser layer of the user-configurable keybindings
system. The TUI dispatcher (which actually consults the resolved
keymap during the keyloop) is built on top of this in subsequent
steps.

Grammar (emacs-short):

    Tab, Enter, Esc, Space, Backspace, Delete   named keys
    Left, Right, Up, Down                       arrows
    Home, End, PgUp, PgDn, Insert               navigation
    F1 .. F12                                   function keys
    a, Z, >, <, :, /                            literal printable chars
    S-Tab                                       Shift+Tab (only S-Tab)
    C-<letter>                                  Ctrl+letter (a..z)
    C-Right, C-Left                             Ctrl+arrow

Combinations rejected at parse time (no portable terminal encoding):

    C-Tab                                       same byte as Tab
    M-<anything>                                intercepted by the OS
    C-<punctuation>                             requires modifyOtherKeys
    S-<anything-but-Tab>                        ambiguous / non-portable

Resolution to a curses keycode requires curses to be initialised
(``resolve_key`` calls ``curses.tigetstr`` and ``curses.keyname`` for
Ctrl+arrow lookup). Parsing is curses-free and runs at config load.

Contexts:

    grid       main grid keyloop
    entry      cell entry buffer
    visual     visual selection mode
    cmdline    ":" command line
    search     "/" search prompt

Each context keeps its own action -> [keycode, ...] table. The user's
``[keys.<context>]`` overrides merge into the defaults; an explicit
empty list unbinds an action.
"""

from __future__ import annotations

import curses
from dataclasses import dataclass

CONTEXTS: frozenset[str] = frozenset({"grid", "entry", "visual", "cmdline", "search"})

# Action vocabulary. Step 1 lists only the actions exercised by the
# initial sheet-cycling slice plus the always-present cursor moves
# that the grid context will need when mainloop is refactored. Every
# subsequent step (entry/visual/cmdline/search refactor) extends this
# set; unknown actions in a user config are warned about at load time.
KNOWN_ACTIONS: dict[str, frozenset[str]] = {
    "grid": frozenset(
        {
            "cursor_up",
            "cursor_down",
            "cursor_left",
            "cursor_right",
            "next_sheet",
            "prev_sheet",
        }
    ),
    "entry": frozenset(
        {
            "cancel",
            "commit_and_advance_row",
            "commit_and_advance_col",
            "delete_back",
        }
    ),
    "visual": frozenset(
        {
            "cancel",
            "yank",
            "paste",
            "delete",
            "enter_command",
            "cursor_up",
            "cursor_down",
            "cursor_left",
            "cursor_right",
        }
    ),
    "cmdline": frozenset(
        {
            "cancel",
            "commit",
            "delete_back",
        }
    ),
    "search": frozenset(
        {
            "cancel",
            "commit",
            "delete_back",
        }
    ),
}


@dataclass(frozen=True)
class ParsedKey:
    """A key spec parsed into modifiers + base, awaiting resolution
    against a live curses runtime."""

    mods: frozenset[str]  # subset of {"S", "C"}
    base: str  # canonical base name: "Tab", "Right",
    # "F3", or a single character

    def __str__(self) -> str:
        prefix = "".join(f"{m}-" for m in sorted(self.mods))
        return f"{prefix}{self.base}"


# Canonical names of the supported "named" keys. Resolution happens in
# resolve_key(); this map only defines what is *recognised* during
# parsing.
_NAMED_KEYS: frozenset[str] = frozenset(
    {
        "Tab",
        "Enter",
        "Esc",
        "Space",
        "Backspace",
        "Delete",
        "Left",
        "Right",
        "Up",
        "Down",
        "Home",
        "End",
        "PgUp",
        "PgDn",
        "Insert",
    }
    | {f"F{i}" for i in range(1, 13)}
)

_NAMED_KEYS_LOWER: dict[str, str] = {n.lower(): n for n in _NAMED_KEYS}


def _split_modifiers(spec: str) -> tuple[frozenset[str], str]:
    """Strip leading ``X-`` modifiers and return (mod_set, rest)."""
    mods: set[str] = set()
    rest = spec
    while len(rest) >= 2 and rest[1] == "-" and rest[0] in ("S", "C", "M"):
        if rest[0] in mods:
            # Duplicate modifier; treat as a parse error upstream.
            return frozenset(mods), rest
        mods.add(rest[0])
        rest = rest[2:]
    return frozenset(mods), rest


def parse_keyspec(spec: str) -> tuple[ParsedKey | None, str | None]:
    """Parse a key spec.

    Returns ``(ParsedKey, None)`` on success or ``(None, error_msg)``
    on failure. The error message is suitable for inclusion in
    ``Config.warnings``.
    """
    if not isinstance(spec, str) or not spec:
        return None, "empty key spec"

    mods, base = _split_modifiers(spec)
    if not base:
        return None, f"{spec!r}: missing base key after modifiers"

    if "M" in mods:
        return None, (
            f"{spec!r}: Meta/Alt is intercepted by the window manager "
            "on most platforms and cannot be reliably bound"
        )

    canonical = _NAMED_KEYS_LOWER.get(base.lower())
    if canonical is not None:
        return _validate_named_combo(spec, mods, canonical)

    if len(base) == 1:
        return _validate_literal_combo(spec, mods, base)

    return None, f"{spec!r}: unknown key name {base!r}"


def _validate_named_combo(
    spec: str, mods: frozenset[str], base: str
) -> tuple[ParsedKey | None, str | None]:
    has_s = "S" in mods
    has_c = "C" in mods
    if has_s and base != "Tab":
        return None, (
            f"{spec!r}: Shift modifier is only supported with Tab in v1 "
            "(other Shift+key combos are non-portable across terminals)"
        )
    if has_c:
        if base == "Tab":
            return None, (
                f"{spec!r}: Ctrl-Tab has no portable terminal encoding "
                "(Tab and Ctrl-Tab share byte 0x09)"
            )
        if base not in ("Left", "Right"):
            return None, (
                f"{spec!r}: Ctrl is only supported with Left/Right "
                "and a-z; use F-keys or named keys without Ctrl otherwise"
            )
    return ParsedKey(mods, base), None


def _validate_literal_combo(
    spec: str, mods: frozenset[str], ch: str
) -> tuple[ParsedKey | None, str | None]:
    if "S" in mods:
        return None, (
            f"{spec!r}: Shift+character is just the uppercase form; "
            "write the uppercase letter directly"
        )
    if "C" in mods and not ch.isalpha():
        return None, (
            f"{spec!r}: Ctrl with non-letter punctuation has no portable "
            "encoding (requires modifyOtherKeys or kitty keyboard protocol)"
        )
    return ParsedKey(mods, ch), None


def resolve_key(pk: ParsedKey) -> int | None:
    """Resolve a parsed key to a curses keycode. Must be called after
    ``curses.initscr()`` (or at minimum ``curses.setupterm()``).

    Returns ``None`` if the current terminal has no keycode for this
    combination -- e.g., ``C-Right`` on a TERM whose terminfo lacks
    ``kRIT5``. Callers should warn but continue.
    """
    base = pk.base
    if len(base) == 1:
        ch = base
        if "C" in pk.mods and ch.isalpha():
            return ord(ch.lower()) - ord("a") + 1
        return ord(ch)

    if base == "Tab":
        return curses.KEY_BTAB if "S" in pk.mods else 9
    if base in ("Esc",):
        return 27
    if base == "Space":
        return 32
    if base == "Enter":
        return getattr(curses, "KEY_ENTER", 10)
    if base == "Backspace":
        return curses.KEY_BACKSPACE
    if base == "Delete":
        return curses.KEY_DC
    if base == "Insert":
        return curses.KEY_IC
    if base == "Home":
        return curses.KEY_HOME
    if base == "End":
        return curses.KEY_END
    if base == "PgUp":
        return curses.KEY_PPAGE
    if base == "PgDn":
        return curses.KEY_NPAGE
    if base == "Up":
        return curses.KEY_UP
    if base == "Down":
        return curses.KEY_DOWN
    if base == "Left":
        if "C" in pk.mods:
            return _scan_keyname("kLFT5")
        return curses.KEY_LEFT
    if base == "Right":
        if "C" in pk.mods:
            return _scan_keyname("kRIT5")
        return curses.KEY_RIGHT
    if base.startswith("F") and base[1:].isdigit():
        n = int(base[1:])
        # ``curses.KEY_F(n)`` is only injected after ``initscr()``;
        # outside a curses session use the public ``KEY_F0`` base
        # constant (``KEY_F(n) == KEY_F0 + n``).
        keyf = getattr(curses, "KEY_F", None)
        if keyf is not None:
            result: int = keyf(n)
            return result
        key_f0 = getattr(curses, "KEY_F0", None)
        if key_f0 is not None:
            return int(key_f0) + n
        return None
    return None


def _scan_keyname(cap: str) -> int | None:
    """Look up the keycode ncurses assigned to terminfo capability
    ``cap`` (e.g. ``"kRIT5"`` for Ctrl-Right).

    Returns ``None`` if the current terminfo entry does not define the
    capability (Terminal.app, Linux text console, etc.).
    """
    try:
        seq = curses.tigetstr(cap)
    except curses.error:
        return None
    if not seq:
        return None
    needle = cap.encode()
    for code in range(0o400, 0o2000):
        try:
            if curses.keyname(code) == needle:
                return code
        except (ValueError, curses.error):
            continue
    return None


# ---------------------------------------------------------------------------
# Default keymap and merge logic
# ---------------------------------------------------------------------------

# Step 1 ships an empty default keymap. Sheet cycling has *no*
# default; users who want it add it to gridcalc.toml. Subsequent
# steps populate this as each TUI chain is refactored onto the
# dispatcher.
DEFAULT_KEYMAP: dict[str, dict[str, list[ParsedKey]]] = {ctx: {} for ctx in CONTEXTS}


def merge_user_keymap(
    defaults: dict[str, dict[str, list[ParsedKey]]],
    user: dict[str, dict[str, list[ParsedKey]]],
) -> dict[str, dict[str, list[ParsedKey]]]:
    """Merge user overrides into defaults.

    Per-action: the user's list replaces the default's list. An
    explicit empty list unbinds the action. Actions present only in
    defaults pass through. Actions present only in user are added.
    Contexts not in ``CONTEXTS`` are ignored (warned upstream).
    """
    out: dict[str, dict[str, list[ParsedKey]]] = {}
    for ctx in CONTEXTS:
        merged = dict(defaults.get(ctx, {}))
        for action, keys in user.get(ctx, {}).items():
            merged[action] = list(keys)
        out[ctx] = merged
    return out


def detect_conflicts(
    keymap: dict[str, dict[str, list[ParsedKey]]],
) -> list[str]:
    """Return one warning per (context, key) bound to two actions."""
    warnings: list[str] = []
    for ctx, table in keymap.items():
        seen: dict[str, str] = {}
        for action, keys in table.items():
            for pk in keys:
                if not isinstance(pk, ParsedKey):
                    continue
                tag = str(pk)
                if tag in seen and seen[tag] != action:
                    warnings.append(f"keys.{ctx}: {tag} bound to both {seen[tag]!r} and {action!r}")
                else:
                    seen[tag] = action
    return warnings


def build_resolved_keymap(
    user_keys: dict[str, dict[str, list[ParsedKey]]],
) -> tuple[dict[str, dict[int, str]], list[str]]:
    """Resolve user keybindings into ``{context: {keycode: action}}``.

    Must be called after curses is initialised (so ``resolve_key`` can
    consult terminfo). Returns ``(resolved, warnings)``. A binding
    whose ``ParsedKey`` resolves to ``None`` -- the current terminal
    has no keycode for that combo, e.g. ``C-Right`` on Terminal.app
    without modifyCursorKeys -- is dropped with a warning. Conflicts
    within a context (same keycode bound to two actions) are also
    surfaced as warnings; later bindings win.
    """
    merged = merge_user_keymap(DEFAULT_KEYMAP, user_keys)
    resolved: dict[str, dict[int, str]] = {ctx: {} for ctx in CONTEXTS}
    warnings: list[str] = []
    for ctx, table in merged.items():
        seen: dict[int, str] = {}
        for action, keys in table.items():
            if not keys:
                # Empty list = explicit unbind (no defaults exist yet
                # for any action, so this currently has no observable
                # effect, but it must not crash).
                continue
            for pk in keys:
                code = resolve_key(pk)
                if code is None:
                    warnings.append(
                        f"keys.{ctx}.{action}: {pk} has no keycode on this "
                        "terminal (terminfo lacks the relevant capability); "
                        "binding skipped"
                    )
                    continue
                if code in seen and seen[code] != action:
                    warnings.append(
                        f"keys.{ctx}: {pk} bound to both {seen[code]!r} "
                        f"and {action!r}; the latter wins"
                    )
                seen[code] = action
        resolved[ctx] = seen
    return resolved, warnings
