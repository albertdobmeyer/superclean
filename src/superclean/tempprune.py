"""Age-out of temp scratch and user-defined target folders (targets.conf)."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from superclean import config
from superclean.util import friendly_size


def _age_out(root: Path, days: int, ctx) -> dict:
    """Delete files older than `days` under root. Honors dry-run. Returns stats."""
    if not root.exists():
        return {"files": 0, "bytes": 0, "skipped": 0, "missing": True}
    cutoff = time.time() - days * 86400
    n_files = n_bytes = n_skip = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            fp = Path(dirpath) / name
            try:
                st = fp.stat()
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
    stats = _age_out(Path(tempfile.gettempdir()), days, ctx)
    verb = "Would reclaim" if ctx.dry_run else "Reclaimed"
    ctx.log(
        f"  Files: {stats['files']}  {verb}: {friendly_size(stats['bytes'])}  "
        f"Skipped: {stats['skipped']}",
        "OK",
    )
    return stats


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
