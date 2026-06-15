# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
