"""Read-only diagnostic. Shows what superclean could reclaim; changes nothing."""

from __future__ import annotations

import platform
import sys
import urllib.error
import urllib.request

import psutil

from superclean import config, ollama, orphans, perimeter
from superclean.util import friendly_size


def _service_up(url: str, timeout: float = 2.0) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return "Running" if resp.status == 200 else f"HTTP {resp.status}"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "Not running"


def gather(ctx) -> dict:
    """Collect the full diagnostic into a dict (also used for --json)."""
    protected = perimeter.build_protected_pids()
    vm = psutil.virtual_memory()

    top = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            rss = p.info["memory_info"].rss if p.info.get("memory_info") else 0
            top.append({"pid": p.info["pid"], "name": p.info.get("name"), "rss": rss})
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    top.sort(key=lambda x: x["rss"], reverse=True)
    top = top[:10]

    drives = []
    for part in psutil.disk_partitions(all=False):
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

    services = {"Ollama (11434)": "http://localhost:11434/api/tags"}
    services.update(config.services())
    service_health = {name: _service_up(url) for name, url in services.items()}

    return {
        "version": __import__("superclean").__version__,
        "platform": sys.platform,
        "os": platform.platform(),
        "protected_count": len(protected),
        "protected": perimeter.running_protected_summary(),
        "memory": {
            "total": vm.total,
            "available": vm.available,
            "percent": vm.percent,
        },
        "top_processes": [
            {**t, "protected": t["pid"] in protected} for t in top
        ],
        "orphans": orphans.find_orphans(protected),
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
