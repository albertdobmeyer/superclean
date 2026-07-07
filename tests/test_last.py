"""`superclean last`: replay the newest mutating-run block from the logs."""
from __future__ import annotations

from superclean import report
from superclean.util import RunContext

_BLOCK_OLD = """\
[2026-07-06 09:00:00] [HEAD] ==================== RUN START ====================
[2026-07-06 09:00:00] [INFO] Command: dust   DryRun: False   PID: 111
[2026-07-06 09:00:01] [HEAD] ==================== RUN END ====================
[2026-07-06 09:00:01] [INFO] Elapsed: 0.5s   Log: /x
"""

_BLOCK_NEW = """\
[2026-07-07 10:00:00] [HEAD] ==================== RUN START ====================
[2026-07-07 10:00:00] [INFO] Command: sweep   DryRun: True   PID: 222
[2026-07-07 10:00:02] [HEAD] ==================== RUN END ====================
[2026-07-07 10:00:02] [INFO] Elapsed: 1.6s   Log: /x
"""


def _ctx(tmp_path):
    return RunContext(quiet=True, log_path=tmp_path / "out.log")


def test_last_returns_newest_block(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean-2026-07-06.log").write_text(_BLOCK_OLD)
    (tmp_path / "superclean-2026-07-07.log").write_text(_BLOCK_OLD + _BLOCK_NEW)
    result = report.last_run(_ctx(tmp_path))
    assert result["log"].endswith("superclean-2026-07-07.log")
    assert any("Command: sweep" in ln for ln in result["lines"])
    assert not any("Command: dust" in ln for ln in result["lines"])
    assert "Elapsed: 1.6s" in result["lines"][-1]


def test_last_skips_files_without_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "data_dir", lambda: tmp_path)
    (tmp_path / "superclean-2026-07-06.log").write_text(_BLOCK_OLD)
    (tmp_path / "superclean-2026-07-07.log").write_text("[ts] [INFO] report only, no runs\n")
    result = report.last_run(_ctx(tmp_path))
    assert result["log"].endswith("superclean-2026-07-06.log")
    assert any("Command: dust" in ln for ln in result["lines"])


def test_last_with_no_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "data_dir", lambda: tmp_path)
    result = report.last_run(_ctx(tmp_path))
    assert result == {"log": None, "lines": []}


def test_repeat_last_same_day_is_stable(tmp_path, monkeypatch, capsys):
    # last's own output must not poison the log file it scans: a second
    # same-day invocation logging into the SAME day file must find the
    # original run, not its own echo.
    monkeypatch.setattr(report, "data_dir", lambda: tmp_path)
    day = tmp_path / "superclean-2026-07-07.log"
    day.write_text(_BLOCK_NEW)
    ctx = RunContext(log_path=day)
    first = report.last_run(ctx)
    second = report.last_run(ctx)
    assert second["lines"] == first["lines"]
    assert any("Command: sweep" in ln for ln in second["lines"])


def test_log_to_file_false_prints_but_does_not_append(tmp_path, capsys):
    ctx = RunContext(log_path=tmp_path / "l.log")
    ctx.log("console only", to_file=False)
    ctx.log("both")
    text = (tmp_path / "l.log").read_text()
    assert "both" in text
    assert "console only" not in text
    out = capsys.readouterr().out
    assert "console only" in out
