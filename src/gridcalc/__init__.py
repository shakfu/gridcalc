"""gridcalc -- a terminal spreadsheet."""

import functools
from typing import TYPE_CHECKING, Any


@functools.cache
def _version() -> str:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _dist_version

    try:
        # The version is written once, in pyproject.toml, and read back here
        # from the metadata the build wrote. A literal in this file would be a
        # second copy, maintained by hand against one maintained by `make
        # release`, and `gridcalc --version` would eventually report a release
        # nobody shipped.
        __version__ = _dist_version("gridcalc")
    except PackageNotFoundError:
        # A source tree that was never installed has no metadata to read.
        # Saying so beats guessing a plausible number that no distribution
        # corresponds to.
        __version__ = "0+unknown (not installed)"
    return __version__


if TYPE_CHECKING:
    # A module `__getattr__` would tell type checkers that every name exists.
    __version__: str
else:

    def __getattr__(name: str) -> Any:
        """``__version__``, read on first use.

        ``importlib.metadata`` costs about 15 ms to import, and every model run's
        child process imports this package without needing the version. Cached in
        ``_version`` rather than the module dict, which a reload would keep.
        """
        if name == "__version__":
            return _version()
        raise AttributeError(f"module 'gridcalc' has no attribute {name!r}")
