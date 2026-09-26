"""Tab completion and `:help` text for the `:` line (`gridcalc.tui.completion`)."""

import pytest

from gridcalc import commands as shared
from gridcalc.engine import Grid, NamedRange
from gridcalc.tui.commands import _ARG_ALIASES, VIEW_BY_NAME, VIEW_COMMANDS
from gridcalc.tui.completion import command_names, complete, help_lines


@pytest.fixture
def g():
    grid = Grid()
    grid.add_sheet("Data")
    grid.add_sheet("Summary")
    grid.names = [NamedRange(name="sales", c1=0, r1=0, c2=0, r2=3)]
    grid.models = {"plan": object(), "alt": object()}
    return grid


# -- command table --


def test_view_command_names_are_unique():
    names = [n for c in VIEW_COMMANDS for n in c.names]
    assert len(names) == len(set(names))


def test_every_command_name_resolves():
    for name in list(shared.BY_NAME) + list(VIEW_BY_NAME) + list(_ARG_ALIASES):
        assert help_lines(name), name


# -- command names --


def test_unique_prefix_completes_with_a_space(g):
    assert complete("he", g) == ("help ", ["help"])


def test_ambiguous_prefix_extends_to_the_common_part(g):
    new, cands = complete("gf", g)  # gformat is the only canonical `g...` with `gf`
    assert new == "gformat "
    new, cands = complete("she", g)
    assert new == "sheet"
    assert cands == ["sheet", "sheets"]


def test_no_extension_returns_the_candidates(g):
    new, cands = complete("sheet", g)
    assert new == "sheet"
    assert cands == ["sheet", "sheets"]


def test_unknown_prefix_has_no_candidates(g):
    assert complete("zz", g) == ("zz", [])


def test_empty_buffer_lists_every_command(g):
    assert complete("", g)[1] == command_names()


def test_command_prefix_is_case_insensitive(g):
    assert complete("HE", g)[0] == "help "


# -- arguments --


def test_io_subcommand_then_path(g, tmp_path, monkeypatch):
    (tmp_path / "book.xlsx").write_text("")
    (tmp_path / "books").mkdir()
    monkeypatch.chdir(tmp_path)
    assert complete("xlsx l", g) == ("xlsx load ", ["load"])
    assert complete("xlsx load book.", g) == ("xlsx load book.xlsx ", ["book.xlsx"])
    assert complete("xlsx load bo", g)[1] == ["book.xlsx", "books/"]
    # A directory takes no trailing space, so Tab can descend into it.
    assert complete("o books", g)[0] == "o books/"


def test_path_completion_keeps_the_typed_directory(g, tmp_path):
    (tmp_path / "plan.json").write_text("")
    buf = f"w {tmp_path}/pl"
    assert complete(buf, g)[0] == f"w {tmp_path}/plan.json "


def test_hidden_files_need_a_leading_dot(g, tmp_path, monkeypatch):
    (tmp_path / ".secret").write_text("")
    (tmp_path / "shown").write_text("")
    monkeypatch.chdir(tmp_path)
    assert complete("o ", g)[1] == ["shown"]
    assert complete("o .s", g)[1] == [".secret"]


def test_sheet_subcommands_and_names(g):
    assert complete("sheet Su", g) == ("sheet Summary ", ["Summary"])
    assert complete("sheet del D", g) == ("sheet del Data ", ["Data"])
    assert complete("sheet add D", g) == ("sheet add D", [])  # a new name


def test_opt_models(g):
    assert complete("opt run p", g) == ("opt run plan ", ["plan"])
    assert complete("opt r", g)[0] == "opt run "


def test_format_letters_and_names(g):
    assert "," in complete("f ", g)[1]
    assert complete("unname s", g) == ("unname sales ", ["sales"])


def test_registry_choices(g):
    assert complete("mode e", g) == ("mode excel ", ["excel"])
    assert complete("sort A d", g) == ("sort A desc ", ["desc"])
    assert complete("gf $", g)[0] == "gf $ "


def test_alias_resolves_to_its_command(g):
    assert complete("s Su", g)[0] == "s Summary "  # :s is :sheet


def test_help_completes_command_names(g):
    assert complete("help for", g) == ("help format ", ["format"])


def test_unknown_command_has_no_argument_candidates(g):
    assert complete("nosuch x", g) == ("nosuch x", [])


# -- help --


def test_overview_lists_every_command():
    text = "\n".join(help_lines(""))
    for name in command_names():
        assert f":{name} " in text, name


def test_format_help_shows_comma_specs():
    text = "\n".join(help_lines("f"))
    assert ":format <spec>" in text
    assert "1,234.50" in text  # ,.2f rendered through fmt_float
    assert "Comma" in text


def test_view_command_help_shows_usage():
    assert help_lines("xlsx")[0] == ":xlsx save|load [file]"


def test_arg_alias_help_points_at_its_command():
    assert help_lines("tv")[0] == ":tv is :title v"


def test_unknown_topic():
    assert help_lines("nosuch") is None
