"""Pure-function tests for orphan classification."""
from __future__ import annotations

from superclean.orphans import _is_candidate, _parent_gone


def _p(pid, name, ppid, ctime, username="albertd"):
    return {"pid": pid, "name": name, "ppid": ppid, "create_time": ctime,
            "username": username, "cmdline": []}


def test_parent_is_init_means_gone():
    procs = {10: _p(10, "node", 1, 100.0)}
    assert _parent_gone(procs[10], procs)


def test_missing_parent_means_gone():
    procs = {10: _p(10, "node", 999, 100.0)}
    assert _parent_gone(procs[10], procs)


def test_pid_reuse_means_gone():
    procs = {5: _p(5, "bash", 1, 200.0), 10: _p(10, "node", 5, 100.0)}
    # parent started AFTER the child: the original parent died, pid was reused
    assert _parent_gone(procs[10], procs)


def test_live_parent_means_not_gone():
    procs = {5: _p(5, "bash", 1, 50.0), 10: _p(10, "node", 5, 100.0)}
    assert not _parent_gone(procs[10], procs)


def test_user_systemd_subreaper_means_gone():
    procs = {1700: _p(1700, "systemd", 1, 10.0), 10: _p(10, "node", 1700, 100.0)}
    assert _parent_gone(procs[10], procs)


def test_root_systemd_service_child_is_not_flagged_for_other_user():
    procs = {1700: _p(1700, "systemd", 1, 10.0, username="root"),
             10: _p(10, "node", 1700, 100.0, username="albertd")}
    assert not _parent_gone(procs[10], procs)


def test_candidates():
    assert _is_candidate("node", "")
    assert _is_candidate("vite", "")
    assert not _is_candidate("chrome", "/opt/google/chrome/chrome --type=renderer")
    assert _is_candidate("chrome", "chrome --headless --remote-debugging-port=0")
    assert _is_candidate("headless_shell", "headless_shell --headless about:blank")
    assert not _is_candidate("firefox", "firefox -new-window")
    assert _is_candidate("firefox", "firefox --headless -screenshot")
    assert not _is_candidate("cursor", "")
