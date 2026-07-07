# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - unreleased

### Fixed
- Temp age-out ladder was inverted (dust pruned harder than scrub); dust now
  prunes at 14 days, scrub at 7, and the pruner never touches sockets, FIFOs,
  symlinks, or live-session directories (X11/SSH/tmux/systemd/agent scratch).
- Drives report no longer lists snap/squashfs/loop/read-only pseudo-mounts.
- Orphan detection now recognizes processes reparented to the user's
  `systemd --user` subreaper (modern Linux), not just PID 1.
- A config dir is honored if it holds ANY of the three conf files, and each
  file falls back independently to the bundled examples.
- The lockfile is acquired atomically (O_EXCL) and verified for ownership on
  acquire and release; a fatal error under `--json`
  now emits a JSON error envelope instead of nothing; the lock-busy refusal
  does the same.
- Cache purge reports failures honestly (exit-code checked).

### Added
- Headless browsers (Playwright/Puppeteer leftovers) are orphan candidates
  when their command line shows `--headless`.
- Measured reclaim: orphan kills report RSS freed, cache purges report bytes
  freed, and every mutating run ends with a memory/disk total.
- `OLLAMA_HOST` is honored for all Ollama probes and unloads.
- `superclean -h` now explains the full ladder, every utility command, the
  config files, and worked examples (was a bare argparse choices list).
- The no-arg report ends with a one-line pointer to `-h` and `clean`.
- New `superclean clean`: guided cleanup that diagnoses the machine,
  proposes each action group (orphans, idle models, caches, old temp,
  targets.conf) with measured sizes, and runs only what you confirm.
  `--yes` approves every group; it never enters wipe/nuke territory.
- New `superclean init`: copies the example config files into your user
  config dir (never overwrites existing files).
- New `superclean last`: replays the previous mutating run from the logs.
- Report: new LISTENING PORTS section (each port with its owning process,
  protected/orphan marking; degrades gracefully without permissions) and a
  GPU / VRAM section (nvidia-smi when present, AMD via sysfs). Both are
  read-only and appear in `--json` as `ports` and `gpus`.
- `superclean clean`'s cache preview now lists caches that exist but could
  not be sized in time as "size unknown" instead of hiding them.

### Changed
- JSON shape: `caches` entries are now `{"ok", "freed_bytes"}` objects (were
  bare booleans/ints), and the report's service-health key is `Ollama`
  (was `Ollama (11434)`), since the port now follows `OLLAMA_HOST`.
- At `scrub` and above, the single 7-day temp pass replaces the separate
  14-day dust pass it strictly subsumes (`temp_light` is absent from those
  results).
- The run-total reclaim line applies to the portable (macOS/Linux) tiers;
  Windows tiers keep the PowerShell backend's own summary.
- On macOS, read-only mounts (including the sealed system volume) are no
  longer listed under DRIVES; the writable data volume remains.
- The config dir handed to the Windows PowerShell backend may now be one
  that holds any of the three conf files (Python resolves each file with
  per-file fallback; the PS backend reads that single dir as before).

### Internal
- Single shared process snapshot per run (report previously swept all
  processes about four times).

## [2.0.0] - unreleased

Cross-platform rewrite. superclean is now a portable Python CLI (Windows, macOS,
Linux) installable with `uvx` / `pipx`, while the proven PowerShell tool becomes
the Windows deep-clean backend it drives.

### Added
- Cross-platform portable core (Python 3.9+, single dependency `psutil`):
  safety perimeter, orphan detection and kill, package-cache purge, idle Ollama
  unload, temp/targets age-out, and a read-only report, all running on macOS and
  Linux as well as Windows.
- Verb-subcommand surface with the same tiered ladder everywhere:
  `dust -> sweep -> scrub -> wipe -> nuke`, no-arg = safe report, plus
  `report`, `ram`, `protected`.
- `--json` output on every command for scripting.
- The PowerShell backend is bundled into the wheel so `uvx superclean` works on
  a fresh Windows box with no extra steps.

### Changed
- Levels renamed for a single cross-platform vocabulary: `brush -> sweep`,
  `clean -> scrub` (dust/wipe/nuke unchanged).
- The Python launcher owns a single lockfile and passes `--no-lock` to the
  PowerShell backend.
- Config files are shared by both runtimes via `SUPERCLEAN_CONF_DIR`.

### Notes
- macOS/Linux native destructive deep-clean (browser caches, page cache, docker
  prune) is report-only in this version. See the roadmap.

## [1.0.0] - 2026-06-15

First public release.

### Added
- Tiered cleanup levels: `--report`, `--dust`, `--brush`, `--clean`, `--wipe`, `--nuke` (additive).
- Standalone modes: `--ram`, `--gpu-reset`, `--last`, `--list-protected`.
- Modifiers: `--dry-run`, `--yes`, `--i-know`, `--quiet`, `--log`, `--no-color`, `--force-unlock`.
- Protected-process perimeter for editors, terminals, and AI tooling, including
  descendant and ancestor process trees, with `protect.conf` for custom names.
- Smart orphan detection for dead-parent dev servers (node, vite, esbuild, and more).
- RAM/VRAM relief: standby-list flush, working-set trim, idle Ollama model unload.
- Optional config-driven cleanup (`targets.conf`) and health checks (`services.conf`).
- Per-run logging to `%LOCALAPPDATA%\superclean`.
