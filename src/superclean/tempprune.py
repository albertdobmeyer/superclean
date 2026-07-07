"""Age-out of temp scratch and user-defined target folders (targets.conf)."""

from __future__ import annotations

import fnmatch
import os
import stat
import tempfile
import time
from pathlib import Path

from superclean import config
from superclean.util import friendly_size


# Directories under the system temp root that belong to LIVE sessions, not
# garbage: sockets and scratch for X11, SSH agents, tmux, systemd services,
# audio/dbus, and AI-agent session scratchpads. Age says nothing about
# liveness for these, so the temp pruner never descends into them.
_LIVE_SESSION_GLOBS = (
    ".x11-unix", ".ice-unix", ".font-unix", "ssh-*", "tmux-*",
    "systemd-private-*", "snap-private-tmp", "pulse-*", "dbus-*", "claude-*",
)


def _is_live_session_dir(name: str) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatch(n, g) for g in _LIVE_SESSION_GLOBS)


def _age_out(root: Path, days: int, ctx, protect_session_dirs: bool = False) -> dict:
    """Delete regular files older than `days` under root. Honors dry-run.

    Safety: only regular files (sockets, FIFOs, and symlinks are never
    touched), and with protect_session_dirs the live-session directories in
    _LIVE_SESSION_GLOBS are not entered at all.
    """
    if not root.exists():
        return {"files": 0, "bytes": 0, "skipped": 0, "missing": True}
    cutoff = time.time() - days * 86400
    n_files = n_bytes = n_skip = 0
    for dirpath, dirs, files in os.walk(root):
        if protect_session_dirs:
            dirs[:] = [d for d in dirs if not _is_live_session_dir(d)]
        for name in files:
            fp = Path(dirpath) / name
            try:
                st = fp.lstat()
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_mtime >= cutoff:
                    continue
                size = st.st_size
                if not ctx.dry_run:
                    fp.unlink()
                n_files += 1
                n_bytes += size
            except OSError:
                n_skip += 1
    return {"files": n_files, "bytes": n_bytes, "skipped": n_skip, "missing": False}


def prune_temp(ctx, days: int = 7) -> dict:
    """Age out the system temp directory."""
    ctx.log("")
    ctx.log(f"== temp files older than {days} days ==", "HEAD")
    stats = _age_out(Path(tempfile.gettempdir()), days, ctx, protect_session_dirs=True)
    verb = "Would reclaim" if ctx.dry_run else "Reclaimed"
    ctx.log(
        f"  Files: {stats['files']}  {verb}: {friendly_size(stats['bytes'])}  "
        f"Skipped: {stats['skipped']}",
        "OK",
    )
    return stats


def preview_temp(days: int = 7) -> dict:
    """Measure what prune_temp would reclaim, silently. Read-only."""
    return _age_out(
        Path(tempfile.gettempdir()), days, _DryProbe(None), protect_session_dirs=True
    )


def prune_targets(ctx) -> list[dict]:
    """Age out each folder configured in targets.conf (confirm unless --yes)."""
    ctx.log("")
    ctx.log("== Optional: user-defined output folders (targets.conf) ==", "HEAD")
    tgts = config.targets()
    if not tgts:
        ctx.log("  None configured (see targets.conf). Skip.", "SKIP")
        return []

    results = []
    for path, days, label in tgts:
        root = Path(path)
        if not root.exists():
            ctx.log(f"  {label}: not found, skip.", "SKIP")
            continue
        # Size first so the user can decide.
        preview = _age_out(root, days, _DryProbe(ctx))
        if preview["files"] == 0:
            ctx.log(f"  {label}: nothing to clean.", "OK")
            continue
        if not ctx.confirm(
            f"  Delete {preview['files']} files in {label} "
            f"({friendly_size(preview['bytes'])})?"
        ):
            ctx.log("  Skipped.", "SKIP")
            continue
        stats = _age_out(root, days, ctx)
        verb = "Would delete" if ctx.dry_run else "Deleted"
        ctx.log(f"  {verb} {stats['files']} files ({friendly_size(stats['bytes'])}).", "OK")
        results.append({"label": label, **stats})
    return results


class _DryProbe:
    """Wraps a RunContext to force dry-run for the size-preview pass only."""

    def __init__(self, ctx):
        self.dry_run = True
        self._ctx = ctx

    def log(self, *_args, **_kwargs):
        pass
