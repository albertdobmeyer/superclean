---
name: clean
description: Reclaim RAM, VRAM, and disk - kill orphaned dev servers, unload idle models, purge package caches - without touching your editors, terminals, or this Claude Code session.
disable-model-invocation: true
allowed-tools: ["Bash"]
argument-hint: "[dust|sweep|scrub|wipe|nuke]"
---

# superclean clean

Reclaim resources. This skill has side effects: it kills processes and deletes files.
**Never skip the dry run, and never act without the user's confirmation.**

## The ladder

Tiers are additive. Each includes everything lighter.

| Tier | What it adds |
|------|--------------|
| `dust` | temp scratch older than 14 days. Always safe. |
| `sweep` | + kill orphaned dev servers, RAM/VRAM relief (unload idle models) |
| `scrub` | + package caches (pip/npm/uv/pnpm/yarn), temp over 7 days, targets.conf |
| `wipe` | + browser caches, full temp, Playwright builds |
| `nuke` | + destructive: Docker reset, Windows.old |

`$ARGUMENTS` may name a tier. If it is empty, default to `sweep`, which is the tier that
handles the common complaint (leaked processes and pinned VRAM) without touching caches.

## Procedure

**1. Dry run first. Always.**

```bash
uvx superclean-cli <tier> --dry-run --json
```

**2. Show the user exactly what it would do.** Name the processes it would kill with their
RAM, the models it would unload with their VRAM, the caches it would purge with their
sizes, and the total it would reclaim. Prose, not a JSON dump.

**3. Ask for confirmation.** Then, and only then:

```bash
uvx superclean-cli <tier> --yes --json
```

`--yes` is what makes it non-interactive; without it the CLI prompts and will hang here.

**4. Report what was actually reclaimed**, using the `reclaimed` field of the result. If a
step failed or was skipped, say so. Do not round a failure up into a success.

## Hard rules

- **Never run `nuke` on your own initiative.** It is destructive (Docker reset,
  Windows.old) and the CLI requires the user to type `NUKE`. If they ask for it, run the
  dry run, show them, and tell them to run `superclean nuke` themselves in their own
  terminal. Do not pass `--i-know` for them.
- **Never pass `--force-unlock`.** It exists to let a run proceed alongside a live one.
  Nothing good comes of an agent using it.
- **Do not manually `pkill`/`taskkill` anything** as a substitute or a follow-up. That is
  the entire failure mode superclean exists to prevent: `pkill -f node` kills the
  orphaned dev server, and also the editor's language servers, the MCP servers, and this
  session's own runtime.

## Why this is safe to run from inside Claude Code

superclean's perimeter is fail-closed: anything it cannot confidently classify is treated
as protected. It shields editors, terminals, multiplexers, interactive shells, AI coding
tools and the Ollama daemon by name; any process whose command line reveals it is an MCP
server or agent runtime; every descendant of anything protected, transitively; and its own
entire ancestor chain, which includes this session. Kills are re-validated against the
process start time immediately before signalling, so a recycled PID is skipped.

Run `uvx superclean-cli protected` to show the user the full shield list.
