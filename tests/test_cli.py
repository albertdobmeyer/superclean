"""Lock exclusivity and the JSON contract on fatal errors."""
from __future__ import annotations

import json
import os
import subprocess
import sys
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
    # A leftover file from a crashed run carries no OS lock, so it is not an
    # obstacle: the kernel dropped the lock when that process died.
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean.lock").write_text("999999999")  # dead pid
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    cli._release_lock(lock)


def test_garbage_lock_is_reclaimed(tmp_path, monkeypatch):
    # File *content* is a breadcrumb, never lock state - garbage cannot wedge us.
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean.lock").write_text("not-a-pid")
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    cli._release_lock(lock)


def test_live_pid_in_lockfile_does_not_block_an_unlocked_file(tmp_path, monkeypatch):
    # The old design read this PID, saw it alive, and refused. Liveness is now the
    # kernel's business: an unlocked file naming a live PID must not block a run.
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean.lock").write_text(str(os.getpid()))
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


def test_release_never_unlinks_the_lockfile(tmp_path, monkeypatch):
    # Unlinking a path another process may hold open is what let two runs lock
    # different inodes under one name. Release drops the OS lock and nothing else.
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    lock = cli._acquire_lock(_ctx())
    assert lock is not None
    cli._release_lock(lock)
    assert lock.path.exists()


def test_force_unlock_overrides_a_held_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    held = cli._acquire_lock(_ctx())
    assert held is not None
    try:
        assert cli._acquire_lock(_ctx()) is None  # blocked without the override
        forced = cli._acquire_lock(_ctx(force_unlock=True))
        assert forced is not None
        assert forced.held is False  # ran anyway, but does not claim ownership
        cli._release_lock(forced)
    finally:
        cli._release_lock(held)


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


_HOLDER = """\
import os, sys
from superclean import cli
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)
assert cli._os_try_lock(fd), "child could not take the lock"
sys.stdout.write("LOCKED\\n")
sys.stdout.flush()
sys.stdin.readline()
"""


def test_lock_excludes_a_real_second_process_and_survives_its_crash(tmp_path, monkeypatch):
    # The regression test for #19. The old lock was arbitrated by reading a PID out
    # of a file, so two processes could each judge it stale and both end up holding
    # it. Nothing below can be satisfied by content inspection: a genuinely separate
    # process takes the kernel lock, and we must be excluded while it lives and free
    # to proceed once it dies WITHOUT a clean release (SIGKILL, no unlock, no unlink).
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    lockfile = tmp_path / "superclean.lock"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(lockfile)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert holder.stdout.readline().strip() == "LOCKED"
        assert cli._acquire_lock(_ctx()) is None  # excluded across processes
    finally:
        holder.kill()  # crash it: no unlock, no unlink, lockfile left behind
        holder.wait(timeout=30)

    assert lockfile.exists()  # the corpse of the lockfile is still on disk...
    mine = cli._acquire_lock(_ctx())  # ...and must not wedge the next run
    assert mine is not None
    assert mine.held is True
    cli._release_lock(mine)
