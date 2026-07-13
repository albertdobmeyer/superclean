"""superclean command-line entry point.

  superclean              report (safe, read-only, no changes)
  superclean clean        guided cleanup: diagnose, confirm each group, execute
  superclean dust         tier 1  lightest, always-safe (temp >14d)
  superclean sweep        tier 2  + orphan kill, RAM/VRAM relief
  superclean scrub        tier 3  + package caches, temp >7d, targets.conf
  superclean wipe         tier 4  + heavy (browser/temp; Windows full deep-clean)
  superclean nuke         tier 5  destructive (Docker reset, Windows.old) [type NUKE]
  superclean report | ram | protected | init | last
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from superclean import __version__, clean as clean_mod, config, platform_backend, report as report_mod
from superclean.util import RunContext, data_dir

TIERS = ["dust", "sweep", "scrub", "wipe", "nuke"]
COMMANDS = ["report", "protected", "ram", "clean", "init", "last", *TIERS]

_EPILOG = """\
commands:
  (none) / report   safe read-only report: shows what could be reclaimed, changes nothing
  clean             guided cleanup: diagnose, propose actions, confirm each group
  ram               RAM/VRAM relief only: kill orphaned dev processes, unload idle models
  protected         show every process name superclean will never touch
  init              copy the example config files into your user config dir
  last              show the previous mutating run from the logs

the cleanup ladder (each tier includes everything lighter):
  dust    tier 1    lightest, always safe: temp scratch older than 14 days
  sweep   tier 2    + kill orphaned dev processes, RAM/VRAM relief
  scrub   tier 3    + package caches (pip/npm/uv/pnpm/yarn), temp >7d, targets.conf
  wipe    tier 4    + heavy: browser caches, full temp (Windows deep-clean backend)
  nuke    tier 5    + destructive: Docker reset, Windows.old (Windows)  [type NUKE to confirm]

start here:
  superclean                    see what is going on (changes nothing)
  superclean clean              guided cleanup with per-group confirmation
  superclean sweep --dry-run    preview a tier, then run it for real

config files (scaffold with `superclean init`): protect.conf, targets.conf, services.conf
logs: one file per day in your user data dir; `superclean last` replays the newest run
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="superclean",
        description="Agentic-dev garbage collector: reclaim RAM, VRAM, and disk\n"
        "left by parallel dev work, without killing your active tools.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "command",
        nargs="?",
        default="report",
        choices=COMMANDS,
        metavar="command",
        help="what to run (default: report); every command is described below",
    )
    p.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    p.add_argument("--yes", "-y", action="store_true", help="skip y/N prompts")
    p.add_argument("--i-know", action="store_true", help="with nuke: bypass the typed confirm")
    p.add_argument("--quiet", "-q", action="store_true", help="minimal console output")
    p.add_argument("--json", action="store_true", help="emit a JSON result, suppress human output")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p.add_argument(
        "--force-unlock",
        action="store_true",
        help="run even while another superclean holds the lock (rarely needed; unsafe)",
    )
    p.add_argument("--log", help="override the log file path")
    p.add_argument("--version", action="version", version=f"superclean {__version__}")
    return p


# Windows byte-range locks are mandatory: a locked byte cannot be read by anyone
# else. Lock a sentinel byte well past the PID text so the file stays readable.
_LOCK_BYTE = 1024

if sys.platform == "win32":
    import msvcrt

    def _os_try_lock(fd) -> bool:
        try:
            os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _os_unlock(fd) -> None:
        try:
            os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _os_try_lock(fd) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _os_unlock(fd) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


_LOCK_GRACE_SECONDS = 1.0
_LOCK_POLL_SECONDS = 0.01


def _try_lock_with_grace(fd) -> bool:
    """Take the OS lock, tolerating a dead holder's lingering one.

    Windows frees a terminated process's file locks asynchronously, so the lock of a
    run that just crashed can outlive it by a few milliseconds. Failing on the first
    attempt would tell whoever re-runs that a run is "in progress" when none is - the
    phantom stuck lock that --force-unlock existed to work around. Poll briefly; a
    genuinely live holder still loses nothing but a moment on an error path.
    """
    deadline = time.monotonic() + _LOCK_GRACE_SECONDS
    while True:
        if _os_try_lock(fd):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_LOCK_POLL_SECONDS)


class _Lock:
    """A held run-lock: the open fd carrying the OS lock, plus its path."""

    __slots__ = ("path", "fd", "held")

    def __init__(self, path, fd, held: bool):
        self.path = path
        self.fd = fd
        self.held = held


def _acquire_lock(ctx) -> "_Lock | None":
    """Single-run mutex, arbitrated by the kernel rather than by PID inspection.

    The OS drops the lock when the fd closes - including on crash or SIGKILL - so
    a lock can never go stale and nothing has to judge whether some PID is still
    alive. That judgement, and the unlink-then-recreate dance it required, was the
    source of the reclaim race in #19; both are gone. The PID is still written to
    the file, but purely as a human-readable breadcrumb, never as lock state.

    The lockfile is deliberately never unlinked. Removing a path that another
    process may already hold open would let two runs end up locking different
    inodes under the same name - reintroducing the very race this replaces.
    """
    path = data_dir() / "superclean.lock"
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return None

    held = _try_lock_with_grace(fd)
    if not held and not ctx.force_unlock:
        os.close(fd)
        return None

    try:  # breadcrumb for humans reading the file; not consulted by the lock
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode())
    except OSError:
        pass
    return _Lock(path, fd, held)


def _release_lock(lock) -> None:
    if lock is None:
        return
    if lock.held:
        _os_unlock(lock.fd)
    try:
        os.close(lock.fd)
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
    try:
        if cmd == "report":
            result = report_mod.run(ctx)
            return _finish(ctx, cmd, result, 0)
        if cmd == "protected":
            result = report_mod.list_protected(ctx)
            return _finish(ctx, cmd, result, 0)
        if cmd == "init":
            result = config.init_user_conf()
            ctx.log(f"Config dir: {result['dir']}")
            levels = {"created": "OK", "exists": "SKIP", "missing-example": "WARN"}
            for name, status in result["files"].items():
                ctx.log(f"  {name:<15} {status}", levels.get(status, "ERROR"))
            failed = "error" in result or "write-failed" in result["files"].values()
            if failed and result.get("error"):
                ctx.log(f"  {result['error']}", "ERROR")
            return _finish(ctx, cmd, result, 3 if failed else 0)
        if cmd == "last":
            result = report_mod.last_run(ctx)
            return _finish(ctx, cmd, result, 0)
    except Exception as exc:  # noqa: BLE001 - top-level guard, report and exit 3
        ctx.log(f"FATAL: {exc}", "ERROR")
        return _finish(ctx, cmd, {"error": str(exc)}, 3)

    # Mutating commands (ram + tiers): acquire the single lock.
    lock = _acquire_lock(ctx)
    if lock is None:
        ctx.log("ERROR: another superclean run is in progress. Use --force-unlock.", "ERROR")
        return _finish(ctx, cmd, {"error": "another superclean run is in progress (use --force-unlock)"}, 1)
    start = time.time()
    try:
        ctx.log("")
        ctx.log("==================== RUN START ====================", "HEAD")
        ctx.log(f"Command: {cmd}   DryRun: {ctx.dry_run}   PID: {os.getpid()}")
        if cmd == "ram":
            result = platform_backend.run_ram(ctx)
        elif cmd == "clean":
            result = clean_mod.run(ctx)
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
