"""superclean command-line entry point.

  superclean              report (safe, read-only, no changes)
  superclean dust         tier 1  lightest, always-safe
  superclean sweep        tier 2  + orphan kill, RAM/VRAM relief
  superclean scrub        tier 3  + package caches, idle model unload, temp
  superclean wipe         tier 4  + heavy (browser/temp; Windows full deep-clean)
  superclean nuke         tier 5  destructive (Docker reset, Windows.old) [type NUKE]
  superclean report | ram | protected
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import psutil

from superclean import __version__, platform_backend, report as report_mod
from superclean.util import RunContext, data_dir

TIERS = ["dust", "sweep", "scrub", "wipe", "nuke"]
COMMANDS = ["report", "protected", "ram", *TIERS]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="superclean",
        description="Agentic-dev garbage collector: reclaim RAM, VRAM, and disk "
        "left by parallel dev work, without killing your active tools.",
    )
    p.add_argument(
        "command",
        nargs="?",
        default="report",
        choices=COMMANDS,
        help="what to run (default: report)",
    )
    p.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    p.add_argument("--yes", "-y", action="store_true", help="skip y/N prompts")
    p.add_argument("--i-know", action="store_true", help="with nuke: bypass the typed confirm")
    p.add_argument("--quiet", "-q", action="store_true", help="minimal console output")
    p.add_argument("--json", action="store_true", help="emit a JSON result, suppress human output")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p.add_argument("--force-unlock", action="store_true", help="override a stuck lockfile")
    p.add_argument("--log", help="override the log file path")
    p.add_argument("--version", action="version", version=f"superclean {__version__}")
    return p


def _acquire_lock(ctx) -> "object | None":
    lock = data_dir() / "superclean.lock"
    for _ in range(2):  # second pass after clearing a stale lock
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            try:
                existing = int(lock.read_text().strip())
            except (ValueError, OSError):
                existing = 0
            alive = existing > 0 and psutil.pid_exists(existing)
            if alive and not ctx.force_unlock:
                return None
            try:
                lock.unlink()
            except OSError:
                return None
            continue
        except OSError:
            return None
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return lock
    return None


def _release_lock(lock) -> None:
    if lock is None:
        return
    try:
        lock.unlink()
    except OSError:
        pass


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = RunContext(
        dry_run=args.dry_run,
        yes=args.yes,
        i_know=args.i_know,
        quiet=args.quiet,
        json=args.json,
        no_color=args.no_color,
        force_unlock=args.force_unlock,
        log_path=args.log,
    )
    cmd = args.command

    # Read-only commands: no lock needed.
    if cmd == "report":
        result = report_mod.run(ctx)
        return _finish(ctx, cmd, result, 0)
    if cmd == "protected":
        result = report_mod.list_protected(ctx)
        return _finish(ctx, cmd, result, 0)

    # Mutating commands (ram + tiers): acquire the single lock.
    lock = _acquire_lock(ctx)
    if lock is None:
        ctx.log("ERROR: another superclean run is in progress. Use --force-unlock.", "ERROR")
        return 1
    start = time.time()
    try:
        ctx.log("")
        ctx.log("==================== RUN START ====================", "HEAD")
        ctx.log(f"Command: {cmd}   DryRun: {ctx.dry_run}   PID: {os.getpid()}")
        if cmd == "ram":
            result = platform_backend.run_ram(ctx)
        else:
            result = platform_backend.run_tier(ctx, cmd)
        elapsed = time.time() - start
        ctx.log("")
        ctx.log("==================== RUN END ====================", "HEAD")
        ctx.log(f"Elapsed: {elapsed:.1f}s   Log: {ctx.log_path}")
        code = 3 if isinstance(result, dict) and result.get("exit_code") == 3 else 0
        return _finish(ctx, cmd, result, code)
    except Exception as exc:  # noqa: BLE001 - top-level guard, report and exit 3
        ctx.log(f"FATAL: {exc}", "ERROR")
        return _finish(ctx, cmd, {"error": str(exc)}, 3)
    finally:
        _release_lock(lock)


def _finish(ctx, cmd: str, result, code: int) -> int:
    if ctx.json:
        envelope = {
            "version": __version__,
            "platform": sys.platform,
            "command": cmd,
            "dry_run": ctx.dry_run,
            "result": result,
        }
        print(json.dumps(envelope, default=str, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
