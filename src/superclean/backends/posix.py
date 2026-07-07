"""macOS/Linux backend: the universal cleanup ladder.

v1 runs the genuinely portable, high-value work (orphan kill, idle-model unload,
package caches, temp/targets age-out) and is honest about the rest: native
destructive deep-clean (page cache, ~/Library/Caches, docker prune) is
report-only for now and noted as such.
"""

from __future__ import annotations

from superclean import caches, ollama, orphans, perimeter, procs as procs_mod, tempprune
from superclean.util import friendly_size

_RANK = {"dust": 1, "sweep": 2, "scrub": 3, "wipe": 4, "nuke": 5}


def totals(results: dict) -> dict:
    """Aggregate measured reclaim across all steps of a run."""
    ram = 0
    ram += (results.get("orphans") or {}).get("reclaimed_rss", 0)
    ram += (results.get("ollama") or {}).get("reclaimed_bytes", 0)
    disk = 0
    for key in ("temp_light", "temp_deep"):
        disk += (results.get(key) or {}).get("bytes", 0)
    for t in results.get("targets") or []:
        disk += t.get("bytes", 0)
    for v in (results.get("caches") or {}).values():
        if isinstance(v, dict):
            disk += v.get("freed_bytes") or 0
    return {"ram_bytes": ram, "disk_bytes": disk}


_totals = totals


def _ram_relief(ctx) -> dict:
    """Orphan kill + idle Ollama unload. Shared by `ram` and `sweep`+."""
    ctx.log("")
    ctx.log("== Smart orphan dev procs ==", "HEAD")
    snap = procs_mod.snapshot()
    protected = perimeter.build_protected_pids(procs=snap)
    found = orphans.find_orphans(protected, procs=snap)
    kill = orphans.kill_orphans(found, ctx)

    ctx.log("")
    ctx.log("== Idle Ollama model unload ==", "HEAD")
    unload = ollama.idle_unload(ctx)
    return {"orphans": kill, "ollama": unload}


def run_ram(ctx) -> dict:
    ctx.section("SUPERCLEAN -- RAM RELIEF")
    results = _ram_relief(ctx)
    totals = _totals(results)
    results["reclaimed"] = totals
    verb = "Would reclaim (estimate)" if ctx.dry_run else "Reclaimed"
    ctx.log("")
    ctx.log(
        f"  {verb}: {friendly_size(totals['ram_bytes'])} memory, "
        f"{friendly_size(totals['disk_bytes'])} disk.",
        "OK",
    )
    return results


def run_tier(ctx, tier: str) -> dict:
    rank = _RANK[tier]
    ctx.section(f"SUPERCLEAN -- {tier.upper()}")
    results: dict = {}

    # dust (rank 1): lightest, always-safe. At scrub and above the 7-day pass
    # strictly subsumes this 14-day pass, so only one temp walk runs -- which
    # also keeps dry-run reclaim estimates from double-counting old files.
    if rank < 3:
        results["temp_light"] = tempprune.prune_temp(ctx, days=14)

    # sweep (rank 2): reclaim live resources.
    if rank >= 2:
        results.update(_ram_relief(ctx))

    # scrub (rank 3): deeper disk.
    if rank >= 3:
        results["caches"] = caches.purge(ctx)
        results["temp_deep"] = tempprune.prune_temp(ctx, days=7)
        results["targets"] = tempprune.prune_targets(ctx)

    # wipe (rank 4): heavy. Native browser/app caches are report-only in v1.
    if rank >= 4:
        ctx.log("")
        ctx.log("== wipe (heavy) ==", "HEAD")
        ctx.log(
            "  Native browser/app cache wiping is not yet implemented on this OS. "
            "Use targets.conf for specific folders.",
            "SKIP",
        )

    # nuke (rank 5): destructive. No native destructive actions on posix in v1.
    if rank >= 5:
        ctx.log("")
        ctx.log("== nuke (destructive) ==", "HEAD")
        ctx.log(
            "  Native destructive deep-clean (page cache, docker prune) is "
            "report-only on this OS in this version. Nothing destructive run.",
            "SKIP",
        )

    totals = _totals(results)
    results["reclaimed"] = totals
    verb = "Would reclaim (estimate)" if ctx.dry_run else "Reclaimed"
    ctx.log("")
    ctx.log(
        f"  {verb}: {friendly_size(totals['ram_bytes'])} memory, "
        f"{friendly_size(totals['disk_bytes'])} disk.",
        "OK",
    )

    return results
