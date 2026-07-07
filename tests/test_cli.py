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
