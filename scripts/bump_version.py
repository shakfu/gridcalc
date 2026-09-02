"""Rewrite the single ``version =`` line in pyproject.toml.

    python3 scripts/bump_version.py 0.6.0 [path/to/pyproject.toml]

`pyproject.toml` is the one place the version is written -- `gridcalc
--version` reads it back from the installed metadata -- so this one line is
the whole bump, and `make release` calls this before committing and tagging.

It exists as a script rather than a `sed` invocation inside the Makefile
because the `sed` there was the BSD spelling (`sed -i ''`), which is a syntax
error on GNU sed: on Linux the bump silently did nothing while the tag was
created anyway, producing a `v0.6.0` tag on a tree that still said `0.5.1` --
and the publish workflow fires on `v*` tags. Anything that can fail between
"read the version" and "tag it" has to fail *loudly*, which is what the exit
codes below are for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Deliberately strict: a release version, not an arbitrary string. A typo at
# the `make release` prompt should not become a tag.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[abc]\d+|rc\d+|\.post\d+|\.dev\d+)?$")

LINE_RE = re.compile(r"^version = .*$", re.MULTILINE)


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print("usage: bump_version.py <version> [pyproject.toml]", file=sys.stderr)
        return 2
    version = argv[1].strip()
    if not VERSION_RE.match(version):
        print(f"bump_version: not a release version: {version!r}", file=sys.stderr)
        return 2

    # The path is an argument only so the tests can point at a copy; the
    # default is the file `make release` means.
    path = (
        Path(argv[2]) if len(argv) == 3 else Path(__file__).resolve().parents[1] / "pyproject.toml"
    )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"bump_version: {exc}", file=sys.stderr)
        return 1

    new, count = LINE_RE.subn(f'version = "{version}"', text, count=1)
    if count != 1:
        # The file's shape changed; refuse rather than write something odd
        # into a file the build reads.
        print("bump_version: no 'version = ...' line in pyproject.toml", file=sys.stderr)
        return 1
    if new == text:
        print(f"bump_version: already at {version}", file=sys.stderr)
        return 1

    path.write_text(new, encoding="utf-8")
    print(f'pyproject.toml: version = "{version}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
