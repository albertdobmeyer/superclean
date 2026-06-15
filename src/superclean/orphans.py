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

CANDIDATE_NAMES = {
    "node", "python", "python3", "tsx", "ts-node", "esbuild", "vite",
    "next-server", "webpack", "pnpm", "yarn", "rollup", "bun", "deno",
}

_MIN_AGE_SECONDS = 60
_LAUNCHER_RE = re.compile(r"(?i)\b(uvx|pipx|superclean)\b")


def _norm(name: str | None) -> str:
    if not name:
        return ""
    return name.lower().removesuffix(".exe")


def find_orphans(protected: set[int]) -> list[dict]:
    """Return candidate orphan processes. Read-only; never kills."""
    now = time.time()
    procs: dict[int, dict] = {}
    for p in psutil.process_iter(["pid", "name", "ppid", "cmdline", "create_time"]):
        try:
            procs[p.info["pid"]] = p.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue

    orphans = []
    for pid, info in procs.items():
        if _norm(info.get("name")) not in CANDIDATE_NAMES:
            continue
        if pid in protected or pid == os.getpid():
            continue

        ctime = info.get("create_time")
        if ctime is None or (now - ctime) < _MIN_AGE_SECONDS:
            continue

        cmdline = " ".join(info.get("cmdline") or [])
        if _LAUNCHER_RE.search(cmdline):
            continue

        ppid = info.get("ppid")
        parent_gone = False
        if ppid in (0, 1) or ppid is None:
            parent_gone = True
        elif ppid not in procs:
            parent_gone = True
        else:
            parent_ctime = procs[ppid].get("create_time")
            if parent_ctime is not None and parent_ctime > ctime:
                parent_gone = True  # parent PID was reused after our process started

        if parent_gone:
            short = cmdline if len(cmdline) <= 140 else cmdline[:140] + "..."
            orphans.append(
                {
                    "pid": pid,
                    "name": info.get("name"),
                    "create_time": ctime,
                    "ppid": ppid,
                    "cmdline": short,
                }
            )
    return orphans


def kill_orphans(orphans: list[dict], ctx) -> dict:
    """Kill confirmed orphans with kill-time re-validation. Honors dry-run."""
    if not orphans:
        ctx.log("  No orphan dev processes found.", "OK")
        return {"killed": 0, "failed": 0, "skipped": 0}

    ctx.log(f"  Found {len(orphans)} orphan dev process(es):", "INFO")
    for o in orphans:
        tag = "[DRY] " if ctx.dry_run else ""
        ctx.log(f"    {tag}PID {o['pid']:<7} {_norm(o['name']):<12} {o['cmdline']}", "INFO")

    if ctx.dry_run:
        return {"killed": 0, "failed": 0, "skipped": 0}

    killed = failed = skipped = 0
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

    return {"killed": killed, "failed": failed, "skipped": skipped}
