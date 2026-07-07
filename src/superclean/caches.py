"""Package-manager cache purge: pip, npm, uv, pnpm, yarn.

Cross-platform and conservative: each tool runs only if it is on PATH, and
every action is skipped under --dry-run. These caches are global (not scoped to
one project), so this lives at the scrub tier, never in the no-arg default.
Reclaim is measured by sizing each tool's cache dir before and after.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from superclean.util import friendly_size

_TIMEOUT = 120
_QUERY_TIMEOUT = 15

# Substrings that mean "nothing to purge", which some tools report with a
# non-zero exit code (pip does). Treated as success.
_EMPTY_OK_MARKERS = ("no matching packages",)


def _discover_pythons() -> list[str]:
    found = [sys.executable]
    for name in ("python3", "python"):
        path = shutil.which(name)
        if path:
            found.append(path)
    # Preserve order, drop duplicates.
    seen = set()
    out = []
    for p in found:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _query_cache_dir(args: list[str]) -> "Path | None":
    """Ask a tool where its cache lives. None when unknown."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=_QUERY_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or "").strip().splitlines()
    if not lines:
        return None
    p = Path(lines[-1].strip())
    return p if p.is_absolute() else None


def _dir_size(root: "Path | None", budget_seconds: float = 10.0) -> "int | None":
    """Total bytes under root via scandir. None if missing or over budget."""
    if root is None or not root.exists():
        return None
    deadline = time.monotonic() + budget_seconds
    total = 0
    stack = [root]
    while stack:
        if time.monotonic() > deadline:
            return None
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _run(ctx, label: str, args: list[str]) -> bool:
    if ctx.dry_run:
        ctx.log(f"  [DRY] Would run: {' '.join(args)}", "DRY")
        return True
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ctx.log(f"  {label}: failed ({exc}).", "WARN")
        return False
    if proc.returncode != 0:
        output = ((proc.stderr or "") + (proc.stdout or "")).lower()
        if any(marker in output for marker in _EMPTY_OK_MARKERS):
            ctx.log(f"  {label}: already empty.", "OK")
            return True
        tail = ((proc.stderr or proc.stdout or "").strip().splitlines() or [f"exit {proc.returncode}"])[-1]
        ctx.log(f"  {label}: failed ({tail}).", "WARN")
        return False
    ctx.log(f"  {label}: done.", "OK")
    return True


# (label, exe, cache-dir query args, clean args). pip is handled separately
# because it runs per-interpreter.
_TOOLS = (
    ("npm", "npm", ["config", "get", "cache"], ["cache", "clean", "--force"]),
    ("uv", "uv", ["cache", "dir"], ["cache", "clean"]),
    ("pnpm", "pnpm", ["store", "path"], ["store", "prune"]),
    ("yarn", "yarn", ["cache", "dir"], ["cache", "clean"]),
)


def sizes() -> dict:
    """label -> cache bytes for tools on PATH. Read-only preview.

    A value of None means the cache dir exists but could not be sized within
    the walk budget (typically: it is huge). Tools whose cache dir cannot be
    located, or does not exist yet, are omitted entirely.
    """
    out: dict = {}
    pythons = _discover_pythons()
    if pythons:
        cache_dir = _query_cache_dir([pythons[0], "-m", "pip", "cache", "dir"])
        if cache_dir is not None and cache_dir.exists():
            out["pip"] = _dir_size(cache_dir)
    for label, exe, dir_args_tail, _clean_args in _TOOLS:
        path = shutil.which(exe)
        if not path:
            continue
        cache_dir = _query_cache_dir([path, *dir_args_tail])
        if cache_dir is None or not cache_dir.exists():
            continue
        out[label] = _dir_size(cache_dir)
    return out


def _purge_one(ctx, label: str, dir_args: "list[str] | None", clean_args: list[str]) -> dict:
    """Measure -> purge -> re-measure a single tool. Honors dry-run."""
    cache_dir = _query_cache_dir(dir_args) if dir_args else None
    before = _dir_size(cache_dir)
    if ctx.dry_run:
        if before:
            ctx.log(f"  [DRY] {label}: ~{friendly_size(before)} in cache; would purge.", "DRY")
        else:
            ctx.log(f"  [DRY] Would run: {' '.join(clean_args)}", "DRY")
        return {"ok": True, "freed_bytes": before or 0}
    ok = _run(ctx, label, clean_args)
    after = _dir_size(cache_dir)
    freed = max(0, before - after) if before is not None and after is not None else 0
    if freed:
        ctx.log(f"  {label}: freed {friendly_size(freed)}.", "OK")
    return {"ok": ok, "freed_bytes": freed}


def purge(ctx) -> dict:
    """Purge all available package-manager caches. Honors dry-run. Measured."""
    results: dict = {}

    ctx.log("")
    ctx.log("== pip cache purge (all Pythons) ==", "HEAD")
    pythons = _discover_pythons()
    if not pythons:
        ctx.log("  No Python interpreters found. Skip.", "SKIP")
    ok_all = True
    freed = 0
    seen_dirs: set = set()
    for py in pythons:
        cache_dir = _query_cache_dir([py, "-m", "pip", "cache", "dir"])
        key = str(cache_dir) if cache_dir else py
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        one = _purge_one(
            ctx, f"pip ({py})", [py, "-m", "pip", "cache", "dir"],
            [py, "-m", "pip", "cache", "purge"],
        )
        ok_all = ok_all and one["ok"]
        freed += one["freed_bytes"]
    results["pip"] = {"ok": ok_all, "freed_bytes": freed}

    for label, exe, dir_args_tail, clean_args_tail in _TOOLS:
        ctx.log("")
        ctx.log(f"== {label} cache clean ==", "HEAD")
        path = shutil.which(exe)
        if not path:
            ctx.log(f"  {label} not on PATH. Skip.", "SKIP")
            results[label] = {"ok": False, "freed_bytes": 0}
            continue
        results[label] = _purge_one(ctx, label, [path, *dir_args_tail], [path, *clean_args_tail])

    return results
