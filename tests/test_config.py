from pycalc.config import _parse_config, find_config, load_config


class TestParseConfig:
    def test_empty(self):
        cfg = _parse_config({})
        assert cfg.editor == ""
        assert cfg.sandbox is False
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

    def test_wrong_type_editor(self):
        cfg = _parse_config({"editor": 123})
        assert cfg.editor == ""

    def test_wrong_type_sandbox(self):
        cfg = _parse_config({"sandbox": "yes"})
        assert cfg.sandbox is False


class TestLoadConfig:
    def test_from_path(self, tmp_path):
        f = tmp_path / "pycalc.toml"
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
        f = tmp_path / "pycalc.toml"
        f.write_text("not valid toml [[[")
        cfg = load_config(f)
        assert cfg.editor == ""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "pycalc.toml"
        f.write_text("")
        cfg = load_config(f)
        assert cfg.editor == ""
        assert cfg.width == 0

    def test_full_config(self, tmp_path):
        f = tmp_path / "pycalc.toml"
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
        user_dir = tmp_path / "user" / "pycalc"
        user_dir.mkdir(parents=True)
        (user_dir / "pycalc.toml").write_text('editor = "user"')

        cwd = tmp_path / "project"
        cwd.mkdir()
        (cwd / "pycalc.toml").write_text('editor = "project"')

        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user"))

        path = find_config()
        assert path is not None
        cfg = load_config(path)
        assert cfg.editor == "project"

    def test_falls_back_to_user_dir(self, tmp_path, monkeypatch):
        user_dir = tmp_path / "config" / "pycalc"
        user_dir.mkdir(parents=True)
        (user_dir / "pycalc.toml").write_text('editor = "user"')

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
        custom_xdg = tmp_path / "custom_xdg" / "pycalc"
        custom_xdg.mkdir(parents=True)
        (custom_xdg / "pycalc.toml").write_text('editor = "custom"')

        cwd = tmp_path / "empty2"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom_xdg"))

        path = find_config()
        assert path is not None
        cfg = load_config(path)
        assert cfg.editor == "custom"
