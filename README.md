# superclean

**An agentic-dev garbage collector.** One command, a tiered cleanup ladder, that reclaims the RAM, VRAM, and disk left behind by heavy parallel development, and never touches the editors, terminals, or AI tools you have open.

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![python](https://img.shields.io/badge/python-3.9%2B-3776AB)
![license](https://img.shields.io/badge/license-MIT-green)

## Why this exists

If you build with Claude Code (or any agentic workflow), your machine looks like this: several IDE windows, a wall of terminals, a fleet of dev servers, repeated Playwright runs, and one or more local models pinned in VRAM. Most of that never cleans up after itself.

Dev servers get orphaned when their parent shell dies. Playwright leaves stale browser builds. pip, npm, uv, and pnpm caches balloon. Models stay loaded long after you stopped using them. After a few days the system runs at capacity on garbage.

`superclean` is the collector for that garbage. It tells the difference between work you are actively doing and artifacts you are done with, and only removes the second kind.

## The tiered ladder

Cleanup escalates through five additive tiers. Each includes everything lighter. A tier name describes intensity and risk, not a specific action, so the ladder is identical on every OS; each tier does what is available on the current platform and reports what it skipped.

| Command | Tier | What it adds |
|---------|------|--------------|
| `superclean` | (none) | Safe read-only **report**. Changes nothing. |
| `superclean dust` | 1 | Lightest, always-safe: old temp scratch, trivial caches. |
| `superclean sweep` | 2 | + reclaim live resources: orphan-process kill, RAM/VRAM relief. |
| `superclean scrub` | 3 | + the standard deep clean: package caches, idle model unload, logs. |
| `superclean wipe` | 4 | + heavy and deliberate: browser caches, full temp, Playwright builds. |
| `superclean nuke` | 5 | + destructive: Docker reset, Windows.old. Requires typing `NUKE`. |

Risk rises with the climb: tiers 1-3 are everyday-safe, `wipe` confirms, `nuke` makes you type the word. Plus three utilities: `superclean report`, `superclean ram` (RAM/VRAM relief only, no disk), and `superclean protected` (show what is shielded).

## The safety promise

superclean **never** kills your live tools. A generous baseline of editors, terminals, shells, and AI tools is protected by name, together with every one of their child processes, the entire ancestor chain of the running session, and any process whose command line shows it belongs to an AI agent. The tool also protects its own interpreter, so it can never flag itself. When it is unsure about a process, it leaves it alone. You add your own names in `protect.conf`.

## Platform support

| | RAM/VRAM relief | Orphan kill | Cache purge | Deep clean (browser/temp) | Destructive (Docker, Windows.old) |
|---|---|---|---|---|---|
| **Windows** | yes | yes | yes | yes | yes |
| **macOS / Linux** | yes | yes | yes | report-only (v1) | report-only (v1) |

The universal tiers run everywhere. On Windows, the heavy and destructive tiers are handled by a proven PowerShell deep-clean backend that ships with the package. On macOS and Linux, native destructive deep-cleaning is report-only in v1 (see Roadmap).

## Install

Zero-install with [uv](https://docs.astral.sh/uv/), straight from the repo:

```bash
uvx --from git+https://github.com/albertdobmeyer/superclean superclean
uvx --from git+https://github.com/albertdobmeyer/superclean superclean sweep
```

Or clone and install:

```bash
git clone https://github.com/albertdobmeyer/superclean.git
pipx install ./superclean      # or: pip install ./superclean
```

Requires Python 3.9 or newer. The only dependency is `psutil`.

Once published to PyPI, `uvx superclean` and `pip install superclean` will work
by bare name.

## Recommended workflow

```bash
superclean                  # see what is going on, change nothing
superclean sweep --dry-run  # preview the tier you intend to run
superclean sweep            # do it
```

Start at the lightest tier that solves your problem: `sweep` for "too many orphan processes and VRAM is full", `scrub` for "disk is filling up". Reach for `wipe` and `nuke` deliberately.

## Configuration

Three optional files, shared by every platform. superclean looks for them via `SUPERCLEAN_CONF_DIR`, then your per-user config dir, then the bundled examples. Lines starting with `#` are comments.

- **`protect.conf`** - extra process names to never touch (one per line).
- **`targets.conf`** - extra folders to age out at `scrub` (`path|days|label`). This is where machine-specific cleanup lives so the core stays generic.
- **`services.conf`** - extra local services to health-check in the report (`label|url`). Ollama is always checked.

Each ships with commented examples, including the author's own "Albert mode" setup, to copy from.

## Scripting

Every command accepts `--json` for a stable machine-readable result (and suppresses human output), so superclean drops cleanly into pre-commit hooks, CI, or a scheduled idle-clean:

```bash
superclean report --json
superclean sweep --dry-run --json
```

Global flags: `--dry-run`, `--yes/-y`, `--i-know` (only with `nuke`), `--quiet/-q`, `--json`, `--no-color`, `--log <path>`, `--force-unlock`. Exit codes: `0` ok, `1` usage/lock, `3` fatal.

## Logs

Every run is logged in full under your per-user data directory:

- Windows: `%LOCALAPPDATA%\superclean\`
- macOS: `~/Library/Application Support/superclean/`
- Linux: `$XDG_STATE_HOME/superclean/` (or `~/.local/state/superclean/`)

## Safety notes

superclean deletes files and stops processes. It is built to be conservative, but you are responsible for what you run on your machine.

- Use the no-arg report and `--dry-run` first. Always.
- `wipe` clears browser caches only when the browser is closed.
- `nuke` is destructive and irreversible. It requires typing `NUKE` by hand unless you explicitly pass `--yes --i-know`.
- Provided as-is, no warranty. See [LICENSE](LICENSE).

## Roadmap

- Native destructive deep-clean for macOS and Linux (page cache, `~/Library/Caches`, docker prune).
- A scheduled "garbage-collect on idle" mode.
- Per-project orphan attribution in the report.

## Development

The portable core is Python (`src/superclean/`); the Windows deep-clean backend is PowerShell (`windows/`). See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
