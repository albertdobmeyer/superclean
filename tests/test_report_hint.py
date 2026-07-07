"""The human report ends with a discoverability hint; json/quiet stay clean."""
from __future__ import annotations

from superclean import report
from superclean.util import RunContext


def test_hint_present_in_human_output(tmp_path, capsys):
    ctx = RunContext(log_path=tmp_path / "t.log")
    report.run(ctx)
    out = capsys.readouterr().out
    assert "superclean -h" in out
    assert "superclean clean" in out


def test_hint_absent_in_json_mode(tmp_path, capsys):
    ctx = RunContext(json=True, log_path=tmp_path / "t.log")
    report.run(ctx)
    assert "superclean clean" not in capsys.readouterr().out
