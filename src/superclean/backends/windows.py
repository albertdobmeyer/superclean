"""Windows deep-clean backend: delegate a tier to the bundled PowerShell tool.

On Windows the proven PowerShell backend already performs orphan kill, cache
purge, idle-model unload, standby flush, working-set trim, browser/temp caches,
Docker reset, and Windows.old removal. The cross-platform CLI maps a tier to the
matching PS flag and shells out, owning the single lockfile (passes --no-lock).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from superclean import config

# tier / mode name -> PowerShell flag
_FLAG = {
    "dust": "--dust",
    "sweep": "--sweep",
    "scrub": "--scrub",
    "wipe": "--wipe",
    "nuke": "--nuke",
    "ram": "--ram",
    "report": "--report",
    "protected": "--list-protected",
}


def _find_ps1() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "_backend" / "windows" / "superclean.ps1",  # installed wheel
        here.parents[3] / "windows" / "superclean.ps1",               # dev checkout
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def run_tier(ctx, tier: str) -> dict:
    """Invoke the PowerShell backend for the given tier/mode."""
    flag = _FLAG.get(tier)
    if flag is None:
        ctx.log(f"  Unknown tier '{tier}' for the Windows backend.", "ERROR")
        return {"invoked": False, "exit_code": 2}

    ps1 = _find_ps1()
    if ps1 is None:
        ctx.log("  Windows backend (superclean.ps1) not found.", "ERROR")
        return {"invoked": False, "exit_code": 3}

    shell = _powershell()
    if shell is None:
        ctx.log("  Neither pwsh nor powershell found on PATH.", "ERROR")
        return {"invoked": False, "exit_code": 3}

    config.export_conf_dir_env()

    args = [
        shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
        flag, "--no-color", "--no-lock", "--log", str(ctx.log_path),
    ]
    if ctx.dry_run:
        args.append("--dry-run")
    if ctx.yes:
        args.append("--yes")
    if ctx.i_know:
        args.append("--i-know")
    if ctx.quiet or ctx.json:
        args.append("--quiet")

    if ctx.json:
        # Capture so we do not interleave PS text into the JSON stream.
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
        return {"invoked": True, "exit_code": proc.returncode, "stdout": proc.stdout}

    # Inherit stdio so PS output streams live and the NUKE prompt works.
    ctx.log("")
    ctx.log("== windows deep-clean (PowerShell backend) ==", "HEAD")
    proc = subprocess.run(args, check=False)
    return {"invoked": True, "exit_code": proc.returncode}
