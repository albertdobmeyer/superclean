"""Config discovery: any conf file marks a dir; missing files fall back per-file."""
from __future__ import annotations

from superclean import config


def _isolate(monkeypatch, tmp_path):
    """Keep the developer machine's real config dirs and repo root out of the chain."""
    monkeypatch.setattr(config, "_user_config_dir", lambda: tmp_path / "no-user-dir")
    monkeypatch.setattr(config, "_repo_root_dir", lambda: tmp_path / "no-repo-root")


def test_dir_with_only_targets_conf_is_honored(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "targets.conf").write_text("/data/renders|14|Renders\n")
    monkeypatch.setenv("SUPERCLEAN_CONF_DIR", str(tmp_path))
    assert config.conf_dir() == tmp_path
    assert ("/data/renders", 14, "Renders") in config.targets()


def test_per_file_fallback(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    user = tmp_path / "user"
    bundled = tmp_path / "bundled"
    user.mkdir()
    bundled.mkdir()
    (user / "targets.conf").write_text("/data/x|7|X\n")
    (bundled / "protect.conf").write_text("neovide\n")
    (bundled / "services.conf").write_text("API|http://localhost:9999/health\n")
    monkeypatch.setenv("SUPERCLEAN_CONF_DIR", str(user))
    monkeypatch.setattr(config, "_bundled_conf_dir", lambda: bundled)
    # user dir wins for the file it has...
    assert ("/data/x", 7, "X") in config.targets()
    # ...and the other two fall back to the bundled examples
    assert config.protect_names() == ["neovide"]
    assert config.services() == {"API": "http://localhost:9999/health"}


def test_user_file_shadows_bundled(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    user = tmp_path / "user"
    bundled = tmp_path / "bundled"
    user.mkdir()
    bundled.mkdir()
    (user / "protect.conf").write_text("warp\n")
    (bundled / "protect.conf").write_text("neovide\n")
    monkeypatch.setenv("SUPERCLEAN_CONF_DIR", str(user))
    monkeypatch.setattr(config, "_bundled_conf_dir", lambda: bundled)
    assert config.protect_names() == ["warp"]


def test_init_scaffolds_and_never_overwrites(tmp_path, monkeypatch):
    user = tmp_path / "user"
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    for name in ("protect.conf", "targets.conf", "services.conf"):
        (bundled / name).write_text(f"# example {name}\n")
    monkeypatch.setattr(config, "_user_config_dir", lambda: user)
    monkeypatch.setattr(config, "_bundled_conf_dir", lambda: bundled)
    monkeypatch.setattr(config, "_repo_root_dir", lambda: tmp_path / "no-repo")

    result = config.init_user_conf()
    assert result["dir"] == str(user)
    assert set(result["files"].values()) == {"created"}
    assert (user / "protect.conf").read_text() == "# example protect.conf\n"

    (user / "protect.conf").write_text("my-edits\n")
    result = config.init_user_conf()
    assert result["files"]["protect.conf"] == "exists"
    assert (user / "protect.conf").read_text() == "my-edits\n"


def test_init_missing_examples(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_user_config_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(config, "_bundled_conf_dir", lambda: tmp_path / "no-bundled")
    monkeypatch.setattr(config, "_repo_root_dir", lambda: tmp_path / "no-repo")
    result = config.init_user_conf()
    assert set(result["files"].values()) == {"missing-example"}


def test_init_reports_unwritable_dest(tmp_path, monkeypatch):
    blocker = tmp_path / "user"
    blocker.write_text("a file where the config dir should go")
    monkeypatch.setattr(config, "_user_config_dir", lambda: blocker)
    result = config.init_user_conf()
    assert result["files"] == {}
    assert "error" in result
