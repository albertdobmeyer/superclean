"""Safety rules for temp age-out: only old regular files, live-session dirs skipped."""
from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

from superclean.tempprune import _age_out, _is_live_session_dir


class _Ctx:
    dry_run = True

    def log(self, *a, **k):
        pass


def _make_old(path: Path, days: int = 30) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_old_regular_file_is_counted(tmp_path):
    f = tmp_path / "stale.log"
    f.write_text("x" * 100)
    _make_old(f)
    stats = _age_out(tmp_path, days=7, ctx=_Ctx())
    assert stats["files"] == 1
    assert stats["bytes"] == 100


def test_fresh_file_is_kept(tmp_path):
    (tmp_path / "fresh.log").write_text("x")
    stats = _age_out(tmp_path, days=7, ctx=_Ctx())
    assert stats["files"] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_socket_is_never_touched():
    # A short root under /tmp: macOS caps AF_UNIX sun_path at ~104 bytes,
    # which pytest's deep tmp_path can exceed.
    root = Path(tempfile.mkdtemp(prefix="sc-", dir="/tmp"))
    try:
        sock_path = root / "agent.sock"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(sock_path))
            _make_old(sock_path)
            stats = _age_out(root, days=7, ctx=_Ctx())
            assert stats["files"] == 0
        finally:
            s.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_symlink_is_never_touched(tmp_path):
    target = tmp_path / "target.log"
    target.write_text("x")
    link = tmp_path / "link.log"
    link.symlink_to(target)
    _make_old(target)
    # target itself is old and regular -> 1 file; the symlink must not add a second
    stats = _age_out(tmp_path, days=7, ctx=_Ctx())
    assert stats["files"] == 1


def test_live_session_dirs_are_skipped(tmp_path):
    for d in (".X11-unix", "ssh-abc123", "tmux-1000", "claude-1000", "systemd-private-xyz"):
        sub = tmp_path / d
        sub.mkdir()
        f = sub / "old.txt"
        f.write_text("x")
        _make_old(f)
    stats = _age_out(tmp_path, days=7, ctx=_Ctx(), protect_session_dirs=True)
    assert stats["files"] == 0
    # without protection the same tree is prunable (targets.conf semantics)
    stats = _age_out(tmp_path, days=7, ctx=_Ctx())
    assert stats["files"] == 5


def test_is_live_session_dir_patterns():
    for name in (".X11-unix", ".ICE-unix", ".font-unix", "ssh-XYZ", "tmux-1000",
                 "systemd-private-abc", "snap-private-tmp", "pulse-x", "dbus-y", "claude-1000"):
        assert _is_live_session_dir(name)
    for name in ("build", "pip-cache", "pytest-of-albertd"):
        assert not _is_live_session_dir(name)


class _RealCtx:
    dry_run = False

    def log(self, *a, **k):
        pass


def test_real_unlink_deletes_old_and_spares_protected(tmp_path):
    old = tmp_path / "stale.log"
    old.write_text("x" * 10)
    _make_old(old)
    fresh = tmp_path / "fresh.log"
    fresh.write_text("y")
    sess = tmp_path / "claude-1000"
    sess.mkdir()
    inside = sess / "old.txt"
    inside.write_text("z")
    _make_old(inside)
    stats = _age_out(tmp_path, days=7, ctx=_RealCtx(), protect_session_dirs=True)
    assert not old.exists()          # genuinely deleted, not just counted
    assert fresh.exists()
    assert inside.exists()           # live-session dir untouched in a REAL run
    assert stats["files"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="fifos")
def test_fifo_is_never_touched(tmp_path):
    fifo = tmp_path / "pipe.fifo"
    os.mkfifo(fifo)
    _make_old(fifo)
    stats = _age_out(tmp_path, days=7, ctx=_RealCtx())
    assert fifo.exists()
    assert stats["files"] == 0
