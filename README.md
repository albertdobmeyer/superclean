# superclean

**An agentic-dev garbage collector for Windows.** One command reclaims the RAM, VRAM, and disk that heavy parallel development leaves behind, without ever touching the editors, terminals, and AI tools you have open.

![platform](https://img.shields.io/badge/platform-Windows-blue)
![shell](https://img.shields.io/badge/PowerShell-5.1%2B%20%7C%207%2B-5391FE)
![license](https://img.shields.io/badge/license-MIT-green)

## Why this exists

If you build with Claude Code (or any agentic workflow), your machine looks like this: 2 to 10 IDE windows, a wall of terminals, a fleet of dev servers, repeated Playwright runs, and one or more local models loaded into VRAM. Most of that does not clean up after itself.

Dev servers get orphaned when a parent shell dies. Playwright leaves stale browser builds. pip, npm, uv, and pnpm caches balloon. Models stay pinned in VRAM long after you stopped using them. The standby list fills with cached pages. After a few days the system is running at capacity on garbage.

`superclean` is the collector for that garbage. It knows the difference between work you are actively doing and artifacts you are done with, and it only removes the second kind.

## The safety promise

superclean **never** kills your live tools. The following are protected by name, along with every one of their child processes:

> Cursor, VS Code, Antigravity, Claude Desktop, Claude Code (the running session), opencode, Windows Terminal, PowerShell, ollama (daemon, app, and model server), Docker CLI.

It also protects the entire process tree above the running session, and any `node` process whose command line shows it belongs to Claude Code, opencode, or an MCP server. You add your own names in `protect.conf`. When in doubt about a process, it leaves it alone.

## Requirements

- Windows 10 or 11
- Windows PowerShell 5.1 (built in) or PowerShell 7+
- Some actions (standby flush, `C:\Windows\Temp`, `--gpu-reset`, Windows.old removal) do more when run as Administrator, and skip cleanly when not

## Install

```powershell
git clone https://github.com/albertdobmeyer/superclean.git
cd superclean
.\superclean.ps1 --report
```

Optional: put `superclean` on your PATH so you can call it from anywhere.

```powershell
.\install.ps1          # adds a shim to %LOCALAPPDATA%\Microsoft\WindowsApps
```

## Usage

```
superclean <LEVEL or MODE> [MODIFIERS]
```

### Levels (additive: each includes everything below it)

| Level | What it adds |
|-------|--------------|
| `--report`, `-r` | Read-only diagnostic. Shows memory, top RAM consumers, orphans, loaded models, drives, WSL, Docker bloat, Windows.old, Recycle Bin, and service health. Changes nothing. |
| `--dust` | Recycle Bin items older than 7 days, tiny always-safe sub-caches, `%TEMP%` older than 3 days. |
| `--brush` | + smart orphan-process kill, standby-list flush, working-set trim of idle processes, DNS/ARP flush, renewable Cursor/Claude caches. |
| `--clean` | + pip / npm / uv / pnpm cache purge, idle Ollama model unload, log prune, `%TEMP%` older than 7 days, full Recycle Bin, optional `targets.conf` folders. |
| `--wipe` | + browser caches (skipped if the browser is open), old Playwright browser builds, full `%TEMP%`, Discord/Slack caches. |
| `--nuke` | + Docker WSL reset and `C:\Windows.old` removal. Requires typing `NUKE`. |

### Standalone modes

| Mode | What it does |
|------|--------------|
| `--ram` | RAM and VRAM relief only, no disk cleanup: standby flush, working-set trim, orphan kill, idle Ollama unload, DNS/ARP flush. |
| `--gpu-reset` | Re-enumerates the GPU device tree (Administrator only). |
| `--last` | Prints the summary of the previous run from its log. |
| `--list-protected` | Prints the full protected-process list and which are running right now. |
| `--help`, `-h` | Usage. |

### Modifiers (combine with any level or mode)

| Modifier | Effect |
|----------|--------|
| `--dry-run` | Show what would be removed; change nothing. |
| `--yes`, `-y` | Skip the y/N prompts. Does not by itself bypass the `NUKE` confirmation. |
| `--i-know` | With `--yes`, bypasses the `NUKE` typed confirmation (for unattended runs). |
| `--quiet`, `-q` | Minimal console output (full detail still goes to the log). |
| `--log <path>` | Write the run log somewhere other than the default. |
| `--no-color` | Disable ANSI color. |
| `--force-unlock` | Override a stuck lockfile from a previous run. |

## Recommended workflow

```powershell
superclean --report            # see what is going on, change nothing
superclean --brush --dry-run   # preview the level you intend to run
superclean --brush             # do it
```

Start at the lightest level that solves your problem. `--ram` for "everything is sluggish", `--brush` for "too many orphan processes", `--clean` for "disk is filling up". Reach for `--wipe` and `--nuke` deliberately.

## Configuration

All three config files live next to `superclean.ps1` and are optional. Lines starting with `#` are comments.

- **`protect.conf`** - extra process names to never touch (one EXE base name per line). Added to the built-in baseline.
- **`targets.conf`** - extra folders to age out at `--clean` (`path|days|label` per line). This is where machine-specific cleanup lives so the core stays generic.
- **`services.conf`** - extra local services to health-check in `--report` (`label|url` per line). Ollama is always checked by default.

Each ships with commented examples (including the author's own "Albert mode" setup) to copy from.

## Logs

Every run is logged in full to:

```
%LOCALAPPDATA%\superclean\superclean-YYYY-MM-DD.log
```

Use `superclean --last` to print the most recent run, or `--log <path>` to redirect.

## Safety notes

superclean deletes files and stops processes. It is built to be conservative, but you are responsible for what you run on your machine.

- Use `--report` and `--dry-run` first. Always.
- `--wipe` clears browser caches only when the browser is closed, so open tabs and sessions are not affected.
- `--nuke` is destructive and irreversible. It resets Docker's WSL data (all images, containers, volumes) and removes `C:\Windows.old`. It requires typing `NUKE` by hand unless you explicitly pass `--yes --i-know`.
- This software is provided as-is, with no warranty. See [LICENSE](LICENSE).

## Roadmap

- Cross-platform support (macOS/Linux). Today superclean is Windows-only by design: it uses PowerShell, WMI, and direct Win32 calls for standby-list and working-set control.
- A scheduled "garbage-collect on idle" mode.
- Per-project orphan attribution in the report.

## License

MIT. See [LICENSE](LICENSE).
