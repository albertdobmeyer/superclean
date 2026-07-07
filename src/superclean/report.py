"""Read-only diagnostic. Shows what superclean could reclaim; changes nothing."""

from __future__ import annotations

import platform
import sys
import urllib.error
import urllib.request

import psutil

from superclean import (
    config, gpu, ollama, orphans, perimeter, ports as ports_mod, procs as procs_mod,
)
from superclean.util import data_dir, friendly_size

_SKIP_FSTYPES = {"squashfs", "iso9660", "erofs"}


def _keep_partition(part) -> bool:
    """Real, writable disks only: no snap/squashfs images, loop devices, or ro mounts."""
    if part.fstype in _SKIP_FSTYPES:
        return False
    if part.device.startswith("/dev/loop"):
        return False
    opts = set((part.opts or "").split(","))
    if "ro" in opts:
        return False
    return True


def _service_up(url: str, timeout: float = 2.0) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return "Running" if resp.status == 200 else f"HTTP {resp.status}"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "Not running"


def gather(ctx) -> dict:
    """Collect the full diagnostic into a dict (also used for --json)."""
    procs = procs_mod.snapshot()
    protected = perimeter.build_protected_pids(procs=procs)
    vm = psutil.virtual_memory()

    top = []
    for pid, info in procs.items():
        mem = info.get("memory_info")
        top.append({"pid": pid, "name": info.get("name"), "rss": mem.rss if mem else 0})
    top.sort(key=lambda x: x["rss"], reverse=True)
    top = top[:10]

    drives = []
    for part in psutil.disk_partitions(all=False):
        if not _keep_partition(part):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            drives.append(
                {
                    "mount": part.mountpoint,
                    "total": usage.total,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )
        except (PermissionError, OSError):
            continue

    services = {"Ollama": ollama.base_url() + "/api/tags"}
    services.update(config.services())
    service_health = {name: _service_up(url) for name, url in services.items()}

    found_orphans = orphans.find_orphans(protected, procs=procs)
    orphan_pids = {o["pid"] for o in found_orphans}
    port_list = ports_mod.listening_ports(procs, protected)
    for p in port_list:
        p["orphan"] = p["pid"] is not None and p["pid"] in orphan_pids

    return {
        "version": __import__("superclean").__version__,
        "platform": sys.platform,
        "os": platform.platform(),
        "protected_count": len(protected),
        "protected": perimeter.running_protected_summary(procs=procs),
        "memory": {
            "total": vm.total,
            "available": vm.available,
            "percent": vm.percent,
        },
        "gpus": gpu.gpus(),
        "top_processes": [
            {**t, "protected": t["pid"] in protected} for t in top
        ],
        "orphans": found_orphans,
        "ports": port_list,
        "ollama_models": [
            {"name": m["name"], "size_bytes": m["size_bytes"]}
            for m in ollama.loaded_models()
        ],
        "drives": drives,
        "service_health": service_health,
    }


def run(ctx) -> dict:
    """Print the human report (unless --json) and return the data dict."""
    data = gather(ctx)
    if ctx.json:
        return data

    ctx.section("SUPERCLEAN -- REPORT")
    ctx.log(f"  platform: {data['os']}")

    ctx.log("")
    ctx.log("== PROTECTED PROCESSES (will not be killed) ==", "HEAD")
    for name, pids in sorted(data["protected"].items()):
        ctx.log(f"  {name:<22} {len(pids)} running")
    ctx.log(f"  Total protected PIDs (incl descendants): {data['protected_count']}")

    ctx.log("")
    ctx.log("== MEMORY ==", "HEAD")
    m = data["memory"]
    ctx.log(
        f"  RAM: {friendly_size(m['total'] - m['available'])} used of "
        f"{friendly_size(m['total'])} ({m['percent']}%), "
        f"{friendly_size(m['available'])} free"
    )

    ctx.log("")
    ctx.log("== GPU / VRAM ==", "HEAD")
    if not data["gpus"]:
        ctx.log("  No GPU VRAM info discoverable on this system.", "SKIP")
    else:
        for g in data["gpus"]:
            pct = (g["vram_used"] / g["vram_total"] * 100) if g["vram_total"] else 0
            ctx.log(
                f"  {g['name']:<28} {friendly_size(g['vram_used'])} used of "
                f"{friendly_size(g['vram_total'])} ({pct:.0f}%)"
            )

    ctx.log("")
    ctx.log("== TOP 10 PROCESSES BY RAM ==", "HEAD")
    for t in data["top_processes"]:
        tag = "[PROT]" if t["protected"] else "      "
        ctx.log(f"  {tag} PID {t['pid']:<7} {str(t['name']):<25} {friendly_size(t['rss'])}")

    ctx.log("")
    ctx.log("== ORPHAN DEV PROCESSES ==", "HEAD")
    if not data["orphans"]:
        ctx.log("  None found.", "OK")
    else:
        ctx.log(f"  Found {len(data['orphans'])} orphan(s):", "WARN")
        for o in data["orphans"]:
            ctx.log(f"    PID {o['pid']:<7} {str(o['name']):<12} {o['cmdline']}")

    ctx.log("")
    ctx.log("== LISTENING PORTS ==", "HEAD")
    if not data["ports"]:
        ctx.log("  None visible (or no permission to inspect).", "OK")
    else:
        for p in data["ports"]:
            owner = f"{str(p['name'] or '?'):<15} PID {p['pid'] or '?'}"
            tag = " [ORPHAN]" if p["orphan"] else (" [PROT]" if p["protected"] else "")
            ctx.log(f"  :{p['port']:<6} {owner}{tag}", "WARN" if p["orphan"] else "INFO")

    ctx.log("")
    ctx.log("== OLLAMA ==", "HEAD")
    if not data["ollama_models"]:
        ctx.log("  No models loaded (or daemon not running).", "OK")
    else:
        for m in data["ollama_models"]:
            ctx.log(f"  {m['name']:<30} {friendly_size(m['size_bytes'])}")

    ctx.log("")
    ctx.log("== DRIVES ==", "HEAD")
    for d in data["drives"]:
        level = "OK"
        if d["percent"] > 90:
            level = "ERROR"
        elif d["percent"] > 80:
            level = "WARN"
        ctx.log(
            f"  {d['mount']:<10} {d['percent']:>5}% used  "
            f"({friendly_size(d['free'])} free of {friendly_size(d['total'])})",
            level,
        )

    ctx.log("")
    ctx.log("== SERVICE HEALTH ==", "HEAD")
    for name, status in data["service_health"].items():
        ctx.log(f"  {name:<22} {status}", "OK" if status == "Running" else "INFO")
    ctx.log("")
    ctx.log(
        "Tiers: dust < sweep < scrub < wipe < nuke -- `superclean -h` shows the ladder;",
        "SKIP",
    )
    ctx.log("`superclean clean` walks cleanup with a confirmation per group.", "SKIP")
    ctx.log("")
    return data


def list_protected(ctx) -> dict:
    """The `protected` subcommand: show the protected-name roster."""
    summary = perimeter.running_protected_summary()
    extra = config.protect_names()
    if ctx.json:
        return {"running": summary, "conf_additions": extra}

    ctx.section("PROTECTED PROCESS LIST")
    ctx.log("Protected names (baseline + protect.conf):")
    for name in perimeter.all_protected_names():
        count = len(summary.get(name, []))
        tag = "*" if count else " "
        ctx.log(f"  {tag} {name:<22} {count} running")
    ctx.log("")
    ctx.log(f"protect.conf additions: {', '.join(extra) if extra else '(none)'}")
    return {"running": summary, "conf_additions": extra}


def last_run(ctx) -> dict:
    """The `last` subcommand: replay the newest mutating-run block.

    Only day files in the default data dir are scanned; runs recorded via a
    --log override live outside it and are not visible here.
    """
    logs = sorted(data_dir().glob("superclean-*.log"), reverse=True)
    for path in logs:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        starts = [i for i, ln in enumerate(lines) if "RUN START" in ln]
        if not starts:
            continue
        block = []
        for ln in lines[starts[-1]:]:
            block.append(ln)
            if "Elapsed:" in ln:
                break
        if not ctx.json:
            ctx.section("SUPERCLEAN -- LAST RUN")
            ctx.log(f"  from {path}")
            for ln in block:
                ctx.log(f"  {ln}", to_file=False)
        return {"log": str(path), "lines": block}
    ctx.log("No previous run found in the logs.", "WARN")
    return {"log": None, "lines": []}
