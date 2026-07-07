"""Measured reclaim: RSS from orphan kills, cache bytes, and honest exit codes."""
from __future__ import annotations

import subprocess
from pathlib import Path

from superclean import caches
from superclean.backends import posix
from superclean.backends.posix import _totals
from superclean.orphans import kill_orphans
from superclean.util import RunContext


class _Ctx:
    dry_run = True

    def log(self, *a, **k):
        pass


def test_dry_run_kill_reports_rss_estimate():
    orphans = [
        {"pid": 999999991, "name": "node", "create_time": 1.0, "ppid": 1,
         "cmdline": "node server.js", "rss": 100 * 1024 * 1024},
        {"pid": 999999992, "name": "vite", "create_time": 1.0, "ppid": 1,
         "cmdline": "vite dev", "rss": 50 * 1024 * 1024},
    ]
    result = kill_orphans(orphans, _Ctx())
    assert result["reclaimed_rss"] == 150 * 1024 * 1024


def test_dir_size_measures_and_handles_missing(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 500)
    assert caches._dir_size(tmp_path) == 1500
    assert caches._dir_size(tmp_path / "nope") is None
    assert caches._dir_size(None) is None


def test_run_reports_failure_on_nonzero_exit(monkeypatch):
    logs = []

    class Ctx:
        dry_run = False

        def log(self, msg="", level="INFO"):
            logs.append((level, msg))

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(caches.subprocess, "run", fake_run)
    assert caches._run(Ctx(), "npm", ["npm", "cache", "clean", "--force"]) is False
    assert any(level == "WARN" for level, _ in logs)


def test_empty_pip_cache_counts_as_ok(monkeypatch):
    class Ctx:
        dry_run = False

        def log(self, *a, **k):
            pass

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(
            a[0], returncode=1, stdout="", stderr="ERROR: No matching packages")

    monkeypatch.setattr(caches.subprocess, "run", fake_run)
    assert caches._run(Ctx(), "pip", ["pip", "cache", "purge"]) is True


def test_totals_aggregation():
    results = {
        "orphans": {"killed": 2, "reclaimed_rss": 100},
        "ollama": {"unloaded": 1, "reclaimed_bytes": 200},
        "temp_light": {"files": 1, "bytes": 30, "skipped": 0, "missing": False},
        "temp_deep": {"files": 1, "bytes": 20, "skipped": 0, "missing": False},
        "caches": {"pip": {"ok": True, "freed_bytes": 50}, "npm": {"ok": False, "freed_bytes": 0}},
        "targets": [{"label": "x", "files": 1, "bytes": 5, "skipped": 0, "missing": False}],
    }
    totals = _totals(results)
    assert totals["ram_bytes"] == 300
    assert totals["disk_bytes"] == 105


def test_scrub_runs_single_temp_pass(tmp_path, monkeypatch):
    calls = []

    def fake_prune_temp(ctx, days):
        calls.append(days)
        return {"files": 0, "bytes": 0, "skipped": 0, "missing": False}

    monkeypatch.setattr(posix.tempprune, "prune_temp", fake_prune_temp)
    monkeypatch.setattr(posix.tempprune, "prune_targets", lambda ctx: [])
    monkeypatch.setattr(posix.caches, "purge", lambda ctx: {})
    monkeypatch.setattr(
        posix, "_ram_relief",
        lambda ctx: {"orphans": {"reclaimed_rss": 0}, "ollama": {"reclaimed_bytes": 0}},
    )
    ctx = RunContext(dry_run=True, quiet=True, log_path=tmp_path / "t.log")
    posix.run_tier(ctx, "scrub")
    assert calls == [7]  # the 14-day dust pass must not also run
    calls.clear()
    posix.run_tier(ctx, "dust")
    assert calls == [14]


def test_sizes_reports_unmeasured_existing_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(caches, "_discover_pythons", lambda: [])
    monkeypatch.setattr(
        caches.shutil, "which", lambda exe: "/usr/bin/pnpm" if exe == "pnpm" else None
    )
    monkeypatch.setattr(caches, "_query_cache_dir", lambda args: tmp_path)  # exists
    monkeypatch.setattr(caches, "_dir_size", lambda root, budget_seconds=10.0: None)  # timeout
    assert caches.sizes() == {"pnpm": None}


def test_sizes_omits_missing_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(caches, "_discover_pythons", lambda: [])
    monkeypatch.setattr(
        caches.shutil, "which", lambda exe: "/usr/bin/pnpm" if exe == "pnpm" else None
    )
    monkeypatch.setattr(caches, "_query_cache_dir", lambda args: tmp_path / "nope")
    assert caches.sizes() == {}


def test_dir_size_budget_exceeded_returns_none(monkeypatch, tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x")
    clock = iter([0.0, 100.0, 200.0])
    monkeypatch.setattr(caches.time, "monotonic", lambda: next(clock))
    assert caches._dir_size(tmp_path, budget_seconds=10.0) is None


def test_dir_size_ignores_symlinks(tmp_path):
    real = tmp_path / "real.bin"
    real.write_bytes(b"x" * 100)
    (tmp_path / "link.bin").symlink_to(real)
    assert caches._dir_size(tmp_path) == 100
