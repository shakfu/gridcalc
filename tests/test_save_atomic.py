"""Every save path writes a temp file beside the target and renames it into place.

A save that fails part-way must leave the previous file byte-for-byte intact
and no temp file behind. The failure is produced with ``RLIMIT_FSIZE`` in a
child process, so the writer really does hit EFBIG after partial output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from gridcalc.engine import Grid, Mode

resource = pytest.importorskip("resource")

_CHILD = textwrap.dedent(
    """
    import resource, signal, sys
    from gridcalc.engine import Grid, Mode
    from gridcalc import loader

    path, method = sys.argv[1], sys.argv[2]
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk((c, r, "x" * 40) for c in range(20) for r in range(200))
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (4096, resource.RLIM_INFINITY))
    if method == "loader":
        try:
            loader.save_workbook(g, path)
            rc = 0
        except OSError:
            rc = -1
    else:
        rc = getattr(g, method)(path)
    print(rc)
    """
)


def _big_save_fails(path: Path, method: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(path), method],
        capture_output=True,
        text=True,
        env={**os.environ, "GRIDCALC_SANDBOX": "1"},
        timeout=60,
    )
    return proc.stdout.strip() + proc.stderr


@pytest.mark.parametrize(
    ("name", "method"),
    [
        ("book.json", "jsonsave"),
        ("book.csv", "csvsave"),
        ("book.xlsx", "xlsxsave"),
        ("book.csv", "pdsave"),
        ("book.json", "loader"),
        ("book.xlsx", "loader"),
    ],
)
def test_a_failed_save_leaves_the_original_intact(tmp_path: Path, name: str, method: str) -> None:
    target = tmp_path / name
    original = b"previous contents\n"
    target.write_bytes(original)
    out = _big_save_fails(target, method)
    assert out.startswith("-1"), out
    assert target.read_bytes() == original
    assert os.listdir(tmp_path) == [name]  # no temp file left behind


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcell(0, 0, "42")
    return g


def test_a_save_keeps_the_existing_file_mode(tmp_path: Path) -> None:
    target = tmp_path / "book.json"
    target.write_text("{}")
    target.chmod(0o640)
    assert _grid().jsonsave(str(target)) == 0
    assert target.stat().st_mode & 0o777 == 0o640
    assert json.loads(target.read_text())["sheets"][0]["cells"] == [[42]]


def test_a_new_file_gets_the_umask_mode(tmp_path: Path) -> None:
    target = tmp_path / "new.json"
    assert _grid().jsonsave(str(target)) == 0
    umask = os.umask(0)
    os.umask(umask)
    assert target.stat().st_mode & 0o777 == 0o666 & ~umask


def test_saving_through_a_symlink_replaces_the_link_target(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    assert _grid().jsonsave(str(link)) == 0
    assert link.is_symlink()
    assert json.loads(real.read_text())["sheets"][0]["cells"] == [[42]]


def test_a_save_into_a_missing_directory_fails_cleanly(tmp_path: Path) -> None:
    assert _grid().jsonsave(str(tmp_path / "no" / "such.json")) == -1
