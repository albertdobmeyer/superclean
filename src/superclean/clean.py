"""Guided cleanup: diagnose, propose action groups, confirm each, execute.

`superclean clean` is the workflow command: it composes the same building
blocks the tiers use, driven findings-first with a confirmation per group.
It owns no cleanup logic of its own and never enters wipe/nuke territory
(no browser caches, no docker, no full-temp wipe). --yes approves every
group; in --quiet/--json mode without --yes nothing runs (ctx.confirm is
False there by design).
"""

from __future__ import annotations

from superclean import caches, ollama, orphans, perimeter, procs as procs_mod, tempprune
from superclean.backends import posix
from superclean.util import friendly_size


def run(ctx) -> dict:
    ctx.section("SUPERCLEAN -- GUIDED CLEAN")
    results: dict = {}

    snap = procs_mod.snapshot()
    protected = perimeter.build_protected_pids(procs=snap)
    found = orphans.find_orphans(protected, procs=snap)
    models = ollama.loaded_models() if ollama.is_running() else []
    idle_models = [m for m in models if m["expires_at"] is None]

    ctx.log("")
    ctx.log("== 1. Orphaned dev processes ==", "HEAD")
    if not found:
        ctx.log("  None found.", "OK")
    else:
        held = sum(o.get("rss") or 0 for o in found)
        for o in found:
            ctx.log(f"    PID {o['pid']:<7} {str(o['name']):<12} {o['cmdline']}")
        ctx.log(f"  {len(found)} orphan(s) holding ~{friendly_size(held)} RAM.", "WARN")
        if ctx.confirm(f"  Kill {len(found)} orphan(s)?"):
            results["orphans"] = orphans.kill_orphans(found, ctx)
        else:
            ctx.log("  Skipped.", "SKIP")

    ctx.log("")
    ctx.log("== 2. Idle Ollama models (no keep-alive) ==", "HEAD")
    if not idle_models:
        ctx.log("  None (daemon not running, nothing loaded, or all in active use).", "OK")
    else:
        vram = sum(m["size_bytes"] for m in idle_models)
        for m in idle_models:
            ctx.log(f"    {m['name']:<30} {friendly_size(m['size_bytes'])}")
        if ctx.confirm(
            f"  Unload {len(idle_models)} idle model(s) (~{friendly_size(vram)})?"
        ):
            results["ollama"] = ollama.idle_unload(ctx)
        else:
            ctx.log("  Skipped.", "SKIP")

    ctx.log("")
    ctx.log("== 3. Package-manager caches ==", "HEAD")
    cache_sizes = caches.sizes()
    known_total = sum(v for v in cache_sizes.values() if v)
    if not cache_sizes:
        ctx.log("  No package-manager caches found.", "OK")
    else:
        for label, size in cache_sizes.items():
            shown = f"~{friendly_size(size)}" if size is not None else "size unknown (large?)"
            ctx.log(f"    {label:<8} {shown}")
        prompt = (
            f"  Purge these caches (~{friendly_size(known_total)} measured)?"
            if known_total
            else "  Purge these caches?"
        )
        if ctx.confirm(prompt):
            results["caches"] = caches.purge(ctx)
        else:
            ctx.log("  Skipped.", "SKIP")

    ctx.log("")
    ctx.log("== 4. Temp files older than 7 days ==", "HEAD")
    preview = tempprune.preview_temp(days=7)
    if preview["files"] == 0:
        ctx.log("  Nothing to clean.", "OK")
    else:
        if ctx.confirm(
            f"  Delete {preview['files']} old temp file(s) "
            f"(~{friendly_size(preview['bytes'])})?"
        ):
            results["temp_deep"] = tempprune.prune_temp(ctx, days=7)
        else:
            ctx.log("  Skipped.", "SKIP")

    # targets.conf runs its own per-target preview + confirm flow.
    results["targets"] = tempprune.prune_targets(ctx)

    reclaimed = posix.totals(results)
    results["reclaimed"] = reclaimed
    verb = "Would reclaim (estimate)" if ctx.dry_run else "Reclaimed"
    ctx.log("")
    ctx.log(
        f"  {verb}: {friendly_size(reclaimed['ram_bytes'])} memory, "
        f"{friendly_size(reclaimed['disk_bytes'])} disk.",
        "OK",
    )
    return results
