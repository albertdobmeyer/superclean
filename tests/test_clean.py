"""The guided clean command: composition, confirmation gating, totals."""
from __future__ import annotations

from superclean import clean
from superclean.util import RunContext

_ORPHAN = {"pid": 1, "name": "node", "create_time": 1.0, "ppid": 1,
           "cmdline": "node server.js", "rss": 100}
_MODEL = {"name": "m", "size_bytes": 200, "expires_at": None}


def _stub(monkeypatch, calls, orphans_list, models):
    monkeypatch.setattr(clean.procs_mod, "snapshot", lambda: {})
    monkeypatch.setattr(clean.perimeter, "build_protected_pids", lambda procs=None: set())
    monkeypatch.setattr(clean.orphans, "find_orphans",
                        lambda protected, procs=None: orphans_list)
    monkeypatch.setattr(clean.ollama, "is_running", lambda: bool(models))
    monkeypatch.setattr(clean.ollama, "loaded_models", lambda: models)
    monkeypatch.setattr(
        clean.orphans, "kill_orphans",
        lambda found, ctx: (calls.append("kill"),
                            {"killed": 1, "failed": 0, "skipped": 0, "reclaimed_rss": 100})[1])
    monkeypatch.setattr(
        clean.ollama, "idle_unload",
        lambda ctx: (calls.append("unload"), {"unloaded": 1, "reclaimed_bytes": 200})[1])
    monkeypatch.setattr(clean.caches, "sizes", lambda: {"pip": 50})
    monkeypatch.setattr(
        clean.caches, "purge",
        lambda ctx: (calls.append("purge"), {"pip": {"ok": True, "freed_bytes": 50}})[1])
    monkeypatch.setattr(
        clean.tempprune, "preview_temp",
        lambda days=7: {"files": 2, "bytes": 30, "skipped": 0, "missing": False})
    monkeypatch.setattr(
        clean.tempprune, "prune_temp",
        lambda ctx, days: (calls.append(f"temp{days}"),
                           {"files": 2, "bytes": 30, "skipped": 0, "missing": False})[1])
    monkeypatch.setattr(clean.tempprune, "prune_targets",
                        lambda ctx: (calls.append("targets"), [])[1])


def test_yes_runs_all_groups_and_totals(tmp_path, monkeypatch):
    calls = []
    _stub(monkeypatch, calls, [_ORPHAN], [_MODEL])
    ctx = RunContext(yes=True, quiet=True, log_path=tmp_path / "t.log")
    result = clean.run(ctx)
    assert calls == ["kill", "unload", "purge", "temp7", "targets"]
    assert result["reclaimed"] == {"ram_bytes": 300, "disk_bytes": 80}


def test_declining_everything_changes_nothing(tmp_path, monkeypatch):
    calls = []
    _stub(monkeypatch, calls, [_ORPHAN], [_MODEL])
    # quiet without --yes: ctx.confirm is always False
    ctx = RunContext(quiet=True, log_path=tmp_path / "t.log")
    result = clean.run(ctx)
    assert calls == ["targets"]  # targets group delegates its own per-target confirms
    for key in ("orphans", "ollama", "caches", "temp_deep"):
        assert key not in result
    assert result["reclaimed"] == {"ram_bytes": 0, "disk_bytes": 0}


def test_clean_with_nothing_to_do(tmp_path, monkeypatch):
    calls = []
    _stub(monkeypatch, calls, [], [])
    monkeypatch.setattr(clean.caches, "sizes", lambda: {})
    monkeypatch.setattr(
        clean.tempprune, "preview_temp",
        lambda days=7: {"files": 0, "bytes": 0, "skipped": 0, "missing": False})
    ctx = RunContext(yes=True, quiet=True, log_path=tmp_path / "t.log")
    result = clean.run(ctx)
    assert calls == ["targets"]
    assert result["reclaimed"] == {"ram_bytes": 0, "disk_bytes": 0}
