"""Package-manager cache purge: pip, npm, uv, pnpm, yarn.

Cross-platform and conservative: each tool runs only if it is on PATH, and
every action is skipped under --dry-run. These caches are global (not scoped to
one project), so this lives at the scrub tier, never in the no-arg default.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

_TIMEOUT = 120


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


def _run(ctx, label: str, args: list[str]) -> bool:
    if ctx.dry_run:
        ctx.log(f"  [DRY] Would run: {' '.join(args)}", "DRY")
        return True
    try:
        subprocess.run(args, capture_output=True, timeout=_TIMEOUT, check=False)
        ctx.log(f"  {label}: done.", "OK")
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        ctx.log(f"  {label}: failed ({exc}).", "WARN")
        return False


def purge(ctx) -> dict:
    """Purge all available package-manager caches. Honors dry-run."""
    results = {}

    ctx.log("")
    ctx.log("== pip cache purge (all Pythons) ==", "HEAD")
    pythons = _discover_pythons()
    if not pythons:
        ctx.log("  No Python interpreters found. Skip.", "SKIP")
    for py in pythons:
        _run(ctx, f"pip ({py})", [py, "-m", "pip", "cache", "purge"])
    results["pip"] = len(pythons)

    for label, exe, args in (
        ("npm", "npm", ["cache", "clean", "--force"]),
        ("uv", "uv", ["cache", "clean"]),
        ("pnpm", "pnpm", ["store", "prune"]),
        ("yarn", "yarn", ["cache", "clean"]),
    ):
        ctx.log("")
        ctx.log(f"== {label} cache clean ==", "HEAD")
        path = shutil.which(exe)
        if not path:
            ctx.log(f"  {label} not on PATH. Skip.", "SKIP")
            results[label] = False
            continue
        results[label] = _run(ctx, label, [path, *args])

    return results
