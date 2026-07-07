"""Shared snapshot + name normalization."""
from __future__ import annotations

import os

from superclean.procs import norm, snapshot


def test_norm():
    assert norm("Chrome.EXE") == "chrome"
    assert norm("node") == "node"
    assert norm(None) == ""
    assert norm("") == ""


def test_snapshot_contains_self_with_expected_keys():
    procs = snapshot()
    me = procs.get(os.getpid())
    assert me is not None
    for key in ("name", "ppid", "cmdline", "create_time", "username", "memory_info"):
        assert key in me


def test_snapshot_accepted_by_perimeter_and_orphans():
    from superclean import orphans, perimeter

    procs = snapshot()
    protected = perimeter.build_protected_pids(procs=procs)
    assert os.getpid() in protected
    found = orphans.find_orphans(protected, procs=procs)
    assert os.getpid() not in {o["pid"] for o in found}
