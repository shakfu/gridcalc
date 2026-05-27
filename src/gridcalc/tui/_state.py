"""Shared mutable module state for the TUI package.

``_cfg`` is read by command handlers (e.g. :func:`commands.cmd_edit`) and
written once by :func:`gridcalc.tui.main` at startup. It lives in this leaf
module -- rather than in ``tui/__init__.py`` -- so ``commands.py`` can read it
without importing the package and creating a cycle. It is not patched by any
test, so its location is unconstrained.

The other piece of shared state, ``_resolved_keymap`` (plus ``_action_for``),
deliberately lives in ``tui/__init__.py`` instead: the test-suite rebinds
``gridcalc.tui._resolved_keymap`` directly and expects ``gridcalc.tui._action_for``
to observe it, which only works if both resolve in the package namespace.
"""

from __future__ import annotations

from ..config import Config

_cfg: Config = Config()
