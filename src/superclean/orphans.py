"""Smart orphan dev-process detection and removal.

Ported from the PowerShell backend (core/orphans.ps1). On Windows the PS backend
handles this; the Python implementation runs on macOS/Linux, where an orphaned
child is reparented to init (ppid 1), which is the primary "parent is gone"
signal here, alongside a missing parent or a PID-reuse mismatch.

Safety: a candidate is killed only if it is NOT in the protected set, is at
least 60s old, looks genuinely parentless, and re-validates (same pid + same
start time) immediately before the kill. Anything uncertain is skipped.
"""

from __future__ import annotations

import os
import re
import time

import psutil

from superclean.procs import norm as _norm, snapshot as _snapshot

CANDIDATE_NAMES = {
    "node", "python", "python3", "tsx", "ts-node", "esbuild", "vite",
    "next-server", "webpack", "pnpm", "yarn", "rollup", "bun", "deno",
}

# Browsers are orphan candidates ONLY in headless (Playwright/Puppeteer) form;
# a user's real browser window never matches because it lacks --headless.
HEADLESS_BROWSER_NAMES = {
    "chrome", "chromium", "chromium-browser", "headless_shell", "firefox", "msedge",
}

_MIN_AGE_SECONDS = 60
_LAUNCHER_RE = re.compile(r"(?i)\b(uvx|pipx|superclean)\b")


def _is_candidate(name: "str | None", cmdline: str) -> bool:
    n = _norm(name)
    if n in CANDIDATE_NAMES:
        return True
    return n in HEADLESS_BROWSER_NAMES and "--headless" in cmdline


def _parent_gone(info: dict, procs: "dict[int, dict]") -> bool:
    """True when this process's original parent is no longer there.

    Signals: classic init/missing-parent/PID-reuse, plus the modern-Linux
    case where an orphan is reparented to the user's `systemd --user`
    subreaper (name systemd, not PID 1, same user). Deliberate user services
    that should survive belong in protect.conf.
    """
    ppid = info.get("ppid")
    if ppid is None or ppid in (0, 1):
        return True
    parent = procs.get(ppid)
    if parent is None:
        return True
    p_ctime = parent.get("create_time")
    ctime = info.get("create_time")
    if p_ctime is not None and ctime is not None and p_ctime > ctime:
        return True  # parent PID was reused after this process started
    if (
        _norm(parent.get("name")) == "systemd"
        and ppid != 1
        and parent.get("username")
        and parent.get("username") == info.get("username")
    ):
        return True
    return False


def find_orphans(protected: set[int], procs: "dict[int, dict] | None" = None) -> list[dict]:
    """Return candidate orphan processes. Read-only; never kills."""
    now = time.time()
    procs = procs if procs is not None else _snapshot()

    orphans = []
    for pid, info in procs.items():
        cmdline = " ".join(info.get("cmdline") or [])
        if not _is_candidate(info.get("name"), cmdline):
            continue
        if pid in protected or pid == os.getpid():
            continue

        ctime = info.get("create_time")
        if ctime is None or (now - ctime) < _MIN_AGE_SECONDS:
            continue

        if _LAUNCHER_RE.search(cmdline):
            continue

        if _parent_gone(info, procs):
            mem = info.get("memory_info")
            short = cmdline if len(cmdline) <= 140 else cmdline[:140] + "..."
            orphans.append(
                {
                    "pid": pid,
                    "name": info.get("name"),
                    "create_time": ctime,
                    "ppid": info.get("ppid"),
                    "cmdline": short,
                    "rss": mem.rss if mem else 0,
                }
            )
    return orphans


def kill_orphans(orphans: list[dict], ctx) -> dict:
    """Kill confirmed orphans with kill-time re-validation. Honors dry-run."""
    if not orphans:
        ctx.log("  No orphan dev processes found.", "OK")
        return {"killed": 0, "failed": 0, "skipped": 0, "reclaimed_rss": 0}

    ctx.log(f"  Found {len(orphans)} orphan dev process(es):", "INFO")
    for o in orphans:
        tag = "[DRY] " if ctx.dry_run else ""
        ctx.log(f"    {tag}PID {o['pid']:<7} {_norm(o['name']):<12} {o['cmdline']}", "INFO")

    if ctx.dry_run:
        reclaimed = sum(o.get("rss") or 0 for o in orphans)
        return {"killed": 0, "failed": 0, "skipped": 0, "reclaimed_rss": reclaimed}

    killed = failed = skipped = 0
    reclaimed = 0
    for o in orphans:
        pid = o["pid"]
        if pid == os.getpid():
            skipped += 1
            continue
        try:
            proc = psutil.Process(pid)
            # Re-validate identity: same pid AND same start time (guards PID reuse).
            if abs(proc.create_time() - o["create_time"]) > 0.001:
                ctx.log(f"    PID {pid} reused by another process, skipping.", "SKIP")
                skipped += 1
                continue
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
            killed += 1
            reclaimed += o.get("rss") or 0
            ctx.log(f"    Killed PID {pid}", "OK")
        except psutil.NoSuchProcess:
            ctx.log(f"    PID {pid} already gone, skipping.", "SKIP")
            skipped += 1
        except psutil.AccessDenied:
            ctx.log(f"    No permission to kill PID {pid}, skipping.", "WARN")
            failed += 1
        except psutil.Error as exc:
            ctx.log(f"    Failed to kill PID {pid}: {exc}", "ERROR")
            failed += 1

    return {"killed": killed, "failed": failed, "skipped": skipped, "reclaimed_rss": reclaimed}
