"""macOS/Linux backend: the universal cleanup ladder.

v1 runs the genuinely portable, high-value work (orphan kill, idle-model unload,
package caches, temp/targets age-out) and is honest about the rest: native
destructive deep-clean (page cache, ~/Library/Caches, docker prune) is
report-only for now and noted as such.
"""

from __future__ import annotations

from superclean import caches, ollama, orphans, perimeter, tempprune

_RANK = {"dust": 1, "sweep": 2, "scrub": 3, "wipe": 4, "nuke": 5}


def _ram_relief(ctx) -> dict:
    """Orphan kill + idle Ollama unload. Shared by `ram` and `sweep`+."""
    ctx.log("")
    ctx.log("== Smart orphan dev procs ==", "HEAD")
    protected = perimeter.build_protected_pids()
    found = orphans.find_orphans(protected)
    kill = orphans.kill_orphans(found, ctx)

    ctx.log("")
    ctx.log("== Idle Ollama model unload ==", "HEAD")
    unload = ollama.idle_unload(ctx)
    return {"orphans": kill, "ollama": unload}


def run_ram(ctx) -> dict:
    ctx.section("SUPERCLEAN -- RAM RELIEF")
    return _ram_relief(ctx)


def run_tier(ctx, tier: str) -> dict:
    rank = _RANK[tier]
    ctx.section(f"SUPERCLEAN -- {tier.upper()}")
    results: dict = {}

    # dust (rank 1): lightest, always-safe.
    results["temp_light"] = tempprune.prune_temp(ctx, days=3)

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

    return results
