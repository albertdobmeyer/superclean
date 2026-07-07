"""Lock exclusivity and the JSON contract on fatal errors."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

from superclean import cli


def _ctx(force_unlock=False):
    return SimpleNamespace(force_unlock=force_unlock)


def test_lock_is_exclusive_and_releasable(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    assert cli._acquire_lock(_ctx()) is None  # held by a live pid (ours)
    cli._release_lock(lock)
    lock2 = cli._acquire_lock(_ctx())
    assert lock2 is not None
    cli._release_lock(lock2)


def test_stale_lock_is_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean.lock").write_text("999999999")  # dead pid
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    cli._release_lock(lock)


def test_garbage_lock_is_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean.lock").write_text("not-a-pid")
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    cli._release_lock(lock)


def test_json_fatal_emits_error_envelope(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)

    def boom(ctx, tier):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(cli.platform_backend, "run_tier", boom)
    code = cli.main(["sweep", "--json", "--log", str(tmp_path / "t.log")])
    assert code == 3
    out = capsys.readouterr().out
    data = json.loads(out)  # must be exactly one valid JSON document
    assert data["command"] == "sweep"
    assert "backend exploded" in data["result"]["error"]


def test_release_leaves_foreign_lock_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    lock.write_text("424242")  # simulates another process's lock
    cli._release_lock(lock)
    assert lock.exists()  # foreign lock must not be removed
    lock.unlink()


def test_acquire_backs_off_when_reclamation_race_lost(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    real_fdopen = os.fdopen

    class _Clobbered:
        def __init__(self, fh):
            self._fh = fh

        def __enter__(self):
            self._fh.__enter__()
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

        def write(self, _data):
            # simulate the other process's content winning on disk
            self._fh.write("424242")

    monkeypatch.setattr(cli.os, "fdopen", lambda fd, mode: _Clobbered(real_fdopen(fd, mode)))
    assert cli._acquire_lock(_ctx()) is None
    # the surviving lock belongs to the "other" process and must still exist
    assert (tmp_path / "superclean.lock").exists()


def test_json_lock_busy_emits_error_envelope(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    held = cli._acquire_lock(_ctx())
    assert held is not None
    try:
        code = cli.main(["sweep", "--dry-run", "--json", "--log", str(tmp_path / "t.log")])
        assert code == 1
        data = json.loads(capsys.readouterr().out)  # exactly one valid JSON document
        assert "in progress" in data["result"]["error"]
    finally:
        cli._release_lock(held)


def test_init_json_envelope(tmp_path, monkeypatch, capsys):
    from superclean import config

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    for name in ("protect.conf", "targets.conf", "services.conf"):
        (bundled / name).write_text(f"# example {name}\n")
    monkeypatch.setattr(config, "_user_config_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(config, "_bundled_conf_dir", lambda: bundled)
    monkeypatch.setattr(config, "_repo_root_dir", lambda: tmp_path / "no-repo")
    code = cli.main(["init", "--json", "--log", str(tmp_path / "t.log")])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["command"] == "init"
    assert data["result"]["files"] == {
        "protect.conf": "created",
        "targets.conf": "created",
        "services.conf": "created",
    }


def test_help_documents_ladder_and_commands():
    help_text = cli.build_parser().format_help()
    for needle in ("dust", "sweep", "scrub", "wipe", "nuke", "clean", "init", "last",
                   "cleanup ladder", "start here", "--dry-run", "NUKE",
                   "14 days", ">7d"):
        assert needle in help_text, needle
    # metavar hides the raw choices dump from usage and help body
    assert "{report,protected,ram" not in help_text
    # raw formatter means WE own wrapping: no rendered line may exceed 100 cols
    for line in help_text.splitlines():
        assert len(line) <= 100, f"overlong help line ({len(line)}): {line!r}"


def test_json_fatal_in_readonly_command_emits_envelope(tmp_path, monkeypatch, capsys):
    def boom(ctx):
        raise RuntimeError("report exploded")

    monkeypatch.setattr(cli.report_mod, "run", boom)
    code = cli.main(["report", "--json", "--log", str(tmp_path / "t.log")])
    assert code == 3
    data = json.loads(capsys.readouterr().out)  # exactly one valid JSON document
    assert "report exploded" in data["result"]["error"]
