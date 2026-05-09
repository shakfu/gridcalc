"""Tests for the keybinding parser, registry, and merge logic.

Resolution to curses keycodes (``resolve_key``) is exercised in a
separate test class that calls ``curses.setupterm`` -- skipped when
that fails (e.g., on a CI environment without a usable TERM).
"""

from __future__ import annotations

import curses
import os

import pytest

from gridcalc.keys import (
    CONTEXTS,
    DEFAULT_KEYMAP,
    KNOWN_ACTIONS,
    ParsedKey,
    detect_conflicts,
    merge_user_keymap,
    parse_keyspec,
    resolve_key,
)


class TestParseKeyspec:
    def test_named_tab(self):
        pk, err = parse_keyspec("Tab")
        assert err is None
        assert pk == ParsedKey(frozenset(), "Tab")

    def test_named_arrow(self):
        pk, err = parse_keyspec("Right")
        assert err is None
        assert pk == ParsedKey(frozenset(), "Right")

    def test_function_key(self):
        pk, err = parse_keyspec("F3")
        assert err is None
        assert pk == ParsedKey(frozenset(), "F3")

    def test_named_case_insensitive_base(self):
        pk, err = parse_keyspec("tab")
        assert err is None
        assert pk == ParsedKey(frozenset(), "Tab")

    def test_shift_tab(self):
        pk, err = parse_keyspec("S-Tab")
        assert err is None
        assert pk == ParsedKey(frozenset({"S"}), "Tab")

    def test_ctrl_letter(self):
        pk, err = parse_keyspec("C-x")
        assert err is None
        assert pk == ParsedKey(frozenset({"C"}), "x")

    def test_ctrl_arrow(self):
        pk, err = parse_keyspec("C-Right")
        assert err is None
        assert pk == ParsedKey(frozenset({"C"}), "Right")

    def test_literal_char(self):
        pk, err = parse_keyspec("a")
        assert err is None
        assert pk == ParsedKey(frozenset(), "a")

    def test_literal_punctuation(self):
        pk, err = parse_keyspec(">")
        assert err is None
        assert pk == ParsedKey(frozenset(), ">")

    def test_uppercase_literal(self):
        pk, err = parse_keyspec("Z")
        assert err is None
        assert pk == ParsedKey(frozenset(), "Z")


class TestParseKeyspecRejections:
    def test_empty(self):
        pk, err = parse_keyspec("")
        assert pk is None
        assert err is not None

    def test_meta_rejected(self):
        pk, err = parse_keyspec("M-Tab")
        assert pk is None
        assert err is not None and "Meta" in err

    def test_ctrl_tab_rejected(self):
        pk, err = parse_keyspec("C-Tab")
        assert pk is None
        assert err is not None and "Ctrl-Tab" in err

    def test_ctrl_punctuation_rejected(self):
        pk, err = parse_keyspec("C-,")
        assert pk is None
        assert err is not None and "punctuation" in err

    def test_shift_non_tab_rejected(self):
        pk, err = parse_keyspec("S-Right")
        assert pk is None
        assert err is not None

    def test_shift_char_rejected(self):
        pk, err = parse_keyspec("S-a")
        assert pk is None
        assert err is not None and "uppercase" in err

    def test_ctrl_named_other_than_arrows(self):
        pk, err = parse_keyspec("C-Home")
        assert pk is None
        assert err is not None

    def test_unknown_name(self):
        pk, err = parse_keyspec("Hyper")
        assert pk is None
        assert err is not None and "unknown key name" in err

    def test_modifier_only(self):
        pk, err = parse_keyspec("C-")
        assert pk is None
        assert err is not None

    def test_non_string(self):
        pk, err = parse_keyspec(123)  # type: ignore[arg-type]
        assert pk is None
        assert err is not None


class TestParsedKeyStr:
    def test_no_modifiers(self):
        assert str(ParsedKey(frozenset(), "Tab")) == "Tab"

    def test_shift_tab(self):
        assert str(ParsedKey(frozenset({"S"}), "Tab")) == "S-Tab"

    def test_ctrl_right(self):
        assert str(ParsedKey(frozenset({"C"}), "Right")) == "C-Right"


class TestMergeUserKeymap:
    def test_empty_user_yields_defaults(self):
        defaults = {
            "grid": {"cursor_up": [ParsedKey(frozenset(), "Up")]},
            "entry": {},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        merged = merge_user_keymap(defaults, {})
        assert merged["grid"] == defaults["grid"]

    def test_user_override_replaces(self):
        defaults = {
            "grid": {"cursor_right": [ParsedKey(frozenset(), "Right")]},
            "entry": {},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        user = {
            "grid": {
                "cursor_right": [
                    ParsedKey(frozenset(), "Right"),
                    ParsedKey(frozenset(), "l"),
                ]
            }
        }
        merged = merge_user_keymap(defaults, user)
        assert len(merged["grid"]["cursor_right"]) == 2

    def test_empty_list_unbinds(self):
        defaults = {
            "grid": {"cursor_right": [ParsedKey(frozenset(), "Right")]},
            "entry": {},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        user = {"grid": {"cursor_right": []}}
        merged = merge_user_keymap(defaults, user)
        assert merged["grid"]["cursor_right"] == []

    def test_user_only_action_added(self):
        defaults = {ctx: {} for ctx in CONTEXTS}
        user = {"grid": {"next_sheet": [ParsedKey(frozenset(), "Tab")]}}
        merged = merge_user_keymap(defaults, user)
        assert merged["grid"]["next_sheet"] == [ParsedKey(frozenset(), "Tab")]

    def test_unknown_context_in_user_ignored(self):
        defaults = {ctx: {} for ctx in CONTEXTS}
        user = {"bogus": {"foo": [ParsedKey(frozenset(), "x")]}}
        merged = merge_user_keymap(defaults, user)
        assert "bogus" not in merged


class TestDetectConflicts:
    def test_no_conflicts(self):
        keymap = {
            "grid": {
                "next_sheet": [ParsedKey(frozenset(), "Tab")],
                "prev_sheet": [ParsedKey(frozenset({"S"}), "Tab")],
            },
            "entry": {},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        assert detect_conflicts(keymap) == []

    def test_same_key_two_actions_warns(self):
        tab = ParsedKey(frozenset(), "Tab")
        keymap = {
            "grid": {
                "next_sheet": [tab],
                "cursor_right": [tab],
            },
            "entry": {},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        warnings = detect_conflicts(keymap)
        assert len(warnings) == 1
        assert "Tab" in warnings[0]
        assert "next_sheet" in warnings[0]
        assert "cursor_right" in warnings[0]

    def test_conflict_isolated_to_context(self):
        tab = ParsedKey(frozenset(), "Tab")
        keymap = {
            "grid": {"next_sheet": [tab]},
            "entry": {"commit": [tab]},
            "visual": {},
            "cmdline": {},
            "search": {},
        }
        # Same key in different contexts is fine.
        assert detect_conflicts(keymap) == []


class TestKnownActions:
    def test_grid_actions_include_sheet_cycle(self):
        assert "next_sheet" in KNOWN_ACTIONS["grid"]
        assert "prev_sheet" in KNOWN_ACTIONS["grid"]

    def test_every_context_present(self):
        assert set(KNOWN_ACTIONS.keys()) == set(CONTEXTS)

    def test_default_keymap_empty_step1(self):
        # Step 1 ships zero defaults. Sheet cycling and everything
        # else must come from user config.
        for ctx in CONTEXTS:
            assert DEFAULT_KEYMAP[ctx] == {}


_TERM_OK: bool
try:
    curses.setupterm(os.environ.get("TERM", "xterm-256color"))
    _TERM_OK = True
except (curses.error, Exception):
    _TERM_OK = False


@pytest.mark.skipif(not _TERM_OK, reason="curses.setupterm unavailable")
class TestResolveKey:
    def test_tab(self):
        assert resolve_key(ParsedKey(frozenset(), "Tab")) == 9

    def test_shift_tab(self):
        # KEY_BTAB is defined whenever curses imports.
        assert resolve_key(ParsedKey(frozenset({"S"}), "Tab")) == curses.KEY_BTAB

    def test_esc(self):
        assert resolve_key(ParsedKey(frozenset(), "Esc")) == 27

    def test_space(self):
        assert resolve_key(ParsedKey(frozenset(), "Space")) == 32

    def test_arrow(self):
        assert resolve_key(ParsedKey(frozenset(), "Right")) == curses.KEY_RIGHT

    def test_function_key(self):
        # KEY_F(n) is only injected after initscr(); outside a session
        # we get KEY_F0 + n (the same integer, just expressed via the
        # base constant).
        keyf = getattr(curses, "KEY_F", None)
        expected = keyf(3) if keyf is not None else curses.KEY_F0 + 3
        assert resolve_key(ParsedKey(frozenset(), "F3")) == expected

    def test_literal_char(self):
        assert resolve_key(ParsedKey(frozenset(), "a")) == ord("a")

    def test_ctrl_letter(self):
        assert resolve_key(ParsedKey(frozenset({"C"}), "x")) == 0x18

    def test_ctrl_arrow_returns_int_or_none(self):
        # On terminfo entries that define kRIT5 we get an int; on
        # ones that don't we get None. Either is acceptable -- the
        # caller is expected to warn on None.
        result = resolve_key(ParsedKey(frozenset({"C"}), "Right"))
        assert result is None or isinstance(result, int)
