from gridcalc.config import _parse_config, find_config, load_config
from gridcalc.keys import ParsedKey


class TestParseConfig:
    def test_empty(self):
        cfg = _parse_config({})
        assert cfg.editor == ""
        assert cfg.sandbox is True
        assert cfg.width == 0
        assert cfg.format == ""
        assert cfg.allowed_modules == []

    def test_editor(self):
        cfg = _parse_config({"editor": "nvim"})
        assert cfg.editor == "nvim"

    def test_sandbox_true(self):
        cfg = _parse_config({"sandbox": True})
        assert cfg.sandbox is True

    def test_sandbox_false(self):
        cfg = _parse_config({"sandbox": False})
        assert cfg.sandbox is False

    def test_width_valid(self):
        cfg = _parse_config({"width": 12})
        assert cfg.width == 12

    def test_width_too_small(self):
        cfg = _parse_config({"width": 2})
        assert cfg.width == 0

    def test_width_too_large(self):
        cfg = _parse_config({"width": 100})
        assert cfg.width == 0

    def test_width_bounds(self):
        cfg4 = _parse_config({"width": 4})
        assert cfg4.width == 4
        cfg40 = _parse_config({"width": 40})
        assert cfg40.width == 40

    def test_format(self):
        cfg = _parse_config({"format": "$"})
        assert cfg.format == "$"

    def test_format_multichar_ignored(self):
        cfg = _parse_config({"format": "abc"})
        assert cfg.format == ""

    def test_allowed_modules(self):
        cfg = _parse_config({"allowed_modules": ["numpy", "pandas"]})
        assert cfg.allowed_modules == ["numpy", "pandas"]

    def test_allowed_modules_not_list(self):
        cfg = _parse_config({"allowed_modules": "numpy"})
        assert cfg.allowed_modules == []

    def test_unknown_keys_ignored(self):
        cfg = _parse_config({"unknown_key": "value", "editor": "vim"})
        assert cfg.editor == "vim"
        assert any("unknown_key" in w for w in cfg.warnings)

    def test_width_out_of_range_warns(self):
        cfg = _parse_config({"width": 100})
        assert cfg.width == 0
        assert any("width" in w and "out of range" in w for w in cfg.warnings)

    def test_width_wrong_type_warns(self):
        cfg = _parse_config({"width": "abc"})
        assert cfg.width == 0
        assert any("width" in w for w in cfg.warnings)

    def test_format_invalid_warns(self):
        cfg = _parse_config({"format": "abc"})
        assert cfg.format == ""
        assert any("format" in w for w in cfg.warnings)

    def test_clean_config_has_no_warnings(self):
        cfg = _parse_config({"editor": "vim", "sandbox": True, "width": 10})
        assert cfg.warnings == []

    def test_wrong_type_editor(self):
        cfg = _parse_config({"editor": 123})
        assert cfg.editor == ""

    def test_wrong_type_sandbox(self):
        cfg = _parse_config({"sandbox": "yes"})
        assert cfg.sandbox is True


class TestLoadConfig:
    def test_from_path(self, tmp_path):
        f = tmp_path / "gridcalc.toml"
        f.write_text('editor = "nano"\nsandbox = true\nwidth = 10\n')
        cfg = load_config(f)
        assert cfg.editor == "nano"
        assert cfg.sandbox is True
        assert cfg.width == 10
        assert cfg.config_path == str(f)

    def test_nonexistent_path(self, tmp_path):
        cfg = load_config(tmp_path / "nope.toml")
        assert cfg.editor == ""
        assert cfg.config_path == ""

    def test_invalid_toml(self, tmp_path):
        f = tmp_path / "gridcalc.toml"
        f.write_text("not valid toml [[[")
        cfg = load_config(f)
        assert cfg.editor == ""
        assert any("TOML parse error" in w for w in cfg.warnings)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "gridcalc.toml"
        f.write_text("")
        cfg = load_config(f)
        assert cfg.editor == ""
        assert cfg.width == 0

    def test_full_config(self, tmp_path):
        f = tmp_path / "gridcalc.toml"
        f.write_text(
            'editor = "emacs"\n'
            "sandbox = true\n"
            "width = 15\n"
            'format = "%"\n'
            'allowed_modules = ["numpy", "scipy"]\n'
        )
        cfg = load_config(f)
        assert cfg.editor == "emacs"
        assert cfg.sandbox is True
        assert cfg.width == 15
        assert cfg.format == "%"
        assert cfg.allowed_modules == ["numpy", "scipy"]


class TestFindConfig:
    def test_cwd_takes_precedence(self, tmp_path, monkeypatch):
        user_dir = tmp_path / "user" / "gridcalc"
        user_dir.mkdir(parents=True)
        (user_dir / "gridcalc.toml").write_text('editor = "user"')

        cwd = tmp_path / "project"
        cwd.mkdir()
        (cwd / "gridcalc.toml").write_text('editor = "project"')

        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user"))

        path = find_config()
        assert path is not None
        cfg = load_config(path)
        assert cfg.editor == "project"

    def test_falls_back_to_user_dir(self, tmp_path, monkeypatch):
        user_dir = tmp_path / "config" / "gridcalc"
        user_dir.mkdir(parents=True)
        (user_dir / "gridcalc.toml").write_text('editor = "user"')

        cwd = tmp_path / "empty_project"
        cwd.mkdir()

        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

        path = find_config()
        assert path is not None
        cfg = load_config(path)
        assert cfg.editor == "user"

    def test_no_config_found(self, tmp_path, monkeypatch):
        cwd = tmp_path / "empty"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no_config_here"))

        path = find_config()
        assert path is None

    def test_xdg_config_home_respected(self, tmp_path, monkeypatch):
        custom_xdg = tmp_path / "custom_xdg" / "gridcalc"
        custom_xdg.mkdir(parents=True)
        (custom_xdg / "gridcalc.toml").write_text('editor = "custom"')

        cwd = tmp_path / "empty2"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom_xdg"))

        path = find_config()
        assert path is not None
        cfg = load_config(path)
        assert cfg.editor == "custom"


class TestParseConfigKeys:
    def test_no_keys_section_yields_empty(self):
        cfg = _parse_config({})
        assert cfg.keys == {}

    def test_grid_next_sheet(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": ["Tab"]}}})
        assert cfg.keys == {"grid": {"next_sheet": [ParsedKey(frozenset(), "Tab")]}}
        assert cfg.warnings == []

    def test_multi_binding(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": ["Tab", "F4"]}}})
        assert cfg.keys["grid"]["next_sheet"] == [
            ParsedKey(frozenset(), "Tab"),
            ParsedKey(frozenset(), "F4"),
        ]

    def test_explicit_unbind_preserved(self):
        cfg = _parse_config({"keys": {"grid": {"cursor_right": []}}})
        assert cfg.keys["grid"]["cursor_right"] == []
        assert cfg.warnings == []

    def test_unknown_context_warns(self):
        cfg = _parse_config({"keys": {"bogus": {"foo": ["x"]}}})
        assert "bogus" not in cfg.keys
        assert any("bogus" in w and "unknown context" in w for w in cfg.warnings)

    def test_unknown_action_warns(self):
        cfg = _parse_config({"keys": {"grid": {"warp_drive": ["F1"]}}})
        assert "warp_drive" not in cfg.keys.get("grid", {})
        assert any("warp_drive" in w and "unknown action" in w for w in cfg.warnings)

    def test_invalid_keyspec_warns_and_drops(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": ["C-Tab", "Tab"]}}})
        # Tab survives; C-Tab dropped with a warning.
        assert cfg.keys["grid"]["next_sheet"] == [ParsedKey(frozenset(), "Tab")]
        assert any("Ctrl-Tab" in w for w in cfg.warnings)

    def test_all_invalid_keyspecs_omits_action(self):
        # If every spec is invalid we do *not* fall through to "unbind"
        # -- omitting the action entirely is less surprising.
        cfg = _parse_config({"keys": {"grid": {"next_sheet": ["C-Tab"]}}})
        assert "next_sheet" not in cfg.keys.get("grid", {})

    def test_non_table_keys_warns(self):
        cfg = _parse_config({"keys": "not a table"})
        assert cfg.keys == {}
        assert any("expected table" in w for w in cfg.warnings)

    def test_non_table_context_warns(self):
        cfg = _parse_config({"keys": {"grid": "not a table"}})
        assert "grid" not in cfg.keys
        assert any("keys.grid" in w for w in cfg.warnings)

    def test_non_list_action_warns(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": "Tab"}}})
        assert "next_sheet" not in cfg.keys.get("grid", {})
        assert any("expected list" in w for w in cfg.warnings)

    def test_non_string_spec_warns(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": [123]}}})
        assert any("expected string" in w for w in cfg.warnings)

    def test_keys_does_not_appear_as_unknown_top_level(self):
        cfg = _parse_config({"keys": {"grid": {"next_sheet": ["Tab"]}}})
        assert not any(w.startswith("unknown key") for w in cfg.warnings)
