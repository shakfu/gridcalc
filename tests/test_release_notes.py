"""Tests for scripts/release_notes.py, which builds the GitHub release body."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("release_notes", _SCRIPT)
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [Unreleased]

## [0.10.0]

### Changed

- Faster.

## [0.1.0]

- First.
"""


@pytest.fixture
def changelog(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text(CHANGELOG)
    return p


def run(changelog, version):
    out = changelog.parent / "notes.md"
    rc = release_notes.main([version, "--changelog", str(changelog), "-o", str(out)])
    return rc, out


def test_extracts_version_section(changelog):
    rc, out = run(changelog, "0.10.0")
    assert rc == 0
    assert out.read_text() == "## Changes since the last Release\n\n### Changed\n\n- Faster.\n"


def test_version_dots_are_literal(changelog):
    rc, out = run(changelog, "0.1.0")
    assert rc == 0
    assert out.read_text().endswith("\n\n- First.\n")
    assert run(changelog, "0x1x0")[0] == 2


def test_missing_section_ignores_unreleased(changelog):
    changelog.write_text(CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n- Pending.\n"))
    rc, out = run(changelog, "9.9.9")
    assert rc == 2
    assert not out.exists()


def test_empty_section_fails(changelog):
    changelog.write_text(CHANGELOG.replace("## [0.1.0]\n\n- First.\n", "## [0.1.0]\n\n"))
    assert run(changelog, "0.1.0")[0] == 2
