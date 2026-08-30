"""gridcalc -- a terminal spreadsheet."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    # The version is written once, in pyproject.toml, and read back here from
    # the metadata the build wrote. A literal in this file would be a second
    # copy, maintained by hand against one maintained by `make release`, and
    # `gridcalc --version` would eventually report a release nobody shipped.
    __version__ = _dist_version("gridcalc")
except PackageNotFoundError:
    # A source tree that was never installed has no metadata to read. Saying so
    # beats guessing a plausible number that no distribution corresponds to.
    __version__ = "0+unknown (not installed)"
