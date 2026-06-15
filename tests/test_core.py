"""Core safety + parsing tests. These run on all platforms in CI.

They spawn only throwaway child processes and write only to temp dirs; they
never touch the real machine and never perform a destructive action.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil

from superclean import config, orphans, perimeter


def test_perimeter_protects_self():
    prot = perimeter.build_protected_pids()
    assert os.getpid() in prot, "the running interpreter must always be protected"


def test_perimeter_protects_ancestors():
    prot = perimeter.build_protected_pids()
    parent = psutil.Process(os.getpid()).parent()
    if parent is not None:
        assert parent.pid in prot, "the parent process must be protected"


def test_baseline_names_present():
    names = set(perimeter.all_protected_names())
    for expected in ("cursor", "code", "ollama", "uvx", "superclean"):
        assert expected in names
    # Orphan candidates must NOT be blanket-protected by name.
    assert "node" not in names
    assert "python" not in names


def test_orphans_never_include_self_or_protected():
    prot = perimeter.build_protected_pids()
    found = orphans.find_orphans(prot)
    pids = {o["pid"] for o in found}
    assert os.getpid() not in pids
    assert pids.isdisjoint(prot)


def test_orphans_respect_age_gate():
    # A brand-new child (even if reparented) is younger than the 60s gate,
    # so it must never be flagged as an orphan.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        time.sleep(0.5)
        prot = perimeter.build_protected_pids()
        found = orphans.find_orphans(prot)
        assert child.pid not in {o["pid"] for o in found}
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


def test_config_parsers(tmp_path, monkeypatch):
    (tmp_path / "protect.conf").write_text("# comment\nWindsurf\nzed.exe\n")
    (tmp_path / "targets.conf").write_text("# c\nC:/renders|14|Renders\n/tmp/x\n")
    (tmp_path / "services.conf").write_text("API|http://localhost:3000/health\n")
    monkeypatch.setenv("SUPERCLEAN_CONF_DIR", str(tmp_path))

    assert config.protect_names() == ["windsurf", "zed"]
    tgts = config.targets()
    assert ("C:/renders", 14, "Renders") in tgts
    assert ("/tmp/x", 30, "/tmp/x") in tgts  # default days, label falls back to path
    assert config.services() == {"API": "http://localhost:3000/health"}
