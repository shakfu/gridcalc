# Test-suite override for the topological-recalc feature flag. Default
# is now ON in `Grid.__init__`; set GRIDCALC_TOPO=0 to force the
# fixed-point path on every Grid instance for regression coverage.
import os

_TOPO_ENV = os.environ.get("GRIDCALC_TOPO")

if _TOPO_ENV in ("0", "false", "no"):
    from gridcalc.engine import Grid

    _orig_init = Grid.__init__

    def _legacy_init(self):  # type: ignore[no-untyped-def]
        _orig_init(self)
        self._use_topo_recalc = False

    Grid.__init__ = _legacy_init  # type: ignore[method-assign]
